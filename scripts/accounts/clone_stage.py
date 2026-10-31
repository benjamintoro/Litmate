"""Ensaya copia de identidades existentes, sólo a un SQLite NUEVO de .testtmp.

MySQL: sesión de sólo lectura y snapshot REPEATABLE READ. No se copian sesiones
firmadas con otra clave ni catálogo/RAG. Jamás sobrescribe un destino existente.
"""
import argparse
from collections import Counter
from decimal import Decimal
import datetime
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys


def digest(rows):
    def encode(value):
        if isinstance(value, datetime.datetime):
            return value.astimezone(datetime.timezone.utc).isoformat()
        if isinstance(value, (datetime.date, Decimal)):
            return str(value)
        raise TypeError(type(value).__name__)
    return hashlib.sha256(json.dumps(rows, default=encode, ensure_ascii=True,
                                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--plans-audit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    folder = args.folder.resolve()
    if not folder.is_relative_to(Path.cwd() / '.testtmp') or folder.exists() or args.output.exists():
        parser.error('Usa un destino de ensayo NUEVO en .testtmp y un informe nuevo.')
    subprocess.run([sys.executable, '-B', '-m', 'scripts.accounts.prepare_stage', '--folder', str(folder),
                    '--plans-audit', str(args.plans_audit), '--empty'], check=True)
    from iniciar_mysql_local import local_database_environment
    with local_database_environment(getpass.getpass('Contraseña MySQL de origen, sólo lectura (oculta): ')):
        os.environ.update(DJANGO_SETTINGS_MODULE='litmate_project.reader_settings', LITMATE_DEMO_MODE='local',
            LITMATE_DEMO_WORKSPACE=str(folder), LITMATE_ACCOUNTS_DB=str(folder/'accounts.sqlite3'),
            SECRET_KEY=secrets.token_urlsafe(64))
        import django
        django.setup()
        from django.db import connections, transaction
        from django.contrib.auth.models import User, Group, Permission
        from django.contrib.contenttypes.models import ContentType
        from core.models import PerfilUsuario, AsistenteIA, ConversacionIA, MensajeIA, HistorialChatbot
        from suscripciones.models import PlanSuscripcion, SuscripcionUsuario, HistorialPago
        from reader_accounts.models import AccountEmail
        source, target = connections['default'], connections['accounts']
        with source.cursor() as cursor:
            cursor.execute('SET SESSION TRANSACTION READ ONLY')
            cursor.execute('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            cursor.execute('SELECT DATABASE(), @@session.transaction_read_only')
            if cursor.fetchone() != ('litmate_db', 1):
                raise ValueError('Origen incorrecto o sin protección de sólo lectura.')
        result = {'scope':'isolated account migration rehearsal', 'source_read_only': True,
                  'originals_modified':False, 'tables':{}, 'sessions_imported':0,
                  'public_server_changed':False, 'real_payments_activated':False}
        models = [User, Group, PlanSuscripcion, PerfilUsuario, AsistenteIA, ConversacionIA, MensajeIA,
                  SuscripcionUsuario, HistorialPago, HistorialChatbot]
        with transaction.atomic(using='default'), transaction.atomic(using='accounts'):
            if User.objects.using('accounts').exists() or PlanSuscripcion.objects.using('accounts').exists():
                raise ValueError('El destino ya contiene cuentas o planes. No se reemplazará.')
            for model in models:
                fields = list(model._meta.local_concrete_fields)
                names = [field.attname for field in fields]
                rows = list(model.objects.using('default').order_by('pk').values_list(*names))
                table = target.ops.quote_name(model._meta.db_table)
                columns = ','.join(target.ops.quote_name(field.column) for field in fields)
                sql = 'INSERT INTO ' + table + '('+columns+') VALUES ('+','.join(['%s']*len(fields))+')'
                prepared = [[field.get_db_prep_save(value, target) for field,value in zip(fields,row)] for row in rows]
                with target.cursor() as cursor:
                    if prepared:
                        cursor.executemany(sql, prepared)
                copied = list(model.objects.using('accounts').order_by('pk').values_list(*names))
                if digest(rows) != digest(copied):
                    raise ValueError('No coincide el contenido de ' + model._meta.db_table)
                result['tables'][model._meta.db_table] = {'source_rows':len(rows), 'copied_rows':len(copied),
                                                        'content_sha256_equal':True}
            # Las claves de permisos se reconcilian por identidad lógica, nunca
            # suponiendo que dos migraciones asignaron los mismos IDs.
            permission_map = {}
            for permission in Permission.objects.using('default').select_related('content_type'):
                ct, _ = ContentType.objects.using('accounts').get_or_create(
                    app_label=permission.content_type.app_label, model=permission.content_type.model)
                dest, _ = Permission.objects.using('accounts').get_or_create(content_type=ct,
                    codename=permission.codename, defaults={'name':permission.name})
                permission_map[permission.pk] = dest.pk
            for model in [User.groups.through, User.user_permissions.through, Group.permissions.through]:
                rows = list(model.objects.using('default').values())
                for row in rows:
                    if 'permission_id' in row:
                        row['permission_id'] = permission_map[row['permission_id']]
                    model.objects.using('accounts').create(**row)
                if model.objects.using('accounts').count() != len(rows):
                    raise ValueError('No coinciden las relaciones de permisos.')
                result['tables'][model._meta.db_table] = {'source_rows':len(rows),'copied_rows':len(rows),
                                                        'permission_ids_reconciled':True}
            emails = Counter(email.strip().lower() for email in User.objects.using('accounts').values_list('email',flat=True) if email.strip())
            for user in User.objects.using('accounts').all():
                normalized = user.email.strip().lower()
                if normalized and emails[normalized] == 1:
                    AccountEmail.objects.using('accounts').create(user=user, normalized=normalized)
            result['duplicate_email_groups_needing_review'] = sum(count>1 for count in emails.values())
            with target.cursor() as cursor:
                cursor.execute('PRAGMA foreign_key_check')
                if cursor.fetchall():
                    raise ValueError('Hay relaciones inválidas en el destino de ensayo.')
            # Los ID originales se conservan. Los contadores nuevos nunca quedan
            # por debajo del siguiente ID anunciado por el origen.
            for model in [*models, User.groups.through, User.user_permissions.through, Group.permissions.through]:
                with source.cursor() as cursor:
                    cursor.execute('SELECT AUTO_INCREMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s', [model._meta.db_table])
                    row = cursor.fetchone()
                if row and row[0]:
                    with target.cursor() as cursor:
                        cursor.execute('UPDATE sqlite_sequence SET seq=MAX(seq,%s) WHERE name=%s', [int(row[0])-1,model._meta.db_table])
                        if not cursor.rowcount:
                            cursor.execute('INSERT INTO sqlite_sequence(name,seq) VALUES (%s,%s)', [model._meta.db_table,int(row[0])-1])
        with target.cursor() as cursor:
            cursor.execute('PRAGMA quick_check')
            result['quick_check'] = cursor.fetchone()[0]
            cursor.execute('PRAGMA foreign_key_check')
            result['foreign_key_issues'] = len(cursor.fetchall())
        if result['quick_check'] != 'ok' or result['foreign_key_issues']:
            raise ValueError('El destino de ensayo no pasó la comprobación final.')
        target.close()
        source.close()
        result['destination_file_sha256'] = hashlib.sha256((folder/'accounts.sqlite3').read_bytes()).hexdigest()
        result['copy_used_for_http_or_mobile_tests'] = False
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x',encoding='utf-8') as stream:
            json.dump(result,stream,indent=2)
        print(json.dumps(result))


if __name__ == '__main__':
    main()
