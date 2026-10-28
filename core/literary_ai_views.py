"""Endpoint de IA compatible con el chat principal y el flotante existentes."""
import hashlib
import json
import os
import logging
import copy
import secrets
import sqlite3
import threading
import time
from dataclasses import asdict
from queue import Empty, Full, Queue
from types import SimpleNamespace
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_POST
from .literary_ai import (build_assistant, ChatResult, MAX_HISTORY, MAX_MESSAGE,
                         local_social, obvious_rejection, REFUSAL)
from .quotas import cuota_disponible, verificar_y_consumir_cuota
from .ai_concurrency import acquire, release, rate_increment
from .ai_budget import (request_budget, BudgetExpired, WorkerBusy, chat_timeout,
                        run_before_deadline, budget_timeout, check_budget,
                        pool_in_budget, submit_with_budget, submit_before_deadline)
from .literary_sources import bounded_research
from .literary_conversation import resolve_topic_context, remember_topic
from .ai_progress import (emit_phase, measure_stage, progress_scope, snapshot_metrics,
                          sanitize_metrics, merge_metrics)

logger = logging.getLogger('litmate')
HISTORY_KEY = 'litmate_literary_chat_local_v1'

_TRACE_ENV = 'LITMATE_TRACE_MEMORY'
_TRACE_PATH = os.environ.get('LITMATE_TRACE_MEMORY_PATH',
                            os.path.join('reportes', 'auditoria_conversacional', 'trazas_memoria.jsonl'))


def _memory_trace_enabled():
    return os.environ.get(_TRACE_ENV, '').lower() in {'1', 'true', 'yes', 'on'}


def _memory_trace(event):
    if not _memory_trace_enabled():
        return
    path = os.environ.get('LITMATE_TRACE_MEMORY_PATH', _TRACE_PATH)
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + '\n')
    except OSError:
        pass
STREAM_NONCE_KEY = 'litmate_ai_stream_owner_v1'


def stable_session_owner(request):
    """Identidad privada estable, también para visitantes y signed cookies.

    Debe llamarse en la petición, antes de devolver sus cabeceras. Ni una IP ni
    el literal anonymous bastan para separar trabajos/cachés de dos lectores.
    """
    from .ai_stream_jobs import owner_key
    nonce = request.session.get(STREAM_NONCE_KEY)
    if not isinstance(nonce, str) or len(nonce) != 43:
        nonce = secrets.token_urlsafe(32)
        request.session[STREAM_NONCE_KEY] = nonce
    principal = ('user:' + str(request.user.pk) if request.user.is_authenticated else 'anonymous')
    return owner_key(principal, nonce)


def _safe_diagnostics(result, client):
    """Telemetría pública; excluye prompts, borradores y consultas privadas."""
    diagnostics = result.diagnostics
    allowed = ('elapsed_ms', 'chat_budget_seconds', 'model_calls', 'cache_hit',
               'answer_cache_hit', 'exact_cache_hit', 'semantic_cache_hit')
    allowed += ('exact_answer_cache_hit',)
    allowed += ('verified_narrative_answer', 'narrative_synthesized', 'partial_evidence')
    allowed += ('verified_character_answer', 'character_count')
    allowed += ('discovery_candidates', 'verified_recommendations')
    values = {key: diagnostics[key] for key in allowed
              if type(diagnostics.get(key)) in {int, float, bool}}
    if diagnostics.get('work_type') in {'fiction', 'nonfiction', 'unknown'}:
        values['work_type'] = diagnostics['work_type']
    if diagnostics.get('narrative_failure') in {'audit_not_approved', 'insufficient_content',
            'model_not_configured', 'ValueError', 'TypeError', 'ProviderUnavailable', 'BudgetExpired', 'TimeoutError'}:
        values['narrative_failure'] = diagnostics['narrative_failure']
    metrics = diagnostics.get('progress_metrics', {})
    if isinstance(metrics, dict):
        values['progress_metrics'] = sanitize_metrics(metrics)
    # Estos registros contienen solo identificadores controlados y números,
    # nunca la auditoría de afirmaciones ni los mensajes del usuario.
    timings = diagnostics.get('stage_timings', [])
    if isinstance(timings, list):
        timing_keys = {'stage', 'model', 'elapsed_ms', 'status', 'load_ms',
                       'prompt_eval_ms', 'eval_ms', 'total_ms', 'prompt_eval_count', 'eval_count'}
        values['stage_timings'] = [{key: item[key] for key in timing_keys if key in item}
                                  for item in timings[:128] if isinstance(item, dict)]
    research = diagnostics.get('external_research')
    if isinstance(research, dict):
        keys = {'logical_searches', 'page_slots_reserved', 'external_seconds',
                'http_requests_started', 'pages_extracted'}
        values['external_research'] = {key: research[key] for key in keys
                                      if type(research.get(key)) in {int, float}}
    values['provider'] = str(getattr(client, 'provider', 'local'))[:64]
    values['model_calls'] = getattr(client, 'calls', None)
    return values


@ensure_csrf_cookie
def chatbot_page(request):
    return render(request, 'chatbot.html')


def stream_result(result):
    # Se publica el texto final, después de revisar el borrador completo.
    def events():
        for start in range(0, len(result.text), 160):
            yield 'data: ' + json.dumps({'token': result.text[start:start+160]}, ensure_ascii=False) + '\n\n'
        from .ai_presentation import build_book_cards
        cards = build_book_cards(result)
        if cards:
            # token vacío conserva compatibilidad con los consumidores de sólo texto.
            yield 'data: ' + json.dumps({'token': '', 'books': cards}, ensure_ascii=False) + '\n\n'
        yield 'data: [DONE]\n\n'
    response = StreamingHttpResponse(events(), content_type='text/event-stream; charset=utf-8')
    response['Cache-Control'] = 'no-cache, no-store'
    response['X-Accel-Buffering'] = 'no'
    response['X-Content-Type-Options'] = 'nosniff'
    response['X-LitMate-Status'] = result.status
    return response


