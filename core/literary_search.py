"""Google Books, catálogo, archivos locales y fuentes públicas complementarias."""
import hashlib
import ipaddress
import logging
import re
import socket
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener
from django.conf import settings
from django.core.cache import cache
from django.db.models import Case, IntegerField, Q, Value, When
from .ai_http import NoRedirects, local_origin, read_json_url, read_bounded
from .ai_budget import budget_timeout, submit_with_budget, check_budget, pool_in_budget, request_budget
from .literary_ai import canonical_sources, clean_text, normalized, safe_source_url, has_excerpt
from .local_rag import retrieve_fragments
from .books_google import (search_volumes, get_volume, volume_source, public_query, BooksUnavailable,
                          book_search_profile, book_search_queries, rank_book_sources, source_synopsis)

logger = logging.getLogger('litmate')
STOPWORDS = {'libro', 'libros', 'novela', 'novelas', 'sobre', 'para', 'del', 'los',
             'las', 'una', 'que', 'con', 'por', 'quiero', 'dame', 'titulo',
             'recomienda', 'busco', 'buscar', 'the', 'and', 'books', 'book',
             'intitle', 'inauthor', 'title', 'author'}
TRUSTED_DOMAINS = ('wikipedia.org', 'wikisource.org', 'books.google.com',
                   'books.google.es', 'openlibrary.org', 'gutenberg.org',
                   'memoriachilena.gob.cl', 'bnchile.gob.cl', 'cervantesvirtual.com',
                   'rae.es', 'penguinlibros.com', 'planetadelibros.com',
                   'anagrama-ed.es', 'fce.com.mx')


def _agent():
    contact = clean_text(getattr(settings, 'LITMATE_BOOKS_CONTACT', ''), 100)
    return ('LitMate/Local-1.0' + (' (' + contact + ')' if contact else '')).encode('ascii', 'ignore').decode()


def _cache_key(prefix, query):
    return prefix + hashlib.sha256(query.encode()).hexdigest()


def _cached(key):
    try:
        result = cache.get(key)
        return result if isinstance(result, list) else None
    except Exception:
        return None


def _save(key, result):
    try:
        cache.set(key, result, 900 if result else 30)
    except Exception:
        pass
    return result


def search_catalog(query):
    from .models import Libro
    terms = [t for t in re.findall(r'\w+', query)
             if len(t) >= 3 and normalized(t) not in STOPWORDS][:10]
    if not terms:
        return []
    condition = Q(titulo__icontains=query) | Q(autor__nombre__icontains=query)
    score = Case(When(titulo__iexact=query, then=Value(30)), default=Value(0),
                 output_field=IntegerField())
    for term in terms:
        condition |= Q(titulo__icontains=term) | Q(autor__nombre__icontains=term) | Q(sinopsis__icontains=term)
        score += Case(When(titulo__icontains=term, then=Value(6)),
                      When(autor__nombre__icontains=term, then=Value(4)),
                      When(sinopsis__icontains=term, then=Value(1)),
                      default=Value(0), output_field=IntegerField())
    books = Libro.objects.select_related('autor').filter(condition).annotate(
        literary_rank=score).order_by('-literary_rank', 'id')[:6]
    return [{'title': book.titulo, 'author': book.autor.nombre, 'description': book.sinopsis,
             'synopsis': book.sinopsis, 'image_url': safe_source_url(book.portada_url),
             'categories': [book.genero] if book.genero else [], 'language': book.idioma,
             'year': str(book.fecha_publicacion.year) if book.fecha_publicacion else '',
             'source': 'Catálogo LitMate', 'book_id': 'db_' + str(book.pk), 'kind': 'book'} for book in books]


