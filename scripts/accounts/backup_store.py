"""Respaldo consistente y restauración a un destino nuevo; nunca reemplaza datos."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from contextlib import closing

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def private_path(path):
    path = Path(path).resolve()
    if not (path.is_relative_to(ROOT / 'data/accounts') or path.is_relative_to(ROOT / '.testtmp')):
        raise ValueError('La base debe estar en data/accounts o en un ensayo .testtmp.')
    return path


def checked_avatar(root, name):
    if not re.fullmatch(r'[a-f0-9]{32}\.jpg', name):
        raise ValueError('Nombre de avatar inválido en el respaldo.')
    if root.is_symlink():
        raise ValueError('La carpeta de avatares no puede ser un enlace.')
    path = root/name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 128 * 1024:
        raise ValueError('Falta un avatar o su archivo no es seguro.')
    return path


def avatar_references(database):
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as db:
        return {row[0].split('/')[1] for row in db.execute('SELECT DISTINCT imagen FROM core_perfilusuario')
                if re.fullmatch(r'avatars/[a-f0-9]{32}\.jpg', row[0] or '')}


def create(database, folder):
    from scripts.knowledge.knowledge_campaign import sqlite_snapshot
    from scripts.accounts.promote_stage import inventory
    from reader_accounts.signing_key import _dpapi
    database, folder = private_path(database), Path(folder).resolve()
    if not (folder.is_relative_to(ROOT / 'backups') or folder.is_relative_to(ROOT / '.testtmp')):
        raise ValueError('Usa una carpeta nueva en backups o .testtmp.')
    key = database.with_name(database.name + '.signing.dpapi')
    if not database.is_file() or not key.is_file():
        raise ValueError('Falta la base o su clave protegida; no se regenerará.')
    _dpapi(key.read_bytes(), decrypt=True)
    folder.mkdir(parents=True, exist_ok=False)
    target = folder / 'accounts.sqlite3'
    sqlite_snapshot(database, target)
    with (folder / 'signing.dpapi').open('xb') as stream:
        stream.write(key.read_bytes())
    avatars = {}
    for name in sorted(avatar_references(target)):
        original = checked_avatar(database.parent/'avatars', name)
        (folder/'avatars').mkdir(exist_ok=True)
        with (folder/'avatars'/name).open('xb') as stream:
            stream.write(original.read_bytes())
        avatars[name] = digest(folder/'avatars'/name)
    manifest = {'version': 2, 'database_sha256': digest(target), 'avatars': avatars,
                'key_sha256': digest(folder / 'signing.dpapi'), 'tables': inventory(target)}
    with (folder / 'manifest.json').open('x', encoding='utf8') as stream:
        json.dump(manifest, stream, indent=2)
    return manifest


def restore_new(folder, database, *, deployment_authorized=False):
    from scripts.knowledge.knowledge_campaign import sqlite_snapshot
    from scripts.accounts.promote_stage import inventory
    from reader_accounts.signing_key import _dpapi
    database, folder = private_path(database), Path(folder).resolve()
    if database.is_relative_to(ROOT / 'data/accounts') and not deployment_authorized:
        raise PermissionError('La restauración real requiere autorización explícita.')
    key = database.with_name(database.name + '.signing.dpapi')
    if database.exists() or key.exists():
        raise FileExistsError('El destino ya existe; no se reemplazará.')
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf8'))
    source, source_key = folder / 'accounts.sqlite3', folder / 'signing.dpapi'
    if (manifest.get('version') not in (1, 2) or digest(source) != manifest.get('database_sha256')
            or digest(source_key) != manifest.get('key_sha256')
            or inventory(source) != manifest.get('tables')):
        raise ValueError('El respaldo no coincide con su manifiesto.')
    avatars = manifest.get('avatars', {})
    if not isinstance(avatars, dict):
        raise ValueError('Manifiesto de imágenes inválido.')
    if set(avatars) != avatar_references(source):
        raise ValueError('El respaldo no incluye todas las fotos referenciadas.')
    for name, expected in avatars.items():
        if digest(checked_avatar(folder/'avatars', name)) != expected:
            raise ValueError('Un avatar no coincide con su manifiesto.')
        existing = database.parent/'avatars'/name
        if existing.exists() and digest(checked_avatar(database.parent/'avatars', name)) != expected:
            raise FileExistsError('Ya existe otro avatar; no se reemplazará.')
    _dpapi(source_key.read_bytes(), decrypt=True)
    database.parent.mkdir(parents=True, exist_ok=True)
    sqlite_snapshot(source, database)
    with key.open('xb') as stream:
        stream.write(source_key.read_bytes())
    for name in avatars:
        target = database.parent/'avatars'/name
        if not target.exists():
            target.parent.mkdir(exist_ok=True)
            if target.parent.is_symlink():
                raise ValueError('El destino de imágenes no puede ser un enlace.')
            with target.open('xb') as stream:
                stream.write(checked_avatar(folder/'avatars', name).read_bytes())
    if inventory(database) != manifest['tables']:
        raise ValueError('La restauración no pasó integridad; conserva los archivos e investiga.')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['crear', 'restaurar-nuevo'])
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--deployment-authorized', action='store_true')
    args = parser.parse_args()
    if args.action == 'crear':
        result = create(args.database, args.folder)
    else:
        result = restore_new(args.folder, args.database, deployment_authorized=args.deployment_authorized)
    print(json.dumps({'verified': True, 'tables': len(result['tables']), 'originals_replaced': False}))


if __name__ == '__main__':
    main()
