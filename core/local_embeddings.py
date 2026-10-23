"""Embeddings descargados en Ollama: sin claves, nube ni ejecución de herramientas."""
import math
import hashlib
import os
import re
import time
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from .ai_http import local_origin, read_json_url
from .literary_ai import ProviderUnavailable


IDENTITY_CACHE_SECONDS = 30
_identity_cache = OrderedDict()
_identity_lock = Lock()


def clear_identity_cache():
    """Invalida comprobaciones compartidas; no elimina modelos ni vectores."""
    with _identity_lock:
        _identity_cache.clear()


def _manifest_digest(origin, model):
    """Huella del manifiesto local, sólo para el servicio Ollama por defecto.

    Un puerto distinto puede pertenecer a otro almacén. Si no identificamos el
    manifiesto o no coincide con el digest de /api/tags, no omitimos la
    inspección HTTP. Nunca suponemos que un alias sigue siendo local por su nombre.
    """
    if origin != 'http://127.0.0.1:11434':
        return None
    name = model if ':' in model.rsplit('/', 1)[-1] else model + ':latest'
    path, tag = name.rsplit(':', 1)
    parts = path.split('/')
    if not tag or any(not part or part in {'.', '..'} for part in parts):
        return None
    if len(parts) == 1:
        parts = ['registry.ollama.ai', 'library', *parts]
    elif len(parts) == 2:
        parts = ['registry.ollama.ai', *parts]
    elif len(parts) != 3:
        return None
    if any(not re.fullmatch(r'[A-Za-z0-9_.-]+', part) for part in [*parts, tag]):
        return None
    root = Path(os.environ.get('OLLAMA_MODELS') or Path.home() / '.ollama' / 'models')
    manifest = root / 'manifests' / Path(*parts) / tag
    try:
        # Los manifiestos son pequeños; una ruta inválida no provoca una lectura
        # ilimitada ni una petición de red a una dirección suministrada por el lector.
        with manifest.open('rb') as content:
            raw = content.read(131073)
        if not raw or len(raw) > 131072:
            return None
        return hashlib.sha256(raw).hexdigest()
    except OSError:
        return None


class OllamaEmbeddings:
    def __init__(self, base_url='http://127.0.0.1:11434',
                 model='embeddinggemma:latest', timeout=90):
        self.origin = local_origin(base_url)
        self.model = model.strip()
        self.timeout = max(15, min(int(timeout), 180))
        self._identity = None
        self._identity_checked_at = None
        self._identity_manifest = None
        if (not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}', self.model)
                or 'cloud' in self.model.lower() or '..' in self.model):
            raise ValueError('Se requiere un modelo de embeddings local')

    def identity(self):
        now = time.monotonic()
        manifest = _manifest_digest(self.origin, self.model)
        name = self.model if ':' in self.model.rsplit('/', 1)[-1] else self.model + ':latest'
        if (self._identity and self._identity_checked_at is not None
                and 0 <= now - self._identity_checked_at < IDENTITY_CACHE_SECONDS
                and manifest == self._identity_manifest):
            return self._identity
        key = self.origin, name, manifest
        if manifest:
            with _identity_lock:
                cached = _identity_cache.get(key)
                if cached and 0 <= now - cached[1] < IDENTITY_CACHE_SECONDS:
                    _identity_cache.move_to_end(key)
                    self._identity, self._identity_checked_at = cached
                    self._identity_manifest = manifest
                    return self._identity
        info = read_json_url(self.origin + '/api/show', payload={'model': self.model},
                             headers={'Content-Type': 'application/json'},
                             timeout=15, local=True)
        details = info.get('details') or {}
        if (info.get('remote_host') or info.get('remote_model')
                or details.get('remote_host') or details.get('remote_model')
                or details.get('format') != 'gguf'
                or not (info.get('model_info') or {}).get('general.architecture')
                or 'embedding' not in (info.get('capabilities') or [])
                or 'cloud' in (info.get('capabilities') or [])):
            raise ProviderUnavailable('embeddings_deben_ser_locales')
        tags = read_json_url(self.origin + '/api/tags', timeout=15, local=True)
        for item in tags.get('models', []):
            if isinstance(item, dict) and item.get('name') == name:
                digest = item.get('digest', '')
                if isinstance(digest, str) and re.fullmatch(r'[a-fA-F0-9]{64}', digest):
                    self._identity = name, digest.lower()
                    self._identity_checked_at = time.monotonic()
                    self._identity_manifest = manifest
                    # El hash del archivo sólo autoriza reutilización entre
                    # instancias cuando fue confirmado por la API local.
                    if manifest and manifest == digest.lower():
                        with _identity_lock:
                            _identity_cache[key] = self._identity, self._identity_checked_at
                            _identity_cache.move_to_end(key)
                            while len(_identity_cache) > 16:
                                _identity_cache.popitem(last=False)
                    return self._identity
        raise ProviderUnavailable('embeddings_no_descargados')

    def embed(self, texts, *, query=False):
        if (not isinstance(texts, list) or not 1 <= len(texts) <= 16
                or any(not isinstance(t, str) or not t.strip() or len(t) > 5000 for t in texts)):
            raise ValueError('Lote de embeddings inválido')
        self.identity()
        # EmbeddingGemma usa instrucciones diferentes para consultas y documentos.
        inputs = [('task: search result | query: ' + t if query else t) for t in texts]
        result = read_json_url(self.origin + '/api/embed', payload={
            'model': self.model, 'input': inputs, 'truncate': False, 'keep_alive': '10m',
        }, headers={'Content-Type': 'application/json'}, timeout=self.timeout, local=True)
        vectors = result.get('embeddings')
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ValueError('Cantidad de embeddings inválida')
        output, dimension = [], None
        for vector in vectors:
            if (not isinstance(vector, list) or not 1 <= len(vector) <= 2048
                    or any(type(x) not in {int, float} or not math.isfinite(x) for x in vector)):
                raise ValueError('Embedding inválido')
            if dimension is not None and dimension != len(vector):
                raise ValueError('Dimensiones inconsistentes')
            dimension = len(vector)
            norm = math.sqrt(sum(float(x) ** 2 for x in vector))
            if norm <= 1e-12 or not math.isfinite(norm):
                raise ValueError('Embedding sin información')
            output.append([float(x) / norm for x in vector])
        return output


def configured_embedder(settings):
    if not getattr(settings, 'LITMATE_RAG_SEMANTIC', True):
        return None
    return OllamaEmbeddings(
        getattr(settings, 'LITMATE_OLLAMA_URL', 'http://127.0.0.1:11434'),
        getattr(settings, 'LITMATE_EMBED_MODEL', 'embeddinggemma:latest'),
        getattr(settings, 'LITMATE_EMBED_TIMEOUT', 90))
