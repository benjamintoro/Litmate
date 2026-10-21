"""Identidad de obras basada en metadatos; la similitud no demuestra equivalencia.

Las marcas ``work_binding_verified`` se asignan dentro de los recuperadores,
nunca a partir de instrucciones o atributos de una página remota.
"""
import hashlib
import re
import unicodedata
from urllib.parse import urlsplit


BIBLIOGRAPHIC_ORIGINS = {
    'Google Books API', 'Catálogo LitMate', 'Open Library', 'Wikidata',
    'Conocimiento literario local', 'Biblioteca literaria local',
}
IDENTITY_DOMAINS = (
    'openlibrary.org', 'wikidata.org', 'books.google.com', 'books.google.es',
    'memoriachilena.gob.cl', 'bibliotecanacionaldigital.gob.cl', 'bnchile.gob.cl',
    'literaturasm.cl', 'literaturasm.com', 'penguinlibros.com',
    'planetadelibros.com', 'anagrama-ed.es', 'fce.com.mx', 'cervantesvirtual.com',
    'ci.nii.ac.jp',
)
UNKNOWN_AUTHORS = {'', 'autor no informado', 'autor desconocido', 'fuente web'}


def normalize_identity(value):
    value = ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').casefold())
                    if not unicodedata.combining(c))
    return re.sub(r'\W+', ' ', value).strip()


def same_author_name(first, second):
    """Tolera orden bibliográfico invertido, conservando todos los nombres.

    No equipara un apellido suelto, iniciales distintas ni nombres parciales.
    La inversión no aporta un alias de título ni identifica otra obra.
    """
    left, right = normalize_identity(first), normalize_identity(second)
    if not left or not right or left in UNKNOWN_AUTHORS or right in UNKNOWN_AUTHORS:
        return False
    if left == right:
        return True
    return len(left.split()) >= 2 and sorted(left.split()) == sorted(right.split())


def stable_work_id(title, author):
    value = normalize_identity(title) + '\0' + normalize_identity(author)
    return 'litmate:' + hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]


def _identity_url(value):
    try:
        parts = urlsplit(str(value or ''))
        host = (parts.hostname or '').lower().rstrip('.')
        return (parts.scheme == 'https' and not parts.username and not parts.password
                and parts.port in {None, 443}
                and any(host == domain or host.endswith('.' + domain) for domain in IDENTITY_DOMAINS))
    except (ValueError, TypeError):
        return False


def _known_origin(source):
    origins = str(source.get('source', '')).split(' / ')
    return any(origin in BIBLIOGRAPHIC_ORIGINS for origin in origins) or _identity_url(source.get('url'))


def _literal_title(title):
    """Quita etiquetas de documento, nunca partes del título de una saga."""
    title = re.sub(r'(?i)^anexo\s*:\s*personajes\s+de\s+', '', str(title or ''))
    return re.sub(r'(?i)\s*\((?:novela|novel|libro|book)\)\s*$', '', title).strip()


def confirmed_aliases(source):
    """Solo devuelve variantes con procedencia y ambos títulos en la prueba."""
    if not isinstance(source, dict) or not _known_origin(source):
        return []
    canonical = normalize_identity(source.get('work_title') or source.get('title'))
    author = normalize_identity(source.get('work_author') or source.get('author'))
    aliases, seen = [], set()
    values = source.get('confirmed_aliases', [])
    for item in values[:20] if isinstance(values, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title', '')).strip()[:220]
        alias = normalize_identity(title)
        evidence = str(item.get('evidence', '')).strip()[:1500]
        literal = normalize_identity(evidence)
        url = str(item.get('source_url', '')).strip()[:1500]
        stated_author = normalize_identity(item.get('author'))
        if (not alias or alias == canonical or alias in seen or not _identity_url(url)
                or not canonical or canonical not in literal or alias not in literal
                or (stated_author and stated_author != author)):
            continue
        seen.add(alias)
        aliases.append({'title': title, 'source_url': url, 'evidence': evidence})
    return aliases


def _isbn_values(source):
    values = source.get('isbns', [])
    identifiers = set()
    for value in values[:12] if isinstance(values, list) else []:
        value = re.sub(r'[^\dXx]', '', str(value)).upper()
        if len(value) == 13 and value.isdigit():
            valid = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(value)) % 10 == 0
        elif len(value) == 10 and value[:9].isdigit() and value[-1] in '0123456789X':
            valid = sum((10 if c == 'X' else int(c)) * (10 - i) for i, c in enumerate(value)) % 11 == 0
        else:
            valid = False
        if valid:
            identifiers.add(value)
    return sorted(identifiers)