def rate_allowed(request):
    principal = ('user:' + str(request.user.pk) if request.user.is_authenticated
                 else 'ip:' + request.META.get('REMOTE_ADDR', ''))
    key = ('literary_chat_rate_local:' + hashlib.sha256(principal.encode()).hexdigest()
           + ':' + str(int(time.time()) // 60))
    try:
        return rate_increment(key, timeout=120) <= getattr(settings, 'LITMATE_AI_REQUESTS_PER_MINUTE', 20)
    except Exception:
        logger.warning('IA: no se pudo aplicar el límite de solicitudes')
        return False


def remember(request, state, message, result, elapsed_ms, client, *, topic_context=None):
    topic_changed = remember_topic(state, message, topic_context)
    if not result.remember:
        # The requested work is reader intent, not a rejected answer/fact.
        request.session[HISTORY_KEY] = state
        request.session.modified = True
        if result.status == 'unavailable' and (result.diagnostics.get('narrative_failure')
                                              or result.diagnostics.get('character_failure')):
            if result.diagnostics.get('character_failure'):
                from .ai_character_answers import request_for
            else:
                from .ai_narrative_answers import request_for
            from .literary_focus import focus_history
            pending = request_for(message, focus_history(state), state.get('pending_clarification'))
            if pending and pending.get('title') and not pending.get('ambiguous'):
                task = {'summary': 'Dime la trama', 'characters': 'Dime los personajes',
                        'protagonist': 'Quién es el protagonista', 'character': 'Dime la trama',
                        'relationship': 'Dime la trama'}.get(pending['task'], 'Dime la trama')
                query = task + ' de ' + pending['title']
                if pending.get('author_hint'):
                    query += ' del autor ' + pending['author_hint']
                state['pending_clarification'] = {'original_query': query[:500], 'status': 'unavailable'}
                request.session[HISTORY_KEY] = state
                request.session.modified = True
        elif result.status == 'clarification':
            state['pending_clarification'] = {
                'question': result.text[:500],
                'original_query': message[:500],
                'status': 'clarification'
            }
            request.session[HISTORY_KEY] = state
            request.session.modified = True
        elif topic_changed:
            # Guardar la petición permite continuar tras un fallo. No guardar el
            # borrador rechazado como respuesta ni convertirlo en evidencia.
            request.session[HISTORY_KEY] = state
            request.session.modified = True
        return
    state.pop('pending_clarification', None)
    from .literary_identity import work_identity
    records = {source.get('id'): source for source in result.sources}
    remembered_books = []
    for book in result.books:
        source = records.get(book.get('source_id'), book)
        remembered_books.append({**book, **work_identity(source),
                                'source': source.get('source', ''), 'url': source.get('url', '')})
    turn = {'accepted': True, 'question': message, 'answer': result.text[:5000],
            'sources': result.sources[:8], 'books': remembered_books, 'basis': result.basis,
            'intent': result.intent}
    from .literary_focus import remember_focus
    remember_focus(state, turn)
    state['turns'] = (state.get('turns', []) + [turn])[-MAX_HISTORY:]
    if request.user.is_authenticated:
        try:
            from .models import ConversacionIA, MensajeIA
            with transaction.atomic():
                conv = ConversacionIA.objects.filter(pk=state.get('conversation_id'), usuario=request.user).first()
                if conv is None:
                    conv = ConversacionIA.objects.create(usuario=request.user,
                        session_key=request.session.session_key, titulo=message[:120])
                    state['conversation_id'] = conv.pk
                MensajeIA.objects.create(conversacion=conv, rol='user', contenido=message)
                MensajeIA.objects.create(conversacion=conv, rol='assistant', contenido=result.text,
                    tokens_prompt=client.usage.get('prompt_tokens', 0),
                    tokens_completion=client.usage.get('completion_tokens', 0),
                    tokens_utilizados=client.usage.get('total_tokens', 0),
                    latencia_ms=elapsed_ms, intencion_detectada=result.intent,
                        metadata_json={'policy_version': 'literary-companion-local-v4', 'status': result.status,
                        'sources': result.sources, 'books': result.books, 'basis': result.basis,
                        'provider': client.provider, 'provider_calls': client.calls,
                        'diagnostics': result.diagnostics, 'usage_includes_guards': True})
                ConversacionIA.objects.filter(pk=conv.pk, usuario=request.user).update(
                    total_mensajes=F('total_mensajes')+2, ultima_actividad=timezone.now())
        except Exception as exc:
            logger.warning('IA: historial persistente no disponible (%s)', type(exc).__name__)
    # El middleware guarda los cambios antes de empezar el streaming.
    request.session[HISTORY_KEY] = state
    request.session.modified = True
    if (getattr(settings, 'LITMATE_AI_QUICK_ANSWERS', True)
            and type(getattr(client, 'calls', None)) is int and client.calls == 0):
        from .ai_answer_cache import cache_published_authorship
        cache_published_authorship(message, state, stable_session_owner(request), result)


def _model_answer(message, history, topic_context, retrieval_message):
    """Investiga también obras desconocidas mientras Ollama prepara su respuesta.

    El respaldo no espera a una inferencia extra: conserva resultados públicos
    por si falla la generación. Se reserva un margen dentro del deadline único
    para publicar las referencias, sin reiniciar el reloj ni tocar la sesión.
    """
    from .literary_ai import looks_literary, normalized, requires_exact_text, has_excerpt, simple_literary_route
    from .literary_identity import resolve_followup_context
    from .literary_research import public_research_queries, is_topic_recommendation
    from .literary_search import retrieve_web
    from .literary_sources import SearchResults
    reference = resolve_followup_context(message, history)
    route = simple_literary_route(message)
    recommendation = (is_topic_recommendation(retrieval_message)
                      or is_topic_recommendation(message)
                      or topic_context.get('intent') == 'recommend'
                      or reference.get('reason') in {'similar', 'same_author'})
    eligible = (getattr(settings, 'LITMATE_AI_USE_WEB', True)
                and not requires_exact_text(message) and not has_excerpt(message)
                and not reference['ambiguous']
                and (looks_literary(message, history) or route is not None))
    queries = public_research_queries(retrieval_message, reference['books']) if eligible else []
    with pool_in_budget(1) as pool:
        pending = None
        if queries:
            def research():
                try:
                    with request_budget(time.monotonic() + budget_timeout(8)):
                        return retrieve_web(queries[0])
                except (TimeoutError, OSError, ValueError):
                    return SearchResults(status='unavailable')
            pending = submit_with_budget(pool, research)

        def web_search(query):
            if pending is not None and normalized(query) == normalized(queries[0]):
                try:
                    return pending.result(timeout=budget_timeout(8))
                except TimeoutError:
                    return SearchResults(status='timeout')
            return retrieve_web(query)

        remaining = budget_timeout(chat_timeout(settings))
        margin = min(1.0, remaining / 10)
        with request_budget(time.monotonic() + remaining - margin):
            kwargs = {'web_search': web_search} if pending is not None else {}
            assistant, client = build_assistant(settings, **kwargs)
            try:
                result = assistant.reply(message, history, topic_context=topic_context)
            except BudgetExpired:
                result = ChatResult('No se completó la verificación en el tiempo disponible.',
                    'unavailable', diagnostics={'provider_error': 'tiempo_total_agotado'})
        if result.status == 'clarification' and topic_context.get('subject'):
            from .ai_quick_answers import _simple_topic_request
            if _simple_topic_request(message, topic_context.get('query') or message):
                result = ChatResult('Entendí que buscas libros sobre ' + topic_context['subject'] + '. '
                    'Esta vez no pude verificar suficientes opciones. No necesitas reformular '
                    'la petición; puedes volver a intentarlo.', 'unavailable',
                    diagnostics={**result.diagnostics, 'clear_topic_not_ambiguity': True})
        if (result.status == 'unavailable' and pending is not None
                and not recommendation):
            from .ai_quick_answers import reference_answer
            try:
                waiting = budget_timeout(8)
                found = pending.result(timeout=max(.001, waiting - min(.25, waiting / 10)))
            except (TimeoutError, OSError, ValueError):
                found = []
            backup = reference_answer(message, found, query=queries[0],
                intent=(route or {}).get('intent', 'analysis'), history=history)
            if backup is not None:
                backup.diagnostics.update(original_failure=result.diagnostics, web_backup=True)
                result = backup
        if result.status == 'unavailable' and getattr(settings, 'LITMATE_AI_CATALOG_FALLBACK', True):
            from .ai_catalog_fallback import catalog_fallback
            from .literary_search import search_google
            try:
                with request_budget(getattr(client, 'deadline', time.monotonic() + budget_timeout(1))):
                    fallback = catalog_fallback(retrieval_message, history, search_google,
                        failure_reason=result.diagnostics.get('provider_error', 'quality_check_failed'))
            except BudgetExpired:
                fallback = None
            if fallback is not None:
                fallback.diagnostics['original_failure'] = result.diagnostics
                result = fallback
        if pending is not None:
            pending.cancel()
        return result, client


def _compute_answer(message, history, topic_context):
    """Recoge métricas incluso en las rutas que no llaman a ningún modelo."""
    with progress_scope():
        # Aquí comienza la consulta efectiva a las fichas y al contexto local.
        # No es un temporizador ni una secuencia de animaciones prefijadas.
        emit_phase('search')
        context = dict(topic_context)
        pending_clarification = context.pop('_pending_clarification', None)
        result, client = _compute_answer_impl(
            message, history, context, pending_clarification=pending_clarification)
        result.diagnostics['progress_metrics'] = snapshot_metrics()
        return result, client


def _answer_with_cache(message, history, topic_context, cache_state, cache_owner,
                       request_metrics=None, request_started=None):
    """Sólo datos copiados del lector; ninguna sesión/ORM dentro del worker."""
    from .ai_answer_cache import get_answer, put_answer
    topic_context = dict(topic_context)
    memory_context = topic_context.pop('_memory_context', {})
    from .literary_focus import focus_history
    history = focus_history(cache_state)
    if memory_context:
        from .literary_ai import sanitized_history
        from .ai_character_answers import request_for as character_request
        from .ai_narrative_answers import request_for as narrative_request
        normalized_history = sanitized_history(history)
        _memory_trace({**memory_context, 'phase': 'D_normalized_history',
            'function': '_answer_with_cache/focus_history/sanitized_history',
            'history': [{'question': turn['question'],
                         'book_titles': [book.get('title') for book in turn['books']],
                         'context_work': turn.get('context_work'),
                         'source_count': len(turn['sources'])} for turn in normalized_history],
            'active_work_used': cache_state.get('active_work')})
        resolved = character_request(message, history, cache_state.get('pending_clarification'))
        narrative = narrative_request(message, history, cache_state.get('pending_clarification'))
        _memory_trace({**memory_context, 'phase': 'E_resolver',
                      'function': 'request_for', 'character_request': resolved,
                      'narrative_request': narrative})
    enabled = getattr(settings, 'LITMATE_AI_QUICK_ANSWERS', True)
    with progress_scope() as progress:
        def measured(result, client):
            metrics = snapshot_metrics()
            if request_metrics is not None and request_started is not None:
                metrics = merge_metrics(request_metrics, metrics,
                    offset_ms=max(0., (progress['start'] - request_started) * 1000))
            result.diagnostics['progress_metrics'] = metrics
            if memory_context:
                _memory_trace({**memory_context, 'phase': 'F_after_answer',
                    'function': '_answer_with_cache', 'result_status': result.status,
                    'result_reason': result.diagnostics.get('character_failure')
                        or result.diagnostics.get('narrative_failure')
                        or result.diagnostics.get('provider_error'),
                    'sources': [{'id': source.get('id'), 'title': source.get('title')}
                                for source in result.sources],
                    'audit_decision': result.diagnostics.get('audit', {}).get('decision'),
                    'stage_totals_ms': metrics.get('stage_totals_ms', {})})
            return result, client

        if enabled:
            with measure_stage('cache_lookup'):
                cached = get_answer(message, cache_state, cache_owner)
            if cached is not None:
                return measured(cached, SimpleNamespace(usage={}, provider='verified-answer-cache', calls=0))
        pending_clarification = cache_state.get('pending_clarification')
        compute_context = ({**topic_context, '_pending_clarification': pending_clarification}
                          if isinstance(pending_clarification, dict) else topic_context)
        if cache_state.get('_focus_navigation') and cache_state.get('active_work'):
            result = ChatResult('Volvamos a **' + cache_state['active_work']['title'] +
                                '**. ¿Qué te gustaría comentar?', 'answered', True)
            return measured(result, SimpleNamespace(usage={}, provider='conversation-focus', calls=0))
        result, client = _compute_answer(message, history, compute_context)
        if enabled:
            try:
                from .ai_persistent_router import persist_sources
                persist_sources(result.sources)
            except (OSError, ValueError, sqlite3.Error):
                logger.warning('IA: memoria pública no disponible; se conserva la respuesta validada')
            if getattr(client, 'calls', None) == 0:
                put_answer(message, cache_state, cache_owner, result)
        return measured(result, client)


def _compute_answer_impl(message, history, topic_context, *, pending_clarification=None):
    """Trabajo acotado sin acceso a la sesión ni al consumo de cuotas.

    Todas las rutas comparten el presupuesto recibido por ContextVar. No se
    crea otro de cinco minutos después de que falle una ruta rápida.
    """
    from django.db import close_old_connections
    try:
        retrieval_message = (topic_context['query'] if topic_context.get('followup')
                             and topic_context.get('intent') == 'recommend' else message)
        from .literary_ai import requires_exact_text, has_excerpt, EXACT_TEXT_NEEDED
        if requires_exact_text(message) and not has_excerpt(message):
            from .literary_search import retrieve_book_content
            from .literary_evidence import exact_context_available
            try:
                with request_budget(time.monotonic() + budget_timeout(1)):
                    exact_sources = retrieve_book_content(message, [])
                    if not exact_context_available(message, exact_sources):
                        return (ChatResult(EXACT_TEXT_NEEDED, 'clarification', True),
                                SimpleNamespace(usage={}, provider='exact-text-required', calls=0))
            except BudgetExpired:
                pass
        if getattr(settings, 'LITMATE_AI_QUICK_ANSWERS', True):
            # Resolver personajes antes de las rutas bibliográficas: una
            # pertenencia P674 de Wikidata no sustituye una función narrativa.
            from .ai_character_answers import character_answer
            character = character_answer(message, history, config=settings,
                                          pending_clarification=pending_clarification)
            if character is not None:
                return character, SimpleNamespace(usage=character.diagnostics.get('usage', {}),
                    provider='verified-character-evidence', calls=character.diagnostics.get('model_calls', 0))
            from .ai_related_recommendations import related_recommendation_answer
            from .literary_search import retrieve_discovery_books, enrich_discovery_book_records
            related_candidates = 0

            def related_search(query):
                nonlocal related_candidates
                found = retrieve_discovery_books(query)
                related_candidates += len(found)
                return enrich_discovery_book_records(found)

            try:
                with request_budget(time.monotonic() + budget_timeout(6)):
                    related = related_recommendation_answer(message, history, related_search)
            except (BudgetExpired, TimeoutError, OSError, ValueError):
                related = None
            if related is not None:
                related.diagnostics.update(discovery_candidates=related_candidates,
                                           verified_recommendations=len(related.books))
                return related, SimpleNamespace(usage={}, provider='verified-related-books', calls=0)
            from .ai_narrative_answers import goal_answer
            goal = goal_answer(message, history)
            if goal is not None:
                return goal, SimpleNamespace(usage={}, provider='verified-existing-goal-evidence', calls=0)
            from .ai_persistent_router import indexed_answer, research_answer
            with measure_stage('knowledge_lookup'):
                indexed = indexed_answer(message, history, topic_context=topic_context)
            if indexed is not None:
                return indexed, SimpleNamespace(usage={}, provider='verified-indexed-evidence', calls=0)
            # Una petición de contenido tiene que llegar al generador narrativo.
            # Buscar antes con la ruta genérica agotaba las lecturas y podía
            # publicar fragmentos antes de intentar construir la sinopsis.
            from .ai_narrative_answers import narrative_answer
            try:
                narrative = narrative_answer(message, history, config=settings,
                    pending_clarification=pending_clarification)
            except (TimeoutError, OSError, ValueError):
                narrative = None
            if narrative is not None:
                return narrative, SimpleNamespace(usage=narrative.diagnostics.get('usage', {}),
                    provider='verified-narrative-engine', calls=narrative.diagnostics.get('model_calls', 0))
            try:
                researched = research_answer(message, history)
            except (TimeoutError, OSError, ValueError):
                researched = None
            if researched is not None:
                return researched, SimpleNamespace(usage={}, provider='verified-progressive-research', calls=0)
            from .ai_quick_answers import isbn_lookup_answer, quick_answer
            try:
                with request_budget(time.monotonic() + budget_timeout(5)):
                    direct = isbn_lookup_answer(message)
            except (TimeoutError, OSError, ValueError):
                direct = None
            if direct is not None:
                return direct, SimpleNamespace(usage={}, provider='verified-isbn', calls=0)
            direct = quick_answer(message, history, topic_context=topic_context)
            if direct is not None:
                return direct, SimpleNamespace(usage={}, provider='verified-local-facts', calls=0)
            from .literary_research import is_topic_recommendation
            if is_topic_recommendation(retrieval_message):
                from .ai_quick_answers import verified_book_list_answer
                from .literary_search import retrieve_discovery_books
                from .literary_ai import requested_book_count
                from .books_google import topic_matches
                minimum = requested_book_count(message) or 3
                last_discovery = None

                def discovery(query):
                    # No cerrar la fuente lenta con una única ficha local:
                    # aceptar solo cuando ya hay opciones que respaldan el tema.
                    # Se valida contra la consulta temática resuelta, no contra
                    # una elipsis como «otros dos».
                    nonlocal last_discovery

                    def enough(found):
                        return sum(1 for source in found
                                   if source.get('kind') == 'book'
                                   and topic_matches(source, query)) >= minimum
                    last_discovery = retrieve_discovery_books(query, accept=enough)
                    from .literary_search import enrich_discovery_book_records
                    last_discovery = enrich_discovery_book_records(last_discovery)
                    return last_discovery

                try:
                    # Descubrimiento ligero: devuelve en cuanto hay fichas
                    # verificadas y reserva el resto del reloj para razonar.
                    # La espera externa no puede comerse el turno del modelo.
                    discovery_seconds = float(getattr(
                        settings, 'LITMATE_AI_DISCOVERY_SECONDS', 6))
                    # El segundo extra permite validar y redactar la respuesta
                    # local si la fuente llega justo al límite de la búsqueda.
                    with request_budget(time.monotonic() + budget_timeout(discovery_seconds + 1)):
                        direct = quick_answer(message, history, topic_context=topic_context,
                                              search=discovery)
                except BudgetExpired:
                    direct = None
                if direct is not None:
                    direct.diagnostics.update(discovery_candidates=len(last_discovery or []),
                                              verified_recommendations=len(direct.books))
                    return direct, SimpleNamespace(usage={}, provider='verified-discovery', calls=0)
                if last_discovery and any(source.get('kind') == 'book'
                                          for source in last_discovery):
                    # Las fichas ya verificadas se publican sin esperar al
                    # modelo: una lista bibliográfica honesta es preferible a
                    # un turno agotado por una síntesis que no llega.
                    book_direct = verified_book_list_answer(message, last_discovery,
                        history=history, topic_context=topic_context)
                    if book_direct is not None:
                        book_direct.diagnostics.update(discovery_candidates=len(last_discovery),
                                                       verified_recommendations=len(book_direct.books))
                        return book_direct, SimpleNamespace(
                            usage={}, provider='verified-discovery-list', calls=0)
                from .ai_quick_answers import _simple_topic_request
                if (getattr(settings, 'LITMATE_AI_USE_WEB', True)
                        and _simple_topic_request(message, retrieval_message)):
                    from .ai_recommendation_candidates import resolve_recommendation_candidates
                    from .literary_search import retrieve_web
                    try:
                        with request_budget(time.monotonic() + budget_timeout(7)):
                            pages = retrieve_web(retrieval_message)
                            verified = resolve_recommendation_candidates(
                                retrieval_message, pages, retrieve_discovery_books)
                        if verified:
                            book_direct = verified_book_list_answer(message, verified,
                                history=history, topic_context=topic_context)
                            if book_direct is not None:
                                book_direct.diagnostics.update(
                                    discovery_candidates=len(verified),
                                    verified_recommendations=len(book_direct.books),
                                    bibliographic_candidates_from_web=True)
                                return book_direct, SimpleNamespace(
                                    usage={}, provider='verified-web-discovery-list', calls=0)
                    except (BudgetExpired, TimeoutError, OSError, ValueError):
                        pass
                # Recommendations without sufficient verified books continue
                # through the existing model/tool pipeline. Discovery articles
                # are evidence to investigate, not a substitute book response.
            else:
                from .ai_quick_answers import catalogue_lookup_answer
                from .literary_search import retrieve_books
                try:
                    with request_budget(time.monotonic() + budget_timeout(2.5)):
                        direct = catalogue_lookup_answer(message, history, retrieve_books)
                except BudgetExpired:
                    direct = None
                if direct is not None:
                    return direct, SimpleNamespace(usage={}, provider='verified-catalogue', calls=0)
        if getattr(settings, 'LITMATE_AI_BIBLIOGRAPHIC_FAST_PATH', True):
            from .ai_catalog_fallback import bibliographic_answer
            from .literary_search import search_google
            direct = None
            try:
                with request_budget(time.monotonic() + budget_timeout(2.5)):
                    # Identificar con fichas locales antes de intentar leer páginas.
                    from .ai_identification_details import identification_answer
                    if getattr(settings, 'LITMATE_AI_QUICK_ANSWERS', True):
                        from .ai_quick_answers import quick_knowledge_sources
                        direct = identification_answer(message, search=quick_knowledge_sources)
                    else:
                        direct = identification_answer(message)
                    if (direct is None and getattr(settings, 'LITMATE_AI_PUBLIC_DETAILS_FAST_PATH', True)
                            and getattr(settings, 'LITMATE_AI_USE_WEB', True)):
                        from .ai_public_details import character_answer
                        from .literary_search import retrieve_books, retrieve_web
                        if getattr(settings, 'LITMATE_AI_QUICK_ANSWERS', True):
                            direct = character_answer(retrieval_message, history, quick_knowledge_sources, lambda query: [])
                        if direct is None:
                            direct = character_answer(retrieval_message, history, retrieve_books, retrieve_web)
                    if direct is None:
                        direct = bibliographic_answer(retrieval_message, history, search_google)
            except BudgetExpired:
                direct = None
            if direct is not None:
                provider = ('public-book-details' if direct.diagnostics.get('public_details_fast_path')
                            else 'local-identification' if direct.diagnostics.get('local_identification_fast_path')
                            else 'google-books-metadata')
                return direct, SimpleNamespace(usage={}, provider=provider, calls=0)
        check_budget()
        import uuid
        lock_key, owner_token = 'litmate_local_inference_lock', uuid.uuid4().hex
        try:
            # El lease no se libera desde el hilo HTTP cuando vence su espera:
            # hacerlo permitiría inferencias concurrentes con el trabajo tardío.
            lifetime = max(60, min(int(getattr(settings, 'LITMATE_AI_TOTAL_TIMEOUT', 360)), 600)) + 60
            locked = acquire(lock_key, owner_token, lifetime)
            # El socket vencido puede estar cerrándose todavía. Conceder solo
            # milisegundos de limpieza, no una cola de inferencias costosas.
            if not locked:
                time.sleep(min(.04, budget_timeout(.04)))
                check_budget()
                locked = acquire(lock_key, owner_token, lifetime)
        except Exception:
            locked = False
        if not locked:
            raise WorkerBusy()
        try:
            check_budget()
            return _model_answer(message, history, topic_context, retrieval_message)
        finally:
            try:
                release(lock_key, owner_token)
            except Exception:
                logger.warning('IA: no se pudo liberar el turno local')
    finally:
        # Las conexiones creadas por recuperación SQL pertenecen a este hilo.
        close_old_connections()


def _sse(data):
    return 'data: ' + json.dumps(data, ensure_ascii=False, allow_nan=False) + '\n\n'


def _progressive_response(request, state, message, topic_context, start, deadline,
                          request_metrics=None):
    """Abre progreso antes de esperar; ningún worker obtiene request/sesión.

    La respuesta factual se entrega en el POST de finalización, después del
    guardado normal de SessionMiddleware. Así también funcionan signed cookies
    y servidores que consumen el iterador en otro hilo.
    """
    from .ai_stream_jobs import create_job, complete_job, discard_job, JobBusy
    owner = stable_session_owner(request)
    revision = secrets.token_urlsafe(32)
    try:
        token = create_job(owner, revision,
            {'message': message, 'topic_context': topic_context, 'started': start})
    except (JobBusy, OSError, ValueError, sqlite3.Error):
        return JsonResponse({'response': 'Hay solicitudes pendientes. Espera un momento y vuelve a intentar.'}, status=503)
    events = Queue(maxsize=16)
    completed = object()  # Señal interna; nunca es un evento público de progreso.
    cancellation = threading.Event()
    published = threading.Event()

    def publish(event):
        try:
            events.put_nowait(event)
        except Full:
            # Conservar las fases recientes sin crear una cola sin límite ni
            # frenar la búsqueda si el cliente lee lentamente.
            try:
                events.get_nowait()
            except Empty:
                pass
            try:
                events.put_nowait(event)
            except Full:
                pass

    # copy_context captura progress_scope y bounded_research ANTES de que la
    # vista termine. Crear el Future dentro del iterador perdería esos ámbitos.
    try:
        with progress_scope(publish):
            pending = submit_before_deadline(_answer_with_cache, deadline, message,
                copy.deepcopy(state['turns']), copy.deepcopy(topic_context),
                copy.deepcopy(state), owner, request_metrics, start,
                cancellation=cancellation)
    except (WorkerBusy, BudgetExpired):
        discard_job(token, owner)
        response = JsonResponse({'response': 'La IA local está ocupada. Espera un momento y vuelve a intentar.'}, status=503)
        response['Retry-After'] = '5'
        return response

    def wake_stream(_future):
        # Un resultado local puede estar listo mientras get() espera una fase.
        # Avisar al completar el Future evita añadir el intervalo de sondeo a
        # cada respuesta rápida. La señal no adelanta ni publica su contenido.
        publish(completed)

    pending.add_done_callback(wake_stream)
    state['_stream_revision'] = revision
    request.session[HISTORY_KEY] = state
    request.session.modified = True

    def stream():
        ready = False
        try:
            while True:
                remaining = deadline - time.monotonic()
                try:
                    event = events.get(timeout=max(.001, min(.1, remaining)))
                    if event is not completed:
                        yield _sse(event)
                        continue
                except Empty:
                    pass
                if pending.done():
                    result, client = pending.result()
                    break
                if remaining <= 0:
                    cancellation.set()
                    result = ChatResult('Llegué al límite de tiempo sin completar la verificación de esta respuesta. '
                        'No voy a inventar los datos que faltan. Puedes volver a intentarlo.', 'unavailable',
                        diagnostics={'provider_error': 'tiempo_total_agotado'})
                    client = SimpleNamespace(usage={}, provider='deadline', calls=None)
                    break
            result.diagnostics.update(elapsed_ms=round((time.monotonic() - start) * 1000),
                chat_budget_seconds=chat_timeout(settings), model_calls=getattr(client, 'calls', None))
            receipt = {'result': asdict(result), 'client': {
                'provider': str(getattr(client, 'provider', 'local'))[:64],
                'calls': getattr(client, 'calls', None),
                'usage': {key: value for key, value in getattr(client, 'usage', {}).items()
                          if key in {'prompt_tokens', 'completion_tokens', 'total_tokens'}
                          and type(value) is int and value >= 0}}}
            if not complete_job(token, owner, receipt):
                raise ValueError('Trabajo caducado')
            ready = True
            published.set()
            yield _sse({'ready': token})
            yield 'data: [DONE]\n\n'
        except (BudgetExpired, WorkerBusy):
            yield _sse({'error': 'unavailable', 'response': 'No pude completar esta consulta en el tiempo disponible. Vuelve a intentarlo.'})
            yield 'data: [DONE]\n\n'
        except Exception as exc:
            logger.warning('IA: progreso no disponible (%s)', type(exc).__name__)
            yield _sse({'error': 'unavailable', 'response': 'No pude completar la respuesta. Vuelve a intentarlo.'})
            yield 'data: [DONE]\n\n'
        finally:
            if not ready:
                cancellation.set()
                # cancel() no mata un hilo. El worker conserva el slot y el
                # lease hasta su finally real, aunque el cliente desaparezca.
                discard_job(token, owner)

    response = StreamingHttpResponse(stream(), content_type='text/event-stream; charset=utf-8')
    response['Cache-Control'] = 'no-cache, no-store'
    response['X-Accel-Buffering'] = 'no'
    response['X-Content-Type-Options'] = 'nosniff'
    response['X-LitMate-Progress'] = '1'
    def on_close():
        # También cubre clientes que cierran antes de pedir el primer bloque
        # del generador (su finally todavía no se habría ejecutado).
        if not published.is_set():
            cancellation.set()
            discard_job(token, owner)
    response._resource_closers.append(on_close)
    return response


@require_POST
@csrf_protect
def chatbot_finalize(request):
    """Publica un resultado validado y persiste contexto en una petición normal."""
    from .ai_stream_jobs import (claim_finalization, finish_finalization,
                                 JobUnavailable, JobBusy, JobStale)
    if request.content_type != 'application/json':
        return JsonResponse({'response': 'Envía un mensaje JSON válido.'}, status=415)
    try:
        if len(request.body) > 2048:
            raise ValueError()
        data = json.loads(request.body)
        token = data.get('ready') if isinstance(data, dict) else None
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'response': 'No pude leer la solicitud.'}, status=400)
    owner = stable_session_owner(request)
    # Serializar además por la clave de cuota evita carreras entre dos sesiones
    # del mismo usuario/IP. El valor guardado es un hash, nunca la IP en claro.
    from .quotas import generar_clave_cache_cuota
    quota_owner = hashlib.sha256(generar_clave_cache_cuota(request).encode('utf-8')).hexdigest()
    try:
        job = claim_finalization(token, owner, quota_owner=quota_owner)
    except JobUnavailable:
        return JsonResponse({'response': 'La respuesta pendiente caducó o no pertenece a esta sesión. Vuelve a preguntar.'}, status=404)
    except JobStale:
        return JsonResponse({'response': 'La conversación cambió mientras se preparaba esta respuesta. Vuelve a preguntar.'}, status=409)
    except JobBusy:
        response = JsonResponse({'response': 'La respuesta todavía se está preparando o guardando. Vuelve a intentar.'}, status=409)
        response['Retry-After'] = '1'
        return response
    except (OSError, ValueError, sqlite3.Error):
        return JsonResponse({'response': 'El almacenamiento temporal no está disponible. Vuelve a intentar.'}, status=503)
    state = request.session.get(HISTORY_KEY, {})
    if not isinstance(state, dict) or state.get('_stream_revision') != job['revision']:
        body = {'response': 'La conversación cambió. Vuelve a preguntar.'}
        if job['status'] != 'done':
            finish_finalization(token, owner, {'body': body, 'status': 409, 'state': state})
        return JsonResponse(body, status=409)
    if job['status'] == 'done':
        # Un reintento no vuelve a consumir cuota ni duplica MensajeIA. Si se
        # perdió la respuesta HTTP anterior, sí restaura su cookie de sesión.
        final = job['final']
        request.session[HISTORY_KEY] = final['state']
        request.session.modified = True
        return JsonResponse(final['body'], status=final['status'])
    try:
        result = ChatResult(**job['result']['result'])
        client = SimpleNamespace(**job['result']['client'])
        status = 200
        if result.status == 'answered' and getattr(settings, 'LITMATE_USE_EXISTING_QUOTAS', False):
            quota_ok, quota_info = verificar_y_consumir_cuota(request)
            if not quota_ok:
                body = {'error': 'quota_exceeded', 'info_cuota': quota_info,
                        'response': 'Has alcanzado tu límite diario de consultas.'}
                status = 429
            else:
                body = None
        else:
            body = None
        if body is None:
            payload = job['payload']
            elapsed_ms = round((time.monotonic() - payload['started']) * 1000)
            result.diagnostics['elapsed_ms'] = elapsed_ms
            with progress_scope() as progress:
                with measure_stage('finalization'):
                    remember(request, state, payload['message'], result, elapsed_ms, client,
                             topic_context=payload['topic_context'])
                    _memory_trace({**payload['topic_context'].get('_memory_context', {}),
                        'phase': 'G_after_persist', 'function': 'chatbot_finalize/remember',
                        'result_status': result.status, 'turns_after': len(state.get('turns', [])),
                        'active_work_after': state.get('active_work'),
                        'work_order': state.get('work_order', [])})
                final_metrics = snapshot_metrics()
            result.diagnostics['progress_metrics'] = merge_metrics(
                result.diagnostics.get('progress_metrics', {}), final_metrics,
                offset_ms=max(0., (progress['start'] - payload['started']) * 1000))
            from .ai_presentation import build_book_cards
            body = {'response': result.text, 'status': result.status,
                    'books': build_book_cards(result), 'diagnostics': _safe_diagnostics(result, client)}
        final = {'body': body, 'status': status, 'state': copy.deepcopy(state)}
        finish_finalization(token, owner, final)
        return JsonResponse(body, status=status)
    except Exception as exc:
        # La marca finalizing queda cerrada hasta TTL: un reintento tras una
        # caída no puede consumir otra cuota ni duplicar historial persistente.
        logger.warning('IA: finalización no disponible (%s)', type(exc).__name__)
        return JsonResponse({'response': 'No pude guardar la respuesta de forma segura. Vuelve a intentarlo.'}, status=503)


