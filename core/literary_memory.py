"""Memoria bibliográfica auxiliar, con derechos, procedencia y cola reanudable.

No guarda conversaciones ni salidas del modelo. La autorización de lectura web
no concede permiso de almacenamiento: cada adaptador tiene una política cerrada.
Las lecturas no crean bases ni modifican el catálogo Django.
"""
import hashlib
import json
import re
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from .literary_identity import normalize_identity, same_work, stable_work_id, work_identity

OWNER = 'litmate-literary-memory-v1'
PROVIDERS = {'openlibrary', 'wikidata'}
REQUIREMENTS = {'', 'author', 'characters', 'character_detail', 'summary', 'plot',
    'identification', 'identify', 'relationships', 'events', 'ending', 'themes',
    'metadata', 'recommend', 'book_identity', 'publication', 'synopsis', 'bibliography',
    'recommendation', 'content', 'comparison', 'scenes', 'exact_passage'}
OUTCOMES = {'verified', 'failed', 'hit', 'miss'}
ERRORS = {'unavailable', 'timeout', 'rate_limited', 'invalid_response', 'empty',
          'access_denied', 'budget_exhausted', 'no_verified_match'}
EXCLUSIVE = {'author', 'autor', 'birth', 'death', 'muerte', 'ending', 'desenlace',
             'identity', 'identidad', 'father', 'mother', 'padre', 'madre', 'publication'}


def default_path():
    from django.conf import settings
    return Path(getattr(settings, 'LITMATE_LITERARY_MEMORY_DB',
        Path(settings.BASE_DIR) / 'data' / 'literary_memory.sqlite3')).resolve()


def _path(database=None):
    path = Path(database).absolute() if database is not None else default_path()
    if path.is_symlink() or path.suffix.lower() not in {'.sqlite3', '.sqlite', '.db'}:
        raise ValueError('La memoria necesita una base SQLite auxiliar propia')
    path = path.resolve()
    from django.conf import settings
    forbidden = [getattr(settings, key, '') for key in
        ('LITMATE_KNOWLEDGE_DB', 'LITMATE_KNOWLEDGE_RAG_DB', 'LITMATE_RAG_DB')]
    forbidden.extend(item.get('NAME', '') for item in getattr(settings, 'DATABASES', {}).values()
                     if item.get('ENGINE', '').endswith('sqlite3'))
    if any(str(value) not in {'', ':memory:'} and path == Path(value).resolve()
           for value in forbidden):
        raise ValueError('La memoria debe estar separada de bases existentes y de producción')
    return path


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _hash(*values):
    return hashlib.sha256('\0'.join(str(value) for value in values).encode()).hexdigest()


def _owned(db):
    try:
        row = db.execute("SELECT value FROM memory_meta WHERE key='owner'").fetchone()
        version = db.execute("SELECT value FROM memory_meta WHERE key='schema_version'").fetchone()
    except sqlite3.Error:
        row, version = None, None
    if not row or row[0] != OWNER or not version or version[0] != '1':
        raise ValueError('La base indicada no pertenece a la memoria de LitMate')


