"""Puente de sólo lectura entre biblioteca autorizada y motores existentes.

No publica un fragmento como si fuera una respuesta. Los originales locales
entran a la misma síntesis y auditoría factual, sin búsquedas externas previas.
"""
from pathlib import Path
import re
import sqlite3

from django.conf import settings

from .ai_progress import measure_stage
from .literary_ai import canonical_sources, normalized
from .literary_identity import same_work, title_matches


def library_paths():
    root = Path(settings.BASE_DIR) / 'data' / 'biblioteca'
    return (Path(getattr(settings, 'LITMATE_LIBRARY_DB', root / 'biblioteca.sqlite3')),
            Path(getattr(settings, 'LITMATE_LIBRARY_RAG_DB', root / 'rag.sqlite3')))


def library_revision():
    result = []
    for path in library_paths():
        try:
            info = path.stat()
            result.append((str(path), info.st_mtime_ns, info.st_size))
        except OSError:
            result.append((str(path), 'absent'))
    return result


def library_catalogue(query):
    """Identidades explícitas; no asciende similitudes a coincidencias seguras."""
    from .literary_library import list_library_books
    database, _ = library_paths()
    try:
        return list_library_books(query, database)
    except (OSError, ValueError, sqlite3.Error):
        return []


def library_books_for_query(query, candidates=()):
    """Resuelve la obra local explícita aunque el catálogo use un subtítulo.

    Los resultados de búsqueda pueden escribir «Frankenstein; or, The Modern
    Prometheus» o variar el nombre del autor. El título local se busca en la
    consulta y, si no aparece, se prueban los títulos candidatos exactos. Nunca
    se devuelve un libro local sólo por una semejanza semántica.
    """
    books = library_catalogue(query)
    if not books:
        for candidate in list(candidates)[:3]:
            title = candidate.get('title', '') if isinstance(candidate, dict) else ''
            if title:
                books.extend(library_catalogue(title))
    unique = {}
    for book in books:
        unique.setdefault(book['library_document_id'], book)
    return list(unique.values())


def library_fragments(query, books=(), *, semantic=False, maximum=4):
    from .literary_library import retrieve_library
    database, index = library_paths()
    if not database.is_file():
        return []
    try:
        embedder = None
        if semantic and index.is_file():
            from .local_embeddings import configured_embedder
            embedder = configured_embedder(settings)
        with measure_stage('local_library_retrieval'):
            return retrieve_library(query, database, maximum, books=books or None,
                index=index if semantic and index.is_file() else None, embedder=embedder)
    except (OSError, ValueError, sqlite3.Error, TimeoutError):
        return []


def sources_for_request(message, request):
    """Sólo el libro activo, misma autoría y edición de cada pasaje recuperado."""
    if not request or request.get('ambiguous') or not request.get('title'):
        return []
    books = library_catalogue(request['title'])
    targets = request.get('targets', [])
    books = [book for book in books if title_matches(request['title'], book)
             and (not targets or any(same_work(book, target) for target in targets))]
    if len({(normalized(book['title']), normalized(book['author'])) for book in books}) != 1:
        return []
    # No mezclar traducciones o ediciones al generar una afirmación concreta.
    # Si hay varias, el primer registro editorial estable es un alcance explícito.
    book = books[0]
    names = request.get('names', [])
    query = ' '.join(names) if names else message
    if not names:
        query = re.sub(re.escape(request['title']), '', query, flags=re.I).strip(' ¿?.,') or request['title']
    fragments = library_fragments(query, [book], semantic=getattr(settings,
        'LITMATE_LIBRARY_SEMANTIC_CHAT', False), maximum=4)
    if not fragments and not names:
        # Una petición general de contenido no contiene necesariamente ninguna
        # palabra del original. Recuperar el inicio sirve sólo como evidencia
        # parcial: el auditor sigue decidiendo qué puede contestarse con ella.
        fragments = library_fragments(book['title'], [book], maximum=4)
    fragments = [source for source in fragments if source.get('library_document_id') == book['library_document_id']]
    if not fragments:
        return []
    # El lector ve fragmentos parciales aunque el original esté completo.
    return canonical_sources([book, *fragments], 6)


def character_answer_from_library(message, request, config):
    if config is None:
        return None
    sources = sources_for_request(message, request)
    if not sources:
        return None
    from .ai_narrative_answers import synthesize_answer
    result, client = synthesize_answer(message, request, sources, config)
    result.diagnostics.update(local_library=True, model_calls=client.calls, usage=client.usage,
        library_fragments=sum(source['kind'] == 'excerpt' for source in sources))
    if result.status != 'answered':
        result.diagnostics['character_failure'] = 'local_evidence_not_approved'
    return result
