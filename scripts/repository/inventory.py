"""Inventario estático: no importa Django ni lee .env, bases, uploads o backups."""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
EXCLUDED = {'.git', 'venv', '.venv', 'env', 'backups', 'media', 'logs',
            '.test-tmp', '.testtmp', '__pycache__', 'reportes', 'reports', 'node_modules',
            '.vscode', '.kilo'}
DOCUMENT_MOVES = {
    'README_ASISTENTE_IA.md': 'docs/guides/README_ASISTENTE_IA.md',
    'MYSQL_LOCAL.md': 'docs/guides/MYSQL_LOCAL.md',
    'ARQUITECTURA_IA_RENDIMIENTO.md': 'docs/architecture/ARQUITECTURA_IA_RENDIMIENTO.md',
    'LEEME.md': 'docs/archive/LEEME_IA_V3.md',
    'LitMate_IA_Gratis_Codigo_Completo.md': 'docs/archive/LitMate_IA_Gratis_Codigo_Completo.md',
}
REPORT_MOVES = {name: 'reports/archive/' + name for name in (
    'INFORME_ARQUITECTURA_IA_21_OCTUBRE.md', 'INFORME_BUSQUEDA_LITERARIA.md',
    'INFORME_CONTINUACION_20_OCTUBRE.md', 'INFORME_FUENTES_MODELOS.md',
    'INFORME_RESULTADOS_21_OCTUBRE.md', 'INFORME_SINOPSIS_DOCKER_20261026.md')}
SCRIPT_MOVES = {name: 'scripts/analysis/' + name for name in (
    'analizar_evaluacion_ia.py', 'resumir_benchmark_ia.py')}
MOVES = {**DOCUMENT_MOVES, **REPORT_MOVES, **SCRIPT_MOVES}


def files(root):
    """Poda antes de descender; evita explorar corpus y datos personales."""
    import os
    for current, directories, filenames in os.walk(root):
        directories[:] = sorted(name for name in directories if name not in EXCLUDED
                                 and not (Path(current) == root and name == 'data'))
        for name in sorted(filenames):
            if name.startswith('.env') or name == 'compose.env':
                continue
            path = Path(current) / name
            if path.suffix.lower() in {'.py', '.js', '.html', '.md', '.yml', '.yaml', '.ps1', '.txt', '.json'}:
                yield path


def module_name(path):
    parts = list(path.with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def domain(stem):
    if any(word in stem for word in ('character', 'identity', 'alias', 'focus', 'conversation', 'reference')):
        return 'identity_context'
    if any(word in stem for word in ('rag', 'embedding', 'retriev', 'search', 'google', 'openlibrary', 'wikipedia')):
        return 'retrieval'
    if any(word in stem for word in ('quality', 'audit', 'evidence', 'constraint')):
        return 'verification'
    if any(word in stem for word in ('knowledge', 'memory', 'library', 'learning', 'acquisition', 'gutenberg')):
        return 'knowledge'
    if any(word in stem for word in ('presentation', 'language', 'narrative', 'recommend', 'answer', 'prose')):
        return 'answers'
    return 'runtime'


def proposal(relative):
    name, stem = relative.name, relative.stem
    key = relative.as_posix()
    if key in MOVES:
        return MOVES[key], 'lote 1; alias para guías principales y scripts; referencias verificadas'
    if relative.parts[0] == 'core' and name.startswith('test_'):
        return f'tests/{domain(stem)}/{name}', 'lote futuro: imports cruzados, patch strings y descubrimiento Django'
    if relative.parts[0] == 'core' and len(relative.parts) == 2 and name != 'literary_ai_views.py' and (
            stem.startswith(('ai_', 'literary_', 'local_')) or stem in {'books_google', 'openlibrary_editions'}):
        return f'literary_ai/{domain(stem)}/{name}', 'lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad'
    return key, 'conservar en esta fase; integración Django, datos de prueba o ruta pública'


def collect(root=ROOT):
    root = Path(root).resolve()
    paths = list(files(root))
    modules = {module_name(path.relative_to(root)) for path in paths if path.suffix == '.py'}
    rows, imports, dynamic, literals, anchors, calls, errors = [], [], [], [], [], [], []
    for path in paths:
        relative = path.relative_to(root)
        target, risk = proposal(relative)
        raw = path.read_bytes()
        rows.append({'origin': relative.as_posix(), 'proposed': target, 'risk': risk,
                     'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        if path.suffix != '.py':
            continue
        module = module_name(relative)
        package = module if path.name == '__init__.py' else module.rpartition('.')[0]
        try:
            tree = ast.parse(raw.decode('utf-8-sig'), filename=str(relative))
        except (SyntaxError, UnicodeError) as error:
            errors.append({'file': relative.as_posix(), 'error': type(error).__name__})
            continue
        for node in ast.walk(tree):
            location = {'file': relative.as_posix(), 'line': getattr(node, 'lineno', 0)}
            if isinstance(node, ast.Import):
                imports.extend({**location, 'kind': 'absolute', 'module': alias.name}
                               for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                value = node.module or ''
                if node.level and package:
                    value = importlib.util.resolve_name('.' * node.level + value, package)
                targets = ([value] if value in modules else []) + [value + '.' + alias.name
                           for alias in node.names if value + '.' + alias.name in modules]
                imports.append({**location, 'kind': 'relative' if node.level else 'absolute',
                                'module': value, 'local_modules': targets})
            elif isinstance(node, ast.Call):
                function = ast.unparse(node.func)
                if function.endswith(('import_module', '__import__', 'spec_from_file_location', 'find_spec', 'reload')):
                    first = node.args[0] if node.args else None
                    target = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else '<dynamic>'
                    dynamic.append({**location, 'function': function, 'module': target})
                if function in {'subprocess.run', 'subprocess.Popen', 'call_command'}:
                    calls.append({**location, 'function': function})
            elif isinstance(node, ast.Name) and node.id == '__file__':
                anchors.append(location)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                # Sólo rutas/nombres, nunca líneas de código ni valores privados.
                if (len(value) <= 240 and (re.fullmatch(r'[\w./\\:-]+\.(?:py|md|json|sqlite3|html|ya?ml|txt)', value)
                        or re.fullmatch(r'(?:core|suscripciones|litmate_project|django)\.[\w.]+', value)
                        or value in {'reportes', 'reports', 'static', 'templates', 'fixtures', 'searxng'})):
                    literals.append({**location, 'value': value})
    return {'scope': 'static code and document metadata; excludes credentials, databases, backups, uploads and runtime reports',
        'files': rows, 'imports': imports, 'dynamic_imports': dynamic, 'file_anchors': anchors,
        'path_literals': literals, 'process_and_management_calls': calls, 'parse_errors': errors,
        'migration_files': [row for row in rows if '/migrations/' in row['origin']],
        'counts': {'files': len(rows), 'python_modules': len(modules), 'imports': len(imports),
                   'dynamic_imports': len(dynamic), 'file_anchors': len(anchors)}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('El inventario ya existe; usa otro nombre para conservarlo.')
    result = collect()
    result['git_status'] = subprocess.run(['git', 'status', '--short'], cwd=ROOT,
        capture_output=True, text=True, check=True).stdout.splitlines()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result['counts']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
