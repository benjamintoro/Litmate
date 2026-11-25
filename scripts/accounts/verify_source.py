"""Compara todo el contenido personal MySQL con la copia definitiva en sólo lectura."""
import argparse
import getpass
import json
import os
from pathlib import Path
from scripts.accounts.clone_stage import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    database = args.database.resolve()
    if args.output.exists() or not database.is_file() or not database.is_relative_to(root/'data/accounts'):
        parser.error('Usa un almacén privado existente y un informe nuevo.')
    from iniciar_mysql_local import local_database_environment
    from reader_accounts.signing_key import load_key
    with local_database_environment(getpass.getpass('Contraseña MySQL de origen, sólo lectura (oculta): ')):
        os.environ.update(DJANGO_SETTINGS_MODULE='litmate_project.reader_settings', LITMATE_DEMO_MODE='local',
            LITMATE_DEMO_WORKSPACE=str(root/'.testtmp/unused-source-check'),
            LITMATE_ACCOUNTS_DB=str(database), SECRET_KEY=load_key(database))
        import django
        django.setup()
        from django.conf import settings
        settings.DATABASES['accounts']['NAME'] = database.as_uri()+'?mode=ro'
        settings.DATABASES['accounts']['OPTIONS'] = {'uri': True}
        from django.contrib.auth.models import User, Group
        from django.db import connections, transaction
        from core.models import (PerfilUsuario, AsistenteIA, ConversacionIA, MensajeIA,
                                 HistorialChatbot, LibroFavorito, ListaLectura, ElementoListaLectura)
        from suscripciones.models import PlanSuscripcion, SuscripcionUsuario, HistorialPago
        models = (User, Group, PlanSuscripcion, PerfilUsuario, AsistenteIA, ConversacionIA,
                  MensajeIA, HistorialChatbot, SuscripcionUsuario, HistorialPago,
                  LibroFavorito, ListaLectura, ElementoListaLectura)
        with connections['default'].cursor() as cursor:
            cursor.execute('SET SESSION TRANSACTION READ ONLY')
            cursor.execute('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            cursor.execute('SELECT DATABASE(), @@session.transaction_read_only')
            if cursor.fetchone() != ('litmate_db', 1):
                raise ValueError('Origen no protegido o incorrecto.')
        rows = {}
        with transaction.atomic(using='default'):
            for model in models:
                fields = [field.attname for field in model._meta.local_concrete_fields]
                original = list(model.objects.using('default').order_by('pk').values_list(*fields))
                copied = list(model.objects.using('accounts').order_by('pk').values_list(*fields))
                equal = digest(original) == digest(copied)
                rows[model._meta.db_table] = {'original_rows': len(original), 'copied_rows': len(copied), 'all_fields_equal': equal}
        connections.close_all()
        result = {'both_databases_read_only': True, 'tables': rows,
                  'all_original_account_content_preserved': all(row['all_fields_equal'] for row in rows.values()),
                  'identities_printed': False}
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
        print(json.dumps(result))
        return 0 if result['all_original_account_content_preserved'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
