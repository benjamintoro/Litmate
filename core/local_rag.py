"""SQLite FTS5 + embeddings locales, con filtro por obra y reemplazo atómico."""
import hashlib
import json
import logging
import os
import re
import sqlite3
import struct
import tempfile
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from .literary_ai import clean_text, normalized

logger = logging.getLogger('litmate')
STOPWORDS = {'el', 'la', 'los', 'las', 'de', 'del', 'en', 'un', 'una', 'que',
             'por', 'para', 'con', 'libro', 'libros', 'resume', 'resumen',
             'analiza', 'explica', 'sobre', 'quiero', 'dame', 'autor', 'titulo',
             'como', 'quien', 'porque', 'cual', 'cuales', 'sus', 'este', 'esta',
             'ese', 'esa', 'explicame', 'cuentame', 'contenido', 'pagina', 'capitulo'}


def _pages(path):
    if path.stat().st_size > 25_000_000:
        raise ValueError('El archivo supera 25 MB: ' + path.name)
    if path.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise ValueError('PDF cifrado: ' + path.name)
        if len(reader.pages) > 1500:
            raise ValueError('PDF demasiado extenso: ' + path.name)
        for number, page in enumerate(reader.pages, 1):
            yield f'página {number} del PDF', (page.extract_text() or '')[:100000]
    else:
        raw = path.read_bytes()
        if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
            body = raw.decode('utf-16')
        else:
            try:
                body = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                # Archivos de texto antiguos guardados por Windows/Office.
                body = raw.decode('cp1252')
        yield 'archivo de texto', body


def _chunks(body):
    body = re.sub(r'\s+', ' ', body).strip()
    start = 0
    while start < len(body):
        end = min(start + 1000, len(body))
        if end < len(body):
            boundary = body.rfind(' ', max(start + 800, end - 120), end)
            if boundary > start:
                end = boundary
        fragment = body[start:end].strip()
        if len(fragment) >= 30:
            yield start, fragment
        if end == len(body):
            break
        start = max(start + 1, end - 180)
        while start < end and start > 0 and not body[start - 1].isspace():
            start += 1


def _metadata(db):
    try:
        return dict(db.execute('SELECT key, value FROM rag_metadata'))
    except sqlite3.OperationalError:
        return {}


