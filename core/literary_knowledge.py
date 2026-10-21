"""Fichas factuales locales: procedencia verificable, sin copiar novelas.

La base es independiente de Django y no precisa migraciones. Solo se guardan
metadatos y redacciones originales autorizadas explícitamente; una página
recuperada durante una conversación nunca se incorpora automáticamente.
"""
import hashlib
import ipaddress
import json
import math
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlsplit

from .literary_identity import normalize_identity, stable_work_id, confirmed_aliases


STOPWORDS = set('el la los las un una unos unas de del en y o a al con por para '
    'que como quien cual cuales donde sobre es era hay tiene tenia vive vivia '
    'libro libros obra obras recuerdo recuerdo recordar busco buscaba dime '
    'dame cuenta cuentame explica explicame personajes personaje sucede paso '
    'pasaba pasa menciona mencionaba pregunta quiero saber sus su este esta '
    'ese esa se le lo me mi pero muy mas todos'.split())
ORIGINAL_LICENSE = 'CC0-1.0 (redacción factual original de LitMate; no licencia de la obra ni de las páginas citadas)'


def _path(database=None, config=None):
    if database is not None:
        return Path(database).resolve()
    if config is None:
        from django.conf import settings
        config = settings
    return Path(getattr(config, 'LITMATE_KNOWLEDGE_DB',
        Path(config.BASE_DIR) / 'data' / 'litmate_knowledge.sqlite3')).resolve()


def knowledge_revision(config=None, *, database=None):
    path = _path(database, config)
    try:
        revision = path.stat()
        return f'{path}:{revision.st_mtime_ns}:{revision.st_size}'
    except FileNotFoundError:
        return str(path) + ':sin-fichas'


def _public_reference(value):
    """Solo formato de referencia; las descargas aplican el guardián HTTP."""
    try:
        parts = urlsplit(str(value or ''))
        host = (parts.hostname or '').lower().rstrip('.')
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            pass
        return bool(parts.scheme == 'https' and parts.hostname and '.' in parts.hostname
                    and not parts.username and not parts.password and parts.port in {None, 443}
                    and len(value) <= 1800)
    except (TypeError, ValueError):
        return False


def _schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS knowledge_works ('
        'work_id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL, '
        'record TEXT NOT NULL, updated_at TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS knowledge_facts ('
        'fact_id TEXT PRIMARY KEY, work_id TEXT NOT NULL, topic TEXT NOT NULL, '
        'record TEXT NOT NULL, FOREIGN KEY(work_id) REFERENCES knowledge_works(work_id) ON DELETE CASCADE)')
    db.execute('CREATE INDEX IF NOT EXISTS knowledge_fact_work ON knowledge_facts(work_id)')


def _validated_work(work):
    if not isinstance(work, dict):
        raise ValueError('La ficha debe ser un objeto')
    title, author = (str(work.get(key, '')).strip() for key in ('title', 'author'))
    if not title or not author or len(title) > 220 or len(author) > 220:
        raise ValueError('La ficha necesita título y autor completos')
    source_url = str(work.get('url') or work.get('source_url') or '')
    if not _public_reference(source_url):
        raise ValueError('La ficha necesita una referencia HTTPS pública')
    value = {key: work[key] for key in ('description', 'isbns', 'year', 'image_url',
        'categories', 'confirmed_aliases', 'license', 'provenance', 'source_title') if key in work}
    value.update(title=title, author=author, url=source_url, source='Conocimiento literario local',
                 kind='book', work_id=str(work.get('work_id') or stable_work_id(title, author))[:180])
    value['description'] = str(value.get('description', ''))[:4500]
    value['confirmed_aliases'] = confirmed_aliases(value)
    value['license'] = str(value.get('license') or '')[:500]
    if not value['license'] or work.get('indexing_authorized') is not True:
        raise ValueError('La indexación permanente requiere autorización y procedencia')
    value['indexing_authorized'] = True
    return value


