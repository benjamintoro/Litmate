"""Prepara un delta revisable entre worktrees; nunca aplica cambios ni publica."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PREFIXES = ('reader_accounts/', 'core/', 'litmate_project/', 'templates/', 'static/', 'scripts/')
EXTENSIONS = {'.py', '.html', '.css', '.js', '.mjs', '.cjs', '.txt', '.json'}
ROOT_FILES = {'iniciar_produccion.py','requirements-production.txt'}


def allowed_file(name):
    path=Path(name)
    return (name.startswith(PREFIXES) or name in ROOT_FILES) and path.suffix in (*EXTENSIONS,'.ps1') and not path.is_absolute() and '..' not in path.parts


def sha(data):
    return hashlib.sha256(data).hexdigest()


def delta(name, before, after, *, existed):
    if not existed and not after:
        return f'diff --git a/{name} b/{name}\nnew file mode 100644\nindex 0000000..e69de29\n'
    header = f'diff --git a/{name} b/{name}\n' + ('' if existed else 'new file mode 100644\n')
    lines=difflib.unified_diff(
        before.decode('utf8').splitlines(True), after.decode('utf8').splitlines(True),
        fromfile='a/'+name if existed else '/dev/null', tofile='b/'+name)
    # Git necesita el marcador explícito cuando un archivo carece del LF final.
    # No concatenar la última línea borrada con la primera añadida.
    return header + ''.join(line if line.endswith('\n') else line+'\n\\ No newline at end of file\n' for line in lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-root', type=Path, required=True)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--verify-only', action='store_true', help='Verifica el paquete y las preimágenes sin aplicar ni crear archivos.')
    args = parser.parse_args()
    live, folder = args.live_root.resolve(), args.folder.resolve()
    if live == ROOT or not (live/'.git').is_dir() or not (ROOT/'.git').is_file():
        parser.error('Ejecuta desde un worktree separado y señala la raíz pública.')
    if not folder.is_relative_to(live/'backups'):
        parser.error('El paquete debe permanecer dentro de backups.')
    if args.verify_only:
        manifest = json.loads((folder/'manifest.json').read_text(encoding='utf8'))
        if manifest['patch_sha256'] != sha((folder/'changes.patch').read_bytes()):
            raise ValueError('El parche cambió desde su preparación.')
        for entry in manifest['files']:
            name = entry['path']
            if not allowed_file(name):
                raise ValueError('Ruta no permitida en el manifiesto.')
            target = live/name
            actual = sha(target.read_bytes()) if target.is_file() else None
            if target.is_symlink() or actual != entry['before_sha256'] or sha((folder/'after'/name).read_bytes()) != entry['after_sha256']:
                raise ValueError('El código cambió; no se permite sobrescribirlo: '+name)
        subprocess.run(['git', '-C', str(live), 'apply', '--check', '--ignore-space-change', str(folder/'changes.patch')], check=True)
        print(json.dumps({'verified': True, 'files': len(manifest['files']), 'applied': False}))
        return
    if folder.exists():
        parser.error('El paquete debe ocupar una carpeta NUEVA dentro de backups.')
    candidates = set(subprocess.check_output(['git', '-C', str(ROOT), 'diff', '--name-only', '-z'], text=True).split('\0'))
    candidates.update(subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '--others', '--exclude-standard', '-z'], text=True).split('\0'))
    entries, patch = [], ''
    for name in sorted(candidates):
        if not allowed_file(name):
            continue
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Ruta no permitida.')
        source, target = ROOT/relative, live/relative
        if not source.is_file() or source.is_symlink() or target.is_symlink():
            raise ValueError('No se empaquetan borrados ni enlaces.')
        after = source.read_bytes()
        before = target.read_bytes() if target.is_file() else b''
        if target.is_file() and before.replace(b'\r\n', b'\n') == after.replace(b'\r\n', b'\n'):
            continue
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=False)
        for kind, content in [('after', after), *([('before', before)] if target.is_file() else [])]:
            destination = folder/kind/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(content)
        patch += delta(name, before.replace(b'\r\n', b'\n'), after.replace(b'\r\n', b'\n'), existed=target.is_file())
        entries.append({'path': name, 'before_sha256': sha(before) if target.is_file() else None,
                        'after_sha256': sha(after), 'new_file': not target.is_file()})
    if not entries:
        raise ValueError('No hay cambios nuevos que empaquetar.')
    with (folder/'changes.patch').open('x', encoding='utf8', newline='\n') as stream:
        stream.write(patch)
    subprocess.run(['git', '-C', str(live), 'apply', '--check', '--ignore-space-change', str(folder/'changes.patch')], check=True)
    subprocess.run(['git', '-C', str(ROOT), 'apply', '--reverse', '--check', '--ignore-space-change', str(folder/'changes.patch')], check=True)
    manifest = {'version': 1, 'source_worktree': str(ROOT), 'target': str(live), 'files': entries,
                'patch_sha256': sha((folder/'changes.patch').read_bytes()), 'private_data_included': False,
                'migrations_required': [], 'applied': False, 'forward_check_passed': True, 'reverse_check_passed': True}
    with (folder/'manifest.json').open('x', encoding='utf8') as stream:
        json.dump(manifest, stream, indent=2)
    print(json.dumps({'package': str(folder), 'files': len(entries), 'applied': False,
                      'forward_check_passed': True, 'reverse_check_passed': True}))


if __name__ == '__main__':
    main()