def work_identity(source):
    """Normaliza metadatos internos sin confundir autor de página y autor de obra."""
    if not isinstance(source, dict):
        return {}
    bound = source.get('work_binding_verified') is True
    title = str((source.get('work_title') if bound else source.get('title')) or '').strip()[:220]
    author = str((source.get('work_author') if bound else source.get('author')) or '').strip()[:220]
    if not title or normalize_identity(author) in UNKNOWN_AUTHORS:
        return {}
    identifier = str(source.get('work_id', '')).strip()[:180]
    if not identifier or not (bound or _known_origin(source)):
        identifier = stable_work_id(title, author)
    identity = {'work_id': identifier, 'title': _literal_title(title), 'author': author,
                'confirmed_aliases': confirmed_aliases(source), 'isbns': _isbn_values(source)}
    # El historial vuelve a normalizar estas identidades. Conserva únicamente
    # la procedencia bibliográfica ya admitida, para que ese recorrido no borre
    # alias comprobados. Nunca promueve la URL o etiqueta de una página ajena.
    origins = [origin for origin in str(source.get('source', '')).split(' / ')
               if origin in BIBLIOGRAPHIC_ORIGINS]
    if origins:
        identity['source'] = ' / '.join(dict.fromkeys(origins))
    if _identity_url(source.get('url')):
        identity['url'] = str(source['url']).strip()[:1500]
    return identity


def _titles(identity):
    return {normalize_identity(identity.get('title'))} | {
        normalize_identity(alias['title']) for alias in identity.get('confirmed_aliases', [])}


def title_matches(title, book):
    identity = work_identity(book)
    return bool(identity and normalize_identity(_literal_title(title)) in _titles(identity))


def same_work(source, book):
    """Coincidencia exacta, alias confirmado o identificadores bibliográficos.

    Un resultado encontrado al buscar un libro no queda vinculado automáticamente
    a ese libro. Las páginas sin vínculo interno necesitan título y autor.
    """
    if not isinstance(source, dict) or not isinstance(book, dict):
        return False
    book_identity = work_identity(book)
    if not book_identity:
        return False
    if source.get('kind') == 'web' and source.get('work_binding_verified') is not True:
        identity_text = normalize_identity(source.get('identity_text', ''))
        if not title_matches(source.get('title'), book):
            return False
        author = normalize_identity(book_identity['author'])
        tokens = author.split()
        full_name_present = bool(author and re.search(r'(?<!\w)' + re.escape(author) + r'(?!\w)', identity_text))
        if not full_name_present and len(tokens) >= 2:
            # Nombre y apellido pueden aparecer en orden bibliográfico inverso.
            # Exige una secuencia contigua de TODOS los términos, no palabras
            # dispersas por una reseña que podrían pertenecer a autores distintos.
            full_name_present = any(same_author_name(author, ' '.join(words))
                for words in (identity_text.split()[offset:offset + len(tokens)]
                              for offset in range(max(0, len(identity_text.split()) - len(tokens) + 1))))
        if not full_name_present:
            return False
        adaptation = re.search(r'\b(?:pelicula|serie de television|adaptacion|film|movie)\b', identity_text)
        novel = re.search(r'\b(?:novela|libro|novel|book)\b', identity_text)
        return not (adaptation and (not novel or adaptation.start() < novel.start()))
    source_identity = work_identity(source)
    if not source_identity or not same_author_name(source_identity['author'], book_identity['author']):
        return False
    if _titles(source_identity) & _titles(book_identity):
        return True
    trusted_pair = all(item.get('work_binding_verified') is True or _known_origin(item) for item in (source, book))
    if trusted_pair and source_identity['work_id'] == book_identity['work_id']:
        return True
    return bool(trusted_pair and set(source_identity['isbns']) & set(book_identity['isbns']))


