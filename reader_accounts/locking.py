"""Serializa operaciones de un lector también con MySQL, entre procesos."""
from contextlib import contextmanager
import hashlib

from django.db import DatabaseError, connections


@contextmanager
def reader_lock(actor):
    connection = connections['accounts']
    if connection.vendor != 'mysql':
        yield
        return
    key = 'lm:' + hashlib.sha256(actor.encode()).hexdigest()[:60]
    with connection.cursor() as cursor:
        cursor.execute('SELECT GET_LOCK(%s, 10)', [key])
        if cursor.fetchone()[0] != 1:
            raise DatabaseError('El lector tiene otra operación pendiente. Reintenta la misma solicitud.')
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SELECT RELEASE_LOCK(%s)', [key])
