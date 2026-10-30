"""Caché privada de respuestas extractivas; nunca convierte salida LLM en hechos.

La clave incluye propietario, conversación completa y versiones de evidencia.
Las paráfrasis reutilizan el índice de fuentes, no respuestas por similitud.
"""
from contextlib import closing
from dataclasses import asdict
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
import time

# Cambiar el namespace evita reutilizar referencias admitidas antes de los
# filtros de identidad, sin borrar registros ni datos de conversaciones.
POLICY = 'extractive-answer-v8-literary-coverage'


def _path(database=None):
    from django.conf import settings
    path = Path(database or getattr(settings, 'LITMATE_AI_ANSWER_CACHE_DB',
                                   Path(settings.BASE_DIR) / 'data' / 'litmate_answers.sqlite3'))
    for config in getattr(settings, 'DATABASES', {}).values():
        name = config.get('NAME', '')
        if name and str(name) != ':memory:' and path.resolve() == Path(name).resolve():
            raise ValueError('El caché no puede usar la base Django.')
    return path


def _connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=.3)
    try:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables and 'answer_cache_meta' not in tables:
            raise ValueError('Base ajena al caché de respuestas.')
        if 'answer_cache_meta' in tables:
            marker = db.execute("SELECT value FROM answer_cache_meta WHERE key='owner'").fetchone()
            if marker != ('litmate-private-answers-v1',):
                raise ValueError('Marcador de caché inválido.')
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS answer_cache_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute("INSERT OR IGNORE INTO answer_cache_meta VALUES('owner','litmate-private-answers-v1')")
            db.execute('CREATE TABLE IF NOT EXISTS answers(cache_key TEXT PRIMARY KEY, expires REAL NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS answers_expiry ON answers(expires)')
        return db
    except Exception:
        db.close()
        raise