def bind_source(source, book):
    """Añade el vínculo únicamente después de comprobar la identidad real."""
    if not same_work(source, book):
        return source
    identity = work_identity(book)
    return {**source, 'work_id': identity['work_id'], 'work_title': identity['title'],
            'work_author': identity['author'], 'work_binding_verified': True}


def _title_mention(message, title, author, known_titles):
    """Un prefijo de saga no identifica por sí solo el volumen mencionado.

    Tras el título solo admitimos el final, autoría o continuaciones claras de
    la pregunta. Así «Papelucho y sus personajes» conserva la obra, mientras
    «Papelucho y el marciano» no hereda automáticamente «Papelucho».
    """
    for match in re.finditer(r'(?<!\w)' + re.escape(title) + r'(?!\w)', message):
        suffix = message[match.end():].strip()
        if not suffix:
            return True
        normalized_author = normalize_identity(author)
        if normalized_author and re.match(r'^(?:de|del autor|de la autora)\s+'
                                          + re.escape(normalized_author) + r'(?:\b|$)', suffix):
            return True
        if re.search(r'\bcompara\b', message):
            if re.match(r'^(?:con|frente a|versus|vs)\b', suffix):
                return True
            if suffix.startswith('y ') and suffix[2:] in known_titles:
                return True
        if re.match(r'^(?:(?:y|pero|tambien)\s+)?(?:sus?\s+|(?:el|la|los|las)\s+)?'
                    r'(?:personajes?|protagonistas?|trama|argumento|final|autor(?:a)?|'
                    r'resumen|tema(?:s)?|capitulos?|escenas?)\b', suffix):
            return True
        if re.match(r'^(?:(?:y|pero|tambien)\s+)?(?:explica(?:me)?|cuenta(?:me)?|'
                    r'dime|describe(?:me)?|analiza|compara|recomienda(?:me)?|'
                    r'por favor|que opinas|que te parece)\b', suffix):
            return True
    return False


