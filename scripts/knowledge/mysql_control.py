"""Operaciones locales explícitas, con contraseña oculta y sin editar .env."""
import argparse
import getpass
import json
import os
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--backup', type=Path)
    action.add_argument('--prepare-schema', action='store_true')
    action.add_argument('--pilot-catalog', type=Path)
    action.add_argument('--project-ledger', type=Path)
    action.add_argument('--http-smoke', action='store_true')
    action.add_argument('--conflicts', action='store_true')
    action.add_argument('--review-version')
    parser.add_argument('--backup-root', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--state-db', type=Path)
    parser.add_argument('--max-records', type=int, default=100)
    parser.add_argument('--batch-size', type=int, default=25)
    parser.add_argument('--max-seconds', type=float, default=60)
    parser.add_argument('--max-storage-mb', type=int, default=16)
    parser.add_argument('--replay', action='store_true')
    parser.add_argument('--record-id')
    parser.add_argument('--evidence-url')
    parser.add_argument('--operator-confirmed', action='store_true')
    args = parser.parse_args(argv)
    from iniciar_mysql_local import local_database_environment
    password = getpass.getpass('Contraseña MySQL local (oculta): ')
    with local_database_environment(password, development_http=args.http_smoke):
        password = None
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'litmate_project.settings')
        import django
        django.setup()
        from core.database_transfer import create_backup, verify_backup
        if args.backup:
            manifest = create_backup(args.backup)
            verify_backup(args.backup)
            report = {'backup_verified': True, 'tables': len(manifest['database']['tables']),
                'rows': sum(table['count'] for table in manifest['database']['tables'].values()),
                'files': len(manifest['files'])}
        else:
            if not args.backup_root or not args.output or args.output.exists():
                raise ValueError('Indica respaldo y salida nuevos.')
            manifest = verify_backup(args.backup_root)
            from django.db import connection
            if (connection.vendor != 'mysql' or connection.settings_dict.get('HOST') != '127.0.0.1'
                    or connection.settings_dict.get('NAME') != 'litmate_db'):
                raise ValueError('Se requiere MySQL local.')
            if args.prepare_schema:
                from core.bibliographic_operations import prepare_schema
                report = prepare_schema(args.backup_root, manifest)
            elif args.http_smoke:
                from core.bibliographic_operations import http_smoke
                report = http_smoke(args.backup_root, manifest)
            elif args.conflicts or args.review_version:
                from django.core.management import call_command
                import io
                output = io.StringIO()
                command_args = (['--conflicts'] if args.conflicts else [
                    '--review-version', args.review_version, '--record-id', args.record_id or '',
                    '--evidence-url', args.evidence_url or ''])
                if args.operator_confirmed:
                    command_args.append('--operator-confirmed')
                call_command('proyectar_catalogo_mysql', *command_args, stdout=output)
                report = json.loads(output.getvalue())
            else:
                from core.bibliographic_operations import pilot, project_and_audit
                if args.pilot_catalog:
                    report = pilot(args.pilot_catalog, args.backup_root, manifest,
                                   state_database=args.state_db, maximum=args.max_records)
                else:
                    report = project_and_audit(args.project_ledger, args.backup_root, manifest,
                        maximum=args.max_records, replay=args.replay, batch_size=args.batch_size,
                        max_seconds=args.max_seconds, max_storage_mb=args.max_storage_mb)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({key: value for key, value in report.items() if key not in {'integrity', 'examples', 'queries', 'sql_preview'}},
                         ensure_ascii=True), flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'passed': False, 'error_class': type(error).__name__}), flush=True)
        raise SystemExit(1)
