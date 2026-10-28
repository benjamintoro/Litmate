"""Adquisición bibliográfica acotada, reanudable y sin generación de hechos.

Los volcados se procesan en streaming. Un ledger SQLite separado conserva sólo
metadatos permitidos, procedencia y una bandeja de proyección idempotente hacia
``literary_memory``. No es la base Django ni descarga novelas o imágenes.

Open Library exige usar sus volcados oficiales para adquisición masiva; las
consultas a su API se reservan a búsquedas pequeñas iniciadas por una persona.
Las descripciones, biografías y reseñas OL no reciben permiso implícito de copia.
"""
import gzip
import hashlib
import json
import math
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

OWNER = 'litmate-literary-acquisition-v1'
VERSION = '1'
MAX_LINE = 1024 * 1024
PROVIDERS = ('openlibrary', 'wikidata', 'wikipedia')
POLICIES = {
    'openlibrary': {
        'documentation': 'https://openlibrary.org/developers/dumps',
        'license_url': 'https://openlibrary.org/developers/licensing',
        'license': 'Open Library bibliographic facts; rights vary',
        'scope': 'minimal_bibliographic_metadata_only',
    },
    'bne': {
        'documentation': 'https://www.bne.es/es/perfiles/bibliotecarios/suministro-registros',
        'license_url': 'https://www.bne.es/es/aviso-legal',
        'license': 'CC0-1.0', 'scope': 'catalog_metadata_only',
    },
    'wikidata': {
        'documentation': 'https://www.wikidata.org/wiki/Wikidata:Data_access',
        'license_url': 'https://www.wikidata.org/wiki/Wikidata:Licensing',
        'license': 'CC0-1.0', 'scope': 'structured_statements_not_independent_verification',
    },
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(str(value).encode('utf-8')).hexdigest()


def _text(value, maximum=220):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return ''
    value = re.sub(r'\s+', ' ', str(value)).strip()
    return value[:maximum] if len(value) <= maximum else ''


def _strings(value, maximum=24, length=100):
    return list(dict.fromkeys(item for item in (_text(row, length) for row in
        value[:maximum] if isinstance(row, str)) if item)) if isinstance(value, list) else []


def _path(database):
    if database is None:
        raise ValueError('Indica una base auxiliar explícita de adquisición.')
    path = Path(database).absolute()
    if path.is_symlink() or path.suffix.lower() not in {'.sqlite', '.sqlite3', '.db'}:
        raise ValueError('La adquisición necesita su propia SQLite auxiliar.')
    path = path.resolve()
    from django.conf import settings
    forbidden = [getattr(settings, key, '') for key in ('LITMATE_LITERARY_MEMORY_DB',
        'LITMATE_KNOWLEDGE_DB', 'LITMATE_KNOWLEDGE_RAG_DB', 'LITMATE_RAG_DB',
        'LITMATE_AI_RUNTIME_DB', 'LITMATE_AI_STREAM_DB', 'LITMATE_AI_ANSWER_CACHE_DB')]
    forbidden += [item.get('NAME', '') for item in getattr(settings, 'DATABASES', {}).values()]
    if any(str(item) not in {'', ':memory:'} and path == Path(item).resolve() for item in forbidden):
        raise ValueError('El ledger debe estar separado de las bases existentes.')
    return path


def _owned(db):
    try:
        owner = db.execute("SELECT value FROM acquisition_meta WHERE key='owner'").fetchone()
        version = db.execute("SELECT value FROM acquisition_meta WHERE key='version'").fetchone()
    except sqlite3.Error:
        owner = version = None
    if not owner or owner[0] != OWNER or not version or version[0] != VERSION:
        raise ValueError('La SQLite indicada no es un ledger de adquisición de LitMate.')


def initialize_acquisition_store(database):
    path = _path(database)
    if path.exists():
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.5)) as db:
            _owned(db)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb'):
            pass
    except FileExistsError:
        return initialize_acquisition_store(path)
    with closing(sqlite3.connect(path, timeout=.5)) as db, db:
        db.executescript('''
            CREATE TABLE acquisition_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE acquisition_datasets(dataset_id TEXT PRIMARY KEY,provider TEXT NOT NULL,
                source_url TEXT NOT NULL,sha256 TEXT NOT NULL,offset INTEGER NOT NULL,
                records INTEGER NOT NULL,finished INTEGER NOT NULL,updated_at REAL NOT NULL);
            CREATE TABLE acquisition_records(record_id TEXT PRIMARY KEY,provider TEXT NOT NULL,
                kind TEXT NOT NULL,external_id TEXT NOT NULL,revision INTEGER NOT NULL,
                content_hash TEXT NOT NULL,record TEXT NOT NULL,acquired_at REAL NOT NULL,
                verified_at REAL NOT NULL,UNIQUE(provider,external_id));
            CREATE TABLE acquisition_relations(record_id TEXT NOT NULL,predicate TEXT NOT NULL,
                target TEXT NOT NULL,PRIMARY KEY(record_id,predicate,target));
            CREATE INDEX acquisition_target ON acquisition_relations(target,predicate);
            CREATE TABLE acquisition_history(record_id TEXT NOT NULL,content_hash TEXT NOT NULL,
                record TEXT NOT NULL,replaced_at REAL NOT NULL,PRIMARY KEY(record_id,content_hash));
            CREATE TABLE acquisition_outbox(record_id TEXT PRIMARY KEY,content_hash TEXT NOT NULL,
                state TEXT NOT NULL,last_code TEXT NOT NULL);
        ''')
        db.executemany('INSERT INTO acquisition_meta VALUES (?,?)', [('owner', OWNER), ('version', VERSION)])
    return path


