"""Evaluación de recuperación y ranking entrenable, fuera del chat interactivo.

No considera un score de relevancia una prueba factual. Los juicios explícitos
pueden ser 0 (irrelevante), 1 (parcial) o 2 (directo). Un documento no juzgado
no es automáticamente un negativo de entrenamiento. No realiza HTTP, descarga
modelos, cambia settings ni activa artefactos en producción.
"""
import hashlib
import json
import math
import re
import sqlite3
import time
import unicodedata
from collections import Counter
from contextlib import closing
from pathlib import Path


VERSION = 'literary-ranking-v1'
FEATURES = ('body_overlap', 'title_overlap', 'author_overlap', 'phrase_match', 'lexical_rr')
MINIMUM = {'train_pairs': 200, 'train_works': 20, 'train_queries': 80,
           'validation_pairs': 60, 'validation_works': 8, 'validation_queries': 20,
           'test_pairs': 60, 'test_works': 8, 'test_queries': 20}


def _normal(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.lower())
                   if not unicodedata.combining(c))


def _tokens(value):
    stop = {'el', 'la', 'los', 'las', 'de', 'del', 'en', 'un', 'una', 'que', 'y',
            'por', 'para', 'con', 'libro', 'libros', 'quien', 'cual', 'sobre', 'the',
            'of', 'and', 'a', 'an', 'in', 'what', 'who', 'is', 'does', 'novela'}
    return set(t for t in re.findall(r'\w+', _normal(value)) if len(t) >= 3 and t not in stop)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_dataset(dataset):
    """Rechaza referencias rotas y límites abusivos antes de crear un índice."""
    if not isinstance(dataset, dict) or dataset.get('version') != 1:
        raise ValueError('Dataset de recuperación: se requiere version=1')
    documents, queries = dataset.get('documents'), dataset.get('queries')
    if (not isinstance(documents, list) or not 1 <= len(documents) <= 10000
            or not isinstance(queries, list) or not 1 <= len(queries) <= 2000):
        raise ValueError('Dataset vacío o demasiado grande')
    by_id, source_works = {}, {}
    for document in documents:
        if (not isinstance(document, dict) or any(not isinstance(document.get(key), str)
                or not document[key].strip() for key in
                ('id', 'work_id', 'title', 'author', 'text', 'source_url', 'license'))
                or document['id'] in by_id or len(document['text']) > 20000
                or any(len(document[key]) > 1000 for key in ('id', 'work_id', 'title', 'author'))
                or not document['source_url'].startswith('https://')):
            raise ValueError('Documento sin identidad/procedencia o ID duplicado')
        original_hash = document.get('original_sha256')
        if original_hash is not None:
            if not isinstance(original_hash, str) or not re.fullmatch(r'[a-f0-9]{64}', original_hash):
                raise ValueError('SHA256 del original inválido')
            if original_hash in source_works and source_works[original_hash] != document['work_id']:
                raise ValueError('El mismo original aparece en distintas obras; normaliza IDs antes del split')
            source_works[original_hash] = document['work_id']
        if (document.get('text_sha256') is not None and document['text_sha256'] !=
                hashlib.sha256(document['text'].encode('utf-8')).hexdigest()):
            raise ValueError('El fragmento no coincide con su SHA256')
        by_id[document['id']] = document
    seen = set()
    works = {document['work_id'] for document in documents}
    for query in queries:
        if (not isinstance(query, dict) or not isinstance(query.get('id'), str)
                or not query['id'] or query['id'] in seen
                or not isinstance(query.get('text'), str) or not 1 <= len(query['text']) <= 5000
                or query.get('work_id') not in works
                or query.get('label_status') not in {'curated_test', 'agent_reviewed', 'human_reviewed'}
                or not isinstance(query.get('qrels'), dict) or not query['qrels']):
            raise ValueError('Consulta/etiquetas inválidas o ID duplicado')
        seen.add(query['id'])
        for identifier, grade in query['qrels'].items():
            if identifier not in by_id or type(grade) is not int or not 0 <= grade <= 2:
                raise ValueError('Juicio apunta a documento inexistente o relevancia inválida')
            if grade > 0 and by_id[identifier]['work_id'] != query['work_id']:
                raise ValueError('El positivo pertenece a otra obra; divide consultas comparativas')
        if not any(grade > 0 for grade in query['qrels'].values()):
            raise ValueError('Cada consulta requiere al menos un positivo juzgado')
    return dataset


