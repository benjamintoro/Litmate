"""Resultados privados efímeros del SSE, compartidos entre procesos locales.

Esta SQLite es independiente de los modelos de Django. No es conocimiento ni
entrenamiento: preguntas/resultados caducan a los dos minutos y se purgan en
cada acceso. Solo el hilo de la petición finaliza una sesión o consume cuota.
"""
import hashlib
import json
import re
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from django.conf import settings


TTL_SECONDS = 120
_TOKEN = re.compile(r'^[A-Za-z0-9_-]{43}$')


class JobUnavailable(Exception):
    """Trabajo inexistente, caducado o perteneciente a otro lector."""


class JobBusy(Exception):
    """Hay una finalización activa o demasiados trabajos pendientes."""


class JobStale(Exception):
    """La conversación inició una solicitud posterior a este trabajo."""


def _connect():
    default = Path(getattr(settings, 'LITMATE_AI_RUNTIME_DB',
                         Path(settings.BASE_DIR) / 'data' / 'litmate_ia_runtime.sqlite3'))
    path = Path(getattr(settings, 'LITMATE_AI_STREAM_DB', default.with_name('litmate_ia_stream.sqlite3')))
    protected = [config.get('NAME') for config in getattr(settings, 'DATABASES', {}).values()]
    protected.extend(getattr(settings, name, None) for name in (
        'LITMATE_AI_RUNTIME_DB', 'LITMATE_RAG_DB', 'LITMATE_KNOWLEDGE_DB',
        'LITMATE_KNOWLEDGE_RAG_DB', 'LITMATE_AI_ANSWER_CACHE_DB', 'LITMATE_LITERARY_MEMORY_DB'))
    if any(value and str(value) != ':memory:' and path.resolve() == Path(value).resolve()
           for value in protected):
        raise ValueError('Los trabajos SSE requieren una base propia, distinta de Django y sus índices.')
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=2)
    try:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        owned = {'stream_jobs_meta', 'stream_jobs', 'stream_finalizing', 'stream_revisions'}
        if tables and ('stream_jobs_meta' not in tables or not tables <= owned):
            raise ValueError('Base ajena a los trabajos privados de SSE.')
        if 'stream_jobs_meta' in tables:
            marker = db.execute("SELECT value FROM stream_jobs_meta WHERE key='owner'").fetchone()
            if marker != ('litmate-private-stream-v1',):
                raise ValueError('Marcador de trabajos SSE inválido.')
        db.execute('PRAGMA secure_delete=ON')
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS stream_jobs_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute("INSERT OR IGNORE INTO stream_jobs_meta VALUES('owner','litmate-private-stream-v1')")
            db.execute('CREATE TABLE IF NOT EXISTS stream_jobs ('
                       'key TEXT PRIMARY KEY, owner TEXT NOT NULL, revision TEXT NOT NULL, '
                       'status TEXT NOT NULL, payload TEXT NOT NULL, result TEXT, '
                       'final TEXT, expires REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS stream_finalizing ('
                       'owner TEXT PRIMARY KEY, key TEXT NOT NULL, expires REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS stream_revisions ('
                       'owner TEXT PRIMARY KEY, revision TEXT NOT NULL, expires REAL NOT NULL)')
        return db
    except Exception:
        db.close()
        raise


def _key(token):
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise JobUnavailable()
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def _dump(value):
    encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode('utf-8')) > 1024 * 1024:
        raise ValueError('Resultado efímero demasiado grande')
    return encoded


def _purge(db):
    now = time.time()
    db.execute('DELETE FROM stream_jobs WHERE expires <= ?', (now,))
    db.execute('DELETE FROM stream_finalizing WHERE expires <= ?', (now,))
    db.execute('DELETE FROM stream_revisions WHERE expires <= ?', (now,))


def owner_key(principal, session_nonce):
    """Una IP compartida o el literal anonymous nunca identifican una sesión."""
    return hashlib.sha256((str(principal) + '\0' + str(session_nonce)).encode('utf-8')).hexdigest()