def _connect(database, *, write=False):
    path = initialize_acquisition_store(database) if write else _path(database)
    if not path.exists():
        return None
    db = sqlite3.connect(path.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=.5)
    db.row_factory = sqlite3.Row
    try:
        _owned(db)
    except Exception:
        db.close()
        raise
    return db


def _memory_path(database):
    """Valida destino sin crear nada, incluso durante --dry-run."""
    if database is None:
        raise ValueError('Indica una memoria literaria auxiliar explícita.')
    from .literary_memory import _connection, _path as memory_path
    path = memory_path(database)
    if path.exists():
        with _connection(path):
            pass
    return path


def _limits(max_records, max_scanned, max_seconds, max_storage_mb):
    if type(max_records) is not int or not 1 <= max_records <= 100000:
        raise ValueError('max_records debe estar entre 1 y 100000.')
    if type(max_scanned) is not int or not max_records <= max_scanned <= 1000000:
        raise ValueError('max_scanned debe estar entre max_records y 1000000.')
    if not math.isfinite(float(max_seconds)) or not 1 <= float(max_seconds) <= 3600:
        raise ValueError('max_seconds debe estar entre 1 y 3600.')
    if type(max_storage_mb) is not int or not 1 <= max_storage_mb <= 2048:
        raise ValueError('max_storage_mb debe estar entre 1 y 2048.')


