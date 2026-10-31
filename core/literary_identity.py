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
    'Conocimiento literario local', 'Biblioteca literaria local', 'BNE', 'Project Gutenberg',
}
IDENTITY_DOMAINS = (
    'openlibrary.org', 'wikidata.org', 'books.google.com', 'books.google.es',
    'memoriachilena.gob.cl', 'bibliotecanacionaldigital.gob.cl', 'bnchile.gob.cl',
    'literaturasm.cl', 'literaturasm.com', 'penguinlibros.com',
    'planetadelibros.com', 'anagrama-ed.es', 'fce.com.mx', 'cervantesvirtual.com',
    'ci.nii.ac.jp', 'rae.es', 'datos.bne.es', 'catalogo.bne.es', 'www.gutenberg.org',
)
UNKNOWN_AUTHORS = {'', 'autor no informado', 'autor desconocido', 'fuente web'}

# A declaration can include publication year/genre before its literary form.
# Film/character predicates are deliberately excluded. This only discovers a
# published identity; callers still verify author, medium and provenance.
_LITERARY_DECLARATION = (r'(?:es|fue|era|son|is|was)\s+(?:una?|la|el|a|an)\s+'
    r'(?:(?!(?:film|movie|pelicula|adaptation|adaptacion|anime|character|personaje)\b)[\w\x27-]+\s+){0,3}?'
    r'(?:novela|libro|obra|saga|serie de novelas|poema|epopeya|serie de manga|manga|comic|historieta|'
    r'novel|book|play|poem|manga series)\b')


def is_literary_identity(text):
    """Published literary form; a format label does not infer a genre."""
    return bool(re.search(r'\b(?:novelas?|libros?|obras?|ensayos?|novels?|books?|manga|comics?|'
        r'historietas?|poemas?|poetry|epopeyas?|epic poem|plays?|obra teatral|tragedia)\b',
        normalize_identity(text)))


def normalize_identity(value):
    value = ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').casefold())
                    if not unicodedata.combining(c))
    return re.sub(r'\W+', ' ', value).strip()


def ambiguous_work_page(source):
    """A disambiguation index mentions works but is not evidence about one."""
    text = normalize_identity(source.get('identity_text') or source.get('extract')
                              or source.get('description', ''))[:500]
    return (isinstance(source.get('pageprops'), dict) and 'disambiguation' in source['pageprops']
            or bool(re.search(r'\b(?:puede referirse a|puede hacer referencia a|may refer to|desambiguacion|disambiguation)\b', text)))


def author_name_forms(value):
    """Sólo expansiones de iniciales expresamente publicadas entre paréntesis."""
    raw=str(value or '')
    forms={normalize_identity(raw)}
    match=re.fullmatch(r'\s*([A-ZÁÉÍÓÚÑ][\w.\s]{1,80}?)\s*\(([^()]{3,100})\)\s+([^()]{2,100})\s*',raw)
    if match:
        initials=match[1].split()
        expanded=match[2].split()
        if (any(re.fullmatch(r'[A-ZÁÉÍÓÚÑ]\.',part) for part in initials)
                and len(initials)==len(expanded) and all(
                    normalize_identity(a)==normalize_identity(b[0] if len(a)==2 and a.endswith('.') else b)
                    for a,b in zip(initials,expanded))):
            forms.add(normalize_identity(match[1]+' '+match[3]))
            forms.add(normalize_identity(match[2]+' '+match[3]))
    return forms


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
    return any(len(a.split())>=2 and sorted(a.split())==sorted(b.split())
               for a in author_name_forms(first) for b in author_name_forms(second))


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


def _attributed_wikipedia(source):
    attribution=source.get('attribution',{})
    try:
        parts=urlsplit(str(source.get('url','')))
        port=parts.port
    except (ValueError,TypeError):
        return False
    return (source.get('source')=='Wikipedia' and source.get('license')=='CC-BY-SA-4.0'
        and isinstance(attribution,dict) and attribution.get('url')==source.get('url')
        and attribution.get('title')==source.get('title')
        and str(attribution.get('revision_id','')).isdigit()
        and int(attribution['revision_id'])>0
        and attribution.get('authors')=='Wikipedia contributors'
        and attribution.get('license_url')=='https://creativecommons.org/licenses/by-sa/4.0/'
        and parts.scheme=='https' and parts.hostname in {'es.wikipedia.org','en.wikipedia.org'}
        and not parts.username and not parts.password and port in {None,443})


