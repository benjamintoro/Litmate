"""Prepara exclusivamente una base NUEVA de ensayo; jamás migra MySQL o datos reales."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import secrets
import sqlite3


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--plans-audit', type=Path, required=True)
    parser.add_argument('--empty', action='store_true', help='Esquema sin planes para ensayar copia íntegra de cuentas.')
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    folder = args.folder.resolve()
    if folder == root / '.testtmp' or not folder.is_relative_to(root / '.testtmp') or folder.exists():
        parser.error('Se requiere una carpeta NUEVA bajo .testtmp; nunca se reemplaza una existente.')
    audit = json.loads(args.plans_audit.read_text(encoding='utf-8'))
    if audit.get('database') != 'litmate_db' or audit.get('read_only') is not True:
        parser.error('Usa el inventario de planes obtenido en sólo lectura.')
    os.environ.update(DB_ENGINE='sqlite', DB_SQLITE_PATH=str(folder / 'unused-catalogue.sqlite3'),
        DJANGO_SETTINGS_MODULE='litmate_project.reader_settings', LITMATE_DEMO_MODE='local',
        LITMATE_DEMO_WORKSPACE=str(folder), LITMATE_ACCOUNTS_DB=str(folder / 'accounts.sqlite3'),
        SECRET_KEY=secrets.token_urlsafe(64))
    import django
    django.setup()
    from django.conf import settings
    from iniciar_demo import prepare_workspace
    if args.empty:
        folder.mkdir(parents=True)
        (folder/'demo-owner.json').write_text(json.dumps({'owner':'litmate-demo-v1'}),encoding='utf-8')
        for name in ('sessions','media','logs'):
            (folder/name).mkdir()
    else:
        prepare_workspace(folder, settings)
    from django.core.management import call_command
    call_command('migrate', database='accounts', interactive=False, verbosity=0)
    from suscripciones.models import PlanSuscripcion
    for row in ([] if args.empty else audit['plans']):
        PlanSuscripcion.objects.using('accounts').create(**row)
    with closing(sqlite3.connect(folder / 'accounts.sqlite3')) as db:
        check = db.execute('PRAGMA quick_check').fetchone()[0]
        fk = list(db.execute('PRAGMA foreign_key_check'))
        users = db.execute('SELECT COUNT(*) FROM auth_user').fetchone()[0]
    if check != 'ok' or fk or users != 0:
        raise ValueError('El ensayo no pasó su comprobación de integridad o no está vacío de usuarios.')
    from reader_accounts.signing_key import load_key
    load_key(folder / 'accounts.sqlite3')
    print(json.dumps({'stage': str(folder), 'plans_copied': 0 if args.empty else len(audit['plans']), 'users': users,
        'quick_check': check, 'foreign_key_issues': len(fk), 'original_migrations_run': False}))


if __name__ == '__main__':
    main()
