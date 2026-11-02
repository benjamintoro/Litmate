"""Mediciones y fases reales de una consulta, sin guardar texto del lector.

El contexto se comparte deliberadamente entre los trabajadores de la misma
consulta mediante ``copy_context``. Los callbacks nunca frenan una búsqueda.
"""
import threading
import time
import math
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps


_current = ContextVar('litmate_ai_progress', default=None)
_MESSAGES = {'search': 'Buscando información y consultando fuentes...',
             'review': 'Verificando los datos de la respuesta...',
             'writing': 'Preparando mi respuesta...'}
_NAMES = frozenset({'intent', 'conversation', 'local_search', 'web_search',
                    'extraction', 'semantic_retrieval', 'generation', 'audit',
                    'repair', 'delivery', 'model_inspection', 'knowledge_lookup',
                    'cache_lookup', 'retrieval', 'routing', 'finalization'})


@contextmanager
def progress_scope(callback=None):
    """Abre una consulta o reutiliza su contexto al entrar desde otro servicio."""
    existing = _current.get()
    if existing is not None:
        yield existing
        return
    state = {'start': time.monotonic(), 'callback': callback,
             'lock': threading.Lock(), 'events': [], 'timings': [], 'last': None, 'model_calls_started':0}
    token = _current.set(state)
    try:
        yield state
    finally:
        _current.reset(token)


def emit_phase(stage):
    """Publica solamente una fase fija cuando empieza una operación real."""
    state = _current.get()
    if state is None or stage not in _MESSAGES:
        return False
    with state['lock']:
        if state['last'] == stage or len(state['events']) >= 64:
            return False
        event = {'stage': stage, 'message': _MESSAGES[stage],
                 'elapsed_ms': round((time.monotonic() - state['start']) * 1000, 3)}
        state['last'] = stage
        state['events'].append(event)
        callback = state['callback']
    if callback is not None:
        try:
            callback(dict(event))
        except Exception:
            # La instrumentación no puede invalidar una respuesta comprobada.
            pass
    return True


@contextmanager
def measure_stage(name):
    """Cronometra una operación del código; nombres remotos no se registran."""
    state = _current.get()
    if state is None or name not in _NAMES:
        yield
        return
    if name in {'local_search', 'web_search', 'extraction', 'semantic_retrieval',
                'knowledge_lookup', 'retrieval'}:
        emit_phase('search')
    elif name == 'audit':
        emit_phase('review')
    elif name in {'generation', 'repair'}:
        emit_phase('writing')
    started = time.monotonic()
    status = 'failed'
    try:
        yield
        status = 'ok'
    finally:
        row = {'stage': name, 'started_ms': round((started - state['start']) * 1000, 3),
               'elapsed_ms': round((time.monotonic() - started) * 1000, 3),
               'status': status}
        with state['lock']:
            if len(state['timings']) < 128:
                state['timings'].append(row)


def record_model_call():
    """Count actual inference HTTP attempts across every client in this turn."""
    state = _current.get()
    if state is not None:
        with state['lock']:
            state['model_calls_started'] += 1


def snapshot_metrics():
    """Devuelve métricas serializables; nunca prompts, consultas o URLs."""
    state = _current.get()
    if state is None:
        return {}
    with state['lock']:
        rows = [dict(value) for value in state['timings']]
        phases = [dict(value) for value in state['events']]
        totals = {}
        for row in rows:
            totals[row['stage']] = round(totals.get(row['stage'], 0) + row['elapsed_ms'], 3)
        return {'stage_timings': rows, 'stage_totals_ms': totals,
                'model_calls_started':state['model_calls_started'],
                'progress_events': phases,
                'first_phase_emitted_ms': phases[0]['elapsed_ms'] if phases else None,
                'elapsed_ms': round((time.monotonic() - state['start']) * 1000, 3)}


def timed_stage(name):
    """Decorador ligero para servicios existentes sin alterar su contrato."""
    def decorate(function):
        @wraps(function)
        def measured(*args, **kwargs):
            with measure_stage(name):
                return function(*args, **kwargs)
        return measured
    return decorate


def sanitize_metrics(value):
    """Copia pública de métricas: no acepta campos arbitrarios del resultado."""
    if not isinstance(value, dict):
        return {}
    def number(item):
        return type(item) in {int, float} and math.isfinite(item) and item >= 0
    clean = {key: value[key] for key in ('elapsed_ms', 'first_phase_emitted_ms', 'model_calls_started') if number(value.get(key))}
    totals = value.get('stage_totals_ms', {})
    if isinstance(totals, dict):
        clean['stage_totals_ms'] = {key: item for key, item in totals.items() if key in _NAMES and number(item)}
    clean['stage_timings'] = []
    rows = value.get('stage_timings', [])
    if isinstance(rows, list):
        for row in rows[:128]:
            if isinstance(row, dict) and row.get('stage') in _NAMES:
                item = {'stage': row['stage']}
                item.update({key: row[key] for key in ('started_ms', 'elapsed_ms') if number(row.get(key))})
                if row.get('status') in {'ok', 'failed'}:
                    item['status'] = row['status']
                clean['stage_timings'].append(item)
    clean['progress_events'] = []
    rows = value.get('progress_events', [])
    if isinstance(rows, list):
        for row in rows[:64]:
            if isinstance(row, dict) and row.get('stage') in _MESSAGES and number(row.get('elapsed_ms')):
                clean['progress_events'].append({'stage': row['stage'], 'elapsed_ms': row['elapsed_ms']})
    return clean


def merge_metrics(first, second, *, offset_ms=0):
    """Une scopes con un mismo origen, trasladando el inicio del segundo.

    Sólo combina la telemetría permitida; nunca copia texto arbitrario del
    resultado. Los totales siguen siendo inclusivos, no tiempos exclusivos.
    """
    if type(offset_ms) not in {int, float} or not math.isfinite(offset_ms) or offset_ms < 0:
        raise ValueError('Desplazamiento de métricas inválido')
    left, right = sanitize_metrics(first), sanitize_metrics(second)
    timings = left.get('stage_timings', []) + [
        {**row, 'started_ms': round(row.get('started_ms', 0) + offset_ms, 3)}
        for row in right.get('stage_timings', [])]
    timings.sort(key=lambda row: row.get('started_ms', 0))
    # Conservar también las últimas etapas si una consulta llegó al límite.
    if len(timings) > 128:
        timings = timings[:64] + timings[-64:]
    events = left.get('progress_events', []) + [
        {**row, 'elapsed_ms': round(row['elapsed_ms'] + offset_ms, 3)}
        for row in right.get('progress_events', [])]
    events.sort(key=lambda row: row['elapsed_ms'])
    totals = dict(left.get('stage_totals_ms', {}))
    for stage, duration in right.get('stage_totals_ms', {}).items():
        totals[stage] = round(totals.get(stage, 0) + duration, 3)
    result = {'stage_timings': timings, 'stage_totals_ms': totals,
              'model_calls_started':left.get('model_calls_started',0)+right.get('model_calls_started',0),
              'progress_events': events[:64],
              'elapsed_ms': round(max(left.get('elapsed_ms', 0),
                                      right.get('elapsed_ms', 0) + offset_ms), 3)}
    if events:
        result['first_phase_emitted_ms'] = events[0]['elapsed_ms']
    return result