def _revision():
    from django.conf import settings
    from .literary_knowledge import knowledge_revision
    from .literary_memory import revision
    from .ai_library_router import library_revision
    from .bibliographic_repository import repository_revision
    paths = [Path(__file__).parent / 'data' / 'verified_readings.json',
             Path(__file__).parent / 'data' / 'topic_reference.json']
    return [POLICY, knowledge_revision(settings), revision(), library_revision(), repository_revision(),
            [(str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in paths]]


def cache_key(message, state, owner):
    from django.conf import settings
    from .literary_language import request_text
    # Sólo una autoría con título explícito es independiente del historial.
    # «¿Quién escribió ese?» y todos los ordinales conservan el estado entero.
    value = request_text(message).strip('¿?¡!., ')
    standalone = re.fullmatch(r'quien escribio (.{3,180})', value)
    context = {key: value for key, value in state.items() if key != '_stream_revision'}
    if (standalone and len(standalone.group(1).split()) >= 2 and not re.search(
            r'\b(?:ese|esa|este|esta|anterior|segundo|primero|tercero|mismo|ultimo)\b', value)):
        from .literary_identity import title_matches, work_identity
        relevant = []
        for book in [state.get('active_work', {}), *[book for turn in state.get('turns', [])
                if isinstance(turn, dict) for book in turn.get('books', [])]]:
            if isinstance(book, dict) and title_matches(standalone.group(1), book):
                identity = work_identity(book)
                key = (identity.get('title'), identity.get('author'), identity.get('work_id'))
                if key not in relevant:
                    relevant.append(key)
        context = {'explicit_authorship': True, 'matching_works_in_context': relevant}
    # No quitar negaciones, acentos, números ni cambiar el orden de libros.
    value = json.dumps([owner, message.strip(), context, _revision()],
                       ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hmac.new(str(settings.SECRET_KEY).encode(), value.encode(), hashlib.sha256).hexdigest()


def _answer_body(text):
    """Quita los enlaces que la interfaz añade después de validar la respuesta.

    Las respuestas extractivas pueden publicar una cita y luego la URL de su
    fuente. Esa cola no forma parte de las afirmaciones auditadas y no debe
    impedir reutilizar la misma respuesta validada.
    """
    for marker in ('\n\nFuente:', '\n\nFuente de la ficha:',
                   '\n\nFuentes de las fichas:', '\n\nMás sobre los personajes:'):
        text = text.split(marker, 1)[0]
    # La referencia parcial añade una introducción y un alcance que no forman
    # parte de las frases auditadas por reference_answer.
    from .ai_quick_answers import (REFERENCE_PREFIX, REFERENCE_SUFFIX,
                                   SUMMARY_PREFIX, SUMMARY_SUFFIX)
    for prefix in (REFERENCE_PREFIX, SUMMARY_PREFIX):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    for suffix in (REFERENCE_SUFFIX, SUMMARY_SUFFIX):
        text = text.split(suffix, 1)[0]
    # LiteraryAssistant._publish añade «\n\n[1] Título\nURL» por cada web.
    return re.split(r'\n\n\[\d+\] ', text, maxsplit=1)[0]


def _validate(message, result):
    from .literary_ai import has_excerpt, obvious_rejection, requires_exact_text, validate_draft
    from .literary_evidence import validate_evidence
    from .literary_quality import validate_audit
    from .literary_research import is_topic_recommendation
    if is_topic_recommendation(message):
        from .ai_presentation import build_book_cards
        if not build_book_cards(result):
            return False  # Stale article dumps cannot bypass the repaired route.
    if (result.status != 'answered' or not result.remember or result.basis != 'sources'
            or has_excerpt(message) or obvious_rejection(message) or requires_exact_text(message)
            or not result.sources or len(result.sources) > 12):
        return False
    if any(s.get('kind') == 'excerpt' or s.get('injection_detected') or s.get('conflicts_with')
           or s.get('conflicted') for s in result.sources):
        return False
    for source in result.sources:
        if source.get('expires_at'):
            from datetime import datetime
            try:
                expires = source['expires_at']
                timestamp = (float(expires) if str(expires).replace('.', '', 1).isdigit() else
                             datetime.fromisoformat(expires.replace('Z', '+00:00')).timestamp())
                if timestamp <= time.time():
                    return False
            except (ValueError, TypeError):
                return False
    supported = any(result.diagnostics.get(flag) for flag in (
        'verified_quick_answer', 'catalogue_quick_lookup', 'verified_character_followup',
        'web_reference_quick_answer'))
    if not supported:
        return False
    text = _answer_body(result.text)
    draft = {'status': 'answer', 'basis': 'sources', 'text': text, 'books': result.books,
             'citations': [s['id'] for s in result.sources], 'needs_web': False}
    try:
        validate_draft(draft, result.sources)
        validate_evidence(draft, result.sources, message)
        audit = (result.diagnostics.get('audit')
                 or result.diagnostics.get('reference_audit'))
        if audit:
            plan = {'questions': [message], 'search_queries': [], 'needs_contents': False,
                    'needs_fresh_sources': False, 'spoilers_requested': False}
            validate_audit(audit, plan, draft, result.sources, message, strict_facts=True)
        else:
            # Única excepción sin auditoría: plantilla exacta de autoría.
            if result.intent != 'author' or len(result.books) != 1 or len(result.sources) != 1:
                return False
            source = result.sources[0]
            if text != f'**{source["title"]}** es una obra de **{source["author"]}**.':
                return False
        return True
    except (ValueError, TypeError, KeyError):
        return False


def get_answer(message, state, owner, *, database=None):
    from .literary_ai import ChatResult
    try:
        path = _path(database)
        if not path.is_file():
            return None
        key = cache_key(message, state, owner)
        with closing(_connect(path)) as db:
            row = db.execute('SELECT payload FROM answers WHERE cache_key=? AND expires>?',
                             (key, time.time())).fetchone()
        if row:
            result = ChatResult(**json.loads(row[0]))
            if _validate(message, result):
                result.diagnostics['exact_answer_cache_hit'] = True
                return result
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        pass  # Una avería del caché no impide investigar con los validadores.
    return None


def put_answer(message, state, owner, result, *, database=None):
    if not isinstance(owner, str) or not owner or not _validate(message, result):
        return False
    try:
        payload = json.dumps(asdict(result), ensure_ascii=False)
        if len(payload) > 90000:
            return False
        key = cache_key(message, state, owner)
        with closing(_connect(_path(database))) as db, db:
            db.execute('DELETE FROM answers WHERE expires<=?', (time.time(),))
            db.execute('INSERT OR REPLACE INTO answers VALUES(?,?,?)',
                       (key, time.time() + 3600, payload))
            # Capacidad acotada incluso si hay muchos propietarios distintos.
            db.execute('DELETE FROM answers WHERE cache_key IN (SELECT cache_key FROM answers ORDER BY expires DESC LIMIT -1 OFFSET 1000)')
        return True
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return False


def cache_published_authorship(message, state, owner, result, *, database=None):
    """Cachea una autoría explícita bajo el estado que verá el próximo turno.

    El historial cambia al publicar. Guardar sólo la clave previa provoca un
    fallo en la repetición siguiente. No se proyecta esta respuesta a consultas
    deícticas: su significado puede cambiar al añadir el nuevo turno.
    """
    from .literary_identity import title_matches
    from .literary_language import request_text
    value = request_text(message).strip(' ¿?¡!.,')
    match = re.fullmatch(r'quien escribio\s+(.{2,180})', value)
    if (not match or result.intent != 'author' or len(result.sources) != 1
            or result.sources[0].get('kind') != 'book'
            or re.search(r'\b(?:ese|esa|este|esta|anterior|mismo|primero|segundo|tercero)\b',
                         match.group(1))
            or not title_matches(match.group(1), result.sources[0])):
        return False
    # put_answer conserva auditoría, TTL, revisión de evidencia y aislamiento
    # por propietario; no se relaja ni se simplifica la clave conversacional.
    return put_answer(message, state, owner, result, database=database)


def delete_owner_cache(*, database=None):
    """Vacía sólo esta base efímera, sin tocar conocimiento ni conversaciones."""
    path = _path(database)
    if path.is_file():
        with closing(_connect(path)) as db, db:
            db.execute('DELETE FROM answers')