@require_POST
@csrf_protect
@bounded_research
def chatbot_query(request):
    start = time.monotonic()
    deadline = start + chat_timeout(settings)
    if request.content_type != 'application/json':
        return JsonResponse({'response': 'Envía un mensaje JSON válido.'}, status=415)
    try:
        if len(request.body) > 48000:
            return JsonResponse({'response': 'El mensaje es demasiado grande.'}, status=413)
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'response': 'No pude leer el mensaje.'}, status=400)
    message = data.get('message') if isinstance(data, dict) else None
    if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE:
        return JsonResponse({'response': f'Escribe un mensaje de hasta {MAX_MESSAGE} caracteres.'}, status=400)
    message = message.strip()
    # Reutilizar la consulta original cuando el usuario pide reintentar.
    _retry_patterns = ('busca nuevamente', 'intenta otra vez', 'busca más información',
                       'investiga mejor', 'explícamelo mejor', 'dame más detalles',
                       'intentalo otra vez')
    _normalized_msg = message.lower()
    if any(pattern in _normalized_msg for pattern in _retry_patterns):
        _state = request.session.get(HISTORY_KEY, {})
        _pending = _state.get('pending_clarification') if isinstance(_state, dict) else None
        if isinstance(_pending, dict) and _pending.get('original_query'):
            message = _pending['original_query']
        elif isinstance(_state, dict) and _state.get('turns'):
            _last = _state['turns'][-1]
            if isinstance(_last, dict) and _last.get('question'):
                message = _last['question']
    run_id = secrets.token_hex(8)
    if not rate_allowed(request):
        response = JsonResponse({'response': 'Has enviado demasiadas solicitudes. Espera un minuto.'}, status=429)
        response['Retry-After'] = '60'
        return response
    if obvious_rejection(message):
        return stream_result(ChatResult(REFUSAL, 'rejected'))
    social = local_social(message)
    if social:
        return stream_result(ChatResult(social, 'social'))
    if getattr(settings, 'LITMATE_USE_EXISTING_QUOTAS', False):
        quota_ok, quota_info = cuota_disponible(request)
        if not quota_ok:
            response = JsonResponse({'error': 'quota_exceeded', 'info_cuota': quota_info,
                'response': 'Has alcanzado tu límite diario de consultas.'}, status=429)
            retry = quota_info.get('segundos_reinicio')
            if isinstance(retry, int) and retry > 0:
                response['Retry-After'] = str(retry)
            return response
    # No forzar aquí una escritura extra: SessionMiddleware guarda la sesión
    # modificada antes de consumir el stream, así que el historial sigue
    # disponible y se evita duplicar la latencia de MySQL/TiDB.
    owner = 'user:' + str(request.user.pk) if request.user.is_authenticated else 'anonymous'
    memory_context = ({'run_id': run_id, 'conversation': stable_session_owner(request)[:16]}
                      if _memory_trace_enabled() else {})
    _memory_trace({**memory_context, 'phase': 'A_before_load', 'message': message})
    with progress_scope() as progress:
        with measure_stage('conversation'):
            state = request.session.get(HISTORY_KEY, {})
            if (not isinstance(state, dict) or state.get('owner') != owner
                    or not isinstance(state.get('turns'), list)):
                state = {'owner': owner, 'turns': []}
            # Backward compatibility for sessions predating explicit focus.
            if not state.get('active_work') and isinstance(state.get('turns'), list) and state['turns']:
                last = state['turns'][-1]
                books = last.get('books') if isinstance(last, dict) else None
                from .literary_research import is_topic_recommendation
                if (last.get('intent') != 'recommend' and not is_topic_recommendation(last.get('question', ''))
                        and isinstance(books, list) and len(books) == 1 and isinstance(books[0], dict)):
                    book = books[0]
                    identity = {key: book.get(key) for key in
                                ('work_id', 'title', 'author', 'confirmed_aliases', 'isbns')
                                if book.get(key) is not None}
                    if identity.get('title'):
                        state['active_work'] = identity
            turns_before = list(state.get('turns', []))
            active_before = copy.deepcopy(state.get('active_work'))
            from .literary_focus import prepare_focus
            prepare_focus(state, message)
            topic_context = resolve_topic_context(message, state)
            if memory_context:
                memory_context['turn'] = state.get('_trace_turn', 0) + 1
                state['_trace_turn'] = memory_context['turn']
                topic_context['_memory_context'] = memory_context
        request_metrics = merge_metrics({}, snapshot_metrics(),
            offset_ms=max(0., (progress['start'] - start) * 1000))
    _memory_trace({**memory_context, 'phase': 'B_after_load', 'turns_before': len(turns_before),
                   'active_work_before': active_before, 'active_work_selected': state.get('active_work'),
                   'history_questions': [turn.get('question') for turn in turns_before],
                   'topic_context': topic_context})
    _memory_trace({**memory_context, 'phase': 'C_before_answer'})
    if remember_topic(state, message, topic_context):
        # La intención del lector existe aunque falle el proveedor.
        # Se conserva aparte del historial de respuestas aceptadas.
        request.session[HISTORY_KEY] = state
        request.session.modified = True
    if data.get('progress') is True:
        return _progressive_response(request, state, message, topic_context, start, deadline,
                                     request_metrics=request_metrics)
    try:
        result, client = run_before_deadline(_answer_with_cache, deadline, message, state['turns'], topic_context,
                                             dict(state), stable_session_owner(request), request_metrics, start)
    except WorkerBusy:
        response = JsonResponse({'response': 'La IA local está ocupada. Espera un momento y vuelve a intentar.'}, status=503)
        response['Retry-After'] = '5'
        return response
    except BudgetExpired:
        # El problema es técnico, no una supuesta ambigüedad de una petición clara.
        result = ChatResult('Llegué al límite de tiempo sin completar la verificación de esta respuesta. '
                            'No voy a inventar los datos que faltan. Puedes volver a intentarlo.',
                            'unavailable', diagnostics={'provider_error': 'tiempo_total_agotado'})
        # El cliente del trabajo que venció no se devuelve al hilo HTTP. No
        # inventar «cero inferencias»: el número real aquí es desconocido.
        client = SimpleNamespace(usage={}, provider='deadline', calls=None)
    except (TypeError, ValueError):
        return JsonResponse({'response': 'Revisa los valores de configuración de la IA local.'}, status=503)
    # También las rutas rápidas respetan cuotas, sin desactivarse al habilitarlas.
    if result.status == 'answered' and getattr(settings, 'LITMATE_USE_EXISTING_QUOTAS', False):
        quota_ok, quota_info = verificar_y_consumir_cuota(request)
        if not quota_ok:
            return JsonResponse({'error': 'quota_exceeded', 'info_cuota': quota_info,
                'response': 'Has alcanzado tu límite diario de consultas.'}, status=429)
    elapsed_ms = round((time.monotonic() - start) * 1000)
    result.diagnostics.update(elapsed_ms=elapsed_ms, chat_budget_seconds=chat_timeout(settings),
                              model_calls=getattr(client, 'calls', 0))
    remember(request, state, message, result, elapsed_ms, client, topic_context=topic_context)
    _state_after = request.session.get(HISTORY_KEY, {})
    _memory_trace({**memory_context, 'phase': 'G_after_persist', 'result_status': result.status,
                   'turns_after': len(_state_after.get('turns', [])),
                   'active_work_after': _state_after.get('active_work')})
    response = stream_result(result)
    response['Server-Timing'] = f'chat;dur={elapsed_ms}'
    response['X-LitMate-Status'] = result.status
    calls = getattr(client, 'calls', None)
    if type(calls) is int:
        response['X-LitMate-Model-Calls'] = str(calls)
    return response