def search_google(query):
    if not getattr(settings, 'LITMATE_USE_GOOGLE_BOOKS_API', True):
        return []
    if not str(getattr(settings, 'GOOGLE_BOOKS_API_KEY', '')).strip():
        return []
    try:
        profile = book_search_profile(query)
        queries = book_search_queries(query)
        if not queries:
            return []
        maximum = 20 if profile['fiction'] else 8
        items = []
        # Las consultas por género usan la categoría de Google y una alternativa
        # en español. Ambas son acotadas y comparten caché y presupuesto.
        if len(queries) == 1:
            items = search_volumes(queries[0], max_results=maximum, fetch=read_json_url, use_cache=True)
        else:
            def fetch_term(term):
                return search_volumes(term, max_results=maximum, fetch=read_json_url, use_cache=True)
            with pool_in_budget(2) as pool:
                jobs = [submit_with_budget(pool, fetch_term, term) for term in queries]
                for future in jobs:
                    try:
                        items.extend(future.result(timeout=budget_timeout(12)))
                    except BooksUnavailable as exc:
                        logger.warning('Google Books: %s', exc.code)
        by_id = {str(item.get('id') or index): item for index, item in enumerate(items)}
        items = list(by_id.values())
        sources = rank_book_sources([volume_source(item) for item in items], query,
                                    distinct_works=profile['fiction'])
        selected_ids = [source['book_id'] for source in sources[:2] if not source.get('synopsis')]
        for index, item in enumerate(items):
            if item.get('id') in selected_ids and re.fullmatch(
                    r'[A-Za-z0-9_-]{1,100}', str(item.get('id', ''))):
                try:
                    items[index] = get_volume(item['id'], fetch=read_json_url, use_cache=True)
                except BooksUnavailable:
                    pass
        return rank_book_sources([volume_source(item) for item in items], query,
                                  distinct_works=profile['fiction'])[:8]
    except BooksUnavailable as exc:
        logger.warning('Google Books: %s', exc.code)
        return []


def search_openlibrary(query):
    query = public_query(query)
    if not query:
        return []
    try:
        if not cache.add('litmate_local_ol_slot', True, timeout=2):
            return []
    except Exception:
        return []
    params = {'q': query, 'limit': 5, 'lang': 'es',
              'fields': 'key,title,author_name,first_publish_year,subject,cover_i,language'}
    data = read_json_url('https://openlibrary.org/search.json?' + urlencode(params),
                         headers={'User-Agent': _agent()}, timeout=6)
    results = []
    for item in (data.get('docs') or [])[:5]:
        authors, subjects = item.get('author_name') or [], item.get('subject') or []
        work_id = str(item.get('key', ''))
        results.append({'title': item.get('title'),
                        'author': ', '.join(str(a) for a in authors) if isinstance(authors, list) else '',
                        'description': 'Temas del catálogo: ' + ', '.join(str(s) for s in subjects[:12]),
                        'year': str(item.get('first_publish_year') or ''),
                        'categories': [str(s) for s in subjects[:8]],
                        'image_url': ('https://covers.openlibrary.org/b/id/' + str(item['cover_i']) + '-M.jpg'
                                      if type(item.get('cover_i')) is int and item['cover_i'] > 0 else ''),
                        'source': 'Open Library', 'book_id': work_id, 'kind': 'book',
                        'url': 'https://openlibrary.org' + work_id if re.fullmatch(r'/works/OL\d+W', work_id) else ''})
    return results