def _storage_limit(db, maximum):
    page_size = db.execute('PRAGMA page_size').fetchone()[0]
    db.execute('PRAGMA max_page_count=' + str(max(1, maximum // page_size)))


def _source_url(value, provider):
    try:
        parts = urlsplit(value)
        allowed = {'openlibrary': ('openlibrary.org', 'archive.org'),
                   'bne': ('www.bne.es', 'datos.bne.es', 'catalogo.bne.es', 'datos.gob.es')}[provider]
        valid = (parts.scheme == 'https' and parts.hostname in allowed and
                 not parts.username and not parts.password and parts.port in {None, 443}
                 and not parts.query and not parts.fragment)
    except (ValueError, TypeError, KeyError):
        valid = False
    if not valid or len(value) > 1000:
        raise ValueError('Indica la URL HTTPS oficial de procedencia del archivo.')
    return value


def _fingerprint(path, *, deadline, clock):
    if path.is_symlink() or not path.is_file():
        raise ValueError('El volcado debe ser un archivo local regular.')
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while True:
            if clock() >= deadline:
                raise ValueError('Presupuesto agotado verificando el SHA256; amplía max_seconds.')
            chunk = stream.read(MAX_LINE)
            if not chunk:
                break
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('El volcado cambió durante su verificación.')
    return digest.hexdigest(), (after.st_size, after.st_mtime_ns)


def _isbn(value):
    result = []
    for item in value[:24] if isinstance(value, list) else []:
        code = re.sub(r'[\s-]', '', str(item)).upper()
        if len(code) == 13 and code.isdigit():
            valid = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(code)) % 10 == 0
        elif re.fullmatch(r'\d{9}[\dX]', code):
            valid = sum((10 - i) * (10 if c == 'X' else int(c)) for i, c in enumerate(code)) % 11 == 0
        else:
            valid = False
        if valid and code not in result:
            result.append(code)
    return result


def _keys(values, kind):
    expression = {'author': r'/authors/OL\d+A', 'work': r'/works/OL\d+W'}[kind]
    result = []
    for value in values[:12] if isinstance(values, list) else []:
        if isinstance(value, dict):
            candidate = value.get('author', value)
            key = candidate.get('key', '') if isinstance(candidate, dict) else ''
            if isinstance(key, str) and re.fullmatch(expression, key) and key not in result:
                result.append(key)
    return result


def openlibrary_record(line):
    """Proyecta las cinco columnas oficiales; descarta texto narrativo y HTML."""
    if not isinstance(line, bytes) or len(line) > MAX_LINE:
        raise ValueError('invalid_record')
    columns = line.decode('utf-8').rstrip('\r\n').split('\t', 4)
    if len(columns) != 5:
        raise ValueError('invalid_record')
    kind, key, revision, updated, encoded = columns
    patterns = {'/type/author': ('author', r'/authors/OL\d+A'),
                '/type/work': ('work', r'/works/OL\d+W'),
                '/type/edition': ('edition', r'/books/OL\d+M')}
    if kind not in patterns or not re.fullmatch(patterns[kind][1], key):
        raise ValueError('unsupported_record')
    data = json.loads(encoded)
    if (not isinstance(data, dict) or data.get('key') != key or
            not isinstance(data.get('type'), dict) or data['type'].get('key') != kind or
            not revision.isdigit() or len(revision) > 10 or data.get('revision', int(revision)) != int(revision)):
        raise ValueError('invalid_record')
    record = {'provider': 'openlibrary', 'kind': patterns[kind][0], 'external_id': key,
              'revision': int(revision), 'source_updated_at': _text(updated, 80),
              'url': 'https://openlibrary.org' + key, 'license': POLICIES['openlibrary']['license'],
              'policy': 'openlibrary-minimal-metadata-v1', 'extraction_version': VERSION}
    if record['kind'] == 'author':
        record.update(name=_text(data.get('name')), aliases=_strings(data.get('alternate_names'), length=220),
                      birth_date=_text(data.get('birth_date'), 80), death_date=_text(data.get('death_date'), 80))
        if not record['name']:
            raise ValueError('invalid_record')
    else:
        record.update(title=_text(data.get('title')), author_keys=_keys(data.get('authors'), 'author'),
            work_keys=_keys(data.get('works'), 'work'), categories=_strings(data.get('subjects')),
            year=_text(data.get('first_publish_date') or data.get('publish_date'), 80),
            publisher=', '.join(_strings(data.get('publishers'), maximum=3, length=60)),
            isbns=_isbn([*(data.get('isbn_10') or []), *(data.get('isbn_13') or [])]),
            languages=[row['key'].rsplit('/', 1)[-1] for row in
                       (data.get('languages') if isinstance(data.get('languages'), list) else [])[:12]
                       if isinstance(row, dict) and re.fullmatch(r'/languages/[a-z]{3}', str(row.get('key', '')))])
        if not record['title']:
            raise ValueError('invalid_record')
    from .literary_web import public_text_has_injection
    if public_text_has_injection(_json(record)):
        raise ValueError('untrusted_record')
    return record


def bne_record(element):
    """MARC21/XML del suministro BNE: hechos, nunca campo 520/resumen."""
    def children(tag):
        return [node for node in element if node.tag.rsplit('}', 1)[-1] == tag]
    controls = {node.get('tag'): _text(node.text or '', 200) for node in children('controlfield')}
    identifier = controls.get('001', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', identifier):
        raise ValueError('invalid_record')
    fields = {}
    for node in children('datafield'):
        values = [(part.get('code', ''), _text(part.text or '', 220)) for part in node
                  if part.tag.rsplit('}', 1)[-1] == 'subfield']
        fields.setdefault(node.get('tag'), []).append(values)
    def values(tag, code):
        return [text for row in fields.get(tag, [])[:32] for field, text in row if field == code and text]
    def first(tag, code):
        return next(iter(values(tag, code)), '').strip(' /:;,')
    title, author = first('245', 'a'), first('100', 'a')
    if not title or not author:
        raise ValueError('invalid_record')
    # Un número de control MARC no demuestra un URI Linked Data (los MMS ID
    # de Alma, por ejemplo, no son equivalentes a los antiguos identificadores).
    # Sólo se publica un enlace que esté expresamente dentro del registro.
    source_url = ''
    for value in values('024', 'a') + values('856', 'u'):
        try:
            parts = urlsplit(value)
            if (parts.scheme == 'https' and parts.hostname in {'datos.bne.es', 'catalogo.bne.es'}
                    and parts.port in {None, 443} and not parts.username and not parts.password
                    and not parts.query and not parts.fragment
                    and re.fullmatch(r'/resource/[A-Za-z0-9_-]{1,80}', parts.path)):
                source_url = value
                break
        except ValueError:
            continue
    record = {'provider': 'bne', 'kind': 'edition', 'external_id': identifier,
        'revision': 1, 'source_updated_at': controls.get('005', ''), 'title': title, 'author': author,
        'url': source_url, 'license': 'CC0-1.0',
        'policy': 'bne-catalog-cc0-v1', 'extraction_version': VERSION,
        'isbns': _isbn([re.split(r'[ (]', value)[0] for value in values('020', 'a')]),
        'publisher': first('264', 'b') or first('260', 'b'),
        'year': first('264', 'c') or first('260', 'c'),
        'categories': list(dict.fromkeys(values('650', 'a') + values('655', 'a')))[:24],
        'languages': [value for value in values('041', 'a') if re.fullmatch(r'[a-z]{3}', value)]}
    from .literary_web import public_text_has_injection
    if public_text_has_injection(_json(record)):
        raise ValueError('untrusted_record')
    return record


def _put(db, record, *, with_status=False):
    identifier = record['provider'] + ':' + record['external_id']
    encoded, now = _json(record), time.time()
    digest = _hash(encoded)
    previous = db.execute('SELECT * FROM acquisition_records WHERE record_id=?', (identifier,)).fetchone()
    if previous:
        if previous['content_hash'] == digest:
            return 'duplicates' if with_status else False
        if previous['revision'] > record.get('revision', 1):
            return 'stale' if with_status else False
        db.execute('INSERT OR IGNORE INTO acquisition_history VALUES (?,?,?,?)',
                   (identifier, previous['content_hash'], previous['record'], now))
    db.execute('INSERT OR REPLACE INTO acquisition_records VALUES (?,?,?,?,?,?,?,?,?)',
        (identifier, record['provider'], record['kind'], record['external_id'], record.get('revision', 1),
         digest, encoded, now, now))
    db.execute('DELETE FROM acquisition_relations WHERE record_id=?', (identifier,))
    for predicate, keys in [('author', record.get('author_keys', [])), ('edition_of', record.get('work_keys', []))]:
        db.executemany('INSERT OR IGNORE INTO acquisition_relations VALUES (?,?,?)',
                      [(identifier, predicate, key) for key in keys])
    staged = record.get('provenance', {}).get('admission') == 'staged'
    db.execute('INSERT OR REPLACE INTO acquisition_outbox VALUES (?,?,?,?)',
               (identifier, digest, 'staged' if staged else
                'metadata' if record['kind'] == 'author' else 'pending', ''))
    # Llegar un autor/obra permite resolver registros importados en otro orden.
    if not staged:
        db.execute("UPDATE acquisition_outbox SET state='pending',last_code='' WHERE state<>'staged' "
                   'AND record_id IN (SELECT record_id FROM acquisition_relations WHERE target=?)',
                   (record['external_id'],))
    return ('updated' if previous else 'inserted') if with_status else True


def _stored(db, provider, key):
    row = db.execute('SELECT r.record,o.state FROM acquisition_records r LEFT JOIN '
                     'acquisition_outbox o USING(record_id) WHERE r.provider=? AND r.external_id=?',
                     (provider, key)).fetchone()
    if not row or row['state'] == 'staged':
        return None
    record = json.loads(row['record'])
    if record.get('provenance', {}).get('admission') == 'staged' and row['state'] is None:
        return None
    return record


def verify_and_release(path, *, state_database, source_url, expected_sha256,
                       deadline=None, clock=None):
    """Admite un lote sólo después de releer el hash completo del archivo.

    El staging no alimenta el chat, la proyección ni la resolución de autores.
    Las dos comprobaciones separan un cursor reanudable de evidencia admitida.
    Un cierre/timeout anterior a esta operación conserva filas ``staged``.
    """
    clock = clock or time.monotonic
    deadline = deadline if deadline is not None else clock() + 60
    if not re.fullmatch(r'[a-fA-F0-9]{64}', str(expected_sha256)):
        raise ValueError('SHA256 esperado inválido.')
    digest, _ = _fingerprint(Path(path), deadline=deadline, clock=clock)
    if digest != expected_sha256.lower():
        raise ValueError('El archivo cambió; el lote permanece en staging y no se puede proyectar.')
    report = {'released': 0, 'authors': 0, 'sha256': digest}
    with closing(_connect(state_database, write=True)) as db, db:
        rows = db.execute("SELECT r.record_id,r.record,r.external_id,r.kind FROM acquisition_records r "
                          "JOIN acquisition_outbox o USING(record_id) WHERE o.state='staged'")
        admitted_targets = []
        for row in rows:
            if clock() >= deadline:
                raise TimeoutError('budget_exhausted')
            record = json.loads(row['record'])
            provenance = record.get('provenance', {})
            if (provenance.get('admission') != 'staged' or provenance.get('dataset_sha256') != digest
                    or provenance.get('dataset_url') != source_url):
                continue
            state = 'metadata' if row['kind'] == 'author' else 'pending'
            db.execute("UPDATE acquisition_outbox SET state=?,last_code='' WHERE record_id=? AND state='staged'",
                       (state, row['record_id']))
            report['released'] += 1
            report['authors'] += row['kind'] == 'author'
            admitted_targets.append(row['external_id'])
        for target in admitted_targets:
            db.execute("UPDATE acquisition_outbox SET state='pending',last_code='' WHERE state NOT IN ('staged','metadata') "
                       'AND record_id IN (SELECT record_id FROM acquisition_relations WHERE target=?)', (target,))
    return report


def _book_projection(db, record):
    if record.get('book'):
        return record['book'], record.get('sources', [record['book']])
    if record['kind'] == 'author':
        return None
    data = record
    if record['provider'] == 'openlibrary':
        # La edición sólo se vincula mediante works[] literal, nunca por título.
        if record['kind'] == 'edition':
            if len(record.get('work_keys', [])) != 1:
                return None
            data = _stored(db, 'openlibrary', record['work_keys'][0])
            if not data or data.get('kind') != 'work':
                return None
        authors = [_stored(db, 'openlibrary', key) for key in data.get('author_keys', [])]
        if not authors or any(not row or row.get('kind') != 'author' for row in authors):
            return None
        author = ', '.join(row['name'] for row in authors)
        if len(author) > 220:
            return None
        title, url, origin = data['title'], data['url'], 'Open Library'
    else:
        if not data.get('url'):
            return None
        title, author, url, origin = data['title'], data['author'], data['url'], 'BNE'
    source = {'title': title, 'author': author, 'source': origin, 'kind': 'book', 'url': url,
        'description': '', 'license': data['license'], 'policy': data['policy'],
        'storage_policy': data['policy'], 'year': record.get('year') or data.get('year', ''),
        'publisher': record.get('publisher', ''), 'categories': data.get('categories', []),
        'isbns': record.get('isbns', []), 'edition_id': record['external_id'] if record['kind'] == 'edition' else ''}
    languages = record.get('languages', [])
    if len(languages) == 1:
        source['language'] = languages[0]
    return source, [source]


def drain_projection(*, state_database, memory_database, max_records=1000, max_seconds=30):
    """Outbox durable: un corte entre las dos SQLite se reintenta sin duplicados."""
    if _path(state_database) == _memory_path(memory_database):
        raise ValueError('Ledger y memoria deben ser bases diferentes.')
    if not 1 <= max_records <= 100000 or not 0 < float(max_seconds) <= 3600:
        raise ValueError('Presupuesto de proyección inválido.')
    db = _connect(state_database)
    if db is None:
        return {'projected': 0, 'deferred': 0, 'sources': 0}
    db.close()
    from .literary_memory import remember_evidence
    report, deadline = {'projected': 0, 'deferred': 0, 'sources': 0}, time.monotonic() + max_seconds
    with closing(_connect(state_database, write=True)) as db:
        pending = db.execute("SELECT r.record_id,r.content_hash,r.record FROM acquisition_records r "
            "JOIN acquisition_outbox o USING(record_id) WHERE o.state='pending' "
            "ORDER BY CASE WHEN o.last_code='' THEN 0 ELSE 1 END,r.acquired_at "
            'LIMIT ?', (max_records,)).fetchall()
        for row in pending:
            if time.monotonic() >= deadline:
                break
            value = _book_projection(db, json.loads(row['record']))
            if value is None:
                # Sigue pendiente, pero las filas nuevas tienen prioridad para
                # evitar que miles de identidades sin autor bloqueen el lote.
                report['deferred'] += 1
                with db:
                    db.execute("UPDATE acquisition_outbox SET last_code='unresolved_identity' WHERE record_id=?",
                               (row['record_id'],))
                continue
            book, sources = value
            counts = remember_evidence([book], sources, database=memory_database)
            if not counts.get('sources'):
                report['deferred'] += 1
                with db:
                    db.execute("UPDATE acquisition_outbox SET last_code='storage_policy_rejected' WHERE record_id=?",
                               (row['record_id'],))
                continue
            with db:
                db.execute("UPDATE acquisition_outbox SET state='done',last_code='' WHERE record_id=? AND content_hash=?",
                           (row['record_id'], row['content_hash']))
            report['projected'] += 1
            report['sources'] += counts['sources']
    return report


def _checkpoint(db, dataset, provider, source_url, digest, offset, number, finished):
    db.execute('INSERT OR REPLACE INTO acquisition_datasets VALUES (?,?,?,?,?,?,?,?)',
               (dataset, provider, source_url, digest, offset, number, int(finished), time.time()))


def _xml_records(stream, *, clock, deadline):
    # El target impone límites mientras recibe texto, antes de construir un
    # elemento gigante. Sólo conserva el registro actual, nunca el árbol raíz.
    class Target:
        builder = None
        depth = 0
        size = 0
        nodes = 0
        ready = None
        def start(self, tag, attrs):
            self.depth += 1
            if self.depth > 32 or len(attrs) > 30:
                raise ValueError('XML excesivamente profundo o complejo.')
            if tag.rsplit('}', 1)[-1] == 'record':
                if self.builder is not None:
                    raise ValueError('Registros MARCXML anidados no permitidos.')
                self.builder, self.size, self.nodes = ElementTree.TreeBuilder(), 0, 0
            if self.builder is not None:
                self.nodes += 1
                if self.nodes > 10000:
                    raise ValueError('Registro MARCXML con demasiados elementos.')
                self.builder.start(tag, attrs)
        def data(self, value):
            if self.builder is not None:
                self.size += len(value.encode('utf-8'))
                if self.size > MAX_LINE:
                    raise ValueError('Registro XML excesivamente grande.')
                self.builder.data(value)
        def end(self, tag):
            if self.builder is not None:
                self.builder.end(tag)
                if tag.rsplit('}', 1)[-1] == 'record':
                    self.ready.append(self.builder.close())
                    self.builder = None
            self.depth -= 1
        def doctype(self, name, pubid, system):
            raise ValueError('XML con DTD o entidades no permitido.')
        def close(self):
            return None
    target = Target()
    target.ready = []
    parser = ElementTree.XMLParser(target=target)
    tail, bytes_without_record = b'', 0
    while True:
        if clock() >= deadline:
            raise TimeoutError('budget_exhausted')
        chunk = stream.read(65536)
        if not chunk:
            try:
                parser.close()
            except ElementTree.ParseError:
                raise ValueError('MARCXML truncado o inválido.') from None
            return
        check = tail + chunk
        if re.search(br'<!\s*(DOCTYPE|ENTITY)\b', check, re.I):
            raise ValueError('XML con DTD o entidades no permitido.')
        tail = check[-32:]
        bytes_without_record += len(chunk)
        if bytes_without_record > 2 * MAX_LINE:
            raise ValueError('Registro XML o cabecera excesivamente grande.')
        try:
            parser.feed(chunk)
        except ElementTree.ParseError:
            raise ValueError('MARCXML inválido; no se interpretan entidades externas.') from None
        while target.ready:
            bytes_without_record = 0
            yield target.ready.pop(0)


def _import(path, *, provider, state_database, memory_database, source_url, max_records=1000,
            max_scanned=10000, max_seconds=60, max_storage_mb=64, dry_run=False, subjects=(),
            languages=(), expected_sha256='', resume=True, clock=None):
    _limits(max_records, max_scanned, max_seconds, max_storage_mb)
    state = _path(state_database)
    if state == _memory_path(memory_database):
        raise ValueError('Indica una memoria auxiliar distinta del ledger.')
    source_url = _source_url(source_url, provider)
    if expected_sha256 and not re.fullmatch(r'[a-fA-F0-9]{64}', expected_sha256):
        raise ValueError('SHA256 esperado inválido.')
    clock, start = clock or time.monotonic, time.monotonic()
    started = clock()
    deadline = started + float(max_seconds)
    path = Path(path).absolute()
    digest, signature = _fingerprint(path, deadline=deadline, clock=clock)
    if expected_sha256 and digest != expected_sha256.lower():
        raise ValueError('El SHA256 no coincide con el esperado.')
    filters = _json({'subjects': sorted(subjects), 'languages': sorted(languages)})
    dataset = _hash(provider + '\0' + str(path.resolve()) + '\0' + source_url + '\0' + filters)
    previous, db = None, _connect(state)
    if db is not None:
        try:
            previous = db.execute('SELECT * FROM acquisition_datasets WHERE dataset_id=?', (dataset,)).fetchone()
            if previous and resume and previous['sha256'] != digest:
                raise ValueError('El volcado cambió; usa un nuevo archivo o --restart explícito.')
        finally:
            db.close()
    offset = previous['offset'] if previous and resume else 0
    number = previous['records'] if previous and resume else 0
    report = {'provider': provider, 'dry_run': bool(dry_run), 'sha256': digest, 'dataset_id': dataset,
        'scanned': 0, 'accepted': 0, 'inserted': 0, 'duplicates': 0, 'rejected': 0,
        'filtered': 0, 'offset_before': offset, 'offset_after': offset, 'complete': False,
        'status': 'bounded', 'seconds': 0., 'network_requests': 0, 'llm_calls': 0,
        'verification_scope': 'metadata_policy_shape_checksum_not_independent_fact_verification',
        'admission': {'released': 0, 'authors': 0},
        'projection': {'projected': 0, 'deferred': 0, 'sources': 0}}
    writable = None
    if not dry_run:
        writable = _connect(state, write=True)
        _storage_limit(writable, max_storage_mb * 1024 * 1024)
    opener = gzip.open if path.suffix.lower() == '.gz' else open
    try:
        with opener(path, 'rb') as stream:
            if provider == 'openlibrary':
                # gzip.seek hace trabajo no interrumpible; saltamos en trozos.
                remaining = offset
                if path.suffix.lower() != '.gz':
                    stream.seek(offset)
                    remaining = 0
                while remaining:
                    if clock() >= deadline:
                        raise TimeoutError('budget_exhausted')
                    chunk = stream.read(min(MAX_LINE, remaining))
                    if not chunk:
                        raise ValueError('Checkpoint fuera del archivo.')
                    remaining -= len(chunk)
                def records():
                    while True:
                        if clock() >= deadline:
                            raise TimeoutError('budget_exhausted')
                        line = stream.readline(MAX_LINE + 1)
                        if not line:
                            return
                        if len(line) > MAX_LINE:
                            raise ValueError('Línea demasiado grande; archivo no confiable.')
                        yield stream.tell(), line
                iterator = records()
            else:
                iterator = enumerate(_xml_records(stream, clock=clock, deadline=deadline), 1)
            for position, raw in iterator:
                if provider == 'bne' and position <= offset:
                    continue
                if report['scanned'] >= max_scanned or report['accepted'] >= max_records or clock() >= deadline:
                    break
                report['scanned'] += 1
                number += 1
                try:
                    record = openlibrary_record(raw) if provider == 'openlibrary' else bne_record(raw)
                except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError):
                    record = None
                    report['rejected'] += 1
                if record:
                    if ((subjects and record['kind'] != 'author' and not any(
                            term.casefold() in subject.casefold() for term in subjects for subject in record.get('categories', [])))
                            or (languages and record['kind'] == 'edition' and not
                                set(languages).intersection(record.get('languages', [])))):
                        report['filtered'] += 1
                        record = None
                    else:
                        record['provenance'] = {'dataset_url': source_url, 'dataset_sha256': digest,
                                                'record_number': number, 'source_id': record['external_id'],
                                                'admission': 'staged'}
                        report['accepted'] += 1
                inserted = None
                if writable:
                    with writable:
                        if record:
                            inserted = _put(writable, record)
                        _checkpoint(writable, dataset, provider, source_url, digest, position, number, False)
                    if inserted is not None:
                        report['inserted' if inserted else 'duplicates'] += 1
                report['offset_after'] = position
            else:
                report['complete'], report['status'] = True, 'complete'
            if writable:
                with writable:
                    _checkpoint(writable, dataset, provider, source_url, digest,
                                report['offset_after'], number, report['complete'])
    except TimeoutError:
        report['status'] = 'budget_exhausted'
    except sqlite3.OperationalError as exc:
        if 'full' not in str(exc).lower():
            raise
        report['status'] = 'storage_limit'
    except KeyboardInterrupt:
        report['status'] = 'paused'
    finally:
        if writable:
            writable.close()
    if signature != (path.stat().st_size, path.stat().st_mtime_ns):
        # Ya se conservaron registros con su hash anterior; no proyectarlos.
        raise ValueError('El archivo cambió durante la importación; no se proyectó a memoria.')
    if not dry_run and report['status'] not in {'storage_limit', 'paused'}:
        remaining = max(0, deadline - clock())
        if remaining:
            try:
                report['admission'] = verify_and_release(path, state_database=state,
                    source_url=source_url, expected_sha256=digest, deadline=deadline, clock=clock)
            except (TimeoutError, ValueError) as exc:
                if isinstance(exc, ValueError) and 'Presupuesto' not in str(exc):
                    raise
                report['status'] = 'budget_exhausted'
            remaining = max(0, deadline - clock())
            if remaining and report['admission']['released']:
                report['projection'] = drain_projection(state_database=state, memory_database=memory_database,
                    max_records=max_records, max_seconds=min(remaining, 3600))
    report['seconds'] = round(time.monotonic() - start, 4)
    return report


def import_openlibrary_dump(path, **options):
    """TSV oficial plano/gzip; autores→obras→ediciones recomendado, sin HTML."""
    return _import(path, provider='openlibrary', **options)


def import_bne_marcxml(path, **options):
    """MARCXML local oficial CC0; reanuda por ordinal con memoria acotada."""
    return _import(path, provider='bne', **options)


def query_acquisition(query, *, provider='openlibrary', state_database, memory_database,
                      max_results=5, max_seconds=12, dry_run=False, fetch=None, book=None):
    """Lookup humano pequeño; deliberadamente sin paginación ni modo masivo API."""
    from .books_google import public_query
    from .literary_identity import bind_source, same_work, work_identity
    from .literary_sources import research_scope
    from .ai_budget import request_budget
    if provider not in PROVIDERS or not 1 <= max_results <= 5 or not 1 <= max_seconds <= 30:
        raise ValueError('Proveedor o límites de consulta no permitidos.')
    if not isinstance(query, str) or not query.strip() or public_query(query) != query or len(query) > 220:
        raise ValueError('Usa únicamente título, autor o identificadores bibliográficos públicos.')
    state = _path(state_database)
    if state == _memory_path(memory_database):
        raise ValueError('La memoria debe ser distinta del ledger.')
    if provider == 'wikipedia' and not work_identity(book):
        raise ValueError('Wikipedia necesita una identidad bibliográfica confirmada (--title y --author).')
    if fetch is None:
        if provider == 'openlibrary':
            from .literary_search import search_openlibrary
            fetch = lambda value: search_openlibrary(value, details=False)
        elif provider == 'wikidata':
            from .literary_wikidata import search_wikidata
            fetch = search_wikidata
        else:
            from .literary_search import search_wikipedia
            fetch = search_wikipedia
    start = time.monotonic()
    try:
        with request_budget(start + max_seconds), research_scope(maximum=1, seconds=max_seconds,
                                                               pages=2 if provider == 'wikipedia' else 0):
            found = fetch(query)
    except (OSError, ValueError, TypeError) as exc:
        from .literary_sources import SearchResults, error_status
        found = SearchResults(status=error_status(exc))
    status = getattr(found, 'status', 'ok' if found else 'empty')
    report = {'provider': provider, 'dry_run': bool(dry_run), 'status': status, 'accepted': 0,
              'inserted': 0, 'duplicates': 0, 'sources': 0, 'seconds': 0., 'llm_calls': 0}
    if status not in {'ok', 'partial'}:
        report['seconds'] = round(time.monotonic() - start, 4)
        return report
    if not isinstance(found, (list, tuple)):
        report.update(status='invalid_response', seconds=round(time.monotonic() - start, 4))
        return report
    found = [source for source in found[:20] if isinstance(source, dict)]
    if provider == 'wikipedia' and book:
        from .ai_character_answers import bind_character_profile, _profile_facts
        found = [_profile_facts(bound, {'names': [bound['title']]}) if
                 (bound := bind_character_profile(source, book)) else source for source in found]
    books = ([book] if book else [source for source in found if source.get('kind') == 'book'
                                 and work_identity(source)])[:max_results]
    candidates = []
    from .literary_memory import _projection
    for candidate in books:
        # La política de almacenamiento existente decide campo por campo.
        admitted = [_projection(bind_source(source, candidate), candidate)
                    for source in found if same_work(source, candidate)]
        admitted = [source for source in admitted if source]
        # La proyección autorizada conserva una revisión de Wikipedia, pero
        # el reingreso exige también el marcador explícito de almacenamiento.
        admitted = [{**source, 'storage_policy': source['policy']} if
                    source.get('policy') == 'wikipedia-cc-by-sa-4.0-v1' else source
                    for source in admitted]
        if not admitted:
            continue
        safe_book = next((source for source in admitted if source.get('kind') == 'book'), None)
        if not safe_book:
            from .literary_memory import _work
            safe_book = _work(candidate)
        if not safe_book:
            continue
        identity = work_identity(safe_book)
        record = {'provider': provider, 'kind': 'work', 'external_id': identity['work_id'],
                  'revision': 1, 'book': safe_book, 'sources': admitted, 'policy': 'existing_source_policy',
                  'extraction_version': VERSION}
        candidates.append(record)
    report['accepted'] = len(candidates)
    if not dry_run and candidates:
        with closing(_connect(state, write=True)) as db, db:
            _storage_limit(db, 64 * 1024 * 1024)
            for record in candidates:
                report['inserted' if _put(db, record) else 'duplicates'] += 1
        projection = drain_projection(state_database=state, memory_database=memory_database,
            max_records=max_results, max_seconds=max_seconds)
        report['sources'] = projection['sources']
    report['seconds'] = round(time.monotonic() - start, 4)
    return report


def acquisition_stats(database):
    db = _connect(database)
    if db is None:
        return {'exists': False, 'records': 0, 'datasets': 0, 'pending': 0, 'staged': 0, 'by_provider': {}}
    with closing(db):
        return {'exists': True,
            'records': db.execute('SELECT COUNT(*) FROM acquisition_records').fetchone()[0],
            'datasets': db.execute('SELECT COUNT(*) FROM acquisition_datasets').fetchone()[0],
            'pending': db.execute("SELECT COUNT(*) FROM acquisition_outbox WHERE state='pending'").fetchone()[0],
            'staged': db.execute("SELECT COUNT(*) FROM acquisition_outbox WHERE state='staged'").fetchone()[0],
            'by_provider': dict(db.execute('SELECT provider,COUNT(*) FROM acquisition_records GROUP BY provider'))}
