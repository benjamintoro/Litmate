"""Lanzador de ensayo: reutiliza la demo y prohíbe escrituras fuera del ensayo."""
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

ROOT = Path.cwd()
FOLDER = ROOT / '.testtmp/recall-final-http-20261031'
REPORT = ROOT / 'reports/recuerdos_opencode_20261031/instancia_final.json'


def main():
    if FOLDER.exists() or REPORT.exists():
        raise RuntimeError('Usa un ensayo nuevo; se conserva la evidencia existente.')
    os.environ.update(LITMATE_AUTO_ENRICHMENT='False', LITMATE_TRACE_MEMORY='False')
    import django
    from django.conf import settings
    original_setup = django.setup
    def setup(*args, **kwargs):
        settings.LOGGING_CONFIG = None
        original_setup(*args, **kwargs)
        logging.disable(logging.CRITICAL)
    import iniciar_demo
    original_prepare = iniciar_demo.prepare_workspace
    def prepare(folder, config):
        path, stores = original_prepare(folder, config)
        stores['CACHES'] = {'default': {'BACKEND':'django.core.cache.backends.locmem.LocMemCache',
                                       'LOCATION':'recall-final-isolated'}}
        return path, stores
    native_sqlite = sqlite3.connect
    def sqlite_guard(database, *args, **kwargs):
        name = str(database).replace('\\', '/')
        isolated = str(FOLDER).replace('\\', '/') in name
        readonly = name.startswith('file:') and 'mode=ro' in name and kwargs.get('uri')
        if not isolated and not readonly:
            raise RuntimeError('SQLite de escritura fuera del ensayo bloqueado')
        return native_sqlite(database, *args, **kwargs)
    from django.db.backends.signals import connection_created
    tables = ('auth_user','core_conversacionia','core_mensajeia','suscripciones_suscripcionusuario',
              'suscripciones_historialpago','core_libro','core_kbrecord')
    metadata = {'public_services_touched':False,'port':8007,'auxiliary_writes':'isolated only'}
    def counts(connection):
        with connection.cursor() as cursor:
            result = {}
            for table in tables:
                cursor.execute('SELECT COUNT(*) FROM '+connection.ops.quote_name(table))
                result[table] = cursor.fetchone()[0]
            return result
    def protect(sender, connection, **kwargs):
        if connection.vendor != 'mysql':
            raise RuntimeError('Conexión ORM inesperada')
        with connection.cursor() as cursor:
            cursor.execute('SET SESSION TRANSACTION READ ONLY')
            cursor.execute('SELECT DATABASE(), @@session.transaction_read_only')
            database, readonly = cursor.fetchone()
            if database != 'litmate_db' or readonly != 1:
                raise RuntimeError('No se garantiza MySQL local read-only')
        if 'counts_before' not in metadata:
            metadata.update(mysql_read_only=True,model=settings.LITMATE_LOCAL_MODEL,
                            counts_before=counts(connection))
            REPORT.write_text(json.dumps(metadata,indent=2),encoding='utf8')
    connection_created.connect(protect, weak=False, dispatch_uid='recall-final-readonly')
    try:
        with patch('django.setup',setup), patch('iniciar_demo.prepare_workspace',prepare), \
                patch('sqlite3.connect',side_effect=sqlite_guard):
            iniciar_demo.main(['--modo','local','--puerto','8007','--carpeta',str(FOLDER),
                              '--google-books-sin-facturacion'])
    finally:
        if 'counts_before' in metadata:
            from django.db import connection
            metadata['counts_after'] = counts(connection)
            metadata['counts_unchanged'] = metadata['counts_before']==metadata['counts_after']
            REPORT.write_text(json.dumps(metadata,indent=2),encoding='utf8')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
