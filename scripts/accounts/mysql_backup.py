"""Respaldo lógico consistente de MySQL y restauración verificable en SQLite nuevo."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


def restored_fingerprint(expected, actual):
    """Conserva la huella histórica admitiendo ISO equivalentes solo en fechas.

    Django puede serializar .000Z desde MySQL y Z al restaurar en SQLite.
    No se normalizan textos del usuario, identificadores ni fechas diferentes.
    """
    from copy import deepcopy
    from django.apps import apps
    from django.db.models import DateTimeField
    from django.utils.dateparse import parse_datetime
    from scripts.accounts.prepare_mysql import fingerprint
    reference={(row['model'], str(row['pk'])):row for row in expected}
    normalized=deepcopy(actual)
    for row in normalized:
        prior=reference.get((row['model'],str(row['pk'])))
        if prior is None:
            continue
        model=apps.get_model(row['model'])
        for field in model._meta.fields:
            if not isinstance(field,DateTimeField):
                continue
            before=prior['fields'].get(field.name)
            after=row['fields'].get(field.name)
            if isinstance(before,str) and isinstance(after,str) and before!=after:
                try:
                    first,second=parse_datetime(before),parse_datetime(after)
                except ValueError:
                    continue
                if first is not None and second is not None and first==second:
                    row['fields'][field.name]=before
    return fingerprint(normalized)


def restore_check(folder, destination):
    target = destination / 'accounts/users.sqlite3'
    if target.exists():
        raise FileExistsError('La restauración necesita un archivo de cuentas nuevo.')
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf8'))
    for name, expected in manifest.get('private_files', {}).items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Referencia de archivo privado inválida.')
        if hashlib.sha256((folder / relative).read_bytes()).hexdigest() != expected:
            raise ValueError('Un archivo privado del respaldo no coincide.')
    for name in ('LITMATE_ACCOUNTS_BACKEND', 'LITMATE_ACCOUNTS_MYSQL_NAME',
                 'LITMATE_ACCOUNTS_MYSQL_USER', 'LITMATE_ACCOUNTS_MYSQL_PASSWORD'):
        os.environ.pop(name, None)
    from scripts.accounts.community_test_settings import configure
    configure(destination)
    import django
    django.setup()
    from django.db import connections, transaction
    from django.db.migrations.executor import MigrationExecutor
    from django.core import serializers
    from scripts.accounts.prepare_mysql import fingerprint, records
    connection = connections['accounts']
    if connection.vendor != 'sqlite' or Path(connection.settings_dict['NAME']).resolve() != target.resolve():
        raise ValueError('La restauración requiere SQLite aislado en el destino indicado.')
    raw = (folder / 'accounts.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest['sha256']:
        raise ValueError('La huella del respaldo no coincide.')
    executor = MigrationExecutor(connections['accounts'])
    executor.migrate(executor.loader.graph.leaf_nodes())
    with transaction.atomic(using='accounts'):
        with connections['accounts'].constraint_checks_disabled():
            for item in serializers.deserialize('json', raw.decode('utf8')):
                item.save(using='accounts')
        connections['accounts'].check_constraints()
    if restored_fingerprint(json.loads(raw), records()) != manifest['models']:
        raise ValueError('La restauración no conserva filas e identificadores.')
    shutil.copy2(folder / 'signing.dpapi', Path(str(target) + '.signing.dpapi'))
    if (folder / 'avatars').exists():
        shutil.copytree(folder / 'avatars', destination / 'accounts/avatars')
    return {'restore_verified': True, 'models': len(manifest['models']),
            'rows': sum(model['count'] for model in manifest['models'].values())}


def create(root, signing_database):
    from django.db import connections, transaction
    from scripts.accounts.prepare_mysql import records, fingerprint
    from reader_accounts.production_runtime import FileLease
    root = Path(root).resolve()
    parent = root / 'backups/mysql-accounts'
    parent.mkdir(parents=True, exist_ok=True)
    with FileLease(parent / 'backup.lock'):
        folder = parent / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        folder.mkdir()
        with connections['accounts'].cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        with transaction.atomic(using='accounts'):
            data = records()
        raw = json.dumps(data, ensure_ascii=False).encode('utf8')
        (folder / 'accounts.json').write_bytes(raw)
        key = Path(str(signing_database) + '.signing.dpapi')
        shutil.copy2(key, folder / 'signing.dpapi')
        avatars = Path(signing_database).parent / 'avatars'
        if avatars.is_dir():
            shutil.copytree(avatars, folder / 'avatars')
        private_files = {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in folder.rglob('*') if path.is_file() and path.name != 'accounts.json'}
        manifest = {'backend': 'mysql', 'schema': connections['accounts'].settings_dict['NAME'],
                    'sha256': hashlib.sha256(raw).hexdigest(), 'models': fingerprint(data), 'private_files': private_files}
        (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
        (root / '.testtmp').mkdir(exist_ok=True)
        with TemporaryDirectory(prefix='mysql-restore-', dir=root / '.testtmp') as temporary:
            completed = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-m', 'scripts.accounts.mysql_backup',
                '--restore-check', str(folder), '--destination', temporary], cwd=root,
                capture_output=True, text=True, encoding='utf8', timeout=120)
            if completed.returncode:
                raise ValueError('El respaldo MySQL no pasó la restauración aislada.')
            result = json.loads(completed.stdout.strip().splitlines()[-1])
        result.update(backup=str(folder), sha256=manifest['sha256'], status='verified')
        (folder / 'verified.json').write_text(json.dumps(result, indent=2), encoding='utf8')
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore-check', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if not args.destination.resolve().is_relative_to(root / '.testtmp'):
        parser.error('La restauración requiere un directorio nuevo en .testtmp.')
    print(json.dumps(restore_check(args.restore_check, args.destination)))