def remember_work(work, *, database=None):
    """Actualiza solo la ficha recibida; reemplaza sus hechos de forma atómica.

    No acepta resultados web arbitrarios como autorización. El llamador debe
    aportar redacción y licencia para almacenamiento permanente. No realiza HTTP.
    """
    value = _validated_work(work)
    facts = []
    raw_facts = work.get('facts', [])
    if not isinstance(raw_facts, list) or len(raw_facts) > 100:
        raise ValueError('Demasiados datos en una ficha')
    for item in raw_facts:
        if not isinstance(item, dict):
            raise ValueError('Dato factual inválido')
        text, url = str(item.get('text', '')).strip(), str(item.get('source_url', ''))
        if not text or len(text) > 4500 or not _public_reference(url):
            raise ValueError('Cada dato necesita texto acotado y referencia HTTPS')
        topic = str(item.get('topic', 'summary'))[:60]
        fact = {key: item[key] for key in ('character_facts', 'keywords', 'source_title',
                'scope', 'provenance', 'conflicts_with') if key in item}
        fact.update(text=text, source_url=url, topic=topic, license=value['license'],
            work_id=value['work_id'], recorded_at=datetime.now(timezone.utc).isoformat())
        identity = '\0'.join((value['work_id'], topic, normalize_identity(text), url))
        fact['fact_id'] = hashlib.sha256(identity.encode()).hexdigest()[:32]
        facts.append(fact)
    path = _path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        db.execute('PRAGMA foreign_keys=ON')
        _schema(db)
        db.execute('INSERT INTO knowledge_works VALUES (?,?,?,?,?) ON CONFLICT(work_id) '
            'DO UPDATE SET title=excluded.title,author=excluded.author,record=excluded.record,'
            'updated_at=excluded.updated_at', (value['work_id'], value['title'], value['author'],
            json.dumps(value, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
        db.execute('DELETE FROM knowledge_facts WHERE work_id=?', (value['work_id'],))
        db.executemany('INSERT OR IGNORE INTO knowledge_facts VALUES (?,?,?,?)', [
            (fact['fact_id'], value['work_id'], fact['topic'], json.dumps(fact, ensure_ascii=False))
            for fact in facts])
    return value


def _records(database=None):
    path = _path(database)
    if not path.is_file():
        return [], []
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            works = [json.loads(row[0]) for row in db.execute(
                'SELECT record FROM knowledge_works ORDER BY work_id LIMIT 5000')]
            facts = [json.loads(row[0]) for row in db.execute(
                'SELECT record FROM knowledge_facts ORDER BY fact_id LIMIT 30000')]
        return works, facts
    except (sqlite3.Error, ValueError, TypeError):
        return [], []


def lookup_work(title='', author='', *, work_id='', database=None):
    """Solo identidad exacta o alias bibliográfico confirmado; nunca similitud."""
    works, _ = _records(database)
    matches = []
    wanted, writer = normalize_identity(title), normalize_identity(author)
    for work in works:
        if work_id:
            if work.get('work_id') == work_id:
                return work
            continue
        titles = {normalize_identity(work['title'])} | {
            normalize_identity(alias['title']) for alias in work.get('confirmed_aliases', [])}
        if wanted and wanted in titles and (not writer or writer == normalize_identity(work['author'])):
            matches.append(work)
    return matches[0] if len(matches) == 1 else None


def lookup_facts(work_id='', *, database=None, topic='', maximum=20):
    if not work_id:
        return []
    _, facts = _records(database)
    return [fact for fact in facts if fact['work_id'] == work_id
            and (not topic or fact.get('topic') == topic)][:max(1, min(int(maximum), 100))]


def _terms(text):
    return list(dict.fromkeys(term for term in normalize_identity(text).split()
                             if len(term) >= 3 and term not in STOPWORDS))[:32]


def _score(query, work, facts):
    text = normalize_identity(query)
    titles = [normalize_identity(work['title'])] + [normalize_identity(alias['title'])
        for alias in work.get('confirmed_aliases', [])]
    exact = any(re.search(r'(?<!\w)' + re.escape(title) + r'(?!\w)', text) for title in titles)
    terms = _terms(query)
    words = set(_terms(' '.join([work['title'], work['author'], work.get('description', '')]
        + [fact['text'] + ' ' + ' '.join(fact.get('keywords', [])) for fact in facts])))
    hits = []
    for term in terms:
        if term in words:
            hits.append(term)
        elif len(term) >= 6 and any(len(word) >= 6 and abs(len(word) - len(term)) <= 2
                and SequenceMatcher(None, term, word).ratio() >= .87 for word in words):
            hits.append(term)
    # Una pista genérica aislada (mujer, viaje, bosque) no identifica una obra.
    proper_words = set(_terms(work['title'] + ' ' + work['author']))
    entity_words = {normalize_identity(character.get('name', '')) for fact in facts
        for character in fact.get('character_facts', []) if isinstance(character, dict)}
    named = any(len(term) >= 6 and term not in proper_words and any(
        SequenceMatcher(None, term, entity).ratio() >= .87 for entity in entity_words) for term in hits)
    if not exact and len(hits) < 2 and not named:
        return 0
    return (20 if exact else 0) + sum(1 + math.log2(1 + len(term)) / 4 for term in hits)


def knowledge_sources(work, facts):
    """Devuelve metadatos + evidencia web, sin convertir resúmenes en novela."""
    result = [dict(work)]
    grouped = {}
    for fact in facts:
        grouped.setdefault(fact['source_url'], []).append(fact)
    for url, group in grouped.items():
        characters = [character for fact in group for character in fact.get('character_facts', [])]
        body = '\n'.join(fact['text'] for fact in group)
        body += ''.join('\n' + character['name'] + ': ' + character['role']
                        for character in characters if character.get('name') and character.get('role'))
        result.append({'title': group[0].get('source_title') or work.get('source_title') or work['title'],
            'author': 'Fuente web', 'kind': 'web', 'source': 'Conocimiento literario local',
            'url': url, 'description': body[:6500],
            'read_mode': 'resumen factual original con procedencia; no texto de la novela',
            'license': work['license'], 'work_id': work['work_id'], 'work_title': work['title'],
            'work_author': work['author'], 'work_binding_verified': True,
            'confirmed_aliases': work.get('confirmed_aliases', []), 'character_facts': characters,
            'character_scope': 'partial', 'fact_topics': sorted({fact['topic'] for fact in group}),
            'literary_facts': [{'topic': fact['topic'], 'evidence': fact['text'],
                'subject': work['title']} for fact in group],
            'fact_ids': [fact['fact_id'] for fact in group], 'complete_work': False})
    return result


def search_knowledge(query, maximum=5, *, database=None, work_id=None):
    works, facts = _records(database)
    related = {work['work_id']: [fact for fact in facts if fact['work_id'] == work['work_id']]
               for work in works if not work_id or work['work_id'] == work_id}
    ranked = []
    for work in works:
        if work['work_id'] not in related:
            continue
        score = _score(query, work, related[work['work_id']])
        if score > 0 or work_id:
            ranked.append((score, work))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]['title']))
    result = []
    maximum = max(1, min(int(maximum), 12))
    for _, work in ranked[:3]:
        result.extend(knowledge_sources(work, related[work['work_id']]))
        if len(result) >= maximum:
            break
    return result[:maximum]


