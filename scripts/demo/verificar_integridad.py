"""Inventario final de sólo lectura: MySQL, SQLite originales y entorno privado."""
from contextlib import closing
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import sqlite3


def main():
    from iniciar_mysql_local import local_database_environment
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=root / 'reports/demo_20261103/integridad_cierre.json')
    args = parser.parse_args()
    output = args.output
    if output.exists():
        raise ValueError('El informe existe; conservarlo y usar otra ejecución documentada.')
    password = getpass.getpass('Contraseña MySQL local (oculta): ')
    with local_database_environment(password):
        password = None
        os.environ['DJANGO_SETTINGS_MODULE'] = 'litmate_project.settings'
        import django
        django.setup()
        from django.db import connection
        from django.conf import settings
        with connection.cursor() as cursor:
            cursor.execute('SET SESSION TRANSACTION READ ONLY')
            cursor.execute('SELECT DATABASE(), @@session.transaction_read_only')
            database, read_only = cursor.fetchone()
            if database != 'litmate_db' or not read_only:
                raise ValueError('Destino distinto del MySQL local de sólo lectura.')
            counts = {}
            for table in connection.introspection.table_names(cursor):
                cursor.execute('SELECT COUNT(*) FROM ' + connection.ops.quote_name(table))
                counts[table] = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM core_libro WHERE LOWER(titulo) LIKE %s', ['%mala costumbre%'])
            external_work_in_original_catalogue = cursor.fetchone()[0]
            external_in_kb = {}
            for table, field in [('core_kbrecord', 'label'), ('core_kbname', 'normalized')]:
                cursor.execute('SELECT COUNT(*) FROM ' + table + ' WHERE LOWER(' + field + ') LIKE %s',
                               ['%mala costumbre%'])
                external_in_kb[table] = cursor.fetchone()[0]
        baseline = json.loads((output.parent / 'integrity_baseline.json').read_text())
        hashes = {name: {'before': digest, 'after': hashlib.sha256((root / name).read_bytes()).hexdigest()}
                  for name, digest in baseline.items()}
        for value in hashes.values():
            value['unchanged'] = value['before'] == value['after']
        checks = {}
        for name in baseline:
            if not name.endswith('.sqlite3'):
                continue
            with closing(sqlite3.connect((root / name).resolve().as_uri() + '?mode=ro', uri=True)) as db:
                checks[name] = {'quick_check': db.execute('PRAGMA quick_check').fetchone()[0],
                                'foreign_key_issues': len(db.execute('PRAGMA foreign_key_check').fetchall())}
        report = {'mysql_database': database, 'mysql_session_read_only': bool(read_only),
                  'mysql_counts': counts, 'mysql_tables': len(counts), 'mysql_rows': sum(counts.values()),
                  'external_test_work_in_original_libro': external_work_in_original_catalogue,
                  'external_test_title_in_original_kb': external_in_kb,
                  'hashes': hashes, 'sqlite': checks,
                  'ai_requests_per_minute': settings.LITMATE_AI_REQUESTS_PER_MINUTE,
                  'migrations_executed': False, 'imports_executed': False}
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=True, indent=2)
        print(json.dumps({key: report[key] for key in ('mysql_database', 'mysql_session_read_only',
                         'mysql_tables', 'mysql_rows', 'external_test_work_in_original_libro')}))
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