@contextmanager
def _connection(database=None, *, write=False):
    path = _path(database)
    if not path.is_file():
        if not write:
            yield None
            return
        initialize_store(path)
    with closing(sqlite3.connect(path.as_uri() + ('?mode=rw' if write else '?mode=ro'),
                                uri=True, timeout=.5)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        _owned(db)
        with db:
            yield db


def initialize_store(database=None):
    """Crea solamente una base nueva; nunca adopta una SQLite desconocida."""
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
        return initialize_store(path)
    with closing(sqlite3.connect(path, timeout=.5)) as db, db:
        db.executescript('''
            CREATE TABLE memory_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE memory_works(work_id TEXT PRIMARY KEY,title_key TEXT NOT NULL,
                author_key TEXT NOT NULL,record TEXT NOT NULL);
            CREATE INDEX memory_work_title ON memory_works(title_key,author_key);
            CREATE TABLE memory_aliases(title_key TEXT NOT NULL,author_key TEXT NOT NULL,
                work_id TEXT NOT NULL,PRIMARY KEY(title_key,author_key,work_id));
            CREATE TABLE memory_entities(entity_id TEXT PRIMARY KEY,work_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,label TEXT NOT NULL,record TEXT NOT NULL);
            CREATE INDEX memory_entity_work ON memory_entities(work_id,entity_type);
            CREATE TABLE memory_sources(source_id TEXT PRIMARY KEY,work_id TEXT NOT NULL,
                provider TEXT NOT NULL,url TEXT NOT NULL,policy TEXT NOT NULL,
                retrieved_at REAL NOT NULL,verified_at REAL NOT NULL,expires_at REAL NOT NULL,
                content_hash TEXT NOT NULL,record TEXT NOT NULL,
                FOREIGN KEY(work_id) REFERENCES memory_works(work_id));
            CREATE INDEX memory_source_work ON memory_sources(work_id,expires_at);
            CREATE TABLE memory_assertions(assertion_id TEXT PRIMARY KEY,work_id TEXT NOT NULL,
                source_id TEXT NOT NULL,subject TEXT NOT NULL,predicate TEXT NOT NULL,
                object_value TEXT NOT NULL,topic TEXT NOT NULL,record TEXT NOT NULL,
                FOREIGN KEY(source_id) REFERENCES memory_sources(source_id) ON DELETE CASCADE);
            CREATE INDEX memory_assertion_work ON memory_assertions(work_id,predicate,subject);
            CREATE TABLE memory_conflicts(conflict_id TEXT PRIMARY KEY,work_id TEXT NOT NULL,
                assertion_a TEXT NOT NULL,assertion_b TEXT NOT NULL,status TEXT NOT NULL);
            CREATE INDEX memory_conflict_work ON memory_conflicts(work_id,status);
            CREATE TABLE memory_history(snapshot_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,
                work_id TEXT NOT NULL,retrieved_at REAL NOT NULL,content_hash TEXT NOT NULL,
                record TEXT NOT NULL);
            CREATE TABLE memory_jobs(job_id TEXT PRIMARY KEY,work_id TEXT NOT NULL,
                requirement TEXT NOT NULL,provider TEXT NOT NULL,priority INTEGER NOT NULL,
                status TEXT NOT NULL,attempts INTEGER NOT NULL,not_before REAL NOT NULL,
                lease_until REAL NOT NULL,lease_token TEXT NOT NULL,worker_id TEXT NOT NULL,
                last_error TEXT NOT NULL,payload TEXT NOT NULL,
                UNIQUE(work_id,requirement,provider));
            CREATE INDEX memory_job_pending ON memory_jobs(status,not_before,priority);
            CREATE TABLE memory_usage(work_id TEXT NOT NULL,requirement TEXT NOT NULL,
                provider TEXT NOT NULL,hits INTEGER NOT NULL DEFAULT 0,
                verified INTEGER NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,
                total_latency REAL NOT NULL DEFAULT 0,PRIMARY KEY(work_id,requirement,provider));
        ''')
        try:
            db.execute('CREATE VIRTUAL TABLE memory_fts USING fts5(source_id UNINDEXED,'
                'work_id UNINDEXED,title,author,body,tokenize="unicode61 remove_diacritics 2")')
            fts = '1'
        except sqlite3.OperationalError:
            fts = '0'
        db.executemany('INSERT INTO memory_meta VALUES (?,?)',
                       [('owner', OWNER), ('schema_version', '1'), ('revision', '0'), ('fts', fts)])
    return path


def _bump(db):
    db.execute("UPDATE memory_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")


def revision(database=None):
    with _connection(database) as db:
        if db is None:
            return 'missing'
        return str(db.execute("SELECT value FROM memory_meta WHERE key='revision'").fetchone()[0])


def _public_url(value):
    from .literary_knowledge import _public_reference
    value = str(value or '')
    return value if _public_reference(value) and not urlsplit(value).query else ''


def _origin(value, host):
    try:
        parts = urlsplit(value)
        return parts.hostname == host and parts.scheme == 'https' and not parts.query
    except ValueError:
        return False


def _work(book):
    identity = work_identity(book)
    if not identity or len(identity['title']) > 220 or len(identity['author']) > 220:
        return None
    identifier = stable_work_id(identity['title'], identity['author'])
    value = {key: identity[key] for key in ('title', 'author', 'confirmed_aliases', 'isbns')
             if key in identity}
    value.update(work_id=identifier, kind='book', source=str(book.get('source', ''))[:80])
    if _public_url(book.get('url')):
        value['url'] = book['url']
    for key in ('year', 'publisher', 'language', 'edition_id'):
        if isinstance(book.get(key), (str, int)):
            value[key] = str(book[key])[:220]
    value['categories'] = [str(item)[:100] for item in book.get('categories', [])[:12]
                           if isinstance(item, str)] if isinstance(book.get('categories'), list) else []
    return value


def _curated(source, book):
    # Solo el texto exacto del corpus original revisado recibe esta licencia;
    # copiar una etiqueta CC0 a una página arbitraria no la autoriza.
    from .literary_knowledge import seed_works, knowledge_sources, ORIGINAL_LICENSE
    if str(source.get('license', '')) != ORIGINAL_LICENSE:
        return None
    for seed in seed_works():
        if not same_work(seed, book):
            continue
        seed = {**seed, 'work_id': stable_work_id(seed['title'], seed['author']),
                'kind': 'book', 'source': 'Conocimiento literario local'}
        for known in knowledge_sources(seed, [dict(fact, work_id=seed['work_id'],
                fact_id=_hash(fact['text']), license=ORIGINAL_LICENSE) for fact in seed['facts']]):
            if (source.get('url') == known.get('url') and source.get('description', '') ==
                    known.get('description', '') and source.get('kind') == known.get('kind')):
                return {**known, 'policy': 'curated-original-v1', 'provider': 'curated',
                        'license': ORIGINAL_LICENSE, 'indexing_authorized': True}
    return None


def _projection(source, book):
    if (not isinstance(source, dict) or source.get('memory_verified') is True
            or source.get('permanent_index_allowed') is False
            or source.get('generated_by') or source.get('llm_generated')
            or str(source.get('source', '')).lower() in {'llm', 'ollama', 'model', 'ia'}):
        return None
    if len(str(source.get('description', ''))) > 6500:
        return None
    url = _public_url(source.get('url'))
    if not url or not same_work(source, book):
        return None
    from .literary_web import public_text_has_injection
    if public_text_has_injection(str(source.get('description', ''))):
        return None
    title, author = book['title'], book['author']
    origin = str(source.get('source', ''))
    if origin == 'Open Library' and _origin(url, 'openlibrary.org') and re.fullmatch(
            r'/works/OL\d+W', urlsplit(url).path) and source.get('kind') == 'book':
        # Nunca conservamos sinopsis, reseñas, portadas o pasajes de OL.
        book = _work(source)
        if not book:
            return None
        body = title + ', de ' + author + '.'
        if book.get('categories'):
            body += '\nTemas del catálogo: ' + ', '.join(book['categories'])
        return {**book, 'url': url, 'description': body,
            'license': 'Open Library bibliographic facts; rights vary',
            'policy': 'openlibrary-minimal-metadata-v1', 'provider': 'openlibrary',
            'read_mode': 'metadatos bibliográficos; no sinopsis ni texto de la obra'}
    if origin == 'Wikidata' and _origin(url, 'www.wikidata.org') and re.fullmatch(
            r'/wiki/Q\d+', urlsplit(url).path) and source.get('license') in {'CC0', 'CC0-1.0'}:
        book = _work(source)
        if not book:
            return None
        description = str(source.get('description', ''))[:1800]
        value = {**book, 'url': url, 'kind': source.get('kind'), 'source': origin,
            'description': description, 'license': 'CC0-1.0', 'policy': 'wikidata-statements-v1',
            'provider': 'wikidata', 'claim_verification': 'declaración de Wikidata; no corroboración independiente'}
        if source.get('kind') == 'web':
            value.update(work_title=title, work_author=author, work_binding_verified=True,
                         author='Fuente web')
        for key in ('character_facts', 'literary_facts'):
            if isinstance(source.get(key), list):
                value[key] = _literal_facts(source[key], description, key)
        return value
    curated = _curated(source, book)
    if curated:
        return curated
    # Wikipedia exige una política explícita del adaptador y atribución
    # verificable a una revisión; el permiso general de extracción no basta.
    attribution = source.get('attribution')
    if (origin == 'Wikipedia' and (urlsplit(url).hostname or '') in
            {'es.wikipedia.org', 'en.wikipedia.org'}
            and source.get('storage_policy') == 'wikipedia-cc-by-sa-4.0-v1'
            and source.get('license') == 'CC-BY-SA-4.0' and isinstance(attribution, dict)
            and attribution.get('authors') == 'Wikipedia contributors'
            and attribution.get('license_url') == 'https://creativecommons.org/licenses/by-sa/4.0/'
            and str(attribution.get('revision_id', '')).isdigit()
            and attribution.get('url') == url and attribution.get('title') == source.get('title')):
        book = _work(source)
        if not book:
            return None
        body = str(source.get('description', ''))[:1800]
        return {**book, 'title': source['title'], 'author': 'Fuente web', 'kind': 'web',
            'source': origin, 'url': url, 'description': body, 'license': 'CC-BY-SA-4.0',
            'policy': 'wikipedia-cc-by-sa-4.0-v1', 'provider': 'wikipedia',
            'attribution': {key: str(attribution[key])[:1800] for key in
                            ('authors', 'title', 'url', 'license_url', 'revision_id') if key in attribution},
            'work_title': title, 'work_author': author, 'work_binding_verified': True,
            'character_facts': _literal_facts(source.get('character_facts', []), body, 'character_facts'),
            'literary_facts': _literal_facts(source.get('literary_facts', []), body, 'literary_facts')}
    return None


def _literal_facts(items, body, kind):
    result = []
    if not isinstance(items, list):
        return result
    normalized_body = normalize_identity(body)
    for item in items[:24]:
        if not isinstance(item, dict):
            continue
        keys = ('name', 'role') if kind == 'character_facts' else (
            'topic', 'subject', 'relation', 'predicate', 'value', 'object', 'evidence', 'scope')
        fact = {key: str(item[key])[:1000] for key in keys if isinstance(item.get(key), str)}
        required = ('name', 'role') if kind == 'character_facts' else ('evidence',)
        if all(fact.get(key) and normalize_identity(fact[key]) in normalized_body for key in required):
            # Explicit subject/relation/value must also occur in the evidence;
            # a valid quote is not permission to attach an unrelated statement.
            if kind == 'literary_facts' and any(normalize_identity(fact[key]) not in
                    normalize_identity(fact['evidence']) for key in ('subject', 'value', 'object')
                    if fact.get(key)):
                continue
            predicate = normalize_identity(fact.get('relation') or fact.get('predicate'))
            if kind == 'literary_facts' and predicate:
                evidence = normalize_identity(fact['evidence'])
                alternatives = {
                    'mother': ('mother', 'madre'), 'madre': ('mother', 'madre'),
                    'father': ('father', 'padre'), 'padre': ('father', 'padre'),
                    'birth': ('birth', 'nacio', 'nace', 'nacimiento'),
                    'death': ('death', 'died', 'muerte', 'muere', 'murio', 'fallece'),
                    'muerte': ('death', 'died', 'muerte', 'muere', 'murio', 'fallece'),
                    'author': ('author', 'autor', 'autora', 'escrito', 'escrita'),
                    'publication': ('publication', 'published', 'publicacion', 'publicado', 'publicada'),
                }.get(predicate, (predicate,))
                # Names co-occurring in a passage do not prove a relationship.
                # Unknown predicates and negated passages stay as raw evidence,
                # never as a positive graph assertion inferred by the model.
                if (not any(re.search(r'(?<!\w)' + re.escape(word) + r'(?!\w)', evidence)
                            for word in alternatives)
                        or re.search(r'\b(?:no|nunca|not|never)\b', evidence)):
                    continue
            result.append(fact)
    return result


def _assertions(value, book):
    result = [(book['title'], 'author', book['author'], 'author',
               {'evidence': book['title'] + ', de ' + book['author'] + '.'})]
    for fact in value.get('character_facts', []):
        result.append((fact['name'], 'role', fact['role'], 'characters', fact))
    for fact in value.get('literary_facts', []):
        predicate = normalize_identity(fact.get('relation') or fact.get('predicate') or fact.get('topic'))
        obj = fact.get('value') or fact.get('object') or fact.get('evidence', '')
        if predicate and obj:
            result.append((fact.get('subject') or book['title'], predicate, obj,
                           fact.get('topic', 'summary'), fact))
    return result


def _conflicts(db, work_id):
    db.execute('DELETE FROM memory_conflicts WHERE work_id=?', (work_id,))
    rows = db.execute('SELECT a.assertion_id,a.subject,a.predicate,a.object_value,a.source_id '
        'FROM memory_assertions a JOIN memory_sources s ON s.source_id=a.source_id '
        'WHERE a.work_id=? AND s.expires_at>?', (work_id, time.time())).fetchall()
    groups = {}
    for row in rows:
        if row['predicate'] in EXCLUSIVE:
            groups.setdefault((normalize_identity(row['subject']), row['predicate']), []).append(row)
    for group in groups.values():
        for index, left in enumerate(group):
            for right in group[index + 1:]:
                if (left['source_id'] != right['source_id'] and
                        normalize_identity(left['object_value']) != normalize_identity(right['object_value'])):
                    pair = sorted([left['assertion_id'], right['assertion_id']])
                    db.execute('INSERT OR IGNORE INTO memory_conflicts VALUES (?,?,?,?,?)',
                        (_hash(*pair), work_id, *pair, 'open'))


def remember_evidence(books, sources, *, database=None):
    """Proyecta datos públicos admitidos; nunca incorpora una respuesta generada."""
    result = {'works': 0, 'sources': 0, 'assertions': 0, 'skipped': 0, 'changed': 0}
    if not isinstance(books, (list, tuple)) or not isinstance(sources, (list, tuple)):
        return result
    candidates = []
    for raw in list(books)[:12]:
        book = _work(raw) if isinstance(raw, dict) else None
        if book:
            for source in list(sources)[:40]:
                projected = _projection(source, book)
                if projected:
                    candidates.append((_work(projected) or book, projected))
    result['skipped'] = max(0, len(sources) - len(candidates))
    if not candidates:
        return result
    now = time.time()
    seen_works = set()
    with _connection(database, write=True) as db:
        for book, value in candidates:
            work_id = book['work_id']
            # Metadata comes only from an admitted structured source, not from
            # unrelated fields on the selected book supplied by the model.
            book = _work(value) or book
            book['work_id'] = work_id
            existing = db.execute('SELECT record FROM memory_works WHERE work_id=?', (work_id,)).fetchone()
            if existing:
                previous_book = json.loads(existing[0])
                # A character passage is not a replacement for edition/catalog
                # metadata. Merge only already-admitted bibliographic fields.
                for key in ('categories', 'isbns', 'confirmed_aliases'):
                    old = previous_book.get(key, [])
                    new = book.get(key, [])
                    book[key] = list({_json(item): item for item in old + new}.values())[:20]
                for key in ('url', 'source', 'year', 'publisher', 'language', 'edition_id'):
                    if previous_book.get(key) and (not book.get(key) or value.get('kind') == 'web'):
                        book[key] = previous_book[key]
            db.execute('INSERT INTO memory_works VALUES (?,?,?,?) ON CONFLICT(work_id) '
                'DO UPDATE SET record=excluded.record', (work_id, normalize_identity(book['title']),
                normalize_identity(book['author']), _json(book)))
            for alias in [book['title']] + [item['title'] for item in book.get('confirmed_aliases', [])]:
                db.execute('INSERT OR IGNORE INTO memory_aliases VALUES (?,?,?)',
                    (normalize_identity(alias), normalize_identity(book['author']), work_id))
            source_id = _hash(work_id, value['provider'], value['url'], value.get('kind', 'book'))
            value['work_id'] = work_id
            if value.get('kind') == 'web':
                value.update(work_title=book['title'], work_author=book['author'])
            digest = _hash(_json(value))
            previous = db.execute('SELECT content_hash,record,retrieved_at FROM memory_sources '
                                  'WHERE source_id=?', (source_id,)).fetchone()
            if previous and previous['content_hash'] != digest:
                db.execute('INSERT OR IGNORE INTO memory_history VALUES (?,?,?,?,?,?)',
                    (_hash(source_id, previous['content_hash']), source_id, work_id,
                     previous['retrieved_at'], previous['content_hash'], previous['record']))
            ttl = 30 * 86400 if value['provider'] in {'curated', 'openlibrary'} else 7 * 86400
            db.execute('INSERT INTO memory_sources VALUES (?,?,?,?,?,?,?,?,?,?) '
                'ON CONFLICT(source_id) DO UPDATE SET policy=excluded.policy,'
                'retrieved_at=excluded.retrieved_at,verified_at=excluded.verified_at,'
                'expires_at=excluded.expires_at,content_hash=excluded.content_hash,record=excluded.record',
                (source_id, work_id, value['provider'], value['url'], value['policy'],
                 now, now, now + ttl, digest, _json(value)))
            if not previous or previous['content_hash'] != digest:
                result['changed'] += 1
                db.execute('DELETE FROM memory_assertions WHERE source_id=?', (source_id,))
                for subject, predicate, obj, topic, record in _assertions(value, book):
                    aid = _hash(source_id, subject, predicate, obj)
                    db.execute('INSERT OR IGNORE INTO memory_assertions VALUES (?,?,?,?,?,?,?,?)',
                        (aid, work_id, source_id, subject, predicate, obj, topic, _json(record)))
                    result['assertions'] += 1
                    if predicate == 'role':
                        db.execute('INSERT OR REPLACE INTO memory_entities VALUES (?,?,?,?,?)',
                            (_hash(work_id, 'character', normalize_identity(subject)), work_id,
                             'character', subject, _json({'name': subject})))
                if db.execute("SELECT value FROM memory_meta WHERE key='fts'").fetchone()[0] == '1':
                    db.execute('DELETE FROM memory_fts WHERE source_id=?', (source_id,))
                    db.execute('INSERT INTO memory_fts VALUES (?,?,?,?,?)',
                        (source_id, work_id, book['title'], book['author'], value['description']))
            entity_values = [('work', book['title']), ('author', book['author'])]
            entity_values += [('isbn', isbn) for isbn in book.get('isbns', [])]
            entity_values += [('genre', name) for name in book.get('categories', [])]
            entity_values += [(key, book[key]) for key in ('publisher', 'edition_id') if book.get(key)]
            for entity_type, label in entity_values:
                db.execute('INSERT OR REPLACE INTO memory_entities VALUES (?,?,?,?,?)',
                    (_hash(work_id, entity_type, label), work_id, entity_type, label, '{}'))
            seen_works.add(work_id)
            result['sources'] += 1
        for work_id in seen_works:
            _conflicts(db, work_id)
            # Removing a character from a refreshed snapshot must not leave a
            # detached historical entity looking current to future graph readers.
            db.execute("DELETE FROM memory_entities WHERE work_id=? AND entity_type='character'", (work_id,))
            characters = db.execute("SELECT DISTINCT a.subject FROM memory_assertions a "
                "JOIN memory_sources s ON s.source_id=a.source_id WHERE a.work_id=? "
                "AND a.predicate='role' AND s.expires_at>?", (work_id, now)).fetchall()
            for character in characters:
                label = character[0]
                db.execute('INSERT OR IGNORE INTO memory_entities VALUES (?,?,?,?,?)',
                    (_hash(work_id, 'character', normalize_identity(label)), work_id,
                     'character', label, _json({'name': label})))
        result['works'] = len(seen_works)
        # Also invalidates TTL-sensitive cached reads after a re-verification.
        _bump(db)
    return result


def get_work(work_id, *, database=None):
    with _connection(database) as db:
        if db is None:
            return None
        row = db.execute('SELECT record FROM memory_works WHERE work_id=?', (str(work_id),)).fetchone()
        return dict(json.loads(row[0]), memory_verified=True) if row else None


def list_works(*, database=None, limit=100):
    with _connection(database) as db:
        if db is None:
            return []
        return [dict(json.loads(row[0]), memory_verified=True) for row in db.execute('SELECT record FROM memory_works '
            'ORDER BY work_id LIMIT ?', (max(1, min(int(limit), 1000)),))]


def _current_source(db, source_id, now, expected_hash=''):
    row = db.execute('SELECT * FROM memory_sources WHERE source_id=? AND expires_at>?',
                     (str(source_id), now)).fetchone()
    if not row or (expected_hash and str(expected_hash) != row['content_hash']):
        return None
    conflict = db.execute('SELECT 1 FROM memory_conflicts c JOIN memory_assertions a '
        'ON a.assertion_id=c.assertion_a OR a.assertion_id=c.assertion_b '
        'JOIN memory_assertions b ON b.assertion_id=c.assertion_a OR b.assertion_id=c.assertion_b '
        'JOIN memory_sources s ON s.source_id=b.source_id '
        "WHERE c.status='open' AND a.source_id=? AND s.expires_at>? AND b.source_id<>a.source_id LIMIT 1",
        (str(source_id), now)).fetchone()
    if conflict:
        return None
    source = json.loads(row['record'])
    source.update(memory_source_id=row['source_id'], content_hash=row['content_hash'],
                  evidence_hash=row['content_hash'], retrieved_at=row['retrieved_at'],
                  last_verified_at=row['verified_at'], expires_at=row['expires_at'],
                  memory_verified=True, trust='untrusted_data')
    return source


def get_current_source(source_id, expected_hash='', *, database=None):
    """Revalida un fragmento de RAG contra su snapshot, TTL y contradicciones."""
    with _connection(database) as db:
        return _current_source(db, source_id, time.time(), expected_hash) if db else None


def export_index_sources(*, database=None, limit=5000):
    """Inventario autorizado y determinista para el índice auxiliar, sin HTTP.

    Cada documento conserva licencia, atribución y hash del snapshot. La mera
    exportación no renueva su verificación ni lo convierte en una novela.
    """
    with _connection(database) as db:
        if db is None:
            return []
        now = time.time()
        rows = db.execute('SELECT source_id FROM memory_sources WHERE expires_at>? '
            'ORDER BY source_id LIMIT ?', (now, max(1, min(int(limit), 5000)))).fetchall()
        result = []
        for row in rows:
            source = _current_source(db, row[0], now)
            if source:
                result.append(source)
        return result


def retrieve_evidence(query, *, books=(), requirement='', database=None, limit=8):
    """Recuperación local sin HTTP/LLM; nunca devuelve fuentes caducadas o en conflicto."""
    if requirement not in REQUIREMENTS:
        return [], []
    limit = max(1, min(int(limit), 20))
    with _connection(database) as db:
        if db is None:
            return [], []
        identifiers = []
        for raw in list(books)[:12]:
            identity = work_identity(raw) if isinstance(raw, dict) else None
            if not identity:
                continue
            matches = db.execute('SELECT work_id FROM memory_aliases WHERE title_key=? AND author_key=?',
                (normalize_identity(identity['title']), normalize_identity(identity['author']))).fetchall()
            identifiers.extend(row[0] for row in matches)
            identifiers.append(stable_work_id(identity['title'], identity['author']))
        if identifiers:
            rows = db.execute('SELECT source_id FROM memory_sources WHERE work_id IN (' +
                ','.join('?' for _ in identifiers) + ') ORDER BY verified_at DESC LIMIT 80', identifiers).fetchall()
        else:
            terms = re.findall(r'\w{3,}', normalize_identity(query))[:24]
            if not terms:
                return [], []
            fts = db.execute("SELECT value FROM memory_meta WHERE key='fts'").fetchone()[0] == '1'
            if fts:
                expression = ' OR '.join('"' + term + '"' for term in terms)
                rows = db.execute('SELECT source_id FROM memory_fts WHERE memory_fts MATCH ? '
                    'ORDER BY bm25(memory_fts,0,0,5,3,1) LIMIT 40', (expression,)).fetchall()
            else:
                rows = db.execute('SELECT s.source_id FROM memory_sources s JOIN memory_works w '
                    'ON w.work_id=s.work_id WHERE w.title_key=? ORDER BY s.verified_at DESC LIMIT 40',
                    (normalize_identity(query),)).fetchall()
        returned, found, selected = [], {}, set()
        now = time.time()
        for row in rows:
            sid = row[0]
            if sid in selected:
                continue
            selected.add(sid)
            source = _current_source(db, sid, now)
            if not source:
                continue
            # Keep original provenance; being cached is not a new publisher.
            returned.append(source)
            work = db.execute('SELECT record FROM memory_works WHERE work_id=?',
                              (source['work_id'],)).fetchone()
            if work:
                found[source['work_id']] = dict(json.loads(work[0]), memory_verified=True)
            if len(returned) >= limit:
                break
        return list(found.values()), returned


def _category(requirement, provider=''):
    if requirement not in REQUIREMENTS or provider not in PROVIDERS | {'', 'curated', 'wikipedia'}:
        raise ValueError('Categoría bibliográfica no admitida; no se guardan consultas')


def enqueue_refresh(work_id, requirement='', provider='openlibrary', *, priority=0, database=None):
    _category(requirement, provider)
    if provider not in PROVIDERS:
        raise ValueError('Proveedor de actualización no autorizado')
    with _connection(database, write=True) as db:
        work = db.execute('SELECT record FROM memory_works WHERE work_id=?', (str(work_id),)).fetchone()
        if not work:
            raise ValueError('Solo se programan identidades bibliográficas conocidas')
        payload = json.loads(work[0])
        payload = {key: payload[key] for key in ('title', 'author')}
        jid = _hash(work_id, requirement, provider)
        db.execute('INSERT INTO memory_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) '
            'ON CONFLICT(work_id,requirement,provider) DO UPDATE SET '
            'priority=MAX(priority,excluded.priority),'
            "status=CASE WHEN status='done' THEN 'pending' ELSE status END,"
            "not_before=CASE WHEN status='done' THEN excluded.not_before ELSE not_before END",
            (jid, work_id, requirement, provider, max(-10, min(int(priority), 100)), 'pending', 0,
             time.time(), 0, '', '', '', _json(payload)))
        return jid


def claim_job(worker_id, *, lease_seconds=60, database=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', str(worker_id)):
        raise ValueError('Identificador técnico del trabajador inválido')
    with _connection(database, write=True) as db:
        db.execute('BEGIN IMMEDIATE')
        now = time.time()
        if db.execute("SELECT 1 FROM memory_jobs WHERE status='running' AND lease_until>? LIMIT 1",
                      (now,)).fetchone():
            return None
        row = db.execute("SELECT * FROM memory_jobs WHERE (status='pending' AND not_before<=?) "
            "OR (status='running' AND lease_until<=?) ORDER BY priority DESC,not_before,job_id LIMIT 1",
            (now, now)).fetchone()
        if not row:
            return None
        token = uuid.uuid4().hex
        db.execute("UPDATE memory_jobs SET status='running',attempts=attempts+1,lease_until=?,"
            'lease_token=?,worker_id=? WHERE job_id=?',
            (now + max(1, min(int(lease_seconds), 300)), token, worker_id, row['job_id']))
        result = dict(row)
        result.update(id=row['job_id'], status='running', attempts=row['attempts'] + 1,
                      lease_token=token, worker_id=worker_id, payload=json.loads(row['payload']))
        return result


def finish_job(job_id, *, lease_token='', database=None):
    with _connection(database, write=True) as db:
        return bool(db.execute("UPDATE memory_jobs SET status='done',lease_until=0,lease_token='',"
            "worker_id='',last_error='' WHERE job_id=? AND status='running' AND lease_token=? "
            'AND lease_until>?', (str(job_id), str(lease_token), time.time())).rowcount)


def fail_job(job_id, *, lease_token='', retry_after=60, error_code='unavailable', database=None):
    if error_code not in ERRORS:
        raise ValueError('Solo se guardan códigos técnicos de error')
    with _connection(database, write=True) as db:
        return bool(db.execute("UPDATE memory_jobs SET status='pending',not_before=?,lease_until=0,"
            "lease_token='',worker_id='',last_error=? WHERE job_id=? AND status='running' "
            'AND lease_token=? AND lease_until>?',
            (time.time() + max(1, min(int(retry_after), 86400)), error_code,
             str(job_id), str(lease_token), time.time())).rowcount)


def record_use(work_id, requirement, outcome, *, provider='', latency=0, database=None):
    _category(requirement, provider)
    if outcome not in OUTCOMES:
        raise ValueError('La señal debe ser un resultado técnico verificado')
    with _connection(database, write=True) as db:
        if not db.execute('SELECT 1 FROM memory_works WHERE work_id=?', (str(work_id),)).fetchone():
            return False
        elapsed = max(0., min(float(latency), 600.))
        db.execute('INSERT INTO memory_usage VALUES (?,?,?,?,?,?,?) '
            'ON CONFLICT(work_id,requirement,provider) DO UPDATE SET hits=hits+excluded.hits,'
            'verified=verified+excluded.verified,failures=failures+excluded.failures,'
            'total_latency=total_latency+excluded.total_latency',
            (work_id, requirement, provider, int(outcome in {'hit', 'verified'}),
             int(outcome == 'verified'), int(outcome in {'failed', 'miss'}), elapsed))
        return True


def usage_stats(database=None):
    with _connection(database) as db:
        if db is None:
            return []
        return [dict(row) for row in db.execute('SELECT * FROM memory_usage ORDER BY '
                                               'verified DESC,hits DESC,work_id LIMIT 1000')]


def delete_usage(database=None):
    with _connection(database) as db:
        if db is None:
            return 0
    with _connection(database, write=True) as db:
        return db.execute('DELETE FROM memory_usage').rowcount
