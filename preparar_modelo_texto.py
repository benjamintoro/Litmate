"""Prepara un alias textual del GGUF existente, sin descargas ni inferencias.

Por defecto solo inspecciona. --create solicita explícitamente crear el alias
fijo; nunca modifica ni elimina el modelo original, .env o la aplicación.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError

from core.ai_http import local_origin, read_json_url


SOURCE = 'qwen3.5:9b-q4_K_M'
TARGET = 'litmate-qwen35-text:9b-q4_K_M'
PREFIX = 'application/vnd.ollama.image.'


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as content:
        for block in iter(lambda: content.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return 'sha256:' + digest.hexdigest()


def manifest_path(root, tag):
    name, version = tag.split(':', 1)
    path = root / 'manifests' / 'registry.ollama.ai' / 'library' / name / version
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('Manifest fuera del almacén local autorizado.')
    return path


def read_layers(root, tag):
    manifest = manifest_path(root, tag)
    raw = manifest.read_bytes()
    if len(raw) > 100_000:
        raise ValueError('Manifest demasiado grande.')
    value = json.loads(raw)
    layers = value.get('layers')
    if not isinstance(layers, list) or not 1 <= len(layers) <= 20:
        raise ValueError('Manifest sin capas válidas.')
    result = {}
    for layer in layers:
        digest, size, kind = layer.get('digest', ''), layer.get('size'), layer.get('mediaType', '')
        if (not re.fullmatch(r'sha256:[a-f0-9]{64}', digest) or type(size) is not int
                or size <= 0 or not isinstance(kind, str)):
            raise ValueError('Digest, tipo o tamaño de capa inválidos.')
        path = root / 'blobs' / digest.replace(':', '-')
        if (path.is_symlink() or not path.resolve().is_relative_to(root / 'blobs')
                or not path.is_file() or path.stat().st_size != size):
            raise ValueError('La capa local no coincide con su ruta o tamaño declarado.')
        result.setdefault(kind, []).append({**layer, 'path': path})
    return result, hashlib.sha256(raw).hexdigest()


def one_layer(layers, kind, *, optional=False):
    values = layers.get(PREFIX + kind, [])
    if not values and optional:
        return None
    if len(values) != 1:
        raise ValueError('Se requiere una sola capa de tipo ' + kind + '.')
    return values[0]


def text_layer(layer):
    if layer is None:
        return ''
    if layer['size'] > 2_000_000 or digest_file(layer['path']) != layer['digest']:
        raise ValueError('Metadatos de capa corruptos o demasiado extensos.')
    return layer['path'].read_bytes().decode('utf-8')


def inspect_profile(root, tag, info, *, textual=False, verify_weights=False):
    details = info.get('details') or {}
    capabilities = info.get('capabilities') or []
    if (details.get('format') != 'gguf' or details.get('family') != 'qwen35'
            or (info.get('model_info') or {}).get('general.architecture') != 'qwen35'
            or not {'completion', 'thinking'} <= set(capabilities)
            or info.get('remote_model') or info.get('remote_host')
            or details.get('remote_model') or details.get('remote_host') or 'cloud' in capabilities):
        raise ValueError('Se requiere el modelo GGUF qwen35 local con chat y thinking.')
    layers, manifest_hash = read_layers(root, tag)
    allowed = {PREFIX + name for name in ('model', 'projector', 'template', 'params', 'license', 'system')}
    allowed.add('application/vnd.docker.distribution.manifest.v2+json')
    if set(layers) - allowed:
        raise ValueError('El perfil tiene capas adicionales no previstas.')
    projector = layers.get(PREFIX + 'projector', [])
    if textual and (projector or 'vision' in capabilities or info.get('projector_info')):
        raise ValueError('El alias todavía contiene un proyector o capacidad visual.')
    if not textual and (not projector or 'vision' not in capabilities):
        raise ValueError('El modelo original no corresponde al perfil visual esperado.')
    model = one_layer(layers, 'model')
    with model['path'].open('rb') as content:
        if content.read(4) != b'GGUF':
            raise ValueError('La capa principal no es un archivo GGUF.')
    if verify_weights and digest_file(model['path']) != model['digest']:
        raise ValueError('El hash del GGUF no coincide con el manifest.')
    template = text_layer(one_layer(layers, 'template'))
    if info.get('template') != template:
        raise ValueError('La plantilla de la API difiere del blob local.')
    params = json.loads(text_layer(one_layer(layers, 'params')))
    if not isinstance(params, dict):
        raise ValueError('Los parámetros deben formar un objeto JSON.')
    license_text = text_layer(one_layer(layers, 'license'))
    system = text_layer(one_layer(layers, 'system', optional=True))
    directives = {}
    for name in ('RENDERER', 'PARSER'):
        values = re.findall(r'^' + name + r'\s+([^\r\n]+)$', info.get('modelfile', ''), re.M)
        if len(values) != 1 or values[0].strip() != 'qwen3.5':
            raise ValueError('No se pudo preservar el renderer/parser original qwen3.5.')
        directives[name.lower()] = values[0].strip()
    profile = {'files': {'model.gguf': model['digest']}, 'template': template,
               'parameters': params, 'license': license_text, **directives}
    if system:
        profile['system'] = system
    return profile, {'source_manifest_sha256': manifest_hash, 'model_digest': model['digest'],
        'model_bytes': model['size'], 'excluded_projector_bytes': sum(layer['size'] for layer in projector)}


def existing_profile_matches(info, profile):
    """/api/show puede exponer un alias que ya no tiene manifest plano visible."""
    details = info.get('details') or {}
    capabilities = info.get('capabilities') or []
    if (details.get('format') != 'gguf' or details.get('family') != 'qwen35'
            or (info.get('model_info') or {}).get('general.architecture') != 'qwen35'
            or not {'completion', 'thinking'} <= set(capabilities) or 'vision' in capabilities
            or info.get('projector_info') or info.get('remote_host') or info.get('remote_model')
            or details.get('remote_host') or details.get('remote_model') or 'cloud' in capabilities):
        return False
    modelfile = info.get('modelfile', '')
    weights = re.findall(r'^FROM\s+([^\r\n]+)$', modelfile, re.M)
    expected_digest = profile['files']['model.gguf'].split(':', 1)[1]
    if len(weights) != 1 or not re.search(r'sha256[:-]' + expected_digest + r'[\"\s]*$', weights[0]):
        return False
    for name in ('renderer', 'parser'):
        if re.findall(r'^' + name.upper() + r'\s+([^\r\n]+)$', modelfile, re.M) != [profile[name]]:
            return False
    if (info.get('template') != profile['template'] or info.get('license') != profile['license']
            or (info.get('system') or '') != profile.get('system', '')):
        return False
    parsed = {}
    for line in str(info.get('parameters', '')).splitlines():
        match = re.fullmatch(r'\s*(\w+)\s+(.+?)\s*', line)
        if not match:
            return False
        key, value = match.groups()
        try:
            value = json.loads(value)
        except ValueError:
            value = value.strip('"')
        parsed.setdefault(key, []).append(value)
    expected = profile['parameters']
    if set(parsed) != set(expected):
        return False
    for key, value in expected.items():
        actual = parsed[key]
        if isinstance(value, list):
            if actual != value and actual != [value]:
                return False
        elif actual != [value]:
            return False
    return True


def prepare(*, base_url='http://127.0.0.1:11434', models_dir=None, create=False, fetch=read_json_url):
    origin = local_origin(base_url)
    root = Path(models_dir or os.environ.get('OLLAMA_MODELS') or Path.home() / '.ollama' / 'models').resolve()
    def request(endpoint, payload=None):
        return fetch(origin + endpoint, payload=payload, headers={'Content-Type': 'application/json'},
                     timeout=120 if endpoint == '/api/create' else 15, local=True)
    def show(tag):
        try:
            return request('/api/show', {'model': tag})
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise
    info = show(SOURCE)
    if info is None:
        raise ValueError('El modelo original no está disponible localmente.')
    profile, metadata = inspect_profile(root, SOURCE, info, verify_weights=True)
    profile_hash = hashlib.sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    def check_existing():
        existing = show(TARGET)
        if existing is None:
            return False
        if not existing_profile_matches(existing, profile):
            raise ValueError('El alias ya existe con otro GGUF o perfil; no se sobrescribirá.')
        return True
    existing = check_existing()
    status = 'existing_profile_verified' if existing else 'ready_not_created'
    if create and not existing:
        # Revisa otra vez antes de una operación que el servidor podría usar
        # para reemplazar un tag. No se envía from, quantize ni un proyector.
        existing = check_existing()
        if not existing:
            if hashlib.sha256(manifest_path(root, SOURCE).read_bytes()).hexdigest() != metadata['source_manifest_sha256']:
                raise ValueError('El manifest original cambió durante la comprobación.')
            result = request('/api/create', {'model': TARGET, 'stream': False, **profile})
            if result.get('status') != 'success' or not check_existing():
                raise ValueError('La creación no produjo un alias textual verificable.')
            status = 'created_and_profile_verified'
        else:
            status = 'existing_profile_verified'
    if hashlib.sha256(manifest_path(root, SOURCE).read_bytes()).hexdigest() != metadata['source_manifest_sha256']:
        raise ValueError('El manifest original cambió; no se confirma su conservación.')
    return {'source': SOURCE, 'target': TARGET, 'status': status, 'profile_sha256': profile_hash,
            'source_manifest_unchanged': True, 'inference_executed': False, **metadata}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:11434')
    parser.add_argument('--models-dir', type=Path)
    parser.add_argument('--create', action='store_true', help='Crea únicamente el alias fijo si todavía no existe.')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        report = prepare(base_url=args.url, models_dir=args.models_dir, create=args.create)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as output:
                json.dump(report, output, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError, TypeError, KeyError):
        print('No se pudo verificar el perfil local; no se autoriza sobrescribir ningún alias.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