def search_knowledge_semantic(query, maximum=3, *, config=None, embedder=None,
                              work_id=None, database=None):
    """Reutiliza el índice híbrido local con procedencia factual, nunca novela."""
    if config is None:
        from django.conf import settings
        config = settings
    index = Path(database or getattr(config, 'LITMATE_KNOWLEDGE_RAG_DB',
        Path(config.BASE_DIR) / 'data' / 'litmate_knowledge_rag.sqlite3'))
    if not index.is_file():
        return []
    if embedder is None:
        from .local_embeddings import configured_embedder
        embedder = configured_embedder(config)
    from .local_rag import retrieve_fragments
    books = None
    if work_id:
        work = lookup_work(work_id=work_id, database=getattr(config, 'LITMATE_KNOWLEDGE_DB', None))
        if not work:
            return []
        books = [work]
    return [source for source in retrieve_fragments(query, index, maximum,
        embedder=embedder, book_identities=books) if source.get('kind') in {'book', 'web'}]


def seed_works():
    """Redacciones originales breves verificadas el 15-10-2026.

    CC0 se aplica solo a esta redacción. No redistribuye portadas, novelas,
    sinopsis editoriales ni páginas completas. Las referencias no conceden
    derechos sobre el contenido de los sitios citados.
    """
    papelucho = 'https://literaturasm.cl/diario-secreto-de-papelucho-y-el-marciano/'
    prince = 'https://www.lepetitprince.com/loeuvre/'
    farm = 'https://www.penguin.co.uk/books/57033/animal-farm-by-orwell-george/9780141393056'
    crime = 'https://www.penguinlibros.com/es/libros-clasicos/365707-libro-crimen-y-castigo-9788491057314'
    return [
        {'title': 'Diario secreto de Papelucho y el marciano', 'author': 'Marcela Paz',
         'url': papelucho, 'isbns': ['9789563495768', '9789563634136'],
         'confirmed_aliases': [{'title': 'Papelucho y el marciano',
             'source_url': 'https://ci.nii.ac.jp/ncid/BA64258717',
             'evidence': 'El catálogo bibliográfico CiNii registra Diario secreto de Papelucho y el Marciano, de Marcela Paz, y Papelucho y el Marciano como Other Title.'}],
         'description': 'Papelucho relata su convivencia con Det, un amigo extraterrestre. Su amistad combina dificultades cotidianas con la posibilidad de conocer otros mundos.',
         'facts': [{'topic': 'characters', 'source_url': papelucho, 'scope': 'partial',
             'text': 'En Diario secreto de Papelucho y el marciano, de Marcela Paz, Papelucho cuenta cómo convive con Det. Det es su amigo de otro planeta; esa convivencia provoca problemas y enfados, y abre la posibilidad de viajar a otros mundos.',
             'keywords': ['niño', 'marciano', 'extraterrestre', 'Det', 'Papelucho'],
             'character_facts': [{'name': 'Papelucho', 'role': 'Narra su convivencia con Det.'},
                 {'name': 'Det', 'role': 'Amigo extraterrestre de Papelucho, cuya convivencia causa dificultades y permite imaginar viajes a otros mundos.'}]},
            {'topic': 'relationships', 'source_url': papelucho, 'scope': 'partial',
             'text': 'La convivencia de Papelucho con Det provoca problemas y enfados y ofrece la posibilidad de viajar a otros mundos.',
             'keywords': ['Det', 'convivencia', 'problemas', 'viajes']}],
         'license': ORIGINAL_LICENSE, 'indexing_authorized': True},
        {'title': 'El principito', 'author': 'Antoine de Saint-Exupéry',
         'url': 'https://es.literaturasm.com/personaje/principito',
         'description': 'Un niño procede de un planeta diminuto, cuida una rosa y viaja por otros mundos. En la Tierra conoce a un zorro y a un aviador.',
         'facts': [{'topic': 'identification', 'source_url': prince,
             'text': 'El principito, de Antoine de Saint-Exupéry, trata de un niño que vive en un planeta muy pequeño y se siente responsable de una rosa. Visita otros planetas. En la Tierra entabla amistad con un zorro y encuentra a un aviador en el desierto del Sahara.',
             'keywords': ['niño', 'planeta', 'pequeño', 'diminuto', 'rosa', 'flor', 'zorro', 'aviador', 'cuida', 'cuidaba'],
             'character_facts': [{'name': 'El principito', 'role': 'Niño viajero que cuida una rosa en su pequeño planeta.'},
                 {'name': 'El zorro', 'role': 'Amigo que el principito conoce en la Tierra.'},
                 {'name': 'El aviador', 'role': 'Encuentra al principito en el Sahara.'}]}],
         'license': ORIGINAL_LICENSE, 'indexing_authorized': True},
        {'title': 'Rebelión en la granja', 'author': 'George Orwell',
         'url': 'https://www.penguinlibros.com/es/literatura-contemporanea/24583-ebook-rebelion-en-la-granja-edicion-definitiva-avalada-por-the-orwell-estate-9788490325087',
         'description': 'Los animales de una granja se rebelan contra su dueño. El proyecto de igualdad deriva en una nueva dominación dirigida por los cerdos.',
         'facts': [{'topic': 'identification', 'source_url': farm,
             'text': 'Rebelión en la granja, de George Orwell, se publicó originalmente como Animal Farm. Los animales expulsan al granjero con un ideal de libertad e igualdad, pero los cerdos concentran el poder. La idea recordada de que todos los animales son iguales pertenece a esta obra; aquí se parafrasea, sin establecer una traducción textual, página o edición española.',
             'keywords': ['animales', 'iguales', 'igualdad', 'granja', 'rebelión', 'cerdos', 'frase', 'decían']}],
         'license': ORIGINAL_LICENSE, 'indexing_authorized': True},
        {'title': 'Crimen y castigo', 'author': 'Fiódor M. Dostoievski', 'url': crime,
         'isbns': ['9788491057314'],
         'description': 'El estudiante Raskólnikov comete un asesinato y afronta una intensa culpa. La novela explora sus justificaciones y el conflicto moral que sigue al crimen.',
         'facts': [{'topic': 'characters', 'source_url': crime,
             'text': 'Raskólnikov es el joven estudiante protagonista de Crimen y castigo, de Fiódor M. Dostoievski. Su justificación de un asesinato y la culpa posterior constituyen el conflicto descrito por la ficha editorial.',
             'keywords': ['Raskólnikov', 'Raskolnikov', 'Raskolnikof', 'estudiante', 'culpa'],
             'character_facts': [{'name': 'Raskólnikov', 'role': 'Estudiante protagonista que comete un asesinato y sufre culpa.'}]}],
         'license': ORIGINAL_LICENSE, 'indexing_authorized': True},
    ]


def prepare_seed_knowledge(database=None):
    """Actualiza estas cuatro fichas; no elimina fichas ajenas."""
    works = []
    for work in seed_works():
        existing = lookup_work(work['title'], work['author'], database=database)
        if existing and existing.get('provenance') != 'litmate_seed_v1':
            # Una ficha aportada manualmente con la misma identidad prevalece.
            works.append(existing)
            continue
        work['provenance'] = 'litmate_seed_v1'
        works.append(remember_work(work, database=database))
    return works
