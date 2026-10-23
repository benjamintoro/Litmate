"""Microbenchmark CPU reproducible de caché RAG, con documentos sintéticos.

No inicia Django, no carga .env ni consulta red/Ollama. BM25/SQLite, matrices y
fusión son reales; los vectores constantes son controles de memoria/caché, no
embeddings neuronales. No mide calidad semántica ni latencia del chat.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import statistics
import tempfile
import time
import tracemalloc

from core import local_rag


class ControlledVectors:
    def __init__(self, dimension=768):
        self.vector = [1 / math.sqrt(dimension)] * dimension

    def identity(self):
        return 'synthetic-cache-control', 'a' * 64

    def embed(self, texts, *, query=False):
        return [list(self.vector) for text in texts]


def summary(samples):
    ordered = sorted(samples)
    return {'samples': len(samples), 'mean_ms': round(statistics.mean(samples), 4),
        'p50_ms': round(statistics.median(samples), 4),
        'p95_ms': round(ordered[max(0, math.ceil(len(samples) * .95) - 1)], 4),
        'max_ms': round(max(samples), 4)}


def signatures(sources):
    return [(source['title'], source['author'], hashlib.sha256(
        source['description'].encode()).hexdigest()) for source in sources]


@contextmanager
def matrix_cache_size(maximum):
    current = local_rag._vector_matrix
    local_rag._vector_matrix = lru_cache(maxsize=maximum)(current.__wrapped__)
    try:
        yield local_rag._vector_matrix
    finally:
        local_rag._vector_matrix.cache_clear()
        local_rag._vector_matrix = current


def run(documents=800, repetitions=80):
    documents = max(4, min(int(documents), 5000))
    repetitions = max(4, min(int(repetitions), 1000))
    base = Path(__file__).resolve().parent
    report = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'kind': 'isolated_synthetic_cpu_cache_microbenchmark',
        'documents': documents, 'corpora': 2, 'controlled_vector_dimension': 768,
        'network_calls': 0, 'llm_calls': 0, 'model_inference': False,
        'source_sha256': {name: hashlib.sha256((base / 'core' / name).read_bytes()).hexdigest()
                          for name in ('local_rag.py', 'local_embeddings.py')},
        'limitations': ['Los vectores constantes son simulados; no evalúan inferencia ni calidad semántica.',
            'SQLite FTS5/BM25, lectura de matrices, RRF y extracción sí son operaciones reales.',
            'La comparación cambia sólo el tamaño de caché de matrices de uno a dos corpus.',
            'No se vacía el caché del sistema operativo ni se controla toda la carga de CPU del equipo.',
            'Los documentos sintéticos no se incorporan al conocimiento ni al catálogo de LitMate.',
            'Estas latencias no predicen el p95 de conversaciones o búsquedas externas.']}
    controlled = ControlledVectors()
    with tempfile.TemporaryDirectory(prefix='litmate-rag-cpu-') as temporary:
        root = Path(temporary)
        indexes = []
        indexed = []
        started = time.perf_counter()
        for corpus in (0, 1):
            folder = root / f'corpus-{corpus}'
            folder.mkdir()
            count = documents // 2 + (1 if corpus == 0 and documents % 2 else 0)
            for number in range(count):
                (folder / f'Obra {corpus} {number:04d}__Autora sintetica.txt').write_text(
                    f'Ficha original sintética número {number} del corpus {corpus}. '
                    'Una exploradora recorre una isla con un mapa de arrecifes. '
                    'La narración de control permite medir recuperación de palabras e identidades, '
                    'sin aportar conocimiento sobre ninguna obra publicada.', encoding='utf-8')
            database = root / f'corpus-{corpus}.sqlite3'
            indexed.append(local_rag.index_documents(folder, database, embedder=controlled))
            indexes.append(database)
        report['indexing_ms'] = round((time.perf_counter() - started) * 1000, 3)
        report['indexed_documents_chunks'] = indexed
        expected_bytes = documents * len(controlled.vector) * 4
        report['combined_vector_data_bytes'] = expected_bytes
        fts_times = []
        for number in range(repetitions):
            started = time.perf_counter()
            local_rag.retrieve_fragments('isla mapa arrecifes', indexes[number % 2], embedder=None)
            fts_times.append((time.perf_counter() - started) * 1000)
        report['real_bm25_only'] = summary(fts_times)
        answers = {}
        for size, name in ((1, 'before_one_corpus_cache'), (2, 'after_two_corpus_cache')):
            with matrix_cache_size(size) as cache:
                # Inicializa imports/BLAS fuera de la ventana; se mide después
                # desde caché de aplicación vacía, con la misma secuencia A/B.
                for database in indexes:
                    local_rag.retrieve_fragments('isla mapa arrecifes', database, embedder=controlled)
                cache.cache_clear()
                durations, rows = [], []
                tracemalloc.start()
                for number in range(repetitions):
                    started = time.perf_counter()
                    found = local_rag.retrieve_fragments('isla mapa arrecifes', indexes[number % 2],
                                                          embedder=controlled)
                    durations.append((time.perf_counter() - started) * 1000)
                    rows.append(signatures(found))
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                info = cache.cache_info()
                answers[name] = rows
                report[name] = {**summary(durations), 'matrix_cache_hits': info.hits,
                    'matrix_cache_misses': info.misses, 'matrix_cache_entries': info.currsize,
                    'tracemalloc_peak_bytes': peak,
                    'first_cold_application_cache_ms': round(durations[0], 4),
                    'subsequent_requests': summary(durations[2:])}
        report['same_retrieved_passages_in_both_modes'] = (
            answers['before_one_corpus_cache'] == answers['after_two_corpus_cache'])
        before = report['before_one_corpus_cache']['mean_ms']
        after = report['after_two_corpus_cache']['mean_ms']
        report['measured_mean_reduction_percent'] = round((before - after) / before * 100, 3)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--documents', type=int, default=800)
    parser.add_argument('--repetitions', type=int, default=80)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args(argv)
    if options.output.exists():
        parser.error('El informe ya existe; usa otro destino.')
    result = run(options.documents, options.repetitions)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({name: result[name] for name in ('real_bm25_only', 'before_one_corpus_cache',
        'after_two_corpus_cache', 'measured_mean_reduction_percent',
        'same_retrieved_passages_in_both_modes')}, ensure_ascii=True), flush=True)
    return 0 if result['same_retrieved_passages_in_both_modes'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
