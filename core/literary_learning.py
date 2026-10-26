"""Actualización literaria incremental y señales agregadas, sin entrenar un LLM.

El trabajador sólo recibe identidades del almacén auxiliar. Nunca guarda una
pregunta, respuesta, nombre de usuario ni borrador del modelo. La utilidad de
un proveedor sirve para ordenar herramientas ya autorizadas; no verifica hechos.
"""
import math
import os
import re
import time
import uuid

from .ai_budget import request_budget
from .literary_identity import bind_source, same_work, work_identity
from .literary_sources import error_status, research_scope


DEFAULT_PROVIDERS = ('openlibrary', 'wikidata')
PROVIDERS = (*DEFAULT_PROVIDERS, 'wikipedia')
REQUIREMENTS = frozenset({'', 'author', 'characters', 'character_detail', 'summary',
    'identification', 'relationships', 'events', 'ending', 'themes', 'metadata', 'recommend',
    'plot', 'identify', 'book_identity', 'publication', 'synopsis', 'bibliography',
    'recommendation', 'content', 'comparison', 'scenes', 'exact_passage'})
_FAILURE_CODES = frozenset({'empty', 'unavailable', 'timeout', 'rate_limited', 'cooldown',
    'invalid_response', 'access_denied', 'unauthorized', 'budget_exhausted',
    'no_verified_match', 'not_permitted', 'no_evidence', 'invalid_identity'})


def provider_order(stats, *, requirement='', eligible=DEFAULT_PROVIDERS):
    """Reordena herramientas, nunca fuentes o afirmaciones por popularidad.

    Con menos de ocho verificaciones/fallos conserva el orden original. La
    contribución está acotada a +/-0,15 y la latencia sólo desempata en 0,01.
    Un ``hit`` de caché no se convierte en evidencia de exactitud factual.
    ``verified`` conserva el nombre histórico del contador de comprobaciones
    de fuente/identidad/cobertura; no acredita verdad independiente, calidad
    de una respuesta LLM ni etiquetas para entrenar un modelo de ranking.
    """
    if requirement not in REQUIREMENTS:
        raise ValueError('Tipo de evidencia no admitido')
    allowed = tuple(dict.fromkeys(provider for provider in eligible if provider in PROVIDERS))
    totals = {provider: [0, 0, 0.0] for provider in allowed}
    for row in stats if isinstance(stats, list) else []:
        if (not isinstance(row, dict) or row.get('provider') not in totals
                or (requirement and row.get('requirement') != requirement)):
            continue
        try:
            verified = max(0, min(int(row.get('verified', 0)), 1_000_000))
            failures = max(0, min(int(row.get('failures', 0)), 1_000_000))
            latency = float(row.get('total_latency', 0))
            if not math.isfinite(latency) or latency < 0:
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        totals[row['provider']][0] += verified
        totals[row['provider']][1] += failures
        totals[row['provider']][2] += min(latency, 1_000_000)
    scores = {}
    for provider, (verified, failures, latency) in totals.items():
        measured = verified + failures
        scores[provider] = (max(-.15, min(.15, (verified + 1) / (measured + 2) - .5))
            - min(.01, latency / max(1, measured) / 10000)) if measured >= 8 else 0
    return sorted(allowed, key=lambda provider: (-scores[provider], allowed.index(provider)))


def prioritize_works(works, stats, *, maximum=5):
    """Prioriza la actualización por demanda agregada, sin cambiar su verdad."""
    maximum = max(1, min(int(maximum), 100))
    demand = {}
    for row in stats if isinstance(stats, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get('work_id'), str):
            continue
        try:
            hits = max(0, min(int(row.get('hits', 0)), 1_000_000))
            failures = max(0, min(int(row.get('failures', 0)), 1_000_000))
        except (TypeError, ValueError, OverflowError):
            continue
        demand[row['work_id']] = demand.get(row['work_id'], 0) + hits + failures
    candidates = [work for work in works if isinstance(work, dict) and work_identity(work)]
    candidates.sort(key=lambda work: (-math.log1p(demand.get(work.get('work_id'), 0)),
                                     str(work.get('work_id', ''))))
    return candidates[:maximum]


