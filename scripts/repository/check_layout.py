"""Valida documentos trasladados y archivos protegidos, sin abrir bases de datos."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
COMPATIBLE = {'README_ASISTENTE_IA.md', 'MYSQL_LOCAL.md', 'LEEME.md',
              'analizar_evaluacion_ia.py', 'resumir_benchmark_ia.py'}


def local_links(path):
    fenced = False
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if re.match(r'^\s*(```|~~~)', line):
            fenced = not fenced
            continue
        if fenced:
            continue
        for target in re.findall(r'\[[^\]\n]+\]\(([^)\n]+)\)', line):
            if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target) or target.startswith('#'):
                continue
            yield target, (path.parent / target.split('#', 1)[0]).resolve()


def verify(manifest_path, *, staged=False):
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    failures = []
    for name, expected in manifest['protected_hashes'].items():
        path = ROOT / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            failures.append('protected_file_changed: ' + name)
    for item in manifest['files']:
        original = ROOT / item['origin']
        saved = Path(manifest_path).parent / item['origin']
        destination = ROOT / item['destination']
        if not saved.is_file() or hashlib.sha256(saved.read_bytes()).hexdigest() != item['sha256']:
            failures.append('backup_mismatch: ' + item['origin'])
        if not destination.is_file():
            failures.append('missing_destination: ' + item['destination'])
        elif item['origin'].endswith('.py') or item['origin'] == 'LitMate_IA_Gratis_Codigo_Completo.md':
            if hashlib.sha256(destination.read_bytes()).hexdigest() != item['sha256']:
                failures.append('implementation_changed: ' + item['destination'])
        if staged:
            if not original.is_file() or hashlib.sha256(original.read_bytes()).hexdigest() != item['sha256']:
                failures.append('original_changed_before_verification: ' + item['origin'])
        elif item['origin'] in COMPATIBLE:
            if not original.is_file():
                failures.append('missing_compatibility_entry: ' + item['origin'])
        elif original.exists():
            failures.append('duplicate_old_document: ' + item['origin'])
    documents = list((ROOT / 'docs').rglob('*.md')) + list((ROOT / 'reports').rglob('*.md'))
    documents += [ROOT / 'README.md', ROOT / 'scripts/README.md']
    documents += [ROOT / name for name in COMPATIBLE if name.endswith('.md')]
    links = 0
    for path in documents:
        if not path.exists():
            continue
        for original, target in local_links(path):
            links += 1
            if not target.exists():
                failures.append('broken_link: ' + path.relative_to(ROOT).as_posix() + ' -> ' + original)
    return {'passed': not failures, 'failures': failures, 'staged': staged,
            'protected_files': len(manifest['protected_hashes']), 'moved_files': len(manifest['files']),
            'local_document_links': links, 'no_database_opened': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--staged', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('El informe ya existe; usa otro nombre.')
    result = verify(args.manifest, staged=args.staged)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