def retrieve_books(query):
    query = clean_text(query, 240)
    if not query:
        return []
    database = Path(getattr(settings, 'LITMATE_RAG_DB',
                            Path(settings.BASE_DIR) / 'data' / 'litmate_rag.sqlite3'))
    revision = str(database.stat().st_mtime_ns) if database.is_file() else 'sin-indice'
    google_revision = str(getattr(settings, 'LITMATE_USE_GOOGLE_BOOKS_API', True)) + ':' + hashlib.sha256(
        str(getattr(settings, 'GOOGLE_BOOKS_API_KEY', '')).encode()).hexdigest()[:12]
    key = _cache_key('litmate_hybrid_books_v5:', query + ':' + revision + ':' + google_revision + ':'
                     + str(getattr(settings, 'LITMATE_RAG_SEMANTIC', True)) + ':'
                     + getattr(settings, 'LITMATE_EMBED_MODEL', 'embeddinggemma:latest'))
    cached = _cached(key)
    if cached is not None:
        return cached
    results = []
    try:
        from .local_embeddings import configured_embedder
        results.extend(retrieve_fragments(query, database, 3,
                       embedder=configured_embedder(settings)))
    except Exception as exc:
        logger.warning('IA: índice local no disponible (%s)', type(exc).__name__)
    # Django/SQL permanece en el hilo de la petición; los hilos solo consultan HTTP.
    try:
        results.extend(search_catalog(query))
    except Exception as exc:
        logger.warning('IA: catálogo no disponible (%s)', type(exc).__name__)
    with pool_in_budget(2) as pool:
        jobs = [('Google Books', submit_with_budget(pool, search_google, query))]
        if getattr(settings, 'LITMATE_AI_USE_OPENLIBRARY', True):
            jobs.append(('Open Library', submit_with_budget(pool, search_openlibrary, query)))
        for name, future in jobs:
            try:
                results.extend(future.result(timeout=budget_timeout(25)))
            except Exception as exc:
                logger.warning('IA: fuente=%s error=%s', name, type(exc).__name__)
    # Mantiene fragmentos reales primero y evita que el límite de contexto elimine Google Books.
    results.sort(key=lambda item: (item.get('kind') == 'excerpt',
                                  item.get('source') == 'Google Books API'), reverse=True)
    grouped = {}
    for item in results:
        grouped.setdefault(item.get('source', ''), []).append(item)
    merged = [group[i] for i in range(6) for group in grouped.values() if i < len(group)]
    merged = rank_book_sources(merged, query)
    return _save(key, canonical_sources(merged, 8))


def enrich_book_sources(sources, message=''):
    """Busca respaldo público para hasta dos fichas sin sinopsis, en veinte segundos.

    Conserva la procedencia: research_summary es un pasaje web y nunca una
    sinopsis editorial de Google. Devuelve libros más evidencia web adicional.
    """
    if not isinstance(sources, list) or (message and has_excerpt(message)):
        return sources if isinstance(sources, list) else []
    books = [dict(source) for source in sources if isinstance(source, dict)]
    missing = [index for index, source in enumerate(books)
               if source.get('kind', 'book') == 'book' and not source.get('synopsis')
               and not source.get('research_summary') and not source_synopsis(source)][:2]
    if not missing:
        return books
    evidence = []
    deadline = time.monotonic() + budget_timeout(20)
    with request_budget(deadline):
        with pool_in_budget(2) as pool:
            jobs = []
            for index in missing:
                book = books[index]
                title = clean_text(book.get('title'), 160)
                author = clean_text(book.get('author'), 100)
                if not title or author == 'Autor no informado':
                    continue
                query = public_query(title + ' ' + author)
                if query:
                    jobs.append((index, submit_with_budget(pool, retrieve_web, query)))
            for index, future in jobs:
                try:
                    found = future.result(timeout=budget_timeout(20))
                except Exception as exc:
                    logger.warning('IA: sinopsis complementaria no disponible (%s)', type(exc).__name__)
                    continue
                book = books[index]
                matching = [source for source in found if isinstance(source, dict)
                            and _web_matches_book(source, book)]
                if not matching:
                    continue
                source = matching[0]
                summary = clean_text(source.get('description'), 1000)
                if not summary:
                    continue
                books[index] = {**book, 'research_summary': summary,
                    'synopsis_source_url': trusted_url(source.get('url')),
                    'description_source': str(source.get('source') or 'Fuente pública de respaldo')[:100]}
                evidence.extend(matching[:1])
    selected_books = [source for source in books if source.get('kind', 'book') == 'book'][:5]
    other_sources = evidence + [source for source in books if source.get('kind', 'book') != 'book']
    # Reservar espacio a la prueba web evita que canonical_sources(maximum=8)
    # descarte justamente el respaldo con el que se completó la ficha.
    return selected_books + other_sources[:3]