def index_documents(folder, database, *, embedder=None, progress=None, metadata=None):
    folder, database = Path(folder).resolve(), Path(database).resolve()
    if not folder.is_dir():
        raise ValueError('No existe la carpeta de libros')
    files = sorted(p for p in folder.iterdir() if p.is_file() and not p.is_symlink()
                   and p.suffix.lower() in {'.pdf', '.txt', '.md'})
    if not files:
        raise ValueError('Agrega archivos Titulo__Autor.pdf, .txt o .md')
    identity = embedder.identity() if embedder is not None else None
    metadata = metadata or {}
    if not isinstance(metadata, dict):
        raise ValueError('Los metadatos deben relacionar nombres de archivo con fichas')
    database.parent.mkdir(parents=True, exist_ok=True)
    fd, staging = tempfile.mkstemp(prefix='litmate-rag-', suffix='.sqlite3', dir=database.parent)
    os.close(fd)
    previous = None
    count, indexed, dimension = 0, 0, None
    try:
        if identity and database.is_file():
            previous = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
            previous_metadata = _metadata(previous)
            if (previous_metadata.get('model'), previous_metadata.get('digest')) != identity:
                previous.close()
                previous = None
        with closing(sqlite3.connect(staging)) as db, db:
            db.execute('CREATE VIRTUAL TABLE chunks USING fts5('
                'title, author, body, filename UNINDEXED, locator UNINDEXED,'
                'document_id UNINDEXED, chunk_id UNINDEXED,'
                'tokenize="unicode61 remove_diacritics 2")')
            db.execute('CREATE TABLE documents (document_id TEXT PRIMARY KEY, title TEXT, author TEXT)')
            db.execute('CREATE TABLE document_metadata (document_id TEXT PRIMARY KEY, record TEXT)')
            db.execute('CREATE TABLE rag_metadata (key TEXT PRIMARY KEY, value TEXT)')
            db.execute('CREATE TABLE rag_vectors (rowid INTEGER PRIMARY KEY, '
                       'chunk_id TEXT UNIQUE, dimension INTEGER, vector BLOB)')
            pending = []

            def flush():
                nonlocal dimension
                if not pending:
                    return
                missing, vectors = [], {}
                for item in pending:
                    cached = previous.execute('SELECT dimension, vector FROM rag_vectors '
                        'WHERE chunk_id=?', (item['chunk_id'],)).fetchone() if previous else None
                    if cached and len(cached[1]) == cached[0] * 4:
                        vectors[item['rowid']] = (cached[0], cached[1])
                    else:
                        missing.append(item)
                if missing:
                    texts = ['title: ' + item['title'] + ' — ' + item['author']
                             + ' | text: ' + item['body'] for item in missing]
                    generated = embedder.embed(texts)
                    if len(generated) != len(missing):
                        raise ValueError('Faltan embeddings')
                    for item, vector in zip(missing, generated):
                        vectors[item['rowid']] = (len(vector), struct.pack('<' + 'f' * len(vector), *vector))
                for item in pending:
                    size, blob = vectors[item['rowid']]
                    if dimension is not None and dimension != size:
                        raise ValueError('El modelo cambió sus dimensiones; reconstruye el índice')
                    dimension = size
                    db.execute('INSERT INTO rag_vectors VALUES (?,?,?,?)',
                               (item['rowid'], item['chunk_id'], size, blob))
                pending.clear()

            for path in files:
                if '__' not in path.stem:
                    raise ValueError('Usa Titulo__Autor en el nombre: ' + path.name)
                title, author = (clean_text(part.replace('_', ' '), 220)
                                 for part in path.stem.split('__', 1))
                if not title or not author:
                    raise ValueError('Falta título o autor: ' + path.name)
                attributes = metadata.get(path.name, {})
                if not isinstance(attributes, dict):
                    raise ValueError('Metadatos inválidos: ' + path.name)
                if attributes.get('kind', 'excerpt') != 'excerpt':
                    # Un resumen propio no se convierte en texto de la novela,
                    # ni concede permiso para citas o páginas de una edición.
                    if (attributes.get('kind') not in {'book', 'web'}
                            or attributes.get('indexing_authorized') is not True
                            or not attributes.get('license') or not attributes.get('url')):
                        raise ValueError('Las fichas necesitan autorización, licencia y fuente: ' + path.name)
                    title = clean_text(attributes.get('work_title', title), 220)
                    author = clean_text(attributes.get('work_author', author), 220)
                if path.stat().st_size > 25_000_000:
                    raise ValueError('El archivo supera 25 MB: ' + path.name)
                document_hash = hashlib.sha256()
                with path.open('rb') as content:
                    for block in iter(lambda: content.read(1024 * 1024), b''):
                        document_hash.update(block)
                digest = document_hash.hexdigest()[:16]
                document_id = hashlib.sha256((digest + title + '\0' + author).encode()).hexdigest()[:24]
                added = db.execute('INSERT OR IGNORE INTO documents VALUES (?,?,?)', (document_id, title, author))
                if added.rowcount == 0:
                    continue
                db.execute('INSERT INTO document_metadata VALUES (?,?)',
                           (document_id, json.dumps(attributes, ensure_ascii=False)))
                before, total_chars = count, 0
                for locator, body in _pages(path):
                    total_chars += len(body)
                    if total_chars > 12_000_000:
                        raise ValueError('Texto demasiado extenso: ' + path.name)
                    for offset, fragment in _chunks(body):
                        count += 1
                        if count > 60000:
                            raise ValueError('La colección supera 60000 fragmentos')
                        chunk_id = hashlib.sha256((document_id + locator + str(offset)
                            + fragment).encode()).hexdigest()[:32]
                        db.execute('INSERT INTO chunks VALUES (?,?,?,?,?,?,?)',
                                   (title, author, fragment, path.name, locator, document_id, chunk_id))
                        if embedder is not None:
                            pending.append({'rowid': count, 'chunk_id': chunk_id, 'title': title,
                                            'author': author, 'body': fragment})
                            if len(pending) == 8:
                                flush()
                        if progress and count % 500 == 0:
                            progress(count)
                if count == before:
                    raise ValueError('No hay texto extraíble: ' + path.name + '. Un PDF escaneado necesita OCR.')
                indexed += 1
            if embedder is not None:
                flush()
                db.executemany('INSERT INTO rag_metadata VALUES (?,?)',
                    [('model', identity[0]), ('digest', identity[1]), ('dimension', str(dimension)),
                     ('chunks', str(count)), ('version', 'hybrid-v2')])
        if previous is not None:
            previous.close()
            previous = None
        os.replace(staging, database)
        _vector_matrix.cache_clear()
        return indexed, count
    finally:
        if previous is not None:
            previous.close()
        Path(staging).unlink(missing_ok=True)


