"""Contratos de recuperación gratuitos; errores nunca equivalen a ausencia de datos."""
import time
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import wraps
from urllib.error import HTTPError, URLError

_scope = ContextVar('litmate_research_scope', default=None)


@contextmanager
def research_scope(maximum=2, seconds=15, pages=3):
    """Comparte límites entre ruta rápida, modelo, auditoría y sus hilos."""
    existing = _scope.get()
    if existing is not None:
        yield existing
        return
    value = {'searches': 0, 'pages': 0, 'seconds': 0.0,
             'maximum': max(0, min(int(maximum), 2)),
             'timeout': max(1, min(float(seconds), 30)),
             'max_pages': max(0, min(int(pages), 3)), 'lock': threading.Lock(),
             'events': []}
    token = _scope.set(value)
    try:
        yield value
    finally:
        _scope.reset(token)


def reserve_search():
    state = _scope.get()
    if state is None:
        return 15.0
    with state['lock']:
        remaining = state['timeout'] - state['seconds']
        if state['searches'] >= state['maximum'] or remaining <= 0:
            return 0.0
        state['searches'] += 1
        return remaining


def account_research(seconds):
    state = _scope.get()
    if state is not None:
        with state['lock']:
            state['seconds'] += max(0, seconds)


def reserve_page():
    state = _scope.get()
    if state is None:
        return True
    with state['lock']:
        if state['pages'] >= state['max_pages']:
            return False
        state['pages'] += 1
        return True


def record_research_event(stage, provider, status, *, count=0):
    """Diagnóstico de operaciones, sin consultas, URLs ni contenido del lector."""
    if stage in {'http_request', 'page_read'} and status == 'started':
        from .ai_progress import emit_phase
        emit_phase('search')
    state = _scope.get()
    if state is None:
        return
    # Los identificadores pertenecen al código, nunca a respuestas remotas.
    stages = {'http_request', 'page_read', 'cache_hit', 'supplementary_synopsis'}
    providers = {'Open Library', 'Google Books', 'SearXNG', 'Wikipedia', 'DuckDuckGo', 'web'}
    statuses = {'started', 'ok', 'empty', 'partial', 'cached', 'disabled',
                'unavailable', 'timeout', 'rate_limited', 'invalid_response',
                'access_denied', 'unauthorized', 'cooldown', 'budget_exhausted',
                'robots_denied', 'robots_unavailable', 'unsupported_type',
                'no_verified_match', 'invalid_json'}
    if stage not in stages or provider not in providers:
        return
    event = {'stage': stage, 'provider': provider,
             'status': status if status in statuses else 'unavailable',
             'count': max(0, min(int(count), 20))}
    with state['lock']:
        if len(state['events']) < 80:
            state['events'].append(event)


def research_snapshot():
    """Copia serializable: reservar una página no equivale a haberla leído."""
    state = _scope.get()
    if state is None:
        return {}
    with state['lock']:
        events = [dict(event) for event in state['events']]
        return {'logical_searches': state['searches'], 'page_slots_reserved': state['pages'],
                'external_seconds': round(state['seconds'], 3), 'events': events,
                'http_requests_started': sum(event['stage'] == 'http_request'
                                             and event['status'] == 'started' for event in events),
                'pages_extracted': sum(event['count'] for event in events
                                       if event['stage'] == 'page_read' and event['status'] == 'ok')}


def bounded_research(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        from django.conf import settings
        with research_scope(getattr(settings, 'LITMATE_RESEARCH_MAX_SEARCHES', 2),
                            getattr(settings, 'LITMATE_RESEARCH_TIMEOUT', 15),
                            getattr(settings, 'LITMATE_RESEARCH_MAX_PAGES', 3)):
            return function(*args, **kwargs)
    return wrapped


class SearchResults(list):
    def __init__(self, items=(), *, status='ok', providers=None):
        super().__init__(items)
        self.status = status if items or status != 'ok' else 'empty'
        self.providers = providers or {}


def error_status(error):
    code = getattr(error, 'code', '')
    mapped = {'http_403': 'access_denied', 'http_401': 'unauthorized',
              'service_unavailable': 'unavailable', 'connection_failed': 'unavailable',
              'dns_failed': 'unavailable', 'dns_busy': 'unavailable'}
    if code in mapped:
        return mapped[code]
    if code in {'timeout', 'rate_limited', 'access_denied', 'unavailable', 'invalid_response',
                'robots_denied', 'robots_unavailable', 'unsupported_type', 'budget_exhausted'}:
        return code
    if isinstance(error, HTTPError):
        return {429: 'rate_limited', 403: 'access_denied', 401: 'unauthorized'}.get(
            error.code, 'unavailable')
    if isinstance(error, (TimeoutError,)):
        return 'timeout'
    if isinstance(error, URLError) and isinstance(error.reason, TimeoutError):
        return 'timeout'
    return 'invalid_response' if isinstance(error, (ValueError, TypeError)) else 'unavailable'


def _retry_after_seconds(value):
    """Segundos de Retry-After; admite la forma numérica y la fecha HTTP."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        pass
    try:
        target = parsedate_to_datetime(text)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return int((target - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def cooldown_seconds(error):
    """Pausa mínima para respetar un límite remoto.

    ``PublicFetchError`` conserva el Retry-After del 429; los errores de
    urllib lo exponen en ``headers``. El mínimo de 5 s evita una ráfaga de
    reintentos cuando el servidor no informa un plazo.
    """
    retry_after = getattr(error, 'retry_after', None)
    if retry_after is not None:
        seconds = _retry_after_seconds(retry_after)
        if seconds is not None:
            return max(5, min(seconds, 600))
    if isinstance(error, HTTPError):
        seconds = _retry_after_seconds(error.headers.get('Retry-After'))
        if seconds is not None:
            return max(5, min(seconds, 600))
    return 30