@require_POST
@csrf_protect
def voice_query(request):
    """La voz es opcional y externa; comparte los límites de recursos del asistente."""
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'Envía el texto como JSON.'}, status=415)
    try:
        if len(request.body) > 16000:
            return JsonResponse({'error': 'El texto es demasiado largo para la voz.'}, status=413)
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'No pude leer el texto.'}, status=400)
    text = data.get('text') if isinstance(data, dict) else None
    if not isinstance(text, str) or not text.strip() or len(text) > 3500:
        return JsonResponse({'error': 'Envía entre 1 y 3500 caracteres.'}, status=400)
    if not getattr(settings, 'LITMATE_TTS_ENABLED', False):
        return JsonResponse({'error': 'La voz externa está desactivada en este servidor.'}, status=503)
    identity = ('u:' + str(request.user.pk) if request.user.is_authenticated
                else 'ip:' + request.META.get('REMOTE_ADDR', ''))
    key = 'ai_voice_rate:' + hashlib.sha256(identity.encode()).hexdigest() + ':' + str(int(time.time()) // 60)
    try:
        if rate_increment(key, 120) > 5:
            response = JsonResponse({'error': 'Espera un minuto antes de generar más audio.'}, status=429)
            response['Retry-After'] = '60'
            return response
    except Exception:
        return JsonResponse({'error': 'La voz no está disponible ahora.'}, status=503)
    from .services_voice import (obtener_audio_miku, VoiceInputError, VoiceUnavailable,
                                 VoiceBusy, VoiceServiceError)
    try:
        return JsonResponse({'status': 'ok', 'audio_url': obtener_audio_miku(text)})
    except VoiceInputError:
        return JsonResponse({'error': 'El texto no es válido para generar audio.'}, status=400)
    except VoiceBusy:
        response = JsonResponse({'error': 'La voz está ocupada. Vuelve a intentar.'}, status=503)
        response['Retry-After'] = '5'
        return response
    except (VoiceUnavailable, VoiceServiceError):
        return JsonResponse({'error': 'No pude generar la voz. Puedes seguir leyendo la respuesta.'}, status=503)