def load_dataset(path):
    path = Path(path)
    if path.stat().st_size > 25_000_000:
        raise ValueError('Dataset supera 25 MB')
    return validate_dataset(json.loads(path.read_text(encoding='utf-8')))


def split_by_work(dataset, *, seed='litmate-ranking-v1'):
    """Agrupa todas las variantes de una obra. Nunca parte consultas al azar.

    El orden depende exclusivamente del identificador y semilla, no de etiquetas
    ni resultados. 60/20/20; con tres o más obras reserva ambos holdouts.
    """
    validate_dataset(dataset)
    works = sorted({query['work_id'] for query in dataset['queries']},
                   key=lambda value: hashlib.sha256((seed + '\0' + value).encode()).hexdigest())
    count = len(works)
    n_test = max(1, count // 5) if count >= 3 else 0
    n_validation = max(1, count // 5) if count >= 3 else 0
    partitions = {'train': set(works[:count - n_test - n_validation]),
                  'validation': set(works[count - n_test - n_validation:count - n_test]),
                  'test': set(works[count - n_test:]) if n_test else set()}
    return {name: [query for query in dataset['queries'] if query['work_id'] in identities]
            for name, identities in partitions.items()}


def ranking_metrics(ranking, qrels, *, k=5):
    """Macro métricas convencionales; duplicados nunca multiplican aciertos.

    Precision@k divide por k incluso si se recuperaron menos resultados.
    Positivo significa relevancia >=1; nDCG usa ganancias graduadas 2**r-1.
    Los no juzgados reciben cero sólo al evaluar, nunca al entrenar.
    """
    if type(k) is not int or not 1 <= k <= 100:
        raise ValueError('k debe estar entre 1 y 100')
    unique = list(dict.fromkeys(ranking))
    relevant = {identifier for identifier, grade in qrels.items() if grade > 0}
    hits = sum(identifier in relevant for identifier in unique[:k])
    recall = lambda at: (sum(identifier in relevant for identifier in unique[:at])
                         / len(relevant)) if relevant else 0.
    dcg = sum((2 ** qrels.get(identifier, 0) - 1) / math.log2(rank + 2)
              for rank, identifier in enumerate(unique[:10]))
    ideal = sum((2 ** grade - 1) / math.log2(rank + 2)
                for rank, grade in enumerate(sorted(qrels.values(), reverse=True)[:10]))
    reciprocal = next((1 / rank for rank, identifier in enumerate(unique, 1)
                       if identifier in relevant), 0.)
    return {'recall@5': recall(5), 'recall@10': recall(10), f'precision@{k}': hits / k,
            'mrr': reciprocal, 'ndcg@10': dcg / ideal if ideal else 0.,
            'judged_fraction@10': sum(i in qrels for i in unique[:10]) / min(10, len(unique))
                if unique else 0.}


def reciprocal_rank_fusion(rankings, *, constant=60):
    if not isinstance(constant, (int, float)) or not math.isfinite(constant) or constant <= 0:
        raise ValueError('Constante RRF inválida')
    scores = Counter()
    for ranking in rankings:
        for position, identifier in enumerate(dict.fromkeys(ranking), 1):
            scores[identifier] += 1 / (constant + position)
    return sorted(scores, key=lambda identifier: (-scores[identifier], str(identifier)))


def _percentile(values, percentile):
    values = sorted(values)
    return values[max(0, math.ceil(percentile * len(values)) - 1)] if values else 0.


def evaluate(dataset, retrieve, *, queries=None, k=5, label='retrieval'):
    """retrieve(query) retorna IDs en orden. Medición real de esa función, no E2E."""
    validate_dataset(dataset)
    documents = {document['id']: document for document in dataset['documents']}
    rows = []
    for query in dataset['queries'] if queries is None else queries:
        started = time.perf_counter()
        ranking = list(dict.fromkeys(retrieve(query)))[:100]
        latency = time.perf_counter() - started
        unjudged = getattr(retrieve, 'unjudged_documents', {})
        if any(identifier not in documents and identifier not in unjudged for identifier in ranking):
            raise ValueError('La recuperación devolvió IDs ajenos al corpus evaluado')
        top = documents.get(ranking[0], unjudged.get(ranking[0], {})) if ranking else {}
        rows.append({'id': query['id'], 'work_id': query['work_id'], 'ranking': ranking,
            'latency_seconds': latency, 'work_identification_correct': top.get('work_id') == query['work_id'],
            **ranking_metrics(ranking, query['qrels'], k=k)})
    metrics = {key: sum(row[key] for row in rows) / len(rows) if rows else 0.
               for key in ('recall@5', 'recall@10', f'precision@{k}', 'mrr', 'ndcg@10',
                           'judged_fraction@10', 'work_identification_correct')}
    latencies = [row['latency_seconds'] for row in rows]
    return {'version': VERSION, 'dataset_sha256': fingerprint(dataset), 'method': label,
        'queries': len(rows), 'metrics': metrics,
        'latency_seconds': {'mean': sum(latencies) / len(rows) if rows else 0.,
                            'p50': _percentile(latencies, .5), 'p95': _percentile(latencies, .95)},
        'scope': 'retrieval_only_not_chat_or_factual_accuracy', 'results': rows}


class FixtureBM25:
    """FTS5 real sobre anotaciones de evaluación, SQLite únicamente en memoria.

    Reproduce pesos BM25 y prefijos del índice local, sin consultar qrels.
    No incorpora los fixtures al conocimiento o a las respuestas del chat.
    """
    def __init__(self, dataset):
        validate_dataset(dataset)
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE VIRTUAL TABLE evidence USING fts5('
            'title,author,body,identifier UNINDEXED,tokenize="unicode61 remove_diacritics 2")')
        self.db.executemany('INSERT INTO evidence VALUES(?,?,?,?)',
            [(d['title'], d['author'], d['text'], d['id']) for d in dataset['documents']])

    def __call__(self, query):
        from .local_rag import STOPWORDS
        # Keep production query term order: truncation must not depend on a set.
        terms = list(dict.fromkeys(t for t in re.findall(r'\w+', _normal(query['text']))
                                  if len(t) >= 3 and t not in STOPWORDS))[:18]
        if not terms:
            return []
        match = ' OR '.join('"' + term + '"*' for term in terms)
        return [row[0] for row in self.db.execute('SELECT identifier FROM evidence '
            'WHERE evidence MATCH ? ORDER BY bm25(evidence,.3,.2,1.),rowid LIMIT 32', (match,))]

    def close(self):
        self.db.close()


def features(query, document, *, lexical_position=0):
    wanted = _tokens(query['text'])
    overlap = lambda value: len(wanted & _tokens(value)) / max(1, len(wanted))
    return [overlap(document['text']), overlap(document['title']), overlap(document['author']),
        float(_normal(document['title']) in _normal(query['text'])),
        1 / lexical_position if lexical_position > 0 else 0.]


def training_readiness(dataset, partitions=None):
    """Exige etiquetas humanas explícitas y cobertura, no presume revisión."""
    validate_dataset(dataset)
    partitions = partitions or split_by_work(dataset)
    documents = {document['id']: document for document in dataset['documents']}
    counts, reasons = {}, []
    used_works = set()
    for name in ('train', 'validation', 'test'):
        queries = partitions.get(name, [])
        works = {query['work_id'] for query in queries}
        if used_works & works:
            reasons.append('work_leakage')
        used_works |= works
        # A negative from a held-out work may not become a training example.
        labels = [(query, identifier, grade) for query in queries
                  if query.get('label_status') == 'human_reviewed'
                  and query.get('label_evidence_verified') is True
                  for identifier, grade in query['qrels'].items()
                  if documents[identifier]['work_id'] in works]
        # Duplicating IDs or the same paraphrase does not increase sample size.
        unique = {}
        for query, identifier, grade in labels:
            key = (query['work_id'], _normal(query['text']).strip(), identifier)
            if key in unique and unique[key][2] != grade:
                reasons.append(name + '_conflicting_duplicate_labels')
            unique[key] = (query, identifier, grade)
        labels = list(unique.values())
        counts[name + '_pairs'] = len(labels)
        counts[name + '_works'] = len({q['work_id'] for q, _, _ in labels})
        counts[name + '_queries'] = len({(q['work_id'], _normal(q['text']).strip())
                                        for q, _, _ in labels})
        if not {0, 1}.issubset({int(grade > 0) for _, _, grade in labels}):
            reasons.append(name + '_needs_positive_and_negative_labels')
    reasons.extend('insufficient_' + key for key, minimum in MINIMUM.items() if counts[key] < minimum)
    return {'ready': not reasons, 'counts': counts, 'minimum': MINIMUM.copy(),
            'reasons': list(dict.fromkeys(reasons)), 'model_activated': False}


def _sigmoid(score):
    return 1 / (1 + math.exp(-max(-30., min(30., score))))


def train_candidate(dataset, *, epochs=160, rate=.08, max_seconds=30., max_pairs=50000):
    """Regresión logística L2 pequeña; sólo tras suficientes etiquetas de calidad.

    El holdout test se consulta una vez, después de congelar hiperparámetros.
    Retorna artefacto inactivo y veredicto; no hay integración automática al chat.
    """
    if type(epochs) is not int or not 1 <= epochs <= 1000 or not 0 < rate <= .5:
        raise ValueError('Configuración de entrenamiento fuera de límites')
    if (not isinstance(max_seconds, (int, float)) or not math.isfinite(max_seconds)
            or not 0 < max_seconds <= 300 or type(max_pairs) is not int
            or not 200 <= max_pairs <= 50000):
        raise ValueError('Presupuesto de entrenamiento fuera de límites')
    started = time.monotonic()
    partitions = split_by_work(dataset)
    readiness = training_readiness(dataset, partitions)
    if not readiness['ready']:
        return {'trained': False, 'readiness': readiness, 'reason': 'insufficient_trusted_labels'}
    documents = {document['id']: document for document in dataset['documents']}
    with closing(FixtureBM25(dataset)) as baseline:
        rows = []
        works = {query['work_id'] for query in partitions['train']}
        seen = set()
        for query in partitions['train']:
            if query.get('label_status') != 'human_reviewed' or query.get('label_evidence_verified') is not True:
                continue
            positions = {identifier: rank for rank, identifier in enumerate(baseline(query), 1)}
            for identifier, grade in query['qrels'].items():
                key = query['work_id'], _normal(query['text']).strip(), identifier
                if documents[identifier]['work_id'] in works and key not in seen:
                    seen.add(key)
                    if len(rows) >= max_pairs:
                        return {'trained': False, 'reason': 'training_pair_budget_exhausted',
                                'readiness': readiness, 'model_activated': False}
                    rows.append((features(query, documents[identifier],
                                          lexical_position=positions.get(identifier, 0)), int(grade > 0)))
        weights, bias = [0.] * len(FEATURES), 0.
        for _ in range(epochs):
            if time.monotonic() - started > max_seconds:
                return {'trained': False, 'reason': 'training_time_budget_exhausted',
                        'readiness': readiness, 'model_activated': False}
            gradient, intercept = [0.] * len(weights), 0.
            for vector, target in rows:
                error = _sigmoid(bias + sum(w * v for w, v in zip(weights, vector))) - target
                for i, value in enumerate(vector):
                    gradient[i] += error * value
                intercept += error
            for i in range(len(weights)):
                weights[i] -= rate * (gradient[i] / len(rows) + .01 * weights[i])
            bias -= rate * intercept / len(rows)
        def rerank(query):
            candidates = baseline(query)
            positions = {identifier: rank for rank, identifier in enumerate(candidates, 1)}
            def score(identifier):
                vector = features(query, documents[identifier], lexical_position=positions[identifier])
                return _sigmoid(bias + sum(w * v for w, v in zip(weights, vector)))
            return sorted(candidates, key=lambda identifier: (-score(identifier), positions[identifier]))
        evaluation = {}
        for name in ('validation', 'test'):
            trusted = [query for query in partitions[name]
                       if query.get('label_status') == 'human_reviewed'
                       and query.get('label_evidence_verified') is True]
            evaluation[name] = {'baseline': evaluate(dataset, baseline, queries=trusted),
                                'candidate': evaluate(dataset, rerank, queries=trusted, label='logistic_l2')}
    reasons = []
    for name, pair in evaluation.items():
        before, after = pair['baseline']['metrics'], pair['candidate']['metrics']
        if after['ndcg@10'] < before['ndcg@10'] + .01:
            reasons.append(name + '_ndcg_gain_below_0.01')
        for key in ('recall@5', 'recall@10', 'mrr', 'work_identification_correct'):
            if after[key] + 1e-9 < before[key]:
                reasons.append(name + '_regression_' + key)
        if pair['candidate']['latency_seconds']['p95'] > max(.02, pair['baseline']['latency_seconds']['p95'] * 1.5):
            reasons.append(name + '_latency_regression')
    return {'trained': True, 'version': VERSION, 'dataset_sha256': fingerprint(dataset),
        'scope': 'offline_declared_dataset_bm25_not_production_index',
        'features': list(FEATURES), 'weights': weights, 'bias': bias,
        'epochs': epochs, 'learning_rate': rate, 'readiness': readiness,
        'training_and_evaluation_seconds': time.monotonic() - started,
        'evaluation': evaluation, 'retrieval_candidate_eligible': not reasons,
        'activation_eligible': False,
        'rejection_reasons': reasons, 'model_activated': False,
        'activation_pending': 'independent_factual_and_resource_evaluation',
        'limitation': 'Retrieval judgments do not establish factual answer quality; independent review required.'}


def index_retriever(dataset, index, *, embedder=None):
    """Adapta el índice local existente; coincidencia por identidad y fragmento.

    Los documentos de qrels deben nombrar fragmentos reales presentes en el
    índice. No se rellena con documentos correctos sólo por coincidir la obra.
    local_rag tiene un límite de ocho: se informa al evaluar Recall@10.
    """
    from .local_rag import retrieve_fragments
    validate_dataset(dataset)
    index = Path(index).resolve()
    if not index.is_file():
        raise ValueError('No existe el índice local a evaluar')
    documents = dataset['documents']
    diagnostics = {'semantic_requested': embedder is not None,
                   'embedding_calls': 0, 'embedding_failures': 0}
    unjudged_documents = {}
    class ObservedEmbeddings:
        def identity(self):
            return embedder.identity()

        def embed(self, *args, **kwargs):
            diagnostics['embedding_calls'] += 1
            try:
                return embedder.embed(*args, **kwargs)
            except Exception:
                diagnostics['embedding_failures'] += 1
                raise
    observed = ObservedEmbeddings() if embedder is not None else None
    def retrieve(query):
        matched = []
        for fragment in retrieve_fragments(query['text'], index, maximum=8, embedder=observed):
            found = []
            original_hash = fragment.get('original_sha256')
            if not original_hash and any(document.get('original_sha256') for document in documents):
                # local_rag deliberately exposes only a reduced source schema.
                # Rehydrate the edition hash from this read-only index instead
                # of silently accepting another edition with the same title.
                try:
                    with closing(sqlite3.connect(index.as_uri() + '?mode=ro', uri=True)) as db:
                        row = db.execute('SELECT m.record FROM chunks c JOIN document_metadata m '
                            'ON m.document_id=c.document_id WHERE c.chunk_id=?',
                            (fragment.get('book_id'),)).fetchone()
                    metadata = json.loads(row[0]) if row else {}
                    original_hash = metadata.get('original_sha256')
                except (sqlite3.Error, ValueError, TypeError):
                    original_hash = None
            for document in documents:
                same_identity = (
                    document['original_sha256'] == original_hash if document.get('original_sha256') else
                    (_normal(fragment.get('work_title') or fragment.get('title', '')) == _normal(document['title'])
                     and _normal(fragment.get('work_author') or fragment.get('author', '')) == _normal(document['author'])))
                if (same_identity
                        and ((document.get('chunk_id') and document['chunk_id'] == fragment.get('book_id'))
                             or re.sub(r'\s+', ' ', _normal(document['text'])).strip()
                             in re.sub(r'\s+', ' ', _normal(fragment.get('description', ''))).strip())):
                    found.append(document['id'])
            if found:
                matched.extend(found)
            else:
                # Preserve an unjudged chunk's rank. Dropping it would inflate
                # MRR/nDCG when the only labelled passage was the eighth hit.
                identifier = 'unjudged:' + fingerprint({
                    'chunk_id': fragment.get('book_id'), 'body': fragment.get('description', '')})
                work_id = next((d['work_id'] for d in documents
                                if original_hash and d.get('original_sha256') == original_hash), '')
                unjudged_documents[identifier] = {'id': identifier, 'work_id': work_id}
                matched.append(identifier)
        return list(dict.fromkeys(matched))
    retrieve.diagnostics = diagnostics
    retrieve.unjudged_documents = unjudged_documents
    return retrieve