@lru_cache(maxsize=2)
def _vector_matrix(path, mtime_ns, size):
    import numpy as np
    revision = Path(path).stat()
    if (revision.st_mtime_ns, revision.st_size) != (mtime_ns, size):
        raise ValueError('El índice fue reconstruido durante la consulta')
    with closing(sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)) as db:
        metadata = _metadata(db)
        rows = db.execute('SELECT rowid, dimension, vector FROM rag_vectors ORDER BY rowid').fetchall()
    if not rows:
        return metadata, np.empty(0, dtype=np.int64), np.empty((0, 0), dtype=np.float32)
    dimension = int(metadata['dimension'])
    if not 1 <= dimension <= 2048 or len(rows) > 60000:
        raise ValueError('Índice vectorial inválido')
    matrix = np.empty((len(rows), dimension), dtype=np.float32)
    ids = np.empty(len(rows), dtype=np.int64)
    for i, (rowid, dims, blob) in enumerate(rows):
        if dims != dimension or len(blob) != 4 * dimension:
            raise ValueError('Vector almacenado inválido')
        ids[i] = rowid
        matrix[i] = np.frombuffer(blob, dtype='<f4')
    if not np.isfinite(matrix).all():
        raise ValueError('El índice contiene números inválidos')
    revision = Path(path).stat()
    if (revision.st_mtime_ns, revision.st_size) != (mtime_ns, size):
        raise ValueError('El índice fue reconstruido durante la consulta')
    matrix.flags.writeable = False
    return metadata, ids, matrix


def _book_filter(db, query, book_titles, book_identities=None):
    try:
        documents = db.execute('SELECT document_id, title, author FROM documents').fetchall()
    except sqlite3.OperationalError:
        return None
    if book_identities:
        wanted = {(normalized(b.get('title')), normalized(b.get('author')))
                  for b in book_identities if isinstance(b, dict)
                  and b.get('title') and b.get('author')}
        return [row[0] for row in documents if (normalized(row[1]), normalized(row[2])) in wanted]
    if book_titles:
        wanted = {normalized(t) for t in book_titles if isinstance(t, str) and t.strip()}
        return [row[0] for row in documents if normalized(row[1]) in wanted]
    value = normalized(query)
    matched = [row[0] for row in documents if len(normalized(row[1])) >= 4
               and re.search(r'(?<!\w)' + re.escape(normalized(row[1])) + r'(?!\w)', value)]
    return matched or None