def confirmed_aliases(source):
    """Solo devuelve variantes con procedencia y ambos títulos en la prueba."""
    if not isinstance(source, dict):
        return []
    wikipedia=_attributed_wikipedia(source)
    if not _known_origin(source) and not wikipedia:
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
        wiki_proof=(wikipedia and urlsplit(url).scheme=='https'
            and urlsplit(url).hostname in {'es.wikipedia.org','en.wikipedia.org'}
            and evidence.startswith('MediaWiki langlinks: title=')
            and re.search(r'; wikibase_item=Q[1-9]\d*; revisions=\d+,\d+$',evidence)
            and evidence.endswith(','+str(source['attribution']['revision_id'])))
        if (not alias or alias == canonical or alias in seen or not (_identity_url(url) or wiki_proof)
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


def book_named_in_message(book, message):
    """Comprueba el título canónico o un alias confirmado dentro de la consulta."""
    identity = work_identity(book)
    value = normalize_identity(message)
    return bool(identity and value and any(
        title and title in value for title in _titles(identity)))


_WEB_TITLE_SEPARATORS = (' - ', ' | ', ' – ', ' — ', ' / ', ': ')
_WEB_SUFFIX_WORDS = (
    'wikipedia', 'la enciclopedia', 'enciclopedia', 'resumen', 'analisis',
    'sinopsis', 'argumento', 'trama', 'personajes', 'ficha', 'opiniones',
    'resena', 'critica', 'libro', 'novela', 'texto', 'guia', 'estudio',
    'comentario', 'introduccion', 'prologo', 'edicion',
)
_WEB_SUFFIX_HOSTS = (
    'wikipedia', 'lecturalia', 'culturagenial', 'aibooksummarizer',
    'resumenlibro', 'planetadelibros', 'cervantesvirtual', 'textos.info',
    'losresumenes', 'capsulasliterarias', 'austen.com', 'gutenberg',
    'archive.org', 'americanliterature',
)


def _web_suffix_is_safe(suffix, author):
    """Acepta sufijos de sitio o de ficha, nunca un volumen distinto.

    «Orgullo y prejuicio: zombis» no es la misma obra; «Orgullo y prejuicio -
    Wikipedia» sí puede serlo si además aparece la autoría en el texto.
    """
    suffix = suffix.strip(' .,;:|/-–—')
    if not suffix:
        return True
    if author and (suffix == author or suffix.startswith(author + ' ')):
        return True
    if re.match(r'^(?:de|por|by)\s+' + (re.escape(author) if author else r'$'), suffix):
        return True
    if any(suffix.startswith(host) for host in _WEB_SUFFIX_HOSTS):
        return True
    return any(re.match(r'^' + re.escape(word) + r'(?:\b|$)', suffix)
               for word in _WEB_SUFFIX_WORDS)


def web_title_matches(title, book):
    """Reconoce el título canónico dentro del título de una página pública.

    Los buscadores añaden « - Wikipedia», «: resumen y personajes» o el nombre
    del sitio. Se exige que el prefijo coincida exactamente con la obra o alias
    y que el resto sea un descriptor de página; los subtítulos de sagas no se
    recortan.
    """
    identity = work_identity(book)
    if not identity:
        return False
    known = _titles(identity)
    normalized = normalize_identity(_literal_title(title))
    if normalized in known:
        return True
    author = normalize_identity(identity.get('author'))
    if author:
        qualified=re.fullmatch(r'(.+?)\s*\(([^()]+)\)\s*',str(title))
        if (qualified and normalize_identity(qualified[1]) in known
                and normalize_identity(qualified[2])==author.split()[-1]
                and len(author.split())>=2):
            # Sólo formato de página. same_work sigue exigiendo autor completo
            # en su introducción y rechaza películas/adaptaciones.
            return True
        trimmed = re.sub(r'\s*[,/]\s*(?:de|por|by)\s+' + re.escape(author)
                         + r'(?:\b|$).*$', '', normalized).strip()
        if trimmed in known:
            return True
        normalized = trimmed or normalized
    for canonical in known:
        if not canonical:
            continue
        if normalized.startswith(canonical + ' ') and _web_suffix_is_safe(
                normalized[len(canonical):], author):
            return True
        for separator in _WEB_TITLE_SEPARATORS:
            if normalized.startswith(canonical + separator) and _web_suffix_is_safe(
                    normalized[len(canonical) + len(separator):], author):
                return True
    return False


def published_title_alias(source, title):
    """An explicit alternative title in an attributed encyclopedia lead.

    Does not infer identity from a shared prefix or a redirect to a character.
    Author and publication type must still be checked by the caller.
    """
    if not isinstance(source, dict) or source.get('source') != 'Wikipedia':
        return False
    attribution = source.get('attribution', {})
    if (not isinstance(attribution, dict) or source.get('license') != 'CC-BY-SA-4.0'
            or attribution.get('url') != source.get('url')
            or attribution.get('title') != source.get('title')
            or not str(attribution.get('revision_id', '')).isdigit()
            or attribution.get('authors') != 'Wikipedia contributors'
            or attribution.get('license_url') != 'https://creativecommons.org/licenses/by-sa/4.0/'):
        return False
    if urlsplit(str(source.get('url', ''))).hostname not in {'es.wikipedia.org', 'en.wikipedia.org'}:
        return False
    text = normalize_identity(source.get('identity_text', ''))
    canonical = normalize_identity(_literal_title(source.get('title')))
    alias = normalize_identity(title)
    if alias in {normalize_identity(item['title']) for item in confirmed_aliases(source)}:
        return True
    raw = ''.join(c for c in unicodedata.normalize('NFKD', str(source.get('identity_text', '')).casefold())
                  if not unicodedata.combining(c))
    # Article headings can omit an alternative subtitle that the introduction
    # explicitly publishes ("X; or, Y is a novel by ..."). This is literal
    # evidence of the FULL requested title, never a shared-prefix alias. The
    # caller still requires the complete author and checks literary medium.
    leading = re.match(r'(.{2,240}?)\s+'+_LITERARY_DECLARATION,raw[:700])
    if (leading and normalize_identity(leading[1]) == alias and canonical
            and re.match(re.escape(canonical)+r'(?:\s|$)',alias)):
        return True
    alias_marker=(r'\b(?:o simplemente|tambien (?:llamad[oa]|conocid[oa] como)|also known as)\s+[«“"]?')
    translated_marker=(r'\(\s*(?:en (?:ingles|frances|aleman|italiano|portugues|japones)|'
                       r'titulo original(?: en \w+)?|original title)\s*[:,]?\s*[«“"]?')
    return bool(canonical and alias and text.startswith(canonical + ' ')
        and re.search('(?:'+alias_marker+'|'+translated_marker+')'
                      + re.escape(alias).replace(r'\ ', r'\s+')
                      + r'(?=[»”"]?(?:\s*[)(,.;:]|\s+(?:es|fue|is|was|o)\b|$))', raw[:700]))


def same_work(source, book):
    """Coincidencia exacta, alias confirmado o identificadores bibliográficos.

    Un resultado encontrado al buscar un libro no queda vinculado automáticamente
    a ese libro. Las páginas sin vínculo interno necesitan título y autor.
    """
    if not isinstance(source, dict) or not isinstance(book, dict):
        return False
    if source.get('kind') == 'web' and ambiguous_work_page(source):
        return False
    book_identity = work_identity(book)
    if not book_identity:
        return False
    if source.get('kind') == 'web' and source.get('work_binding_verified') is not True:
        identity_text = normalize_identity(source.get('identity_text', ''))
        if not (title_matches(source.get('title'), book)
                or web_title_matches(source.get('title'), book)
                or any(published_title_alias(source, title) for title in _titles(book_identity))):
            return False
        author = normalize_identity(book_identity['author'])
        tokens = author.split()
        full_name_present = bool(author and re.search(r'(?<!\w)' + re.escape(author) + r'(?!\w)', identity_text))
        if not full_name_present and len(tokens) >= 2:
            # Nombre y apellido pueden aparecer en orden bibliográfico inverso.
            # Exige una secuencia contigua de TODOS los términos, no palabras
            # dispersas por una reseña que podrían pertenecer a autores distintos.
            full_name_present = any(same_author_name(form, ' '.join(words))
                for form in author_name_forms(book_identity['author'])
                for words in (identity_text.split()[offset:offset + len(form.split())]
                              for offset in range(max(0,len(identity_text.split())-len(form.split())+1))))
        if not full_name_present:
            return False
        adaptation = re.search(r'\b(?:pelicula|serie de television|adaptacion|film|movie|anime|serie de animacion)\b', identity_text)
        novel = re.search(r'\b(?:novelas?|libros?|novels?|books?|manga|comics?|historietas?)\b', identity_text)
        return not (adaptation and (not novel or adaptation.start() < novel.start()))
    source_identity = work_identity(source)
    if source_identity and _titles(source_identity) & _titles(book_identity):
        def anchors(item):
            if not _known_origin(item):return set()
            parts=urlsplit(str(item.get('url','')))
            host=(parts.hostname or '').lower()
            known=(host in {'www.wikidata.org','wikidata.org'} and re.fullmatch(r'/wiki/Q\d+',parts.path)
                or host=='openlibrary.org' and re.fullmatch(r'/works/OL\d+W',parts.path)
                or host=='www.gutenberg.org' and re.fullmatch(r'/ebooks/\d+',parts.path)
                or host in {'es.wikipedia.org','en.wikipedia.org'} and parts.path.startswith('/wiki/'))
            return {(host,parts.path)} if known and parts.scheme=='https' else set()
        # Un identificador bibliográfico compartido verifica las variantes;
        # parecido del nombre o un apellido común no lo hacen.
        if anchors(source) & anchors(book):return True
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


_TITLE_PREFIX_FRAMING = {
    'cuentame', 'cuenta', 'hablame', 'habla', 'dime', 'di', 'explicame', 'explica',
    'resume', 'resumen', 'describe', 'analiza', 'compara', 'recomienda', 'quiero',
    'necesito', 'sabes', 'conoces', 'opinas', 'parece', 'de', 'del', 'la', 'el',
    'los', 'las', 'un', 'una', 'unos', 'unas', 'sobre', 'acerca', 'en', 'para',
    'por', 'con', 'y', 'e', 'o', 'u', 'a', 'al', 'se', 'es', 'era', 'fue', 'son',
    'eran', 'fueron', 'que', 'quien', 'quienes', 'cual', 'cuales', 'como', 'cuando',
    'donde', 'trata', 'va', 'pasa', 'sucede', 'ocurre', 'escribio', 'autor', 'autora',
    'libro', 'novela', 'obra', 'texto', 'cuento', 'ensayo', 'trama', 'argumento',
    'sinopsis', 'personajes', 'protagonista', 'protagonistas', 'final', 'desenlace',
    'favor', 'porfavor', 'do', 'da', 'dos', 'das', 'no', 'na', 'nos', 'nas', 'em',
    'um', 'uma', 'the', 'of', 'in', 'on', 'about', 'by', 'and', 'a', 'an', 'book', 'novel',
    'otro', 'otra', 'mismo', 'misma', 'parecido', 'parecida', 'similar'
}


def _title_mention(message, title, author, known_titles):
    """Un prefijo de saga no identifica por sí solo el volumen mencionado.

    Tras el título solo admitimos el final, autoría o continuaciones claras de
    la pregunta. Así «Papelucho y sus personajes» conserva la obra, mientras
    «Papelucho y el marciano» no hereda automáticamente «Papelucho».
    """
    known_words = {w for t in known_titles for w in re.findall(r'\w+', t)}
    for match in re.finditer(r'(?<!\w)' + re.escape(title) + r'(?!\w)', message):
        prefix = message[:match.start()].strip()
        if prefix:
            prefix_tokens = re.findall(r'\w+', prefix)
            if not all(token in _TITLE_PREFIX_FRAMING or token in known_words for token in prefix_tokens):
                continue
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


def _identity_author(source):
    """Autor publicado en la introducción de una página de obra admitida."""
    bound = str(source.get('work_author') or '').strip()
    if bound and normalize_identity(bound) not in UNKNOWN_AUTHORS:
        return bound
    text = str(source.get('identity_text') or source.get('description') or '')
    attributed = re.search(r'\b(?i:atribuid[oa]\s+(?:a|al)|attributed\s+to)\s+'
        r'(?:(?i:poeta|autor|autora|escritor|escritora)\s+(?:[a-záéíóúüñ]+\s+){0,2})?'
        r'([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÜÑáéíóúüñ’\'-]+)(?=[.,;:]|$)', text)
    if attributed:
        return attributed.group(1)
    for marker in (r'escrit[oa](?:\s+e\s+ilustrad[oa])?\s+por',
                   r'written(?:\s+and\s+illustrated)?\s+by',
                   r'creada?\s+por', r'obra\s+de', r'autor(?:a)?\s+',
                   r'escritor(?:a)?\s+', r'novel\s+by\s+', r'(?:novela|libro|poema(?:\s+épico)?)\s+de\s+'):
        match = re.search(r'(?i)\b' + marker + r'\b(.{0,120})', text)
        if not match:
            continue
        # No cortar en las iniciales («J. R. R. Tolkien»): sólo cierra la
        # oración un punto que no sigue a una única letra mayúscula.
        segment = re.split(r'(?<![A-ZÁÉÍÓÚÑ])[.;]', match.group(1), maxsplit=1)[0]
        segment = re.split(r'(?i)\b(?:first published|published|publicad[oa]|seriali[sz]ed|'
                           r'ilustrad[oa]|illustrated|traducid[oa]|translated)\b',segment,maxsplit=1)[0]
        names = re.findall(
            r'\b(?:[A-ZÁÉÍÓÚÑ]\.|[A-ZÁÉÍÓÚÑ][\wáéíóúüñ\'’\-]+)'
            r'(?:\s+(?:[A-ZÁÉÍÓÚÑ]\.|[A-ZÁÉÍÓÚÑ][\wáéíóúüñ\'’\-]+)){1,5}', segment)
        if len(names) == 1:
            # The byline is the first name after the authorship marker. A
            # later magazine, publisher or another title is not its author.
            return names[0].strip()
    return ''


def _verified_web_work(source):
    """Obra documentada por una introducción Wikipedia verificable.

    Sólo sirve para recordar el orden de las obras ya comentadas. No crea una
    ficha bibliográfica, no aporta ISBN y no se usa como prueba de contenido.
    """
    if (not isinstance(source, dict) or source.get('kind') != 'web'
            or source.get('source') != 'Wikipedia'
            or source.get('license') != 'CC-BY-SA-4.0'
            or source.get('injection_detected') or source.get('conflicts_with')):
        return {}
    attribution = source.get('attribution')
    if not isinstance(attribution, dict):
        return {}
    if (attribution.get('authors') != 'Wikipedia contributors'
            or attribution.get('license_url') != 'https://creativecommons.org/licenses/by-sa/4.0/'
            or attribution.get('url') != source.get('url')
            or attribution.get('title') != source.get('title')
            or not str(attribution.get('revision_id', '')).isdigit()):
        return {}
    if 'fragmento del buscador' in normalize_identity(source.get('read_mode', '')):
        return {}
    title = str(source.get('work_title') or source.get('title') or '').strip()
    identity = normalize_identity(source.get('identity_text', ''))
    token = normalize_identity(title)
    if (not title or not identity or re.search(r'\b(?:categoria|category|anexo)\b', token)
            or not re.search(r'(?<!\w)' + re.escape(token) + r'.{0,400}?\b'+_LITERARY_DECLARATION, identity)):
        return {}
    author = _identity_author(source)
    if normalize_identity(author) in UNKNOWN_AUTHORS:
        return {}
    return {'title': _literal_title(title), 'author': author,
            'work_id': stable_work_id(title, author), 'source': 'Wikipedia',
            'url': str(source.get('url') or '')[:1500]}


def _history_works(turn):
    """Restaura las obras de un turno, prefiriendo fichas y luego páginas."""
    selected = turn.get('context_work')
    if isinstance(selected, dict) and selected.get('title'):
        return [selected]
    works = []
    for book in turn.get('books') if isinstance(turn.get('books'), list) else []:
        if isinstance(book, dict) and work_identity(book):
            works.append(book)
    if works:
        return works
    for source in turn.get('sources') if isinstance(turn.get('sources'), list) else []:
        work = _verified_web_work(source)
        if not work:
            continue
        if any(same_work(work, previous) or (
                normalize_identity(work['title']) == normalize_identity(previous['title'])
                and same_author_name(work['author'], previous['author']))
               for previous in works):
            continue
        works.append(work)
    return works


def _ordinal_works(lists, index, *, returning):
    """Resuelve un ordinal sin confundir una lista con el orden del chat."""
    if returning and index == 0 and lists:
        # «Volvamos al primer libro» retorna al primer título comentado, salvo
        # que el último turno haya presentado una lista con varias opciones.
        if len(lists[-1]) > 1:
            return [lists[-1][0]]
        first = []
        for books in lists:
            for book in books:
                if not any(same_work(book, previous) for previous in first):
                    first.append(book)
        if first:
            return [first[0]]
    for books in reversed(lists):
        if len(books) > index:
            return [books[index]]
    flat = []
    for books in lists:
        for book in books:
            if not any(same_work(book, previous) for previous in flat):
                flat.append(book)
    return [flat[index]] if len(flat) > index else []


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
    lists = [_history_works(turn) for turn in turns]
    from .literary_research import is_topic_recommendation
    selection_lists = [_history_works({**turn, 'context_work': None})
                       if turn.get('intent') == 'recommend' or is_topic_recommendation(turn.get('question', ''))
                       else books for turn, books in zip(turns, lists)]
    known_titles = {title for books in selection_lists for book in books
                    for title in _titles(work_identity(book))}
    # Corrección explícita: «no, el otro libro». Se resuelve sólo si hay una
    # obra activa y otra distinta en la lista inmediatamente anterior; con dos
    # candidatos sin referencia previa se pregunta en lugar de adivinar.
    correction = re.search(
        r'\bno\b(?:\s+\w+){0,6}\s+(?:el|la)\s+otr[oa]\s+'
        r'(?:libro|novela|obra|uno|una)\b'
        r'(?:\s+que\s+(?:mencionaste|dijiste|recomendaste))?$', value)
    other_request = re.match(
        r'^(?:y\s+)?(?:el|la)\s+otr[oa]\s+(?:libro|novela|obra|uno|una)\b'
        r'(?:\s+que\s+(?:mencionaste|dijiste|recomendaste))?$', value)
    if correction or other_request:
        active = []
        for books in reversed(lists):
            if not books:
                continue
            if len(books) == 1:
                active = books
                continue
            candidates = [book for book in books
                          if not any(same_work(book, previous) for previous in active)]
            if len(candidates) == 1:
                return {**result, 'books': candidates, 'reason': 'correction_other'}
            return {**result, 'ambiguous': True, 'reason': 'correction_other'}
        return result
    ordinal = re.search(r'\b(?:el|la|del|de la|al|a la)\s+(primero|primer|primera|segundo|segunda|tercero|tercer|tercera|cuarto|cuarta|quinto|quinta)\b', value)
    if ordinal and (re.search(r'[«“"]([^»”"\n]{2,180})[»”"]', message)
            or (re.search(r'\b(?:quien escribio|quien es el autor|quien es la autora)\b', value)
                and re.match(r'\s+(?!(?:libro|novela|obra|titulo)\b)\w', value[ordinal.end():]))):
        # «¿Quién escribió El segundo sexo?» introduce un título, no la segunda
        # ficha de una lista anterior. La identidad exacta se resuelve después.
        ordinal = None
    if ordinal:
        index = {'primero': 0, 'primer': 0, 'primera': 0, 'segundo': 1, 'segunda': 1,
                 'tercero': 2, 'tercer': 2, 'tercera': 2, 'cuarto': 3, 'cuarta': 3,
                 'quinto': 4, 'quinta': 4}[ordinal.group(1)]
        returning = bool(re.search(r'\b(?:volvamos|volver|regresemos|retomemos|'
                                   r'vuelve|regresa|retoma)\b', value))
        recommendations=[books for turn,books in zip(turns,selection_lists)
                         if turn.get('intent')=='recommend' or is_topic_recommendation(turn.get('question',''))]
        selected = (recommendations[-1][index:index+1] if recommendations and not returning
                    else _ordinal_works(selection_lists, index, returning=returning))
        if selected:
            return {**result, 'books': selected, 'reason': relation or 'ordinal'}
        return result
    # Un título explícito conocido cambia la obra activa aunque haya otra más reciente.
    named = []
    for books in reversed(selection_lists):
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
    subject = re.search(
        r'\b(?:personajes? de|protagonistas? de|sucede en|pasa en|hablame de|cuentame de|'
        r'cuentame sobre(?: la trama de| el argumento de| la sinopsis de| el libro| la obra)?|'
        r'trama de|argumento de|sinopsis de|resumen de|de que trata(?: el libro| la obra)?|'
        r'de que va(?: el libro| la obra)?|que explica(?: el libro| la obra)?|'
        r'sobre el libro|sobre la obra)\s+(.+)', value)
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
            authors = {normalize_identity(work_identity(book).get('author')) for book in books}
            if len(books) == 1 or (relation == 'same_author' and len(authors) == 1):
                return {**result, 'books': books, 'reason': relation}
            return {**result, 'ambiguous': True, 'reason': relation}
        return {**result, 'reason': relation}
    referential = bool(re.search(r'\b(?:sus|su|ese|esa|este|esta|el mismo|la misma|y sus|y que|y quien|que sucede con|que paso con|que pasa con|quien es|'
                                r'quien (?:debia|debe|acompana|destruye|ayuda|protege|salva))\b', value))
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
