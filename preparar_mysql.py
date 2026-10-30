"""Safe database preparation. Password is read locally with getpass, never argv.

No command changes the application's selected database or writes to its source.
"""
import argparse
from datetime import datetime
import getpass
import json
import os
from pathlib import Path
import sys


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest='action', required=True)
    backup = commands.add_parser('respaldo', help='Snapshot + verified SQLite fallback + files.')
    backup.add_argument('--salida', type=Path, required=True)
    check = commands.add_parser('verificar', help='Verify backup hashes and data without importing.')
    check.add_argument('--respaldo', type=Path, required=True)
    for name in ('comprobar-mysql', 'importar-mysql', 'verificar-mysql'):
        command = commands.add_parser(name)
        command.add_argument('--respaldo', type=Path, required=True)
        command.add_argument('--host', default='127.0.0.1')
        command.add_argument('--puerto', type=int, default=3306)
        command.add_argument('--base', default='litmate_db')
        command.add_argument('--usuario', default='litmate_app')
        if name == 'importar-mysql':
            command.add_argument('--reanudar-esquema-vacio', action='store_true',
                                 help='Only resume an identical schema with zero application rows.')
            command.add_argument('--aplicacion-detenida', action='store_true',
                                 help='Confirm Django/workers are stopped to avoid concurrent writes.')
    return root


def run(argv=None):
    args = parser().parse_args(argv)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'litmate_project.settings')
    import django
    django.setup()
    from core.database_transfer import (TransferError, create_backup, verify_backup,
        temporary_alias, import_database, compare_database, source_unchanged, json_write)
    if args.action == 'respaldo':
        manifest = create_backup(args.salida)
        print(json.dumps({'backup_verified': True, 'tables': len(manifest['database']['tables']),
              'rows': sum(t['count'] for t in manifest['database']['tables'].values()),
              'auxiliary_sqlite': len(manifest['sqlite_stores']), 'path': str(args.salida)}))
        return 0
    manifest = verify_backup(args.respaldo)
    if args.action == 'verificar':
        print(json.dumps({'backup_verified': True, 'tables': len(manifest['database']['tables'])}))
        return 0
    if args.action == 'importar-mysql' and not args.aplicacion_detenida:
        raise TransferError('Detén Django y sus trabajadores; usa --aplicacion-detenida después.')
    if args.host not in {'127.0.0.1', 'localhost', '::1'}:
        raise TransferError('Este procedimiento está limitado al servidor local.')
    # Separate variable: never reuse the existing TiDB DB_PASSWORD by accident.
    password = os.environ.get('LITMATE_MYSQL_PASSWORD')
    if password is None:
        if not sys.stdin.isatty():
            raise TransferError('Ejecuta el comando en tu terminal para introducir la contraseña oculta.')
        password = getpass.getpass('Contraseña MySQL local (no se muestra ni guarda): ')
    from litmate_project.database_settings import database_config
    config = database_config(Path(__file__).resolve().parent, {
        'DB_ENGINE': 'mysql', 'DB_NAME': args.base, 'DB_USER': args.usuario,
        'DB_PASSWORD': password, 'DB_HOST': args.host, 'DB_PORT': str(args.puerto)})
    password = None
    with temporary_alias('transfer_mysql', config) as target:
        target.ensure_connection()
        with target.cursor() as cursor:
            cursor.execute('SELECT VERSION(), @@character_set_database, @@collation_database, '
                           '@@default_storage_engine, @@sql_mode')
            version, charset, collation, engine, mode = cursor.fetchone()
        if 'tidb' in version.lower() or target.mysql_version < (8, 0, 11):
            raise TransferError('El destino debe ser MySQL local compatible con Django 5.2.')
        if charset != 'utf8mb4' or engine.lower() != 'innodb' or 'STRICT_TRANS_TABLES' not in mode:
            raise TransferError('El destino requiere utf8mb4, InnoDB y modo estricto.')
        report = {'server_version': version, 'charset': charset, 'collation': collation,
                  'engine': engine, 'connected': True, 'imported': False,
                  'driver': target.connection.__class__.__module__,
                  'tables_before': len(target.introspection.table_names())}
        trace = []
        if args.action == 'comprobar-mysql':
            from core.database_transfer import fresh_mysql_metadata
            fresh_mysql_metadata(target)
            counts, sequences = {}, {}
            with target.cursor() as cursor:
                for name in target.introspection.table_names():
                    cursor.execute('SELECT COUNT(*) FROM ' + target.ops.quote_name(name))
                    counts[name] = cursor.fetchone()[0]
                cursor.execute('SHOW TABLE STATUS')
                names = [c[0] for c in cursor.description]
                for row in cursor.fetchall():
                    status = dict(zip(names, row))
                    sequences[status['Name']] = status['Auto_increment']
            report.update(counts=counts, next_ids=sequences)
        if args.action == 'importar-mysql':
            # Freshness and backup integrity are checked before the first target DDL.
            source_unchanged(args.respaldo, manifest, trace=trace)
            report['tables'] = import_database(target, args.respaldo / 'database', manifest['database'],
                                               resume_empty=args.reanudar_esquema_vacio, trace=trace)
            report['imported'] = True
        elif args.action == 'verificar-mysql':
            report['tables'] = compare_database(target, args.respaldo / 'database', manifest['database'],
                                               stage='target.independent_verification', trace=trace)
            report['integrity_verified'] = True
            from django.core.checks import run_checks
            issues = run_checks(databases=[target.alias])
            if any(issue.level >= 40 for issue in issues):
                raise TransferError('La comprobación Django del destino devolvió errores.')
            report['django_database_checks'] = 'ok'
        report['counter_trace'] = trace
        report_root = Path(__file__).resolve().parent / 'reportes' / 'mysql_20261028'
        report_root.mkdir(parents=True, exist_ok=True)
        path = report_root / ('mysql_' + args.action + '_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
        json_write(path, report)
        summary = {k: v for k, v in report.items() if k not in {'tables', 'counter_trace', 'counts', 'next_ids'}}
        print(json.dumps({**summary, 'tables': len(report.get('tables', {})), 'report': str(path)}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(run())
    except Exception as error:
        from core.database_transfer import TransferError
        if isinstance(error, TransferError):
            print(str(error), file=sys.stderr)
        else:
            code = error.args[0] if error.args and isinstance(error.args[0], int) else None
            # DB errors may embed values from rows or credentials. Never print them.
            print(json.dumps({'failed': True, 'error_class': type(error).__name__, 'error_code': code,
                'note': 'No se cambió el motor de la aplicación. Si comenzó DDL en un destino vacío, '
                        'puede quedar el esquema creado; no se elimina automáticamente.'}), file=sys.stderr)
        raise SystemExit(1)