def retrieve_fragments(query, database, maximum=4, *, embedder=None,
                       book_titles=None, book_identities=None, minimum_similarity=0.35):
    database = Path(database).resolve()
    if not database.is_file():
        return []
    maximum = max(1, min(int(maximum), 8))
    terms = list(dict.fromkeys(t for t in re.findall(r'\w+', normalized(query))
                              if len(t) >= 3 and t not in STOPWORDS))[:18]
    revision = database.stat()
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
        allowed = _book_filter(db, query, book_titles, book_identities)
        if allowed == []:
            return []
        conditions, params = [], []
        if allowed is not None:
            conditions.append('document_id IN (' + ','.join('?' for _ in allowed) + ')')
            params.extend(allowed)
        page = re.search(r'\bpagina\s+(?:numero\s+)?(\d+)\b', normalized(query))
        if page:
            if allowed is None:
                return []
            conditions.append('locator=?')
            params.append('página ' + page.group(1) + ' del PDF')
        where = (' AND ' + ' AND '.join(conditions)) if conditions else ''
        match = ' OR '.join('"' + t + '"*' for t in terms)
        lexical = db.execute('SELECT rowid FROM chunks WHERE chunks MATCH ?' + where
            + ' ORDER BY bm25(chunks, 0.3, 0.2, 1.0), rowid LIMIT 32', [match, *params]).fetchall() if terms else []
        ranking = {row[0]: 1 / (60 + rank) for rank, row in enumerate(lexical, 1)}
        metadata = _metadata(db)
        if embedder is not None and metadata.get('version') == 'hybrid-v2' and not page:
            try:
                import numpy as np
                if embedder.identity() != (metadata.get('model'), metadata.get('digest')):
                    raise ValueError('El modelo de embeddings cambió: vuelve a indexar')
                _, ids, matrix = _vector_matrix(str(database), revision.st_mtime_ns, revision.st_size)
                current = database.stat()
                if (current.st_mtime_ns, current.st_size) != (revision.st_mtime_ns, revision.st_size):
                    raise ValueError('El índice cambió durante la consulta')
                vector = np.asarray(embedder.embed([query], query=True)[0], dtype=np.float32)
                if vector.shape != (matrix.shape[1],):
                    raise ValueError('Dimensión de consulta inválida')
                similarities = matrix @ vector
                eligible = np.isfinite(similarities) & (similarities >= minimum_similarity)
                if conditions:
                    eligible_ids = [row[0] for row in db.execute('SELECT rowid FROM chunks WHERE '
                                    + ' AND '.join(conditions), params)]
                    eligible &= np.isin(ids, eligible_ids)
                indices = np.flatnonzero(eligible)
                best = indices[np.argsort(similarities[indices], kind='stable')[::-1][:32]]
                for rank, index in enumerate(best, 1):
                    rowid = int(ids[index])
                    ranking[rowid] = ranking.get(rowid, 0) + 1 / (60 + rank)
            except Exception as exc:
                logger.warning('IA: búsqueda semántica no disponible (%s); se usa FTS', type(exc).__name__)
        if page and not ranking:
            ranking = {row[0]: 1 / (60 + i) for i, row in enumerate(db.execute(
                'SELECT rowid FROM chunks WHERE ' + ' AND '.join(conditions) + ' ORDER BY rowid LIMIT 8', params), 1)}
        selected, seen_texts = [], []
        for rowid in sorted(ranking, key=lambda i: (-ranking[i], i)):
            row = db.execute('SELECT title, author, body, filename, locator, document_id, chunk_id '
                             'FROM chunks WHERE rowid=?', (rowid,)).fetchone()
            if not row:
                continue
            title, author, body, filename, locator, document_id, chunk_id = row
            content = normalized(body)
            if any(content == text or (len(content) > 100 and content in text) for text in seen_texts):
                continue
            try:
                metadata_row = db.execute('SELECT record FROM document_metadata WHERE document_id=?',
                                          (document_id,)).fetchone()
                attributes = json.loads(metadata_row[0]) if metadata_row else {}
            except (sqlite3.OperationalError, ValueError, TypeError):
                attributes = {}
            source = {'title': title, 'author': author, 'description': body, 'kind': 'excerpt',
                'source': 'Colección local: ' + filename, 'locator': locator,
                'book_id': chunk_id, 'read_mode': 'fragmento recuperado'}
            if attributes:
                for key in ('kind', 'source', 'url', 'license', 'work_id', 'work_title',
                            'work_author', 'work_binding_verified', 'confirmed_aliases',
                            'isbns', 'character_facts', 'character_scope', 'fact_topics',
                            'literary_facts', 'fact_ids', 'memory_source_id', 'content_hash',
                            'evidence_hash', 'policy', 'attribution', 'memory_verified',
                            'expires_at', 'last_verified_at'):
                    if key in attributes:
                        source[key] = attributes[key]
                if source['kind'] != 'excerpt':
                    source.update(locator='ficha factual local', complete_work=False,
                        read_mode='resumen original autorizado; no texto de la novela')
                    if attributes.get('memory_source_id'):
                        source['read_mode'] = 'candidato del índice de memoria; requiere revalidación de fuente'
                    source['literary_facts'] = [fact for fact in source.get('literary_facts', [])
                        if isinstance(fact, dict) and fact.get('evidence')
                        and fact['evidence'] in body]
                    source['character_facts'] = [fact for fact in source.get('character_facts', [])
                        if isinstance(fact, dict) and fact.get('name') and fact['name'] in body
                        and fact.get('role') and fact['role'] in body]
                    if source['kind'] == 'web':
                        source['author'] = 'Fuente web'
            selected.append(source)
            seen_texts.append(content)
            if len(selected) == maximum:
                break
    return selected