def _covers_requirement(work, books, sources, requirement):
    """Un registro bibliográfico no satisface preguntas sobre la narración."""
    matching = [source for source in sources if isinstance(source, dict) and same_work(source, work)]
    if not any(same_work(book, work) for book in books) or not matching:
        return False
    if requirement in {'', 'metadata', 'author', 'bibliography', 'book_identity'}:
        return True
    if requirement in {'themes', 'recommend', 'recommendation'}:
        return any(source.get('categories') for source in matching)
    # Las materias/identificadores de un catálogo no son una sinopsis ni
    # prueban escenas, personajes o relaciones.
    narrative = [source for source in matching if source.get('policy') !=
                 'openlibrary-minimal-metadata-v1' and (source.get('kind') == 'web'
                 or source.get('policy') == 'curated-original-v1')]
    if not narrative:
        return False
    if requirement in {'summary', 'synopsis', 'plot', 'identification', 'identify'}:
        return any(len(str(source.get('description', ''))) >= 60 for source in narrative)
    from .literary_research import assess_evidence
    from .literary_ai import canonical_sources
    if requirement in {'characters', 'character_detail', 'relationships'}:
        # P674 proves membership, not a narrative role. Keeping that admitted
        # statement in memory must not complete a job asking for useful roles.
        narrative = [{**source, 'character_facts': [fact for fact in source.get('character_facts', [])
            if isinstance(fact, dict) and not fact.get('membership_only') and not re.search(
                r'personaje registrado|registered character|character (?:listed|registered) for this work',
                str(fact.get('role', '')), re.I)]} for source in narrative]
    prompts = {'characters': 'Dime los personajes de ', 'character_detail': 'Dime los personajes de ',
        'relationships': 'Explica la relación entre los personajes de ',
        'events': 'Qué sucede en ', 'ending': 'Cómo termina ', 'scenes': 'Describe escenas de ',
        'content': 'Explica el contenido de '}
    if requirement not in prompts:
        return False
    evidence = canonical_sources([*books, *narrative], 12)
    return assess_evidence(prompts[requirement] + work['title'], evidence,
                           selected_books=[work], intent='analysis')['sufficient']


def schedule_known_works(*, database=None, maximum=5, requirement='metadata', provider='openlibrary'):
    """Encola sólo identidades existentes cuya evidencia ya no está vigente.

    No es un rastreador de internet: el inventario es bibliográfico y la cola
    conserva identificador/requisito/proveedor, nunca la pregunta del lector.
    """
    if requirement not in REQUIREMENTS or provider not in PROVIDERS:
        raise ValueError('Herramienta o evidencia no admitida')
    from .literary_memory import list_works, usage_stats, retrieve_evidence, enqueue_refresh
    maximum = max(1, min(int(maximum), 100))
    works = prioritize_works(list_works(database=database, limit=1000),
                             usage_stats(database=database), maximum=100)
    jobs = []
    for work in works:
        fresh_books, fresh_sources = retrieve_evidence(work['title'], books=[work],
            requirement=requirement, database=database, limit=8)
        if _covers_requirement(work, fresh_books, fresh_sources, requirement):
            continue
        identifier = enqueue_refresh(work['work_id'], requirement, provider,
            priority=max(0, 100 - len(jobs)), database=database)
        if identifier:
            jobs.append(identifier)
        if len(jobs) >= maximum:
            break
    return jobs


def _bibliographic_query(work, provider):
    from .books_google import public_query
    identity = work_identity(work)
    if not identity:
        raise ValueError('invalid_identity')
    parts = [identity['title'], identity['author']]
    # Si la sanitización detecta datos privados se descarta la identidad en
    # lugar de consultar una versión incompleta que podría ser otra obra.
    if any(public_query(part) != part or '\n' in part or '"' in part for part in parts):
        raise ValueError('invalid_identity')
    query = (f'title:"{parts[0]}" author:"{parts[1]}"' if provider == 'openlibrary'
             else f'"{parts[0]}" {parts[1]}' if provider == 'wikipedia'
             else parts[0])
    if len(query) > 240:
        raise ValueError('invalid_identity')
    return query


def _fetch_public_metadata(work, provider):
    query = _bibliographic_query(work, provider)
    if provider == 'openlibrary':
        from .literary_search import search_openlibrary
        return search_openlibrary(query, details=False)
    if provider == 'wikidata':
        from .literary_wikidata import search_wikidata
        return search_wikidata(query)
    if provider == 'wikipedia':
        from .literary_search import search_wikipedia
        return search_wikipedia(query)
    raise ValueError('not_permitted')


