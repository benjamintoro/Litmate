"""Embeddings descargados en Ollama: sin claves, nube ni ejecución de herramientas."""
import math
import re
from .ai_http import local_origin, read_json_url
from .literary_ai import ProviderUnavailable


class OllamaEmbeddings:
    def __init__(self, base_url='http://127.0.0.1:11434',
                 model='embeddinggemma:latest', timeout=90):
        self.origin = local_origin(base_url)
        self.model = model.strip()
        self.timeout = max(15, min(int(timeout), 180))
        self._identity = None
        if (not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}', self.model)
                or 'cloud' in self.model.lower() or '..' in self.model):
            raise ValueError('Se requiere un modelo de embeddings local')

    def identity(self):
        if self._identity:
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
        name = self.model if ':' in self.model.rsplit('/', 1)[-1] else self.model + ':latest'
        for item in tags.get('models', []):
            if isinstance(item, dict) and item.get('name') == name:
                digest = item.get('digest', '')
                if isinstance(digest, str) and re.fullmatch(r'[a-fA-F0-9]{64}', digest):
                    self._identity = name, digest.lower()
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
