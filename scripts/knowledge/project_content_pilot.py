"""Proyección pequeña del ledger existente; respaldo, auditoría aditiva y sin .env."""
import argparse
import getpass
import json
import os
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--ledger',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--replay',action='store_true')
    args=parser.parse_args()
    if args.output.exists():
        parser.error('Conserva el informe anterior; utiliza otra salida.')
    from iniciar_mysql_local import local_database_environment
    password=getpass.getpass('Contraseña MySQL local (oculta): ')
    with local_database_environment(password):
        password=None
        os.environ.setdefault('DJANGO_SETTINGS_MODULE','litmate_project.settings')
        import django
        django.setup()
        from django.db import connection
        from core.database_transfer import verify_backup
        from core.bibliographic_expansion import preserve_expansion_rows
        from core.bibliographic_repository import project_ledger
        from core.literary_acquisition import acquisition_stats
        if connection.vendor!='mysql' or connection.settings_dict['HOST']!='127.0.0.1':
            raise ValueError('Sólo MySQL local explícito.')
        manifest=verify_backup(args.backup)
        preserve_expansion_rows(args.backup,manifest)
        if acquisition_stats(args.ledger).get('records',0)>25:
            raise ValueError('Este piloto admite un ledger de hasta 25 registros.')
        # El límite incluye el catálogo existente (~84 MiB), no sólo el delta.
        result=project_ledger(args.ledger,max_records=25,batch_size=3,max_seconds=20,
                              max_storage_mb=128,replay=args.replay)
        report={'projection':result,'integrity':preserve_expansion_rows(args.backup,manifest)}
        args.output.write_text(json.dumps(report,ensure_ascii=True,indent=2),encoding='utf8')
        print(json.dumps({'projection':result,'original_tables_verified':len(report['integrity'])},ensure_ascii=True))


if __name__=='__main__':
    main()
