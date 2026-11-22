"""Salud local y agregados: abre SQLite en lectura, sin mensajes ni identidades."""
from contextlib import closing
from pathlib import Path
import sqlite3


def account_health(database):
    from django.conf import settings
    from django.db import connections, DatabaseError
    if settings.configured and settings.DATABASES.get('accounts', {}).get('ENGINE') == 'django.db.backends.mysql':
        try:
            connection = connections['accounts']
            required = ['auth_user', 'django_session', 'core_conversacionia', 'core_librofavorito',
                        'reader_accounts_usagebucket', 'suscripciones_historialpago']
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                present = set(connection.introspection.table_names(cursor))
            return {'status': 'ok' if set(required) <= present else 'degraded', 'backend': 'mysql'}
        except DatabaseError:
            return {'status': 'unavailable', 'backend': 'mysql'}
    path = Path(database).resolve()
    if not path.is_file():
        return {'status': 'unavailable'}
    tables = {'accounts': 'auth_user', 'conversations': 'core_conversacionia',
              'favorites': 'core_librofavorito', 'reading_lists': 'core_listalectura',
              'query_operations': 'reader_accounts_queryoperation', 'payments': 'suscripciones_historialpago'}
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=1)) as db:
            integrity = db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
            foreign_keys_valid = not db.execute('PRAGMA foreign_key_check').fetchall()
            counts = {label: db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for label, table in tables.items()}
        return {'status': 'ok' if integrity and foreign_keys_valid else 'degraded',
                'integrity_valid': integrity, 'foreign_keys_valid': foreign_keys_valid, 'counts': counts}
    except sqlite3.Error:
        return {'status': 'unavailable'}