def _web_matches_book(source, book):
    if source.get('kind') != 'web' or not trusted_url(source.get('url')):
        return False
    title = normalized(book.get('title'))
    text = normalized(str(source.get('title', '')) + ' ' + str(source.get('description', '')))
    if not title or title not in text:
        return False
    # Títulos cortos como "1984" se comparten entre contextos; la autoría evita
    # atribuir al libro una página que habla sólo del año o de otra obra homónima.
    author_words = [word for word in re.findall(r'\w+', normalized(book.get('author')))
                    if len(word) >= 4 and word not in {'autor', 'autora', 'informado', 'fuente', 'google', 'books'}]
    return bool(author_words and any(word in text for word in author_words))


def retrieve_book_content(message, candidates):
    """Solo consulta la colección local; el texto no sale a motores de búsqueda."""
    from .local_embeddings import configured_embedder
    database = Path(getattr(settings, 'LITMATE_RAG_DB',
                            Path(settings.BASE_DIR) / 'data' / 'litmate_rag.sqlite3'))
    if not database.is_file():
        return []
    query = clean_text(message, 1800)
    titles = [b.get('title', '') for b in candidates[:2] if isinstance(b, dict)]
    identities = [b for b in candidates[:2] if isinstance(b, dict) and b.get('author')]
    key = _cache_key('litmate_content_v3:', query + repr(titles) + repr(identities)
        + str(database.stat().st_mtime_ns)
        + str(getattr(settings, 'LITMATE_RAG_SEMANTIC', True))
        + getattr(settings, 'LITMATE_EMBED_MODEL', 'embeddinggemma:latest'))
    cached = _cached(key)
    if cached is not None:
        return cached
    return _save(key, retrieve_fragments(query, database, 4, book_titles=titles,
        book_identities=identities,
        embedder=configured_embedder(settings),
        minimum_similarity=float(getattr(settings, 'LITMATE_RAG_MIN_SIMILARITY', 0.35))))


