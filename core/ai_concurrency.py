"""Coordinación local entre procesos, independiente de las tablas de Django.

SQLite sólo contiene hashes de contadores y leases, nunca mensajes ni claves.
Para varias máquinas se puede elegir Redis como backend mediante CACHE_URL.
"""
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from django.conf import settings
from django.core.cache import cache


def _connect():
    path = Path(getattr(settings, 'LITMATE_AI_RUNTIME_DB',
                Path(settings.BASE_DIR) / 'data' / 'litmate_ia_runtime.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=2)
    db.execute('CREATE TABLE IF NOT EXISTS leases (key TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS counters (key TEXT PRIMARY KEY, amount INTEGER NOT NULL, expires REAL NOT NULL)')
    return db


def _backend():
    backend = getattr(settings, 'LITMATE_AI_LOCK_BACKEND', 'sqlite')
    if backend not in {'sqlite', 'cache', 'redis'}:
        raise ValueError('Backend de coordinación IA inválido')
    if backend == 'redis':
        config = settings.CACHES['default']
        if config.get('BACKEND') != 'django.core.cache.backends.redis.RedisCache':
            raise ValueError('Configura CACHE_URL para utilizar Redis')
    return backend


def rate_increment(key, timeout=120):
    if _backend() in {'cache', 'redis'}:
        if cache.add(key, 1, timeout=timeout):
            return 1
        return cache.incr(key)
    now = time.time()
    with closing(_connect()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM counters WHERE expires <= ?', (now,))
        db.execute('INSERT INTO counters VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET amount=amount+1',
                   (key, now + timeout))
        return db.execute('SELECT amount FROM counters WHERE key=?', (key,)).fetchone()[0]


def acquire(key, token, seconds):
    if _backend() in {'cache', 'redis'}:
        return cache.add(key, token, timeout=seconds)
    now = time.time()
    with closing(_connect()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM leases WHERE expires <= ?', (now,))
        cursor = db.execute('INSERT OR IGNORE INTO leases VALUES (?,?,?)', (key, token, now + seconds))
        return cursor.rowcount == 1


def release(key, token):
    backend = _backend()
    if backend == 'redis':
        # Compare-and-delete atómico: nunca borra un lease renovado por otra petición.
        from django.core.cache import caches
        client = caches['default']._cache.get_client(key, write=True)
        real_key = caches['default'].make_key(key)
        serialized = caches['default']._cache._serializer.dumps(token)
        client.eval('if redis.call("get",KEYS[1])==ARGV[1] then return redis.call("del",KEYS[1]) else return 0 end',
                    1, real_key, serialized)
    elif backend == 'cache':
        if cache.get(key) == token:
            cache.delete(key)
    else:
        with closing(_connect()) as db, db:
            db.execute('DELETE FROM leases WHERE key=? AND owner=?', (key, token))
