"""Selección reproducible y controles de expansión; reutiliza el importador oficial."""
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import time
from collections import Counter, defaultdict, deque


def genre(categories):
    text = ' '.join(categories).lower()
    for name, pattern in (
        ('manga', r'\bmanga\b'), ('juvenil', r'juvenile|children'),
        ('poesia', r'poetry|poems'), ('historia', r'history'),
        ('ensayo', r'essays'), ('ficcion', r'fiction|novel|stories'),
        ('artes', r'\bart\b|painting|music'), ('ciencia', r'science|nature')):
        if re.search(pattern, text):
            return name
    return 'otros'


def pending_memory_projection(ledger):
    """Un cursor CSV terminado no implica que terminó el outbox de memoria."""
    from contextlib import closing
    from .literary_acquisition import _connect
    db = _connect(ledger)
    if db is None:
        return 0
    with closing(db):
        return db.execute("SELECT COUNT(*) FROM acquisition_outbox WHERE state != 'done'").fetchone()[0]


def select_catalog(path, maximum, excluded_pairs=(), excluded_ids=()):
    """Round-robin por idioma, tema y nacimiento del autor; no infiere nacionalidad.

    El muestreo favorece cobertura, no reproduce la distribución del catálogo.
    La fecha del autor NO se presenta como fecha de publicación de la obra.
    Sólo mantiene metadatos mínimos en memoria (catálogo acotado a 150 MB).
    """
    from .literary_gutenberg import catalog_record, _bounded_lines
    from .literary_memory import normalize_identity
    from .literary_identity import work_identity
    if not 1 <= maximum <= 10000:
        raise ValueError('El lote debe tener entre 1 y 10000 registros.')
    excluded_pairs, excluded_ids = set(excluded_pairs), set(excluded_ids)
    groups, seen = defaultdict(list), set()
    counts = Counter()
    opener = gzip.open if Path(path).suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8-sig', newline='') as stream:
        csv.field_size_limit(64000)
        for row in csv.DictReader(_bounded_lines(stream, time.monotonic()+120)):
            counts['scanned'] += 1
            record = catalog_record(row)
            if not record:
                counts['invalid_or_ambiguous'] += 1
                continue
            identity = work_identity(record['book'])
            pair = (normalize_identity(identity['title']), normalize_identity(identity['author']))
            if record['external_id'] in excluded_ids or pair in excluded_pairs:
                counts['already_known'] += 1
                continue
            signature = (*pair, tuple(sorted(record['languages'])))
            if signature in seen:
                counts['same_title_author_language_skipped'] += 1
                continue
            seen.add(signature)
            birth = re.search(r',\s*(\d{3,4})\??\s*-', record['catalog_author_label'])
            period = str((int(birth[1])//100)*100) if birth else 'sin_fecha'
            item = {'id': record['external_id'], 'title': record['title'], 'author': record['author'],
                    'language': record['languages'][0], 'genre': genre(record['book']['categories']),
                    'author_birth_century': period}
            groups[(item['language'], item['genre'], period)].append(item)
    # Mezcla estable independiente del orden de IDs: no favorece los primeros ebooks.
    queues = {key: deque(sorted(values, key=lambda x: hashlib.sha256(x['id'].encode()).digest()))
              for key, values in groups.items()}
    languages = defaultdict(list)
    for key in sorted(queues):
        languages[key[0]].append(key)
    positions = Counter()
    selected = []
    while len(selected) < maximum and languages:
        for language in sorted(list(languages), key=lambda v: (v != 'es', v != 'en', v)):
            keys = languages[language]
            index = positions[language] % len(keys)
            key = keys[index]
            selected.append(queues[key].popleft())
            if not queues[key]:
                keys.pop(index)
                if not keys:
                    del languages[language]
            else:
                positions[language] += 1
            if len(selected) == maximum:
                break
    return {'selected': selected, 'counts': dict(counts), 'available_unique': len(seen),
            'distribution': {field: dict(Counter(item[field] for item in selected))
                for field in ('language', 'genre', 'author_birth_century')}}


def preserve_expansion_rows(root, manifest):
    """Filas originales inmutables; sólo crecen las tablas KB.

    Los controles de proyección son operativos: permiten avanzar el cursor,
    nunca eliminar controles ni retroceder. No relaja el verificador de migración.
    """
    from django.db import connection
    from .database_transfer import decode, fingerprint, table_rows
    result = {}
    append_only = {'core_kbrecord', 'core_kbname', 'core_kbrelation', 'core_kbversion'}
    for table, info in manifest['database']['tables'].items():
        with gzip.open(Path(root)/'database'/info['file'], 'rt', encoding='utf-8') as stream:
            original = [[decode(value) for value in json.loads(line)] for line in stream]
        actual = table_rows(connection, table)
        columns, pk = info['columns'], info['pk']
        index = columns.index(pk) if pk else None
        keys = {row[index] for row in original} if index is not None else set()
        old_actual = [row for row in actual if row[index] in keys] if index is not None else actual
        if table == 'core_kbprojection':
            old_by_id = {row[index]: row for row in old_actual}
            cursor_index = columns.index('last_rowid')
            if (len(old_actual) != len(original) or any(
                    old_by_id[row[index]][cursor_index] < row[cursor_index] for row in original)):
                raise ValueError('Se perdió o retrocedió un control de proyección.')
        else:
            current = fingerprint(table, columns, old_actual, pk)
            if any(current[key] != info[key] for key in current):
                raise ValueError('Una fila original cambió: '+table)
            if table not in append_only and len(actual) != len(original):
                raise ValueError('Cambió una tabla ajena al catálogo: '+table)
        result[table] = {'original_rows': len(original), 'preserved': True,
                         'added': len(actual)-len(original)}
    connection.check_constraints()
    return result


def retrieval_audit(records, sample_size=120):
    from .bibliographic_repository import lookup_sources
    from .ai_quick_answers import catalogue_lookup_answer
    from .literary_memory import normalize_identity, retrieve_evidence
    examples, times, memory_times = [], [], []
    ordered = sorted(records, key=lambda r: hashlib.sha256(r['id'].encode()).digest())
    for item in ordered[:sample_size]:
        tick = time.monotonic()
        sources = lookup_sources(item['title'])
        answer = catalogue_lookup_answer('¿Quién escribió '+item['title']+'?', [], lookup_sources)
        elapsed = (time.monotonic()-tick)*1000
        times.append(elapsed)
        matching = [source for source in sources if
                    normalize_identity(source.get('author', '')) == normalize_identity(item['author'])]
        correct = bool(answer and answer.status == 'answered' and matching and
                       normalize_identity(item['author']) in normalize_identity(answer.text))
        memory_tick = time.monotonic()
        books, memory_sources = retrieve_evidence(item['title'], limit=5)
        memory_times.append((time.monotonic()-memory_tick)*1000)
        memory_match = any(normalize_identity(book.get('title', '')) == normalize_identity(item['title'])
            and normalize_identity(book.get('author', '')) == normalize_identity(item['author']) for book in books)
        examples.append({'id': item['id'], 'title': item['title'], 'author': item['author'],
            'retrieved_expected_author': bool(matching), 'correct_authorship': correct,
            'memory_top5': memory_match,
            'answered': bool(answer and answer.status == 'answered'),
            'answer': answer.text if answer else None, 'milliseconds': round(elapsed, 3)})
    return {'samples': len(examples), 'retrieved': sum(x['retrieved_expected_author'] for x in examples),
        'correct': sum(x['correct_authorship'] for x in examples),
        'wrong': sum(x['answered'] and not x['correct_authorship'] for x in examples),
        'p50_ms': statistics.median(times) if times else None,
        'p95_ms': sorted(times)[math.ceil(len(times)*.95)-1] if times else None,
        'memory_top5': sum(item['memory_top5'] for item in examples),
        'memory_p95_ms': sorted(memory_times)[math.ceil(len(memory_times)*.95)-1] if memory_times else None,
        'examples': examples, 'llm_calls': 0, 'test_type': 'real_local_mysql_no_network'}


def resource_snapshot():
    from evaluar_chat_http import memory_snapshot
    from django.db import connection
    from .literary_memory import default_path
    with connection.cursor() as cursor:
        cursor.execute('SELECT TABLE_NAME,DATA_LENGTH,INDEX_LENGTH FROM information_schema.tables '
                       'WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME LIKE %s', ['core_kb%'])
        storage = [{'table': r[0], 'data': r[1], 'index': r[2]} for r in cursor.fetchall()]
    memory = default_path()
    return {'free_disk_bytes': shutil.disk_usage(Path.cwd()).free,
            'process': memory_snapshot(), 'mysql_estimates': storage,
            'memory_db_bytes': memory.stat().st_size if memory.exists() else 0}
