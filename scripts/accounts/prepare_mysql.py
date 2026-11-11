"""Ensayo de cuentas en una base MySQL nueva. Conserva copias privadas en .testtmp."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3

ROOT = Path(__file__).resolve().parents[2]


def fingerprint(records):
    grouped = {}
    for row in records:
        grouped.setdefault(row['model'], []).append(row)
    return {model: {
        'count': len(rows),
        'sha256': hashlib.sha256(json.dumps(
            sorted(rows, key=lambda row: str(row['pk'])),
            ensure_ascii=True, sort_keys=True).encode()).hexdigest(),
    } for model, rows in grouped.items()}


def setup(folder):
    from scripts.accounts.community_test_settings import configure
    configure(folder)
    from reader_accounts.signing_key import load_key
    os.environ['SECRET_KEY'] = load_key(folder/'accounts/users.sqlite3')
    os.environ['LITMATE_SIMULATED_CHECKOUT_ENABLED'] = '1'
    for name in ('AI_RUNTIME_DB', 'AI_STREAM_DB', 'AI_ANSWER_CACHE_DB'):
        os.environ['LITMATE_'+name] = str(folder/'runtime'/(name.lower()+'.sqlite3'))
    import django
    django.setup()


def records():
    from django.apps import apps
    from django.core import serializers
    from reader_accounts.router import is_account
    models = [model for model in apps.get_models()
              if is_account(model._meta.app_label, model._meta.model_name)]
    objects = (obj for model in models for obj in model.objects.using('accounts').order_by('pk').iterator())
    return json.loads(serializers.serialize('json', objects))


def prepare(source, folder):
    source = source.resolve()
    allowed = Path('G:/Proyecto/Litmate/data/accounts/users.sqlite3').resolve()
    if source != allowed and not source.is_relative_to(ROOT/'.testtmp'):
        raise ValueError('Usa cuentas del principal o una copia bajo .testtmp.')
    if folder.exists():
        raise FileExistsError('El destino debe ser nuevo.')
    key = source.with_name(source.name+'.signing.dpapi')
    if not source.is_file() or not key.is_file():
        raise ValueError('Falta el almacén o su clave protegida.')
    (folder/'accounts').mkdir(parents=True)
    with sqlite3.connect(source.as_uri()+'?mode=ro', uri=True) as src:
        with sqlite3.connect(folder/'accounts/users.sqlite3') as dst:
            src.backup(dst)
    shutil.copyfile(key, folder/'accounts/users.sqlite3.signing.dpapi')
    if (source.parent/'avatars').is_dir():
        shutil.copytree(source.parent/'avatars', folder/'accounts/avatars')
    setup(folder)
    from django.core.management import call_command
    call_command('migrate', database='accounts', interactive=False, verbosity=0)
    data = records()
    fixture = folder/'cuentas.json'
    fixture.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
    inventory = fingerprint(data)
    result = {
        'snapshot_only': True, 'source_unchanged': True,
        'fixture_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(),
        'models': inventory, 'rows': sum(value['count'] for value in inventory.values()),
        'mysql_executed': False,
        'remaining_dependencies': [
            'Ensayar con credencial local MySQL para una base nueva.',
            'Adaptar preflight, respaldo y restauración que actualmente usan SQLite.',
            'Conservar la clave de firma y medios al cambiar el almacén.',
            'Validar concurrencia de cuotas y cambios de plan bajo MySQL.',
        ],
    }
    (folder/'manifest.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    return result


def rehearse(folder, schema, credential):
    if not re.fullmatch(r'litmate_accounts_ensayo_[a-z0-9_]{6,40}', schema):
        raise ValueError('Nombre de base aislada inválido.')
    manifest = json.loads((folder/'manifest.json').read_text())
    fixture = folder/'cuentas.json'
    if hashlib.sha256(fixture.read_bytes()).hexdigest() != manifest['fixture_sha256']:
        raise ValueError('La copia privada cambió.')
    from reader_accounts.signing_key import _dpapi
    password = _dpapi(credential.read_bytes(), decrypt=True).decode()
    import MySQLdb
    user = os.environ.get('LITMATE_MYSQL_TEST_USER', 'litmate_app')
    server = MySQLdb.connect(host='127.0.0.1', port=3306, user=user,
                            passwd=password, charset='utf8mb4')
    with server.cursor() as cursor:
        # CREATE sin IF EXISTS impide adoptar una base con datos anteriores.
        cursor.execute('CREATE DATABASE '+schema+' CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
    server.close()
    setup(folder)
    from django.conf import settings
    from django.db import connections, transaction
    connections['accounts'].close()
    config = settings.DATABASES['accounts']
    config.update(ENGINE='django.db.backends.mysql', NAME=schema, USER=user,
                  PASSWORD=password, HOST='127.0.0.1', PORT='3306',
                  OPTIONS={'charset':'utf8mb4', 'isolation_level':'read committed'})
    del connections['accounts']
    from django.db.migrations.executor import MigrationExecutor
    from django.db.migrations.operations.models import CreateModel
    from django.db.models import ForeignKey
    from reader_accounts.router import is_account
    executor = MigrationExecutor(connections['accounts'])
    for (app, _), migration in executor.loader.disk_migrations.items():
        if app != 'core':
            continue
        for operation in migration.operations:
            if isinstance(operation, CreateModel):
                for _, field in operation.fields:
                    if isinstance(field, ForeignKey) and isinstance(field.remote_field.model, str):
                        target = field.remote_field.model.split('.')
                        if len(target) == 2 and not is_account(target[0], target[1].lower()):
                            field.db_constraint = False
    # Sin post_migrate, los permisos conservan sus IDs originales al importar.
    executor.migrate(executor.loader.graph.leaf_nodes())
    from django.core import serializers
    with transaction.atomic(using='accounts'):
        with connections['accounts'].constraint_checks_disabled():
            for item in serializers.deserialize('json', fixture.read_text(encoding='utf8')):
                item.save(using='accounts')
        connections['accounts'].check_constraints()
    after = fingerprint(records())
    if after != manifest['models']:
        raise ValueError('El ensayo no conserva las filas e identificadores.')
    from django.test import Client
    from django.contrib.auth import authenticate
    from django.contrib.auth.models import User
    from uuid import uuid4
    name = 'migration_'+uuid4().hex[:12]
    trial_password = uuid4().hex+'-Reader!'
    client = Client()
    client.get('/registro/')
    response = client.post('/registro/', {
        'username': name, 'email':name+'@example.invalid',
        'password':trial_password, 'password_confirm':trial_password,
    })
    new_user = User.objects.using('accounts').get(username=name)
    return {
        'mysql_executed': True, 'isolated_schema': schema,
        'all_original_ids_hashes_and_relations_preserved': True,
        'registration': response.status_code == 302 and new_user.check_password(trial_password),
        'login': authenticate(username=name, password=trial_password) is not None,
        'source_changed': False, 'production_cutover_prepared': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['preparar','ensayar'])
    parser.add_argument('--source', type=Path)
    parser.add_argument('--folder', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--schema')
    parser.add_argument('--mysql-secret-file', type=Path)
    args = parser.parse_args()
    folder = args.folder.resolve()
    if not folder.is_relative_to(ROOT/'.testtmp') or args.report.exists():
        parser.error('Utiliza .testtmp y un informe nuevo.')
    if args.action == 'preparar':
        if args.source is None:
            parser.error('Falta --source.')
        result = prepare(args.source, folder)
    else:
        if args.schema is None or args.mysql_secret_file is None:
            parser.error('Faltan el esquema nuevo y la credencial DPAPI local.')
        result = rehearse(folder, args.schema, args.mysql_secret_file)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps({key:value for key,value in result.items() if key != 'models'}))


if __name__ == '__main__':
    main()
