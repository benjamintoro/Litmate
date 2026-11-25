"""Regresión de migración del perfil antiguo a biblioteca privada, sólo ensayo."""
import argparse
import json
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Usa una salida nueva.')
    with TemporaryDirectory(prefix='reader-upgrade-', dir=Path.cwd()/'.testtmp') as temp:
        folder = Path(temp)
        os.environ.update(DB_ENGINE='sqlite', DB_SQLITE_PATH=str(folder/'unused.sqlite3'),
            DJANGO_SETTINGS_MODULE='litmate_project.reader_settings', LITMATE_DEMO_MODE='local',
            LITMATE_DEMO_WORKSPACE=str(folder), LITMATE_ACCOUNTS_DB=str(folder/'accounts.sqlite3'),
            SECRET_KEY=secrets.token_urlsafe(64))
        import django
        django.setup()
        from django.core.management import call_command
        from django.db import connections
        from django.contrib.auth.models import User
        from core.models import PerfilUsuario, LibroFavorito, ListaLectura
        import reader_accounts.router as router
        try:
            old_core = router.ACCOUNT_CORE - {'librofavorito', 'listalectura', 'elementolistalectura'}
            with patch.object(router, 'ACCOUNT_CORE', old_core):
                call_command('migrate', 'auth', database='accounts', interactive=False, verbosity=0)
                call_command('migrate', 'core', database='accounts', interactive=False, verbosity=0)
                call_command('migrate', 'reader_accounts', '0001', database='accounts', interactive=False, verbosity=0)
            user = User.objects.create_user('synthetic-upgrade', password='Verano-6-Seguro-Prueba!')
            profile = PerfilUsuario.objects.create(usuario=user, nombre='Antes de migrar')
            before = (user.pk, user.password, profile.pk)
            call_command('migrate', database='accounts', interactive=False, verbosity=0)
            user.refresh_from_db()
            profile.refresh_from_db()
            assert before == (user.pk, user.password, profile.pk)
            book = LibroFavorito.objects.create(usuario=user, google_id='upgrade-fixture', titulo='Obra sintética', autores='Autora')
            reading_list = ListaLectura.objects.create(usuario=user, nombre='Lista sintética')
            with connections['accounts'].cursor() as cursor:
                cursor.execute('PRAGMA foreign_key_check')
                assert not cursor.fetchall()
            result = {'passed': True, 'old_ids_and_password_preserved': True,
                'personal_tables_created_after_old_migrations': bool(book.pk and reading_list.pk),
                'original_databases_used': False, 'foreign_key_issues': 0}
        finally:
            connections.close_all()
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