def create_job(owner, revision, payload):
    token = secrets.token_urlsafe(32)
    with closing(_connect()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        _purge(db)
        if db.execute('SELECT 1 FROM stream_jobs WHERE owner=? AND status=\'finalizing\'', (owner,)).fetchone():
            raise JobBusy()
        if (db.execute('SELECT COUNT(*) FROM stream_jobs WHERE status IN (\'pending\',\'ready\',\'finalizing\')').fetchone()[0] >= 16
                or db.execute('SELECT COUNT(*) FROM stream_jobs WHERE owner=? '
                              'AND status IN (\'pending\',\'ready\',\'finalizing\')', (owner,)).fetchone()[0] >= 2):
            raise JobBusy()
        db.execute('INSERT INTO stream_jobs VALUES (?,?,?,\'pending\',?,NULL,NULL,?)',
                   (_key(token), owner, revision, _dump(payload), time.time() + TTL_SECONDS))
        db.execute('INSERT INTO stream_revisions VALUES (?,?,?) '
                   'ON CONFLICT(owner) DO UPDATE SET revision=excluded.revision,expires=excluded.expires',
                   (owner, revision, time.time() + TTL_SECONDS))
    return token


def complete_job(token, owner, result):
    with closing(_connect()) as db, db:
        _purge(db)
        changed = db.execute('UPDATE stream_jobs SET status=\'ready\',result=? '
            'WHERE key=? AND owner=? AND status=\'pending\'', (_dump(result), _key(token), owner))
        return changed.rowcount == 1


def discard_job(token, owner):
    try:
        key = _key(token)
        with closing(_connect()) as db, db:
            _purge(db)
            db.execute('DELETE FROM stream_jobs WHERE key=? AND owner=? AND status=\'pending\'', (key, owner))
        return True
    except (OSError, ValueError, sqlite3.Error, JobUnavailable):
        # Un fallo de limpieza no debe ocultar una desconexión. El TTL sigue
        # siendo obligatorio cuando vuelva a estar disponible esta base propia.
        return False


def claim_finalization(token, owner, *, quota_owner=None):
    """Reintentos completados son idempotentes; un proceso caído falla cerrado.

    La marca finalizing no se reabre automáticamente: evita volver a consumir
    cuota tras una caída entre el backend de cuotas y la escritura del recibo.
    No se promete una transacción distribuida entre SQLite/caché/BD de Django.
    """
    key = _key(token)
    with closing(_connect()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        _purge(db)
        row = db.execute('SELECT revision,status,payload,result,final,expires '
                         'FROM stream_jobs WHERE key=? AND owner=?', (key, owner)).fetchone()
        if row is None:
            raise JobUnavailable()
        revision, status, payload, result, final, expires = row
        latest = db.execute('SELECT revision FROM stream_revisions WHERE owner=?', (owner,)).fetchone()
        if latest is None or latest[0] != revision:
            raise JobStale()
        answer = {'revision': revision, 'status': status, 'payload': json.loads(payload),
                  'result': json.loads(result) if result else None,
                  'final': json.loads(final) if final else None}
        if status == 'done':
            return answer
        if status != 'ready':
            raise JobBusy()
        lock_owner = quota_owner or owner
        if db.execute('SELECT 1 FROM stream_finalizing WHERE owner=?', (lock_owner,)).fetchone():
            raise JobBusy()
        db.execute('INSERT INTO stream_finalizing VALUES (?,?,?)', (lock_owner, key, expires))
        db.execute('UPDATE stream_jobs SET status=\'finalizing\' WHERE key=?', (key,))
        return answer


def finish_finalization(token, owner, final):
    key = _key(token)
    with closing(_connect()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        _purge(db)
        changed = db.execute('UPDATE stream_jobs SET status=\'done\',final=? '
                             'WHERE key=? AND owner=? AND status=\'finalizing\'',
                             (_dump(final), key, owner))
        db.execute('DELETE FROM stream_finalizing WHERE key=?', (key,))
        if changed.rowcount != 1:
            raise JobUnavailable()
