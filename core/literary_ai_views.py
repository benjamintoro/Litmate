"""Endpoint de IA compatible con el chat principal y el flotante existentes."""
import hashlib
import json
import logging
import time
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
from .quotas import verificar_y_consumir_cuota
from .ai_concurrency import acquire, release, rate_increment
from .ai_budget import request_budget, BudgetExpired
from .literary_sources import bounded_research
from .literary_conversation import resolve_topic_context, remember_topic

logger = logging.getLogger('litmate')
HISTORY_KEY = 'litmate_literary_chat_local_v1'


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
        if topic_changed:
            # Guardar la petición permite continuar tras un fallo. No guardar el
            # borrador rechazado como respuesta ni convertirlo en evidencia.
            request.session[HISTORY_KEY] = state
            request.session.modified = True
        return
    from .literary_identity import work_identity
    records = {source.get('id'): source for source in result.sources}
    remembered_books = []
    for book in result.books:
        source = records.get(book.get('source_id'), book)
        remembered_books.append({**book, **work_identity(source),
                                'source': source.get('source', ''), 'url': source.get('url', '')})
    turn = {'accepted': True, 'question': message, 'answer': result.text[:5000],
            'sources': result.sources[:8], 'books': remembered_books, 'basis': result.basis}
    if len(remembered_books) == 1:
        state['active_work'] = work_identity(remembered_books[0])
    elif remembered_books:
        state.pop('active_work', None)
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


@require_POST
@csrf_protect
@bounded_research
def chatbot_query(request):
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
    if not rate_allowed(request):
        response = JsonResponse({'response': 'Has enviado demasiadas solicitudes. Espera un minuto.'}, status=429)
        response['Retry-After'] = '60'
        return response
    if obvious_rejection(message):
        return stream_result(ChatResult(REFUSAL, 'rejected'))
    social = local_social(message)
    if social:
        return stream_result(ChatResult(social, 'social'))
    if not request.session.session_key:
        request.session.save()
    owner = 'user:' + str(request.user.pk) if request.user.is_authenticated else 'anonymous'
    state = request.session.get(HISTORY_KEY, {})
    if (not isinstance(state, dict) or state.get('owner') != owner
            or not isinstance(state.get('turns'), list)):
        state = {'owner': owner, 'turns': []}
    topic_context = resolve_topic_context(message, state)
    if remember_topic(state, message, topic_context):
        # La intención del lector existe aunque falle el proveedor.
        # Se conserva aparte del historial de respuestas aceptadas.
        request.session[HISTORY_KEY] = state
        request.session.modified = True
    retrieval_message = (topic_context['query'] if topic_context.get('followup')
                         and topic_context.get('intent') == 'recommend' else message)
    if (getattr(settings, 'LITMATE_AI_BIBLIOGRAPHIC_FAST_PATH', True)
            and not getattr(settings, 'LITMATE_USE_EXISTING_QUOTAS', False)):
        from .ai_catalog_fallback import bibliographic_answer
        from .literary_search import search_google
        from types import SimpleNamespace
        fast_start = time.monotonic()
        try:
            with request_budget(fast_start + 25):
                direct = None
                if (getattr(settings, 'LITMATE_AI_PUBLIC_DETAILS_FAST_PATH', True)
                        and getattr(settings, 'LITMATE_AI_USE_WEB', True)):
                    from .ai_public_details import character_answer
                    from .literary_search import retrieve_books, retrieve_web
                    direct = character_answer(retrieval_message, state['turns'], retrieve_books, retrieve_web)
                if direct is None:
                    direct = bibliographic_answer(retrieval_message, state['turns'], search_google)
        except BudgetExpired:
            direct = None
        if direct is not None:
            remember(request, state, message, direct, round((time.monotonic() - fast_start) * 1000),
                     SimpleNamespace(usage={}, provider='public-book-details' if direct.diagnostics.get(
                         'public_details_fast_path') else 'google-books-metadata', calls=0),
                     topic_context=topic_context)
            return stream_result(direct)
    # SQLite coordina los procesos de un PC; Redis permite compartir el lease entre máquinas.
    import uuid
    lock_key, owner_token = 'litmate_local_inference_lock', uuid.uuid4().hex
    try:
        lifetime = max(60, min(int(getattr(settings, 'LITMATE_AI_TOTAL_TIMEOUT', 360)), 600)) + 60
        locked = acquire(lock_key, owner_token, lifetime)
    except Exception:
        locked = False
    if not locked:
        response = JsonResponse({'response': 'La IA local está ocupada. Espera un momento y vuelve a intentar.'}, status=503)
        response['Retry-After'] = '5'
        return response
    try:
        try:
            assistant, client = build_assistant(settings)
        except (TypeError, ValueError):
            return JsonResponse({'response': 'Revisa los valores de configuración de la IA local.'}, status=503)
        start = time.monotonic()
        result = assistant.reply(message, state['turns'], topic_context=topic_context)
        if result.status == 'unavailable':
                logger.warning('IA: respuesta pendiente (%s)',
                           result.diagnostics.get('provider_error') or
                           result.diagnostics.get('validation_error') or 'quality_check_failed')
        if result.status == 'unavailable' and getattr(settings, 'LITMATE_AI_CATALOG_FALLBACK', True):
            from .ai_catalog_fallback import catalog_fallback
            from .literary_search import search_google
            try:
                with request_budget(getattr(client, 'deadline', start + 20)):
                    fallback = catalog_fallback(retrieval_message, state['turns'], search_google,
                        failure_reason=result.diagnostics.get('provider_error', 'quality_check_failed'))
            except BudgetExpired:
                fallback = None
            if fallback is not None:
                fallback.diagnostics['original_failure'] = result.diagnostics
                result = fallback
        # No se cobra una cuota por ocupado, fallo del proveedor o borrador rechazado.
        if result.status == 'answered' and getattr(settings, 'LITMATE_USE_EXISTING_QUOTAS', False):
            quota_ok, quota_info = verificar_y_consumir_cuota(request)
            if not quota_ok:
                return JsonResponse({'error': 'quota_exceeded', 'info_cuota': quota_info,
                    'response': 'Has alcanzado tu límite diario de consultas.'}, status=429)
        remember(request, state, message, result, round((time.monotonic()-start)*1000), client,
                 topic_context=topic_context)
    finally:
        try:
            release(lock_key, owner_token)
        except Exception:
            logger.warning('IA: no se pudo liberar el turno local')
    return stream_result(result)


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