def trusted_url(value):
    url = safe_source_url(value)
    if not url:
        return ''
    host = urlsplit(url).hostname.lower()
    return url if any(host == domain or host.endswith('.' + domain) for domain in TRUSTED_DOMAINS) else ''


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skipped = [], 0
        self.skip_tags = {'script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'svg', 'noscript'}

    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self.skipped += 1
        elif not self.skipped and tag in {'p', 'li', 'h1', 'h2', 'h3', 'h4', 'section'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in self.skip_tags and self.skipped:
            self.skipped -= 1
        elif not self.skipped and tag in {'p', 'li', 'h1', 'h2', 'h3', 'h4', 'section'}:
            self.parts.append('\n')

    def handle_data(self, text):
        if not self.skipped:
            self.parts.append(text)


def read_public_page(url, query):
    """Solo sitios permitidos; no redirecciones, IP privada ni URL del lector."""
    url = trusted_url(url)
    if not url:
        return ''
    host = urlsplit(url).hostname
    # Open Library solicita usar su API. Google Books suele requerir JS:
    # en ambos casos conservamos el fragmento del buscador.
    if host.endswith('openlibrary.org') or host.startswith('books.google.'):
        return ''
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        return ''
    request = Request(url, headers={'User-Agent': _agent(), 'Accept': 'text/html'})
    import time
    deadline = time.monotonic() + budget_timeout(6)
    with build_opener(NoRedirects()).open(request, timeout=budget_timeout(6)) as response:
        if 'text/html' not in response.headers.get('Content-Type', ''):
            return ''
        raw = read_bounded(response, 400_000, deadline)
        encoding = response.headers.get_content_charset() or 'utf-8'
    check_budget()
    if len(raw) > 400_000:
        raw = raw[:400_000]
    parser = PageText()
    parser.feed(raw.decode(encoding, errors='replace'))
    text = ' '.join(parser.parts)[:60000]
    if len(text) < 100 or re.search(r'captcha|verify you are human|access denied', text[:1000], re.I):
        return ''
    return relevant_passage(text, query)


def _detail_focus(query):
    value = normalized(query)
    if re.search(r'\bpersonajes?|\bprotagonistas?|\bcharacters?|\bcaracterizacion', value):
        return ('personajes', 'protagonistas', 'characters', 'character list')
    if re.search(r'\bargumento|\btrama|\bresumen|\bsinopsis', value):
        return ('argumento', 'trama', 'sinopsis', 'plot', 'resumen')
    if re.search(r'\btemas?|\banalisis|\bideas?|\binterpretacion', value):
        return ('temas', 'analisis', 'interpretacion', 'themes')
    return ()


def relevant_passage(text, query, maximum=1800):
    """Prioriza la sección pedida por el lector sobre coincidencias del título."""
    text = str(text or '')[:60000]
    if not text.strip():
        return ''
    focus = _detail_focus(query)
    if focus:
        labels = '|'.join(re.escape(label) for label in focus)
        # TextExtracts wiki conserva encabezados; PageText conserva saltos de bloque.
        heading = re.search(r'(?im)^\s*(?:={2,}\s*)?(?:' + labels + r')'
                            r'(?: principales?| de la (?:obra|novela))?\s*(?:={2,})?\s*$', text)
        if heading:
            section = text[heading.start():]
            start_level = re.match(r'\s*(={2,})', heading.group(0))
            level = len(start_level.group(1)) if start_level else 2
            body_start = heading.end() - heading.start()
            for end in re.finditer(r'(?m)^\s*(={2,})[^=\n][^\n]*={2,}\s*$', section[body_start:]):
                # Los subtítulos (p. ej. familias de personajes) pertenecen a
                # la sección pedida; se corta sólo en el siguiente capítulo par.
                if len(end.group(1)) <= level:
                    section = section[:body_start + end.start()]
                    break
            if focus[0] == 'personajes':
                # Muchas fichas describen primero casas/grupos con varios párrafos;
                # sus listas breves de nombre y relación son la prueba pertinente.
                # Conservar líneas literales da cabida a más personajes sin resumir
                # ni cambiar relaciones con otro modelo.
                descriptions = [line.strip() for line in section.splitlines()
                    if len(line.strip()) <= 450 and re.match(
                        r'^(?:[-*]\s*)?[A-ZÁÉÍÓÚÑ][^\n,;:]{1,65}[,:]\s*\S', line.strip())
                    and not re.match(r'(?i)^(?:art[ií]culo principal|v[eé]ase|referencias?)\b', line.strip())]
                if len(descriptions) >= 2:
                    section = 'Personajes (descripciones del artículo):\n' + '\n'.join(descriptions)
            return clean_text(section, maximum)
    terms = [term for term in re.findall(r'\w+', normalized(query))
             if len(term) >= 4 and term not in STOPWORDS]
    windows = [text[start:start+maximum] for start in range(0, len(text), max(300, maximum // 3))]
    def score(block):
        value = normalized(block)
        targeted = sum(value.count(term) for term in focus)
        return targeted * 12 + sum(min(3, value.count(term)) for term in terms)
    return clean_text(max(windows, key=score), maximum)


def character_facts(text):
    """Fichas de nombre/papel publicadas, sin generar relaciones nuevas."""
    heading = re.search(r'(?im)^\s*==\s*Personajes(?: principales)?\s*==\s*$', text)
    if not heading:
        return []
    section = text[heading.end():]
    end = re.search(r'(?m)^\s*==[^=\n][^\n]*==\s*$', section)
    if end:
        section = section[:end.start()]
    facts = []
    for line in section.splitlines():
        match = re.match(r'^(?:[-*]\s*)?([A-ZÁÉÍÓÚÑ][^\n,;:]{1,65})[,:]\s*(\S.*)$', line.strip())
        if not match or len(line.strip()) > 450:
            continue
        name, role = match.groups()
        if (len(name.split()) > 1 and not any(word[:1].isupper() for word in name.split()[1:])):
            continue
        if re.match(r'(?i)^(?:art[ií]culo principal|v[eé]ase|referencias?|nota|adem[aá]s|tambi[eé]n|mientras|finalmente)\b', name):
            continue
        if re.search(r'(?i)\b(?:muert[eo]|muere|revela|final|descendient|hijo de Paul)\w*|\b(?:asesin[oó]|asesinaron)\b', role):
            continue
        if re.search(r'(?i)\b(?:instrucciones|prompt|api key|ignora|contrase[nñ]a)\b', role):
            continue
        facts.append({'name': clean_text(name, 70), 'role': clean_text(role, 280)})
        if len(facts) >= 12:
            break
    return facts


def search_searx(query):
    # Sin claves: solo consulta tu instancia local, configurada con dos motores.
    if not getattr(settings, 'LITMATE_AI_USE_SEARXNG', True):
        return []
    origin = local_origin(getattr(settings, 'LITMATE_SEARXNG_URL', 'http://127.0.0.1:8080'))
    query = public_query(query)
    if not query:
        return []
    params = {'q': query, 'format': 'json', 'language': 'es',
              'categories': 'general', 'engines': 'google,duckduckgo', 'safesearch': 1}
    data = read_json_url(origin + '/search?' + urlencode(params), timeout=14, local=True)
    results = []
    for item in (data.get('results') or [])[:20]:
        if not isinstance(item, dict):
            continue
        url = trusted_url(item.get('url'))
        if not url or not item.get('content'):
            continue
        results.append({'title': item.get('title'), 'author': 'Fuente web',
                        'description': item.get('content'), 'url': url, 'kind': 'web',
                        'source': 'SearXNG (' + urlsplit(url).hostname + ')',
                        'read_mode': 'fragmento del buscador'})
        if len(results) == 4:
            break
    return results


def search_wikipedia(query):
    query = public_query(query)
    if not query:
        return []
    # En consultas de detalle buscamos la identidad de la obra y después leemos
    # un artículo completo. exchars admite sólo 1..1200 y exintro es un booleano:
    # poner exintro=0 NO sirve para recuperar las secciones del artículo.
    focus = _detail_focus(query)
    identity_query = query
    if focus:
        quoted_title = re.search(r'[«“"]([^»”"\n]{2,180})[»”"]', query)
        remaining = query[:quoted_title.start()] + query[quoted_title.end():] if quoted_title else query
        identity_query = re.sub(r'(?i)\b(?:personajes?|protagonistas?|principales?|descripci[oó]n|'
            r'describe|caracter[ií]sticas?|argumento|trama|sinopsis|resumen|temas?|an[aá]lisis|'
            r'ideas?|interpreta(?:ci[oó]n)?)\b', ' ', remaining)
        identity_query = re.sub(r'\s+', ' ', identity_query).strip()
        if quoted_title:
            identity_query = 'intitle:"' + quoted_title.group(1) + '" ' + identity_query
        if not identity_query:
            identity_query = query
    params = {'action': 'query', 'format': 'json', 'generator': 'search',
              'gsrsearch': identity_query, 'gsrlimit': 2,
              'gsrnamespace': '0|104' if focus else 0, 'prop': 'extracts|info',
              'inprop': 'url', 'explaintext': 1, 'exintro': 1, 'exchars': 1200}
    data = read_json_url('https://es.wikipedia.org/w/api.php?' + urlencode(params),
                         headers={'User-Agent': _agent()}, timeout=6)
    pages = (data.get('query') or {}).get('pages') or {}
    pages = [page for page in (pages.values() if isinstance(pages, dict) else []) if isinstance(page, dict)]
    if focus and quoted_title:
        wanted = normalized(quoted_title.group(1))
        def same_work(page):
            title = normalized(page.get('title'))
            title = re.sub(r'\s*\((?:novela|libro|book|novel)\)\s*$', '', title)
            title = re.sub(r'^(?:anexo\s*:\s*)?(?:personajes|characters)\s+(?:de|of)\s+', '', title)
            return title == wanted
        matching = [page for page in pages if same_work(page)]
        if matching:
            # Una secuela o la biografía del autor no demuestra las relaciones
            # de los personajes de la obra concreta que eligió el lector.
            pages = matching
    if focus and pages:
        pages.sort(key=lambda page: (any(word in normalized(page.get('title')) for word in focus),
                                    '(novela)' in normalized(page.get('title'))), reverse=True)
        candidate = pages[0]
        page_id = str(candidate.get('pageid', ''))
        if page_id.isdigit() and int(page_id) > 0:
            try:
                details = {'action': 'query', 'format': 'json', 'pageids': page_id,
                           'prop': 'extracts|info', 'inprop': 'url', 'explaintext': 1,
                           'exsectionformat': 'wiki'}
                full = read_json_url('https://es.wikipedia.org/w/api.php?' + urlencode(details),
                                     headers={'User-Agent': _agent()}, timeout=6)
                full_page = ((full.get('query') or {}).get('pages') or {}).get(page_id)
                if isinstance(full_page, dict) and full_page.get('extract'):
                    pages[0] = {**candidate, **full_page,
                                'identity_text': clean_text(candidate.get('extract'), 1200),
                                'character_facts': character_facts(full_page['extract']) if focus[0] == 'personajes' else [],
                                'extract': relevant_passage(full_page['extract'], query),
                                'literary_section_read': True}
            except Exception as exc:
                logger.warning('IA: sección de Wikipedia no disponible (%s)', type(exc).__name__)
    return [{'title': page.get('title'), 'author': 'Fuente web', 'description': page.get('extract'),
             'identity_text': page.get('identity_text', ''), 'character_facts': page.get('character_facts', []),
             'kind': 'web', 'url': trusted_url(page.get('fullurl')),
             'source': 'Wikipedia', 'read_mode': 'pasaje de sección de artículo público' if page.get(
                 'literary_section_read') else 'extracto de introducción'}
            for page in pages[:2] if page.get('extract')]


def retrieve_web(query):
    query = public_query(query)
    if not query:
        return []
    key = _cache_key('litmate_local_web_v4:', query + ':'
                     + str(getattr(settings, 'LITMATE_AI_USE_SEARXNG', True)))
    cached = _cached(key)
    if cached is not None:
        return cached
    groups = []
    with pool_in_budget(3) as pool:
        jobs = [('Wikipedia', submit_with_budget(pool, search_wikipedia, query))]
        if getattr(settings, 'LITMATE_AI_USE_SEARXNG', True):
            jobs = [('SearXNG', submit_with_budget(pool, search_searx, query)),
                    ('Google Books web', submit_with_budget(pool, search_searx, 'site:books.google.com ' + query))] + jobs
        for name, future in jobs:
            try:
                groups.append(future.result(timeout=budget_timeout(20)))
            except Exception as exc:
                logger.warning('IA: búsqueda=%s error=%s', name, type(exc).__name__)
    results = [group[i] for i in range(4) for group in groups if i < len(group)]
    sources = canonical_sources(results, 4)
    for source in sources:
        source['retrieved_at'] = datetime.now(timezone.utc).isoformat()
    # Se extrae solo un pasaje relevante de dos páginas públicas, nunca todo el libro.
    def enrich(source):
        if source.get('read_mode') != 'fragmento del buscador':
            return source
        try:
            body = read_public_page(source['url'], query)
            if body:
                source = {**source, 'description': body, 'read_mode': 'pasaje de página pública'}
        except Exception as exc:
            logger.warning('IA: página no disponible (%s)', type(exc).__name__)
        return source
    with pool_in_budget(2) as pool:
        futures = [submit_with_budget(pool, enrich, source) for source in sources[:2]]
        for index, future in enumerate(futures):
            try:
                sources[index] = future.result(timeout=budget_timeout(8))
            except Exception as exc:
                logger.warning('IA: lectura web no disponible (%s)', type(exc).__name__)
    return _save(key, sources)