def run_refresh_batch(*, database=None, max_jobs=2, max_seconds=30, job_seconds=8,
                      pause_seconds=1, worker_id=None, fetch=None, clock=None, sleeper=None):
    """Procesa una cola durable con concurrencia global uno y HTTP acotado.

    No descarga novelas, no usa inferencia/embeddings y no bloquea Django. Un
    proceso detenido deja leases que otro trabajador puede recuperar al vencer.
    CPU/red: hasta 20 tareas, 120 s por lote, 12 s por tarea y una pausa >=1 s.
    El adaptador de cada fuente mantiene además sus límites HTTP existentes.
    Wikipedia sólo puede consultar su introducción oficial: ``pages=0`` impide
    leer artículos completos o tablas. Sin evidencia suficiente se reprograma;
    no se amplía el permiso de almacenamiento ni se inventan roles.
    """
    from .literary_memory import (claim_job, get_work, remember_evidence,
        finish_job, fail_job, record_use, retrieve_evidence, ERRORS)
    max_jobs = max(1, min(int(max_jobs), 20))
    max_seconds = max(1.0, min(float(max_seconds), 120.0))
    job_seconds = max(1.0, min(float(job_seconds), 12.0))
    pause_seconds = max(1.0, min(float(pause_seconds), 30.0))
    if not all(math.isfinite(value) for value in (max_seconds, job_seconds, pause_seconds)):
        raise ValueError('Presupuestos de tiempo inválidos')
    worker_id = worker_id or 'literary-' + uuid.uuid4().hex[:16]
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', worker_id):
        raise ValueError('Identificador de trabajador inválido')
    clock, sleeper = clock or time.monotonic, sleeper or time.sleep
    fetch = fetch or _fetch_public_metadata
    start = clock()
    report = {'claimed': 0, 'completed': 0, 'deferred': 0, 'stored': 0,
              'seconds': 0.0, 'jobs': [], 'llm_calls': 0,
              'verification_scope': 'source_policy_identity_and_requirement_coverage',
              'independent_factual_corroboration': False}
    for index in range(max_jobs):
        remaining = max_seconds - (clock() - start)
        if remaining < 1:
            break
        job = claim_job(worker_id, lease_seconds=max(30, int(job_seconds) + 10), database=database)
        if not job:
            break
        report['claimed'] += 1
        identifier = job.get('job_id') or job['id']
        token = job['lease_token']
        provider, requirement = job.get('provider'), job.get('requirement', '')
        started = clock()
        code, stored = 'unavailable', 0
        try:
            if provider not in PROVIDERS or requirement not in REQUIREMENTS:
                raise ValueError('not_permitted')
            work = get_work(job['work_id'], database=database)
            if not work:
                raise ValueError('invalid_identity')
            _bibliographic_query(work, provider)
            # Monotonic real es también el reloj usado por los sockets y el
            # guardián HTTP. El reloj inyectado sólo mide/prueba el planificador.
            with request_budget(time.monotonic() + min(job_seconds, remaining)):
                with research_scope(maximum=2, seconds=min(job_seconds, remaining), pages=0):
                    found = fetch(work, provider)
                    status = getattr(found, 'status', 'ok' if found else 'empty')
                    if status not in {'ok', 'partial'}:
                        code = status if status in _FAILURE_CODES else 'unavailable'
                    else:
                        matching = [bind_source(source, work) if source.get('kind') == 'web' else source
                                    for source in found[:12] if isinstance(source, dict)
                                    and same_work(source, work)]
                        if matching:
                            counts = remember_evidence([work], matching, database=database)
                            stored = counts.get('sources', 0)
                            if type(stored) is not int or stored < 0:
                                stored = 0
                            code = 'not_permitted'
                            if stored:
                                cached_books, cached_sources = retrieve_evidence(work['title'],
                                    books=[work], requirement=requirement, database=database, limit=8)
                                code = ('ok' if _covers_requirement(work, cached_books, cached_sources,
                                                                   requirement) else 'no_evidence')
                        else:
                            code = 'no_verified_match'
        except Exception as exc:
            message = str(exc)
            code = message if message in _FAILURE_CODES else error_status(exc)
            if code not in _FAILURE_CODES:
                code = 'unavailable'
        elapsed = max(0.0, clock() - started)
        if code == 'ok':
            accepted = finish_job(identifier, lease_token=token, database=database)
            if accepted:
                record_use(job['work_id'], requirement, 'verified', provider=provider,
                           latency=elapsed, database=database)
                report['completed'] += 1
                report['stored'] += stored
        else:
            backoff = min(3600, 60 * (2 ** min(int(job.get('attempts', 1)), 5)))
            if code in {'empty', 'no_verified_match', 'not_permitted', 'no_evidence'}:
                backoff = max(900, backoff)
            stored_code = code if code in ERRORS else 'unavailable'
            accepted = fail_job(identifier, lease_token=token, retry_after=backoff,
                                error_code=stored_code, database=database)
            if accepted:
                record_use(job['work_id'], requirement, 'failed', provider=provider,
                           latency=elapsed, database=database)
                report['deferred'] += 1
                # Admitted introductory content can be useful even when it
                # does not satisfy this job's character-specific requirement.
                report['stored'] += stored
        # Ningún texto remoto o excepción se introduce en logs persistentes.
        report['jobs'].append({'work_id': job['work_id'], 'provider': provider,
            'requirement': requirement, 'status': code, 'lease_current': bool(accepted),
            'seconds': round(elapsed, 3), 'stored': stored if accepted else 0})
        if index + 1 < max_jobs:
            wait = min(pause_seconds, max(0.0, max_seconds - (clock() - start)))
            if wait > 0:
                sleeper(wait)
    report['seconds'] = round(max(0.0, clock() - start), 3)
    return report


def lower_worker_priority():
    """Prioridad inferior para un comando separado; nunca altera el servidor."""
    try:
        if os.name == 'nt':
            import ctypes
            return bool(ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000))
        if hasattr(os, 'nice'):
            os.nice(5)
            return True
    except (OSError, AttributeError):
        pass
    return False
