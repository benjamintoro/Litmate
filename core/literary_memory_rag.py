"""Índice auxiliar de memoria: BM25 y embeddings opcionales, nunca nueva evidencia.

Sólo indexa snapshots públicos ya admitidos por ``literary_memory``. Recuperar
un fragmento da un candidato: su fuente actual debe conservar hash, vigencia y
ausencia de contradicciones antes de devolverla al asistente.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from .ai_budget import request_budget
from .literary_identity import same_work, work_identity
from .local_rag import index_documents, retrieve_fragments


OWNER = 'litmate-literary-memory-rag-v1'
POLICIES = frozenset({'curated-original-v1', 'openlibrary-minimal-metadata-v1',
                     'wikidata-statements-v1', 'wikipedia-cc-by-sa-4.0-v1',
                     'bne-catalog-cc0-v1', 'gutenberg-catalog-public-domain-v1'})


def index_path(index=None, *, database=None):
    """Separa el índice derivado de toda base o colección ya existente."""
    from django.conf import settings
    from .literary_memory import default_path
    path = Path(index) if index is not None else Path(getattr(settings,
        'LITMATE_LITERARY_MEMORY_RAG_DB', Path(settings.BASE_DIR) / 'data' / 'literary_memory_rag.sqlite3'))
    if path.is_symlink() or path.suffix.lower() not in {'.sqlite3', '.sqlite', '.db'}:
        raise ValueError('Usa un archivo SQLite auxiliar propio para el índice de memoria')
    path = path.resolve()
    forbidden = [database or default_path(), default_path()]
    forbidden.extend(getattr(settings, key, '') for key in
                     ('LITMATE_RAG_DB', 'LITMATE_KNOWLEDGE_DB', 'LITMATE_KNOWLEDGE_RAG_DB'))
    forbidden.extend(item.get('NAME', '') for item in getattr(settings, 'DATABASES', {}).values()
                     if item.get('ENGINE', '').endswith('sqlite3'))
    if any(str(value) not in {'', ':memory:'} and path == Path(value).resolve() for value in forbidden):
        raise ValueError('El índice de memoria no puede sustituir bases ni colecciones existentes')
    return path


def _owned_index(path):
    if not path.exists():
        return
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.5)) as db:
            marker = db.execute('SELECT value FROM rag_metadata WHERE key=?', ('managed_by',)).fetchone()
        if not marker or marker[0] != OWNER:
            raise ValueError('El índice indicado no pertenece a la memoria literaria')
    except sqlite3.Error:
        raise ValueError('El índice indicado no pertenece a la memoria literaria') from None


def _snapshot_metadata(source):
    identity = work_identity(source)
    if (not identity or source.get('memory_verified') is not True
            or source.get('policy') not in POLICIES or source.get('kind') not in {'book', 'web'}
            or not source.get('license') or not isinstance(source.get('description'), str)
            or not source['description'].strip()
            or not re.fullmatch(r'[a-f0-9]{64}', str(source.get('memory_source_id', '')))
            or not re.fullmatch(r'[a-f0-9]{64}', str(source.get('content_hash', '')))):
        raise ValueError('El snapshot necesita fuentes admitidas con identidad, derechos y hash')
    return {**source, 'indexing_authorized': True, 'work_title': identity['title'],
            'work_author': identity['author'], 'work_binding_verified': True}


def build_memory_index(*, database=None, index=None, embedder=None, maximum=5000,
                       max_seconds=300, progress=None, work_ids=()):
    """Construye un índice derivado y reutiliza vectores de la versión anterior.

    El destino final sólo se sustituye cuando el snapshot completo y su marcador
    de propietario están listos. Un error conserva el índice anterior. Los
    embeddings de ese último índice se reutilizan por contenido/modelo/digest;
    un staging interrumpido no es un checkpoint de nuevos vectores ya calculados.
    """
    import time
    from .literary_memory import export_index_sources, revision, READ_POLICY
    maximum = max(1, min(int(maximum), 5000))
    max_seconds = max(1., min(float(max_seconds), 300.))
    destination = index_path(index, database=database)
    if work_ids and destination.exists():
        raise ValueError('Un índice parcial necesita un destino nuevo; no reemplaza otro índice.')
    _owned_index(destination)
    sources = export_index_sources(database=database, limit=maximum, work_ids=work_ids)
    report = {'sources': len(sources), 'documents': 0, 'chunks': 0,
              'semantic': embedder is not None, 'index_updated': False, 'index': str(destination)}
    if not sources:
        report['reason'] = 'no_fresh_sources'
        return report
    # Individual facts may legitimately be shorter than the chunker's minimum.
    # Keep them in the structured store instead of inventing padding or failing
    # the complete derived index because one short character role has no chunk.
    eligible = [source for source in sources if len(re.sub(r'\s+', ' ',
                                                          source['description']).strip()) >= 30]
    report['short_sources_skipped'] = len(sources) - len(eligible)
    sources = eligible
    if not sources:
        report['reason'] = 'no_indexable_sources'
        return report
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_snapshot = tempfile.mkstemp(prefix='litmate-memory-index-', suffix='.sqlite3',
                                      dir=destination.parent)
    os.close(fd)
    snapshot = Path(raw_snapshot)
    try:
        # Copiar el índice gestionado permite a index_documents reutilizar los
        # vectores anteriores, manteniendo el destino final intacto hasta el final.
        if destination.is_file():
            shutil.copyfile(destination, snapshot)
        with tempfile.TemporaryDirectory(prefix='litmate-memory-sources-') as temporary:
            folder, metadata = Path(temporary), {}
            for source in sources:
                attributes = _snapshot_metadata(source)
                filename = source['memory_source_id'] + '__Memoria.txt'
                (folder / filename).write_text(source['description'], encoding='utf-8')
                metadata[filename] = attributes
            with request_budget(time.monotonic() + max_seconds):
                documents, chunks = index_documents(folder, snapshot, embedder=embedder,
                    metadata=metadata, progress=progress)
            with closing(sqlite3.connect(snapshot)) as db, db:
                db.executemany('INSERT OR REPLACE INTO rag_metadata VALUES (?,?)',
                    [('managed_by', OWNER), ('memory_revision', revision(database=database)),
                     ('verification_policy', READ_POLICY)])
            _owned_index(snapshot)
            os.replace(snapshot, destination)
            report.update(documents=documents, chunks=chunks, index_updated=True)
            return report
    finally:
        snapshot.unlink(missing_ok=True)


def search_memory_semantic(query, *, books=(), database=None, index=None, embedder=None, limit=6):
    """Recupera candidatos y rehidrata su fuente vigente desde el almacén.

    Con embedder=None usa exclusivamente BM25, sin HTTP ni carga de modelos.
    El híbrido necesita un embedder local pasado explícitamente por el llamador.
    Las métricas de ranking nunca se convierten en confianza factual.
    """
    from .literary_memory import get_current_source, get_work, retrieve_evidence
    if not isinstance(query, str) or not query.strip() or len(query) > 5000:
        return [], []
    limit = max(1, min(int(limit), 8))
    if not isinstance(books, (list, tuple)):
        return [], []
    requested_books = list(books[:12])
    scope = [work_identity(book) for book in books[:12] if isinstance(book, dict) and work_identity(book)]
    if books and not scope:
        return [], []
    try:
        destination = index_path(index, database=database)
        if not destination.is_file():
            return [], []
        _owned_index(destination)
        if scope:
            # Resolve confirmed title aliases to the canonical identity used by
            # index_documents before ranking, not after a global top-eight.
            known, _ = retrieve_evidence('', books=list(books), database=database, limit=20)
            identities = [*scope, *(work_identity(book) for book in known)]
        else:
            identities = None
        fragments = retrieve_fragments(query, destination, maximum=8, embedder=embedder,
                                       book_identities=identities)
    except (OSError, ValueError, sqlite3.Error):
        return [], []
    sources, books, seen_sources, seen_works = [], [], set(), set()
    for fragment in fragments:
        identifier, digest = fragment.get('memory_source_id'), fragment.get('content_hash')
        if not identifier or not digest or identifier in seen_sources:
            continue
        seen_sources.add(identifier)
        source = get_current_source(identifier, expected_hash=digest, database=database)
        if not source:
            continue
        book = get_work(source['work_id'], database=database)
        if (not book or not same_work(source, book)
                or (scope and not any(same_work(source, requested) for requested in requested_books))):
            continue
        sources.append(source)
        if book['work_id'] not in seen_works:
            books.append(book)
            seen_works.add(book['work_id'])
        if len(sources) >= limit:
            break
    return books, sources