def resolve_followup_context(message, history):
    """Resuelve referencias solo sobre turnos aceptados y obras recibidas."""
    message = str(message or '')
    value = normalize_identity(message)
    result = {'books': [], 'ambiguous': False, 'reason': '', 'entities': []}
    author_reference = re.search(
        r'\b(?:(?:mismo|misma|ese|esa|este|esta) autor(?:a)?|su autor(?:a)?)\b', value)
    request_other = bool(re.search(
        r'\b(?:otr[oa]s?|recomiend\w*|quiero|busco|buscand\w*|dame|mas)\b', value))
    # «¿El segundo es del mismo autor?» comprueba un dato; no pide otra
    # recomendación. Conservar ese matiz evita cambiar la intención del lector.
    factual_author_question = bool(author_reference and not request_other and re.search(
        r'\b(?:es|son|era|eran|fue|fueron)\b', value[:author_reference.start()]))
    same_author = bool(author_reference and not factual_author_question)
    similar = bool(re.search(
        r'\b(?:otr[oa]s?|algo|un[oa]|libros|novelas|obras)\s+'
        r'(?:\w+\s+){0,2}(?:parecid[oa]s?|similar(?:es)?)\b', value))
    relation = 'same_author' if same_author else 'similar' if similar else ''
    turns = [turn for turn in history if isinstance(turn, dict) and turn.get('accepted', True) is True] if isinstance(history, list) else []
    lists = [[book for book in turn.get('books', []) if isinstance(book, dict) and work_identity(book)]
             for turn in turns]
    known_titles = {title for books in lists for book in books
                    for title in _titles(work_identity(book))}
    ordinal = re.search(r'\b(?:el|la|del|de la|al|a la)\s+(primero|primer|primera|segundo|segunda|tercero|tercer|tercera|cuarto|cuarta|quinto|quinta)\b', value)
    if ordinal:
        index = {'primero': 0, 'primer': 0, 'primera': 0, 'segundo': 1, 'segunda': 1,
                 'tercero': 2, 'tercer': 2, 'tercera': 2, 'cuarto': 3, 'cuarta': 3,
                 'quinto': 4, 'quinta': 4}[ordinal.group(1)]
        for books in reversed(lists):
            if len(books) > index:
                return {**result, 'books': [books[index]], 'reason': relation or 'ordinal'}
        return result
    # Un título explícito conocido cambia la obra activa aunque haya otra más reciente.
    named = []
    for books in reversed(lists):
        for book in books:
            titles = _titles(work_identity(book))
            matches = [title for title in titles if len(title) >= 4
                       and _title_mention(value, title, book.get('author'), known_titles)]
            if matches:
                if not any(same_work(book, other) for other in named):
                    named.append(book)
    if named:
        return {**result, 'books': named if len(named) == 1 else [], 'ambiguous': len(named) > 1,
                'reason': relation or 'named_title'}
    # Otro título explícito, entre comillas o tras "libro", no hereda la obra previa.
    if (re.search(r'[«“\"]([^»”\"\n]{2,180})[»”\"]', message)
            or re.search(r'\b(?:cambiemos|ahora (?:el|la|sobre)|libro (?:llamado|titulado))\b', value)
            or (not relation and re.search(r'\b(?:otro|otra)\b', value))):
        return result
    # «Otro parecido a Dune» no debe heredar Papelucho si Dune aún no está en
    # el historial. Solo las referencias deícticas pueden omitir su identidad.
    target = re.search(
        r'\b(?:parecid[oa]s?|similar(?:es)?)\s+a(?:l)?\s+(.+)|'
        r'\b(?:mismo|misma) autor(?:a)? (?:de|que)\s+(.+)', value)
    if relation and target:
        reference = next(part for part in target.groups() if part)
        if not re.match(r'^(?:ese|esa|este|esta|el anterior|la anterior|libro anterior|'
                        r'anterior|ultimo|ultima|el ultimo|la ultima|el mismo|la misma)\b', reference):
            return result
    # Una obra nueva explícita prevalece sobre el «y» de continuación.
    subject = re.search(r'\b(?:personajes? de|protagonistas? de|sucede en|pasa en|hablame de|sobre el libro)\s+(.+)', value)
    if subject and subject.group(1).strip() not in {'el', 'ella', 'ese', 'esa', 'este', 'esta', 'ese libro', 'este libro'}:
        return result
    # El posesivo de «no su título» pertenece al libro que intenta recordar,
    # no a la última obra del chat. «Ese libro» sí conserva su referencia.
    if (re.search(r'\b(?:recuerdo|recordaba)\b.*\b(?:un|otro) (?:libro|cuento|novela)\b', value)
            or (not relation and re.search(r'\bbusco\b.*\b(?:un|otro) (?:libro|cuento|novela)\b', value))
            or re.search(r'\b(?:recuerdo|recordaba)\b.*\b(?:no|sin) (?:su|el) titulo\b', value)):
        return result
    if relation:
        for books in reversed(lists):
            if not books:
                continue
            authors = {normalize_identity(work_identity(book)['author']) for book in books}
            if len(books) == 1 or (relation == 'same_author' and len(authors) == 1):
                return {**result, 'books': books, 'reason': relation}
            return {**result, 'ambiguous': True, 'reason': relation}
        return {**result, 'reason': relation}
    referential = bool(re.search(r'\b(?:sus|su|ese|esa|este|esta|el mismo|la misma|y sus|y que|y quien|que sucede con|que paso con|que pasa con|quien es)\b', value))
    short_continuation = bool(re.match(r'^(?:y )?(?:los |las )?(?:personajes|protagonistas|final|trama|argumento)\b', value))
    if not (referential or short_continuation):
        return result
    for turn, books in reversed(list(zip(turns, lists))):
        if not books:
            continue
        matched = []
        for book in books:
            relevant = [source for source in turn.get('sources', [])
                        if isinstance(source, dict) and same_work(source, book)]
            entity_names = {str(fact.get('name', '')).strip() for source in relevant
                            for fact in (source.get('character_facts') or []) if isinstance(fact, dict)}
            for name in entity_names:
                token = normalize_identity(name)
                if token and re.search(r'(?<!\w)' + re.escape(token) + r'(?!\w)', value):
                    result['entities'].append(name)
                    if book not in matched:
                        matched.append(book)
        if len(matched) == 1:
            return {**result, 'books': matched, 'reason': 'remembered_entity'}
        if len(books) == 1:
            return {**result, 'books': books, 'reason': 'active_work'}
        return {**result, 'ambiguous': True, 'reason': 'multiple_active_works'}
    return result


# Compatibilidad con consumidores anteriores del módulo.
followup_context = resolve_followup_context
