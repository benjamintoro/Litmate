"""Compara FTS5/BM25 con recuperación híbrida del índice auxiliar autorizado.

Solo abre SQLite en modo de lectura. No carga .env, Django, novelas ni usuarios,
no usa un modelo conversacional y no reconstruye el índice. La modalidad híbrida
consulta únicamente el modelo local de embeddings ya descargado.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time


BASE = Path(__file__).resolve().parent
QUERIES = [
    {'id': 'papelucho_paraphrase', 'query': 'Un escolar comparte su vida con un visitante de otro mundo',
     'expected_title': 'Diario secreto de Papelucho y el marciano', 'type': 'paraphrase'},
    {'id': 'papelucho_typo', 'query': 'un nino se hace amigo de un extratrerestre llamado Det',
     'expected_title': 'Diario secreto de Papelucho y el marciano', 'type': 'typo'},
    {'id': 'principito_paraphrase', 'query': 'Un pequeño viajero se preocupa por una flor en su diminuto hogar entre estrellas',
     'expected_title': 'El principito', 'type': 'paraphrase'},
    {'id': 'principito_typo', 'query': 'un niñoo vive en un planetta chico y protege una roza',
     'expected_title': 'El principito', 'type': 'typo'},
    {'id': 'farm_paraphrase', 'query': 'Una revolución de seres de corral termina con gobernantes que concentran el poder',
     'expected_title': 'Rebelión en la granja', 'type': 'paraphrase'},
    {'id': 'farm_typo', 'query': 'animalez de una granjja quieren igualdad y los cerdoss mandan',
     'expected_title': 'Rebelión en la granja', 'type': 'typo'},
    {'id': 'crime_paraphrase', 'query': 'Un universitario intenta justificar una muerte y termina atormentado por remordimientos',
     'expected_title': 'Crimen y castigo', 'type': 'paraphrase'},
    {'id': 'crime_typo', 'query': 'Raskolnikof comete un asesinato y siente culpaa',
     'expected_title': 'Crimen y castigo', 'type': 'typo'},
    {'id': 'unrelated_control', 'query': 'Busco manuales de electricidad doméstica y reparación de motores',
     'expected_title': None, 'type': 'negative_control'},
]


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inspect_index(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('No existe el índice auxiliar; prepara las fichas autorizadas primero.')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
        metadata = dict(db.execute('SELECT key, value FROM rag_metadata'))
        documents = [{'title': title, 'author': author}
                     for title, author in db.execute('SELECT title, author FROM documents ORDER BY title')]
        attributes = [json.loads(row[0]) for row in db.execute('SELECT record FROM document_metadata')]
        chunks = db.execute('SELECT count(*) FROM chunks').fetchone()[0]
        vectors = db.execute('SELECT count(*) FROM rag_vectors').fetchone()[0]
    if (not documents or len(attributes) != len(documents)
            or any(record.get('indexing_authorized') is not True
                   or not record.get('license') or not record.get('url')
                   or record.get('kind') not in {'book', 'web'} for record in attributes)):
        raise ValueError('El benchmark admite solo fichas factuales con autorización y licencia explícitas.')
    return {'path': str(path), 'documents': documents, 'document_count': len(documents),
            'chunks': chunks, 'vectors': vectors, 'metadata': metadata,
            'authorized_factual_cards_only': True}


class ObservedEmbedder:
    """Hace visibles las degradaciones a FTS que el recuperador maneja internamente."""
    def __init__(self, inner):
        self.inner = inner
        self.attempts = 0
        self.successes = 0
        self.errors = []

    def identity(self):
        return self.inner.identity()

    def embed(self, texts, *, query=False):
        self.attempts += 1
        try:
            result = self.inner.embed(texts, query=query)
            self.successes += 1
            return result
        except Exception as exc:
            self.errors.append(type(exc).__name__)
            raise


def rank_result(sources, expected_title):
    from core.literary_identity import normalize_identity
    titles, seen = [], set()
    for source in sources:
        title = source.get('work_title') or source.get('title', '')
        identity = normalize_identity(title)
        if identity not in seen:
            titles.append(title)
            seen.add(identity)
    wanted = normalize_identity(expected_title) if expected_title else None
    rank = next((index for index, title in enumerate(titles, 1)
                 if normalize_identity(title) == wanted), None) if wanted else None
    return {'ranked_titles': titles, 'expected_rank': rank,
            'hit_at_1': rank == 1 if wanted else None,
            'hit_at_3': rank is not None and rank <= 3 if wanted else None,
            'reciprocal_rank': 1 / rank if rank else 0 if wanted else None,
            'negative_control_returned_candidates': bool(titles) if not wanted else None}


def retrieval_metrics(rows, mode):
    positives = [row[mode] for row in rows if row.get('expected_title')
                 and row.get('expected_work_present') and row[mode]['status'] == 'ok']
    negatives = [row[mode] for row in rows if not row.get('expected_title')
                 and row[mode]['status'] == 'ok']
    return {'measured_positive_queries': len(positives),
            'hits_at_1': sum(result['hit_at_1'] for result in positives),
            'hits_at_3': sum(result['hit_at_3'] for result in positives),
            'hit_rate_at_1': sum(result['hit_at_1'] for result in positives) / len(positives) if positives else None,
            'mean_reciprocal_rank': sum(result['reciprocal_rank'] for result in positives) / len(positives) if positives else None,
            'mean_ms': sum(result['milliseconds'] for result in positives) / len(positives) if positives else None,
            'negative_queries': len(negatives),
            'negative_queries_with_candidates': sum(result['negative_control_returned_candidates'] for result in negatives),
            'not_measured_or_degraded_queries': sum(row[mode]['status'] != 'ok' for row in rows)}


def run_benchmark(database, *, embedder=None, queries=None):
    from core.local_rag import retrieve_fragments
    from core.literary_identity import normalize_identity
    path = Path(database).resolve()
    before = file_digest(path)
    index = inspect_index(path)
    known = {normalize_identity(document['title']) for document in index['documents']}
    observed = ObservedEmbedder(embedder) if embedder is not None else None
    hybrid_error = None
    if observed:
        try:
            if observed.identity() != (index['metadata'].get('model'), index['metadata'].get('digest')):
                hybrid_error = 'embedding_model_does_not_match_existing_index'
        except Exception as exc:
            hybrid_error = type(exc).__name__
    rows = []
    for case in queries or QUERIES:
        query = case['query']
        started = time.perf_counter()
        fts = retrieve_fragments(query, path, maximum=4, embedder=None)
        fts_result = {**rank_result(fts, case['expected_title']), 'status': 'ok',
                      'milliseconds': round((time.perf_counter() - started) * 1000, 3)}
        if observed is None or hybrid_error:
            hybrid = {'status': hybrid_error or 'not_run_fts_only', 'milliseconds': None}
        else:
            attempts, successes = observed.attempts, observed.successes
            started = time.perf_counter()
            result = retrieve_fragments(query, path, maximum=4, embedder=observed)
            hybrid = {**rank_result(result, case['expected_title']),
                      'status': 'ok' if observed.attempts > attempts and observed.successes > successes else 'degraded_to_fts',
                      'milliseconds': round((time.perf_counter() - started) * 1000, 3)}
        rows.append({**case, 'expected_work_present': (normalize_identity(case['expected_title']) in known
                                                     if case['expected_title'] else None),
                     'fts': fts_result, 'hybrid': hybrid})
    after = file_digest(path)
    return {'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'test_kind': 'retrieval benchmark; known labels on a small licensed factual corpus; no conversational inference',
            'index': index, 'index_sha256_before': before, 'index_sha256_after': after,
            'index_unchanged': before == after,
            'methods': {'fts': 'SQLite FTS5 BM25', 'hybrid': 'reciprocal rank fusion of FTS5 BM25 and existing local embeddings'},
            'embedding_attempts': observed.attempts if observed else 0,
            'embedding_successes': observed.successes if observed else 0,
            'embedding_errors': observed.errors if observed else [],
            'queries': rows, 'metrics': {mode: retrieval_metrics(rows, mode) for mode in ('fts', 'hybrid')},
            'limitations': ['Solo evalúa las fichas autorizadas presentes, no una biblioteca general.',
                           'Recuperar el título correcto no prueba que una respuesta generada sea factual.',
                           'El tiempo del primer embedding puede incluir carga del modelo; no es una comparación de latencia independiente.',
                           'Un candidato en el control negativo requiere verificar pertinencia; no demuestra identificación correcta.',
                           'Estos casos seleccionados no acreditan una tasa general de errores inferior al 1%.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=BASE / 'data' / 'litmate_knowledge_rag.sqlite3')
    parser.add_argument('--model', default='embeddinggemma:latest')
    parser.add_argument('--fts-only', action='store_true', help='No contacta Ollama; mide únicamente BM25.')
    parser.add_argument('--output', type=Path, default=BASE / 'reportes' /
                        ('rag-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json'))
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        parser.error('El informe ya existe; usa otro nombre para conservarlo.')
    from core.local_embeddings import OllamaEmbeddings
    embedder = None if args.fts_only else OllamaEmbeddings(model=args.model)
    report = run_benchmark(args.database, embedder=embedder)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(output), 'index_unchanged': report['index_unchanged'],
                      'metrics': report['metrics']}, ensure_ascii=True, indent=2))
    return int(not report['index_unchanged'] or (not args.fts_only and not report['embedding_successes']))


if __name__ == '__main__':
    raise SystemExit(main())
