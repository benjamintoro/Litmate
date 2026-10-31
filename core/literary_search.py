"""Google Books, catálogo, archivos locales y fuentes públicas complementarias."""
import hashlib
import ipaddress
import logging
import re
import socket
import sqlite3
import time
import unicodedata
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qs, quote
from urllib.request import Request, build_opener
from django.conf import settings
from django.core.cache import cache
from django.db.models import Case, IntegerField, Q, Value, When
from .ai_http import NoRedirects, local_origin, read_json_url, read_bounded
from .ai_budget import (budget_timeout, submit_with_budget, check_budget, pool_in_budget,
                        request_budget, current_deadline, CHAT_WORK_SECONDS, BudgetExpired)
from .literary_ai import canonical_sources, clean_text, normalized, safe_source_url, has_excerpt
from .local_rag import retrieve_fragments
from .books_google import (search_volumes, get_volume, volume_source, public_query, BooksUnavailable,
                          book_search_profile, book_search_queries, rank_book_sources, source_synopsis,
                          book_topic_profile, topic_matches)
from .literary_sources import (SearchResults, error_status, cooldown_seconds, reserve_page,
                               record_research_event)
from .ai_progress import measure_stage, timed_stage

logger = logging.getLogger('litmate')
STOPWORDS = {'libro', 'libros', 'novela', 'novelas', 'sobre', 'para', 'del', 'los',
             'las', 'una', 'que', 'con', 'por', 'quiero', 'dame', 'titulo',
             'recomienda', 'busco', 'buscar', 'the', 'and', 'books', 'book',
             'intitle', 'inauthor', 'title', 'author'}
TRUSTED_DOMAINS = ('wikipedia.org', 'wikisource.org', 'books.google.com',
                   'books.google.es', 'openlibrary.org', 'gutenberg.org',
                   'memoriachilena.gob.cl', 'bnchile.gob.cl', 'cervantesvirtual.com',
                   'rae.es', 'penguinlibros.com', 'planetadelibros.com',
                   'anagrama-ed.es', 'fce.com.mx', 'wikidata.org', 'literaturasm.cl',
                   'literaturasm.com', 'bibliotecanacionaldigital.gob.cl', 'ci.nii.ac.jp',
                   'penguin.co.uk', 'lepetitprince.com', 'metmuseum.org', 'tuttlepublishing.com')
# Descubrimiento a través de la API del buscador, sin permiso de extracción.
# Un enlace comercial no demuestra disponibilidad, precio ni lectura del libro.
DISCOVERY_ONLY_DOMAINS = ('amazon.com', 'amazon.es', 'buscalibre.cl', 'buscalibre.com',
                          'casadellibro.com', 'goodreads.com', 'barnesandnoble.com',
                          'gandhi.com.mx', 'worldcat.org', 'loc.gov',
                          'bibliotecanacional.gob.cl',
                          # Catálogos y publicaciones institucionales. Descubrir
                          # un enlace no concede licencia ni omite robots/SSRF.
                          'uns.edu.pe', 'pucp.edu.pe', 'unmsm.edu.pe',
                          'unapiquitos.edu.pe', 'clacso.edu.ar', 'ulibros.com')
# El descubrimiento de esta wiki no habilita acceso automatizado a Fandom.
# Su API técnicamente pública no sustituye el permiso exigido por sus términos.
DISCOVERY_ONLY_EXACT_HOSTS = ('lotr.fandom.com',)


def _retrieval_embedder():
    """En chat corto usa FTS ya indexado, sin cargar otra red neuronal en GPU.

    El diagnóstico/indexado offline conserva recuperación híbrida. En el chat,
    cambiar al modelo de embeddings puede gastar todo el turno antes
    de recuperar un solo pasaje; no modifica el índice ni sus evidencias.
    """
    if current_deadline() is not None and budget_timeout(30) <= CHAT_WORK_SECONDS:
        return None
    from .local_embeddings import configured_embedder
    return configured_embedder(settings)


def _agent():
    # Wikimedia distingue entre clientes sin identificar (10 req/min) y
    # clientes con un User-Agent de contacto (200 req/min). Sin URL o correo,
    # un turno real agota el cupo en pocas lecturas y bloquea las obras
    # siguientes. El contacto configurado tiene prioridad; el repositorio
    # público identifica la instalación cuando no existe otro dato.
    contact = clean_text(getattr(settings, 'LITMATE_BOOKS_CONTACT', ''), 100)
    contact = contact or 'https://github.com/benjamintoro/Litmate'
    return ('LitMate/Local-1.0 (' + contact + '; literary research)').encode(
        'ascii', 'ignore').decode()


def _cache_key(prefix, query):
    return prefix + hashlib.sha256(query.encode()).hexdigest()


def _cache_fingerprint(value):
    """Separa consultas que sólo difieren en acentos.

    La búsqueda de Wikipedia no es equivalente para «señor» y «senor»: la
    segunda puede devolver secuelas o adaptaciones antes que la obra. Por eso
    la caché conserva las marcas diacríticas; sólo unifica mayúsculas y espacios.
    """
    text = unicodedata.normalize('NFC', str(value or ''))
    text = ''.join(char for char in text if unicodedata.category(char) != 'Cf')
    return re.sub(r'\s+', ' ', text).strip().casefold()


def _cached(key):
    try:
        result = cache.get(key)
        return result if isinstance(result, list) else None
    except Exception:
        return None


def _save(key, result):
    try:
        # Una caída se gestiona con cooldown; no se anuncia como búsqueda vacía.
        if getattr(result, 'status', 'ok') not in {'unavailable', 'timeout', 'rate_limited', 'invalid_response'}:
            cache.set(key, result, int(getattr(settings, 'LITMATE_RESEARCH_CACHE_SECONDS', 86400)) if result else 60)
    except Exception:
        pass
    return result


@timed_stage('local_search')
def search_catalog(query):
    from .bibliographic_repository import lookup_sources
    structured = lookup_sources(query)
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
    return structured + [{'title': book.titulo, 'author': book.autor.nombre, 'description': book.sinopsis,
             'synopsis': book.sinopsis, 'image_url': safe_source_url(book.portada_url),
             'categories': [book.genero] if book.genero else [], 'language': book.idioma,
             'year': str(book.fecha_publicacion.year) if book.fecha_publicacion else '',
             'source': 'Catálogo LitMate', 'book_id': 'db_' + str(book.pk), 'kind': 'book'} for book in books]


def search_google(query, *, details=True):
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
        selected_ids = [source['book_id'] for source in sources[:2] if details and not source.get('synopsis')]
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
        return SearchResults(status=exc.code, providers={'Google Books': exc.code})


def _openlibrary_fetch(url, *, timeout):
    """Política conservadora de la API: como máximo un GET por segundo.

    El control cubre búsquedas y registros, y usa el mismo caché compartido
    configurado para Django. Una caída del caché no permite ráfagas sin control.
    """
    deadline = time.monotonic() + budget_timeout(min(timeout, 1.2))
    while True:
        try:
            if cache.add('litmate_ol_http_slot', True, timeout=1):
                break
        except Exception:
            raise TimeoutError('openlibrary_rate_control_unavailable') from None
        if time.monotonic() >= deadline:
            raise TimeoutError('openlibrary_local_rate_limit')
        check_budget()
        time.sleep(max(0, min(.05, deadline - time.monotonic())))
    record_research_event('http_request', 'Open Library', 'started')
    try:
        result = read_json_url(url, headers={'User-Agent': _agent()}, timeout=budget_timeout(timeout))
    except Exception as exc:
        record_research_event('http_request', 'Open Library', error_status(exc))
        raise
    record_research_event('http_request', 'Open Library', 'ok')
    return result


def search_openlibrary(query, *, details=True):
    from .literary_sources import research_scope, account_research
    # La búsqueda bibliográfica es una API existente, no otra consulta SearXNG;
    # su tiempo HTTP sí se descuenta del presupuesto externo compartido.
    with research_scope(getattr(settings, 'LITMATE_RESEARCH_MAX_SEARCHES', 2),
                        getattr(settings, 'LITMATE_RESEARCH_TIMEOUT', 15),
                        getattr(settings, 'LITMATE_RESEARCH_MAX_PAGES', 3)) as state:
        remaining = state['timeout'] - state['seconds']
        if remaining <= 0:
            return SearchResults(status='budget_exhausted')
        started = time.monotonic()
        try:
            with request_budget(started + budget_timeout(min(15, remaining))):
                return _search_openlibrary(query, details=details)
        finally:
            account_research(time.monotonic() - started)


def _openlibrary_description(value):
    value = value.get('value') if isinstance(value, dict) else value
    value = clean_text(value, 1600) if isinstance(value, str) else ''
    text = normalized(value)
    if text.strip(' .') in {
        'publisher description', 'no description available',
        'sin descripcion', 'sin descripcion disponible'}:
        return ''
    # Some work records put an ISBD physical extent in description. A count,
    # dimensions and illustration abbreviations are metadata, not a synopsis.
    # Reject only a complete physical statement; numbers inside prose and
    # genuinely short descriptions remain valid.
    units = {'p', 'pp', 'pag', 'pags', 'pagina', 'paginas', 'page', 'pages',
             'h', 'hoja', 'hojas', 'leaf', 'leaves', 'v', 'vol', 'vols',
             'volume', 'volumes', 'tomo', 'tomos', 'cm', 'mm', 'in', 'inch', 'inches'}
    attributes = {'ill', 'il', 'ilus', 'illustration', 'illustrations', 'ilustraciones',
                  'map', 'maps', 'mapa', 'mapas', 'col', 'color', 'coloured', 'colored',
                  'port', 'ports', 'portrait', 'portraits', 'retrato', 'retratos',
                  'plate', 'plates', 'lam', 'laminas', 'table', 'tables', 'tabla', 'tablas',
                  'diag', 'diags', 'diagram', 'diagrams', 'facs', 'facsims', 'fold'}
    tokens = re.findall(r'[^\W\d_]+|\d+(?:[.,]\d+)?|[^\w\s]', text)
    roman = re.compile(r'(?=[mdclxvi]+$)m{0,3}(?:cm|cd|d?c{0,3})'
                       r'(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})')
    def quantity(token):
        return bool(re.fullmatch(r'\d+(?:[.,]\d+)?', token)
                    or (token not in units and roman.fullmatch(token)))
    if (units.intersection(tokens) and any(quantity(token) for token in tokens)
            and all(token in units | attributes | {'.', ',', ':', ';', '(', ')', '[', ']', '+', '-', '/', '×'}
                    or quantity(token) for token in tokens)):
        return ''
    return value


def _openlibrary_edition_aliases(source, edition, *, evidence_url):
    """Variantes publicadas en ediciones anidadas de Search API.

    El subtítulo forma parte del alias si identifica una parte de la obra.
    Solo una edición expresamente completa admite también el título corto.
    Esto no transfiere sinopsis, autores, portadas ni argumentos entre obras.
    """
    if not isinstance(edition, dict):
        return
    work_id, edition_id = str(source.get('book_id', '')), str(edition.get('key', ''))
    if (not re.fullmatch(r'/works/OL\d+W', work_id)
            or not re.fullmatch(r'/books/OL\d+M', edition_id)
            or not source.get('author') or source.get('author') == 'Autor no informado'):
        return
    if 'works' in edition:
        works = edition['works']
        keys = {item.get('key') for item in works if isinstance(item, dict)} if isinstance(works, list) else set()
        if keys != {work_id}:
            return
    title = clean_text(edition.get('title'), 220) if isinstance(edition.get('title'), str) else ''
    subtitle = clean_text(edition.get('subtitle'), 600) if isinstance(edition.get('subtitle'), str) else ''
    original, translated = normalized(source.get('title')), normalized(title)
    if not translated or translated == original:
        return
    # Una extensión del título en el mismo idioma puede ser otra entrega; el
    # enlace de un catálogo colaborativo no autoriza borrar esa distinción.
    if translated.startswith(original + ' ') or original.startswith(translated + ' '):
        return
    complete = bool(re.search(r'\b(?:edici[oó]n completa|complete edition|complete in one volume)\b', subtitle, re.I))
    aliases = [title + (': ' + subtitle if subtitle else '')]
    if subtitle and complete:
        aliases.append(title)
    # La prueba conserva los campos y el anidamiento realmente recibidos, sin
    # presentar una paráfrasis del modelo como cita de la biblioteca.
    evidence = ('Search API: obra ' + source['title'] + '; autor ' + source['author']
        + '; work=' + work_id + '; edición anidada ' + title
        + ('; subtítulo=' + subtitle if subtitle else '') + '; edition=' + edition_id
        + '; título compuesto=' + aliases[0])
    values = source.setdefault('confirmed_aliases', [])
    for alias in aliases:
        if len(alias) <= 220 and not any(normalized(item.get('title')) == normalized(alias) for item in values):
            values.append({'title': alias, 'author': source['author'],
                           'source_url': evidence_url, 'evidence': evidence})


def _openlibrary_complete_edition_alias(source, edition, author_keys, *, reads):
    """Compara el alcance explícito de obra y edición; contar partes no basta."""
    if not isinstance(edition, dict) or not isinstance(author_keys, list):
        return
    authors = {key for key in author_keys if isinstance(key, str) and re.fullmatch(r'OL\d+A', key)}
    subtitle = str(edition.get('subtitle') or '')
    candidates = re.findall(r'(?:^|[/;|]\s*)([IVXLCDM]+|\d+)\s*[.:]\s*\S', subtitle)
    if not authors or len(set(candidates)) < 2:
        return
    work_id, edition_id = source.get('book_id', ''), edition.get('key', '')
    if not re.fullmatch(r'/books/OL\d+M', str(edition_id)):
        return
    work = _openlibrary_detail(work_id, editions=False, reads=reads)
    if not isinstance(work, dict):
        return
    actual_authors = {str(item.get('author', {}).get('key', '')).removeprefix('/authors/')
                      for item in work.get('authors', []) if isinstance(item, dict)
                      and isinstance(item.get('author'), dict)} if isinstance(work.get('authors'), list) else set()
    if actual_authors != authors or normalized(work.get('title')) != normalized(source.get('title')):
        return
    ranges = set()
    for item in work.get('series', []) if isinstance(work.get('series'), list) else []:
        position = re.fullmatch(r'\s*(\d+)\s*[-–]\s*(\d+)\s*', str(item.get('position', ''))) if isinstance(item, dict) else None
        if position:
            first, last = map(int, position.groups())
            if 1 <= first < last <= 20:
                ranges.add(tuple(range(first, last + 1)))
    if len(ranges) != 1:
        return
    roman = {name: index for index, name in enumerate((
        'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X',
        'XI', 'XII', 'XIII', 'XIV', 'XV', 'XVI', 'XVII', 'XVIII', 'XIX', 'XX'), 1)}
    stated_volumes = {int(value) if value.isdigit() else roman.get(value) for value in candidates}
    expected = set(next(iter(ranges)))
    if stated_volumes != expected:
        return
    record = _openlibrary_detail(edition_id, editions=False, reads=reads)
    if not isinstance(record, dict):
        return
    works = record.get('works')
    linked = {item.get('key') for item in works if isinstance(item, dict)} if isinstance(works, list) else set()
    if (linked != {work_id} or normalized(record.get('title')) != normalized(edition.get('title'))
            or normalized(record.get('subtitle')) != normalized(subtitle)):
        return
    volumes = set()
    for item in record.get('table_of_contents', []) if isinstance(record.get('table_of_contents'), list) else []:
        if not isinstance(item, dict) or item.get('level') != 0:
            continue
        match = re.match(r'(?i)^\s*(?:vol\.?|volumen|volume|tomo|parte|book)\s*(\d+)\b', str(item.get('title', '')))
        if match:
            volumes.add(int(match.group(1)))
    if volumes != expected:
        return
    title = clean_text(record.get('title'), 220)
    values = source.setdefault('confirmed_aliases', [])
    if any(normalized(item.get('title')) == normalized(title) for item in values):
        return
    evidence = ('Open Library: obra ' + source['title'] + '; autor ' + source['author']
        + '; work=' + work_id + '; alcance de obra=' + ','.join(map(str, sorted(expected)))
        + '; edición ' + title + '; edition=' + edition_id
        + '; works=' + work_id + '; volúmenes de tabla de contenido='
        + ','.join(map(str, sorted(volumes))) + '; author_keys=' + ','.join(sorted(authors)))
    values.append({'title': title, 'author': source['author'],
                   'source_url': 'https://openlibrary.org' + edition_id + '.json', 'evidence': evidence})


def _openlibrary_edition_metadata(source, edition, *, nested_in_work=False,
                                 requested_language=''):
    """Acepta metadatos de una edición vinculada por la API a la misma obra.

    El anidamiento de Search API es un vínculo documentado. En el endpoint
    de ediciones se exige además ``works`` explícito. No se siguen URLs ni
    enlaces aportados por los registros y un subtítulo nunca es una sinopsis.
    """
    if not isinstance(edition, dict):
        return False
    work_id = source.get('book_id', '')
    edition_id = str(edition.get('key') or '')
    if (not re.fullmatch(r'/works/OL\d+W', work_id)
            or not re.fullmatch(r'/books/OL\d+M', edition_id)):
        return False
    works = edition.get('works')
    if 'works' in edition:
        keys = {item.get('key') for item in works if isinstance(item, dict)} if isinstance(works, list) else set()
        if keys != {work_id}:
            return False
    elif not nested_in_work:
        return False
    # Metadatos inconsistentes de una saga no se arreglan por similitud.
    from .literary_identity import title_matches, _isbn_values
    if not title_matches(edition.get('title'), source):
        return False
    language_values = edition.get('language') if isinstance(edition.get('language'), list) else []
    languages = set(language_values if all(isinstance(value, str) for value in language_values) else [])
    if isinstance(edition.get('languages'), list):
        languages.update(str(item.get('key', '')).removeprefix('/languages/')
                         for item in edition['languages'] if isinstance(item, dict))
    if requested_language and requested_language not in languages:
        return False
    subtitle = clean_text(edition.get('subtitle'), 600) if isinstance(edition.get('subtitle'), str) else ''
    description = _openlibrary_description(edition.get('description'))
    if not subtitle and not description:
        return False
    edition_url = 'https://openlibrary.org' + edition_id
    source['edition'] = edition_id
    if subtitle:
        source['subtitle'] = subtitle
        source['description'] += '\nSubtítulo verificado de una edición: ' + subtitle
    if description and not source.get('synopsis'):
        source['synopsis'] = description
        source['description'] += '\nDescripción del registro de edición: ' + description
        source['description_source'] = 'Open Library, edición ' + edition_id.removeprefix('/books/')
        source['synopsis_source_url'] = edition_url
        source['read_mode'] = 'ficha y descripción de edición; no texto de la obra'
    identifiers = []
    for field in ('isbn_10', 'isbn_13'):
        if isinstance(edition.get(field), list):
            identifiers.extend(edition[field][:8])
    valid_isbns = _isbn_values({'isbns': identifiers})
    if valid_isbns:
        source['isbns'] = sorted(set(source.get('isbns', [])) | set(valid_isbns))
    if not source.get('synopsis'):
        source['read_mode'] = 'ficha y metadatos de edición; no texto de la obra'
    return True


def _openlibrary_detail(work_id, *, editions, reads):
    """Dos GET de detalle como máximo, compartidos por obras y ediciones."""
    if not (re.fullmatch(r'/works/OL\d+W', str(work_id))
            or (not editions and re.fullmatch(r'/books/OL\d+M', str(work_id)))):
        return None
    if not editions:
        from .literary_acquisition import local_openlibrary_detail
        local = local_openlibrary_detail(work_id)
        if local is not None:
            return local
    key = _cache_key('litmate_ol_editions_v1:' if editions else 'litmate_ol_work_v1:', work_id)
    try:
        detail = cache.get(key)
    except Exception:
        detail = None
    def valid_detail(value):
        return (isinstance(value, dict) and (isinstance(value.get('entries'), list)
                if editions else value.get('key') == work_id))
    if valid_detail(detail):
        return detail
    try:
        if cache.get('litmate_ol_cooldown'):
            return None
    except Exception:
        return None
    if reads['used'] >= 2 or not reserve_page():
        return None
    reads['used'] += 1
    url = 'https://openlibrary.org' + work_id + ('/editions.json?limit=5' if editions else '.json')
    try:
        detail = _openlibrary_fetch(url, timeout=4)
        if not valid_detail(detail):
            return None
        try:
            cache.set(key, detail, 86400)
        except Exception:
            pass
        return detail
    except Exception as exc:
        if error_status(exc) in {'rate_limited', 'access_denied', 'unauthorized'}:
            try:
                cache.set('litmate_ol_cooldown', error_status(exc), cooldown_seconds(exc))
            except Exception:
                pass
        return None


def enrich_discovery_book_records(sources):
    """Añade sinopsis opcionales a dos fichas verificadas, sin rehacer búsquedas.

    El enriquecimiento usa el caché, limitador HTTP y cupo de páginas del
    recuperador existente. Su presupuesto local deja un margen de publicación
    al turno padre; fallos o datos ausentes nunca eliminan las fichas obtenidas.
    No interpreta materias de catálogo como argumento ni consulta URLs ajenas.
    """
    if not isinstance(sources, list):
        return []
    result = [dict(source) if isinstance(source, dict) else source for source in sources]
    from .ai_catalog_fallback import _topic_catalogue_origin
    from .literary_web import public_text_has_injection
    try:
        available = budget_timeout(2.25) - .25
        if available <= 0:
            return result
        reads, visited = {'used': 0}, set()
        with request_budget(time.monotonic() + min(2., available)):
            for source in result:
                if (not isinstance(source, dict) or source.get('synopsis')
                        or source.get('research_summary') or len(visited) >= 2):
                    continue
                work_id = str(source.get('book_id', ''))
                try:
                    url = urlsplit(source.get('url', ''))
                    trusted = (_topic_catalogue_origin(source)
                        and 'Open Library' in str(source.get('source', '')).split(' / ')
                        and re.fullmatch(r'/works/OL\d+W', work_id)
                        and url.scheme == 'https' and url.hostname == 'openlibrary.org'
                        and not url.username and not url.password and not url.port
                        and not url.query and not url.fragment and url.path.rstrip('/') == work_id)
                except (TypeError, ValueError):
                    trusted = False
                if (not trusted or work_id in visited or public_text_has_injection(
                        str(source.get('description', '')))):
                    continue
                visited.add(work_id)
                detail = _openlibrary_detail(work_id, editions=False, reads=reads)
                if not isinstance(detail, dict) or detail.get('key') != work_id:
                    continue
                synopsis = _openlibrary_description(detail.get('description'))
                if not synopsis or public_text_has_injection(synopsis):
                    continue
                source.update(synopsis=synopsis, synopsis_source_url=source['url'],
                    description_source='Open Library, registro de obra',
                    read_mode='ficha y descripción bibliográfica; no texto de la obra')
                source['description'] = (str(source.get('description') or '')
                    + '\nSinopsis del registro bibliográfico: ' + synopsis).strip()
    except (BudgetExpired, TimeoutError, OSError, ValueError):
        pass  # La tarjeta original sigue siendo válida aunque falte sinopsis.
    return result


def _search_openlibrary(query, *, details=True):
    query = public_query(query)
    if not query:
        return []
    profile = book_topic_profile(query)
    # Los operadores pertenecen a cada catálogo: Google usa «inauthor»,
    # Open Library documenta «author». Conserva las comillas y el nombre.
    unquoted = normalized(re.sub(r'[«“"]([^»”"\n]*)[»”"]', ' ', query))
    requested_language = 'spa' if re.search(r'\b(?:en|idioma|al)\s+(?:espanol|castellano)\b', unquoted) else ''
    parts = re.split(r'("[^"\n]*"|«[^»\n]*»|“[^”\n]*”)', profile['query'])
    for index in range(0, len(parts), 2):
        # No reinterpretar «inauthor:» o «en español» dentro de un título.
        parts[index] = re.sub(r'(?i)(?<!\w)inauthor\s*:', 'author:', parts[index])
        parts[index] = re.sub(r'(?i)(?<!\w)intitle\s*:', 'title:', parts[index])
        if requested_language:
            parts[index] = re.sub(r'\b(?:en|idioma|al)\s+(?:espa[nñ]ol|castellano)\b',
                                   ' ', parts[index], flags=re.I)
    catalog_query = ''.join(parts).strip()
    if requested_language:
        catalog_query += ' language:' + requested_language
    requested_isbn = query[5:] if re.fullmatch(r'isbn:[\dX]{10,13}', query) else ''
    key = _cache_key('litmate_openlibrary_v10:', catalog_query + ':details=' + str(details) + ':fiction=' +
                     str(bool(re.search(r'\b(?:novelas?|ficcion|fiction)\b', normalized(query)))))
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        if cache.get('litmate_ol_cooldown'):
            return SearchResults(status='cooldown', providers={'Open Library': 'cooldown'})
        if not cache.add('litmate_local_ol_slot', True, timeout=2):
            return SearchResults(status='rate_limited', providers={'Open Library': 'local_rate_limit'})
    except Exception:
        return SearchResults(status='unavailable')
    params = {'q': catalog_query, 'limit': 12 if profile['structured'] else 5, 'lang': 'es',
              'fields': 'key,title,subtitle,author_name,author_key,first_publish_year,subject,cover_i,language,'
                        'editions,editions.key,editions.title,editions.subtitle,editions.language'}
    if not details:
        # Encontrar obras no requiere descargar sus ediciones ni sus sinopsis.
        params['fields'] = 'key,title,subtitle,author_name,first_publish_year,subject,cover_i,language'
    if requested_isbn:
        params['fields'] += ',isbn'
    search_url = 'https://openlibrary.org/search.json?' + urlencode(params)
    try:
        data = _openlibrary_fetch(search_url, timeout=6)
        if not isinstance(data, dict) or not isinstance(data.get('docs'), list):
            return SearchResults(status='invalid_response', providers={'Open Library': 'invalid_response'})
    except Exception as exc:
        status = error_status(exc)
        cache.set('litmate_ol_cooldown', status, cooldown_seconds(exc))
        return SearchResults(status=status, providers={'Open Library': status})
    results, alias_candidates = [], []
    for item in data['docs'][:12]:
        if not isinstance(item, dict):
            continue
        authors, subjects = item.get('author_name') or [], item.get('subject') or []
        work_id = str(item.get('key', ''))
        if re.fullmatch(r'OL\d+W', work_id):
            work_id = '/works/' + work_id
        if not re.fullmatch(r'/works/OL\d+W', work_id) or not item.get('title'):
            continue
        subjects = [clean_text(s, 100) for s in subjects[:80] if isinstance(s, str)] if isinstance(subjects, list) else []
        languages = item.get('language') if isinstance(item.get('language'), list) else []
        if requested_language and requested_language not in languages:
            continue
        source = {'title': clean_text(item.get('title'), 220),
                        'author': ', '.join(clean_text(a, 120) for a in authors[:5] if isinstance(a, str)) if isinstance(authors, list) else '',
                        'description': 'Temas del catálogo: ' + ', '.join(subjects[:12]),
                        'year': str(item.get('first_publish_year') or ''),
                        'categories': subjects,
                        'image_url': ('https://covers.openlibrary.org/b/id/' + str(item['cover_i']) + '-M.jpg'
                                      if type(item.get('cover_i')) is int and item['cover_i'] > 0 else ''),
                        'source': 'Open Library', 'book_id': work_id, 'kind': 'book',
                        'url': 'https://openlibrary.org' + work_id,
                        'read_mode': 'ficha bibliográfica; materias de catálogo, no texto de la obra'}
        if requested_language == 'spa':
            # El registro de obra confirma una edición en español, sin afirmar
            # que su portada o fecha genérica pertenezcan a esa edición.
            source['language'] = 'es'
        if not topic_matches(source, query):
            continue
        # canonical_sources conserva cinco categorías: primero las que respaldan
        # la materia/lugar pedido, sin sustituirlas por etiquetas inventadas.
        facets = profile['subjects'] + profile['places']
        representatives = []
        for row in facets:
            matching = next((subject for subject in subjects if any(re.search(
                r'(?<!\w)' + re.escape(term) + r'(?!\w)', normalized(subject)) for term in row[2])), '')
            if matching and matching not in representatives:
                representatives.append(matching)
        source['categories'] = (representatives + [subject for subject in subjects
                                                  if subject not in representatives])[:12]
        source['description'] = 'Temas del catálogo: ' + ', '.join(source['categories'])
        if requested_isbn and isinstance(item.get('isbn'), list):
            numbers = {re.sub(r'[\s-]', '', str(number)).upper() for number in item['isbn']}
            if requested_isbn in numbers:
                source['isbns'] = [requested_isbn]
                source['description'] += '\nISBN registrado: ' + requested_isbn + '.'
        if isinstance(item.get('subtitle'), str) and item['subtitle'].strip():
            source['subtitle'] = clean_text(item['subtitle'], 600)
            source['description'] += '\nSubtítulo del registro bibliográfico: ' + source['subtitle']
        editions = item.get('editions')
        if isinstance(editions, dict) and isinstance(editions.get('docs'), list):
            for edition in editions['docs'][:3]:
                _openlibrary_edition_aliases(source, edition, evidence_url=search_url)
                alias_candidates.append((source, edition, item.get('author_key')))
                if _openlibrary_edition_metadata(source, edition, nested_in_work=True,
                                                 requested_language=requested_language):
                    break
        results.append(source)
    results = rank_book_sources(results, query, distinct_works=True)[:5]
    if not details:
        return _save(key, SearchResults(results, providers={'Open Library': 'ok'}))
    reads = {'used': 0}
    for source, edition, author_keys in alias_candidates:
        if source in results and reads['used'] < 2:
            _openlibrary_complete_edition_alias(source, edition, author_keys, reads=reads)
    # Las fichas de búsqueda no traen sinopsis. Para las recomendaciones por
    # materia se consulta el registro oficial de hasta dos obras, con caché y
    # el mismo límite de lecturas que el resto de la investigación.
    if profile['structured']:
        for source in results[:2]:
            if source.get('synopsis'):
                continue
            detail = _openlibrary_detail(source['book_id'], editions=False, reads=reads)
            if not isinstance(detail, dict) or detail.get('key') != source['book_id']:
                continue
            synopsis = _openlibrary_description(detail.get('description'))
            if synopsis:
                source['synopsis'] = synopsis
                source['description'] += '\nSinopsis del registro bibliográfico: ' + source['synopsis']
                source['description_source'] = 'Open Library, registro de obra'
                source['synopsis_source_url'] = source['url']
                source['read_mode'] = 'ficha y descripción bibliográfica; no texto de la obra'
            else:
                editions = _openlibrary_detail(source['book_id'], editions=True, reads=reads)
                if isinstance(editions, dict):
                    for edition in editions.get('entries', [])[:5]:
                        if _openlibrary_edition_metadata(source, edition,
                                                         requested_language=requested_language):
                            break
    return _save(key, SearchResults(results, providers={'Open Library': 'ok'}))


def _polite_openlibrary_discovery(query):
    """Una consulta consecutiva puede esperar el slot local, no eludirlo.

    Un 429 remoto/cooldown nunca se reintenta aquí. Sólo la pausa local de dos
    segundos admite una repetición, compartiendo el deadline del descubrimiento.
    """
    found = search_openlibrary(query, details=False)
    if getattr(found, 'providers', {}).get('Open Library') != 'local_rate_limit':
        return found
    until = time.monotonic() + budget_timeout(2)
    try:
        while cache.get('litmate_local_ol_slot'):
            left = until - time.monotonic()
            if left <= 0:
                return found
            time.sleep(budget_timeout(min(.05, left)))
    except BudgetExpired:
        raise
    except Exception:
        return found
    return search_openlibrary(query, details=False)


@timed_stage('retrieval')
def retrieve_discovery_books(query, *, accept=None):
    """Busca fichas ligeras y retorna al tener opciones verificadas, no al último timeout.

    SQL y cada API tienen conexiones propias; nunca reciben sesión ni consumen
    cuota. ``accept`` es un validador local, no un veredicto del modelo. Se
    preservan las fichas ya obtenidas aunque otra fuente falle o quede pendiente.
    """
    from .literary_research import public_research_queries
    public = public_research_queries(query)
    if not public:
        return SearchResults(status='disabled')
    query = public[0]
    from .literary_knowledge import knowledge_revision, search_knowledge
    fingerprint = (book_topic_profile(query)['query'] + ':' + knowledge_revision(settings)
        + ':' + str(getattr(settings, 'LITMATE_AI_USE_OPENLIBRARY', True))
        + ':' + str(getattr(settings, 'LITMATE_USE_GOOGLE_BOOKS_API', False)))
    key = _cache_key('litmate_book_discovery_v1:', fingerprint)
    cached = _cached(key)
    if cached is not None and (accept is None or accept(cached)):
        return cached
    results = search_knowledge(query, maximum=8)
    if results and accept is not None and accept(results):
        return canonical_sources(results)

    def local_catalog():
        from django.db import connections
        try:
            return search_catalog(query)
        finally:
            connections.close_all()

    def google():
        return search_google(query, details=False)

    def openlibrary():
        return _polite_openlibrary_discovery(query)

    providers = {}
    jobs = [('Catálogo LitMate', local_catalog)]
    if getattr(settings, 'LITMATE_USE_GOOGLE_BOOKS_API', False):
        jobs.append(('Google Books', google))
    if getattr(settings, 'LITMATE_AI_USE_OPENLIBRARY', True):
        jobs.append(('Open Library', openlibrary))
    deadline = time.monotonic() + budget_timeout(getattr(settings, 'LITMATE_AI_DISCOVERY_SECONDS', 6))
    with pool_in_budget(len(jobs)) as pool:
        pending = {submit_with_budget(pool, function): name for name, function in jobs}
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            completed, _ = wait(pending, timeout=budget_timeout(remaining), return_when=FIRST_COMPLETED)
            if not completed:
                break
            for future in completed:
                name = pending.pop(future)
                try:
                    found = future.result()
                    results.extend(found)
                    providers[name] = getattr(found, 'status', 'ok' if found else 'empty')
                except Exception as exc:
                    providers[name] = error_status(exc)
            sources = canonical_sources(rank_book_sources(results, query, distinct_works=True))
            if sources and accept is not None and accept(sources):
                return _save(key, SearchResults(sources, providers=providers))
        for future, name in pending.items():
            providers[name] = 'timeout'
            future.cancel()
    sources = canonical_sources(rank_book_sources(results, query, distinct_works=True))
    failed = bool(pending) or any(value not in {'ok', 'empty', 'disabled'} for value in providers.values())
    status = 'partial' if failed and sources else 'unavailable' if failed else 'ok'
    return _save(key, SearchResults(sources, status=status, providers=providers))


@timed_stage('retrieval')
def retrieve_books(query):
    query = clean_text(query, 240)
    if not query:
        return []
    database = Path(getattr(settings, 'LITMATE_RAG_DB',
                            Path(settings.BASE_DIR) / 'data' / 'litmate_rag.sqlite3'))
    revision = str(database.stat().st_mtime_ns) if database.is_file() else 'sin-indice'
    google_revision = str(getattr(settings, 'LITMATE_USE_GOOGLE_BOOKS_API', True)) + ':' + hashlib.sha256(
        str(getattr(settings, 'GOOGLE_BOOKS_API_KEY', '')).encode()).hexdigest()[:12]
    from .literary_knowledge import search_knowledge, knowledge_revision
    from .bibliographic_repository import repository_revision
    key = _cache_key('litmate_hybrid_books_v12:', query + ':' + revision + ':' + knowledge_revision(settings) + ':' + repository_revision() + ':' + google_revision + ':'
                     + str(getattr(settings, 'LITMATE_RAG_SEMANTIC', True)) + ':'
                     + getattr(settings, 'LITMATE_EMBED_MODEL', 'embeddinggemma:latest'))
    cached = _cached(key)
    if cached is not None:
        return cached
    results = search_knowledge(query, maximum=8)
    try:
        results.extend(retrieve_fragments(query, database, 3,
                       embedder=_retrieval_embedder()))
    except Exception as exc:
        logger.warning('IA: índice local no disponible (%s)', type(exc).__name__)
    # Django/SQL permanece en el hilo de la petición; los hilos solo consultan HTTP.
    try:
        results.extend(search_catalog(query))
    except Exception as exc:
        logger.warning('IA: catálogo no disponible (%s)', type(exc).__name__)
    from .literary_identity import title_matches
    # Identidad directa ya disponible: no repetir APIs para la misma ficha.
    exact = [item for item in results if item.get('kind') == 'book' and
             (title_matches(query, item) or normalized(query) ==
              normalized(item.get('title', '') + ' ' + item.get('author', '')))]
    if exact:
        return _save(key, canonical_sources(exact + results, 8))
    if re.search(r'\b(?:recuerdo|recordaba|en que libro|no recuerdo)\b', normalized(query)):
        from .literary_research import assess_evidence
        if assess_evidence(query, canonical_sources(results), intent='identify')['sufficient']:
            return _save(key, canonical_sources(results, 8))
        try:
            from .literary_knowledge import search_knowledge_semantic
            semantic = search_knowledge_semantic(query, maximum=3, config=settings)
            results.extend(semantic)
            if assess_evidence(query, canonical_sources(results), intent='identify')['sufficient']:
                return _save(key, canonical_sources(results, 8))
        except Exception as exc:
            logger.warning('IA: recuperación de fichas semánticas no disponible (%s)', type(exc).__name__)
    # El texto completo puede consultarse localmente. La etapa externa exige
    # una consulta pública autorizada, incluso si procede del clasificador.
    from .literary_research import public_research_queries
    public_queries = public_research_queries(query)
    if not public_queries:
        return _save(key, canonical_sources(results, 8))
    external_query = public_queries[0]
    providers = {}
    with pool_in_budget(2) as pool:
        jobs = [('Google Books', submit_with_budget(pool, search_google, external_query))]
        if getattr(settings, 'LITMATE_AI_USE_OPENLIBRARY', True):
            jobs.append(('Open Library', submit_with_budget(pool, search_openlibrary, external_query)))
        for name, future in jobs:
            try:
                found = future.result(timeout=budget_timeout(25))
                results.extend(found)
                providers[name] = getattr(found, 'status', 'ok' if found else 'empty')
                if name == 'Google Books' and not getattr(settings, 'LITMATE_USE_GOOGLE_BOOKS_API', True):
                    providers[name] = 'disabled'
            except Exception as exc:
                providers[name] = error_status(exc)
                logger.warning('IA: fuente=%s error=%s', name, type(exc).__name__)
    # Mantiene fragmentos reales primero y evita que el límite de contexto elimine Google Books.
    results.sort(key=lambda item: (item.get('kind') == 'excerpt',
                                  item.get('source') == 'Google Books API'), reverse=True)
    grouped = {}
    for item in results:
        grouped.setdefault(item.get('source', ''), []).append(item)
    merged = [group[i] for i in range(6) for group in grouped.values() if i < len(group)]
    merged = rank_book_sources(merged, query)
    sources = canonical_sources(merged, 8)
    failed = any(status not in {'ok', 'empty', 'disabled'} for status in providers.values())
    status = 'partial' if failed and sources else 'unavailable' if failed else 'ok'
    return _save(key, SearchResults(sources, status=status, providers=providers))


def enrich_book_sources(sources, message=''):
    """Busca respaldo público para hasta dos fichas sin sinopsis, en siete segundos.

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
    deadline = time.monotonic() + budget_timeout(7)
    with request_budget(deadline):
        # MediaWiki recomienda solicitudes en serie; dos sinopsis pueden usar
        # la misma API. Comparten el límite total aunque la segunda quede en cola.
        with pool_in_budget(1) as pool:
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
                    found = future.result(timeout=budget_timeout(7))
                except Exception as exc:
                    logger.warning('IA: sinopsis complementaria no disponible (%s)', type(exc).__name__)
                    continue
                book = books[index]
                matching = [source for source in found if isinstance(source, dict)
                            and _web_matches_book(source, book)]
                if not matching:
                    record_research_event('supplementary_synopsis', 'web', 'no_verified_match')
                    continue
                from .literary_identity import bind_source
                matching = [{**bind_source({**source,
                    'title': str(source.get('title') or '').split(' | ', 1)[0].strip(),
                    'identity_text': str(source.get('identity_text') or '') + ' ' +
                        str(source.get('description') or '')}, book),
                    'title': source['title']} for source in matching]
                # Un snippet puede servir para descubrir una página, pero no
                # se convierte en sinopsis ni prueba de haber leído esa página.
                source = matching[0]
                summary = clean_text(source.get('description'), 1000)
                if not summary:
                    continue
                books[index] = {**book, 'research_summary': summary,
                    'synopsis_source_url': trusted_url(source.get('url')),
                    'description_source': str(source.get('source') or 'Fuente pública de respaldo')[:100]}
                record_research_event('supplementary_synopsis', 'web', 'ok', count=1)
                evidence.extend(matching[:1])
    selected_books = [source for source in books if source.get('kind', 'book') == 'book'][:5]
    other_sources = evidence + [source for source in books if source.get('kind', 'book') != 'book']
    # Reservar espacio a la prueba web evita que canonical_sources(maximum=8)
    # descarte justamente el respaldo con el que se completó la ficha.
    return selected_books + other_sources[:3]


def _web_matches_book(source, book):
    if (source.get('kind') != 'web' or not trusted_url(source.get('url'))
            or source.get('injection_detected') is True):
        return False
    if source.get('read_mode') not in {'pasaje de página pública',
            'extracto de introducción', 'pasaje de sección de artículo público'}:
        return False
    description = clean_text(source.get('description'), 1800)
    if len(description) < 60 or normalized(description).startswith('temas del catalogo:'):
        return False
    # Una mención secundaria del título o un apellido compartido no identifica
    # la obra de una página. Reutiliza la identidad bibliográfica y sus alias
    # confirmados, incluyendo la autoría completa en el contenido recuperado.
    from .literary_identity import same_work
    title = str(source.get('title') or '').strip()
    # Los títulos HTML suelen terminar en «| Editorial». No quitamos subtítulos
    # ni prefijos de sagas, que podrían identificar un volumen diferente.
    title = title.split(' | ', 1)[0].strip()
    candidate = {**source, 'title': title, 'identity_text':
        str(source.get('identity_text') or '') + ' ' + description}
    return same_work(candidate, book)


def retrieve_book_content(message, candidates):
    """Solo consulta la colección local; el texto no sale a motores de búsqueda."""
    from .local_embeddings import configured_embedder
    database = Path(getattr(settings, 'LITMATE_RAG_DB',
                            Path(settings.BASE_DIR) / 'data' / 'litmate_rag.sqlite3'))
    from .literary_knowledge import search_knowledge
    knowledge_query = message
    if candidates:
        knowledge_query += ' ' + str(candidates[0].get('title', ''))
    facts = search_knowledge(knowledge_query, maximum=5)
    from .ai_library_router import (library_books_for_query, library_fragments,
                                     library_revision)
    # El catálogo público puede devolver una edición con subtítulo y otro
    # nombre abreviado del autor. Si la consulta nombra una obra local, esa
    # identidad verificada prevalece para no perder el original autorizado.
    local_books = library_books_for_query(message, candidates)
    semantic = bool(getattr(settings, 'LITMATE_LIBRARY_SEMANTIC_CHAT', False))
    facts.extend(library_fragments(message, local_books or candidates,
                                   semantic=semantic, maximum=4))
    if not database.is_file():
        return facts
    query = clean_text(message, 1800)
    titles = [b.get('title', '') for b in candidates[:2] if isinstance(b, dict)]
    identities = [b for b in candidates[:2] if isinstance(b, dict) and b.get('author')]
    key = _cache_key('litmate_content_v4:', query + repr(titles) + repr(identities)
        + str(database.stat().st_mtime_ns) + repr(library_revision())
        + str(getattr(settings, 'LITMATE_RAG_SEMANTIC', True))
        + getattr(settings, 'LITMATE_EMBED_MODEL', 'embeddinggemma:latest'))
    cached = _cached(key)
    if cached is not None:
        return cached
    return _save(key, canonical_sources(facts + retrieve_fragments(query, database, 4, book_titles=titles,
        book_identities=identities,
        embedder=_retrieval_embedder(),
        minimum_similarity=float(getattr(settings, 'LITMATE_RAG_MIN_SIMILARITY', 0.35))), 8))


def trusted_url(value):
    url = safe_source_url(value)
    if not url:
        return ''
    host = urlsplit(url).hostname.lower()
    return url if any(host == domain or host.endswith('.' + domain) for domain in TRUSTED_DOMAINS) else ''


def discovery_url(value):
    """Admite enlaces públicos conocidos para mostrarlos; no autoriza un GET."""
    url = safe_source_url(value)
    if not url:
        return ''
    host = urlsplit(url).hostname.lower()
    return url if (host in DISCOVERY_ONLY_EXACT_HOSTS or any(
        host == domain or host.endswith('.' + domain)
        for domain in TRUSTED_DOMAINS + DISCOVERY_ONLY_DOMAINS)) else ''


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


def _catalogue_api_only(url):
    """Estos catálogos se consultan mediante su API, no gastan lecturas HTML."""
    host=(urlsplit(str(url or '')).hostname or '').lower()
    return host=='openlibrary.org' or host.endswith('.openlibrary.org') or host.startswith('books.google.')


def read_public_page(url, query, *, details=False):
    """Extractor controlado; nunca navega por una URL aportada por el modelo."""
    url = trusted_url(url)
    if not url:
        return ''
    host = urlsplit(url).hostname
    # Open Library solicita usar su API. Google Books suele requerir JS:
    # en ambos casos conservamos el fragmento del buscador.
    if _catalogue_api_only(url):
        return ''
    from .literary_web import extract_public_page
    with measure_stage('extraction'):
        result = extract_public_page(url, query, allowed_domains=TRUSTED_DOMAINS,
                                     timeout=budget_timeout(6))
    if details:
        return result
    return result.get('description', '') if result.get('status') == 'ok' else ''


def read_public_web_page(url, query, *, details=False):
    """Lee una página descubierta por un buscador general público.

    La URL no procede del lector ni del modelo: sólo de resultados de
    DuckDuckGo o motores autorizados del SearXNG local. Se exige HTTPS,
    host público, robots y tamaño máximo.
    """
    url = safe_source_url(url)
    if not url:
        return ''
    host = (urlsplit(url).hostname or '').lower()
    if _catalogue_api_only(url):
        return ''
    from .literary_web import extract_public_page
    with measure_stage('extraction'):
        result = extract_public_page(url, query, allowed_domains=('*',),
                                     timeout=budget_timeout(5))
    if details:
        return result
    return result.get('description', '') if result.get('status') == 'ok' else ''


_WIKIPEDIA_ARTICLES = {'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas',
                        'de', 'del', 'the', 'a', 'an', 'of'}
_WIKIPEDIA_DERIVATIVE = re.compile(
    r'\b(?:pelicula|film|serie de television|videojuego|banda sonora|soundtrack|'
    r'cinematografic\w*|juego de (?:cartas|rol|mesa|tablero))\b')
_WIKIPEDIA_MEDIA_QUALIFIER = re.compile(
    r'\b(?:pelicula|film|serie|videojuego|album|banda sonora|soundtrack|cancion|juego)\b')


def _wikipedia_title_tokens(value):
    """Palabras significativas para comparar una consulta con un título."""
    value = re.sub(r'(?i)\bintitle\s*:\s*', ' ', str(value or ''))
    return [word for word in re.findall(r'\w+', normalized(value))
            if word not in STOPWORDS and word not in _WIKIPEDIA_ARTICLES]


def _wikipedia_page_rank(page, identity_query, focus):
    """Prefiere la obra exacta frente a secuelas, adaptaciones y anexos.

    Wikipedia ordena por relevancia de búsqueda, pero una consulta sin tildes
    puede colocar la obra principal después de varias secuelas. La nota sólo se
    usa para elegir entre los candidatos ya devueltos por la API; no inventa
    títulos ni identifica la obra por sí sola.
    """
    title = normalized(page.get('title'))
    parenthetical = re.search(r'\s*\(([^)]*)\)\s*$', title)
    core = title[:parenthetical.start()].strip() if parenthetical else title
    title_words = _wikipedia_title_tokens(core)
    wanted_words = _wikipedia_title_tokens(identity_query)
    rank = 0
    if title_words and title_words == wanted_words:
        rank += 30
    elif title_words and wanted_words[:len(title_words)] == title_words:
        # El artículo es el título base y la consulta añade autor u otra pista.
        rank += 8
    rank += 2 * len(set(title_words) & set(wanted_words))
    if focus and any(word in title for word in focus):
        rank += 3
    if parenthetical:
        qualifier = normalized(parenthetical.group(1))
        if re.search(r'\b(?:novela|libro|book|novel)\b', qualifier):
            rank += 2
        elif re.search(r'\b(?:desambiguacion|disambiguation)\b', qualifier):
            rank -= 20
        elif _WIKIPEDIA_MEDIA_QUALIFIER.search(qualifier):
            rank -= 20
    if _WIKIPEDIA_DERIVATIVE.search(core):
        rank -= 20
    # A year in the title does not label an adaptation. Prefer the publication
    # type explicitly declared in the introduction before spending page reads.
    intro = normalized(page.get('extract', ''))[:900]
    book_type = re.search(r'\b(?:es|fue|is|was) (?:una?|an?|the) (?:\w+ ){0,3}(?:novela|novel|libro|book|obra literaria)\b', intro)
    media_type = re.search(r'\b(?:es|fue|is|was) (?:una?|an?|the) (?:\w+ ){0,4}(?:pelicula|cortometraje|film|movie|videojuego)\b', intro)
    if media_type and (not book_type or media_type.start() < book_type.start()):
        rank -= 60
    elif book_type:
        rank += 20
    return rank


def _detail_focus(query):
    value = normalized(query)
    if re.search(r'\bcontexto historico\b', value):
        return ('contexto historico', 'contexto histórico', 'historical context')
    if re.search(r'\badaptaciones\b|\badaptations\b', value):
        return ('adaptaciones', 'adaptations')
    if re.search(r'\b(?:personajes?|protagonistas?|antagonistas?|villanos?|characters?|'
                 r'caracterizacion|relacion|parentesco)\b|\bquien es\b', value):
        return ('personajes', 'protagonistas', 'characters', 'main characters', 'character list')
    if re.search(r'\bargumento|\btrama|\bresumen|\bsinopsis|\bdesenlace|\bfinal\b', value):
        return ('argumento', 'trama', 'sinopsis', 'plot', 'plot summary', 'summary', 'synopsis',
                'resumen', 'desenlace', 'final', 'la obra')
    if re.search(r'\btemas?|\banalisis|\bideas?|\binterpretacion', value):
        return ('temas', 'analisis', 'interpretacion', 'themes', 'contenido', 'contents')
    return ()


def main_work_plot(text):
    """Separate an explicitly prepended story from the main work's plot.

    Without an explicit main-work boundary the passage is insufficient; a
    related story must never become the novel's argument just by truncation.
    """
    value = re.sub(r'^\s*==+\s*(?:Argumento|Trama|Sinopsis|Resumen)\s*==+\s*', '', str(text), flags=re.I)
    prefix = re.match(r'(?i)^(?:En algunas ediciones,\s*)?(?:la novela|el libro|la obra)\s+'
        r'(?:va|está)\s+precedid[oa]\s+(?:del?|por)\s+(?:un |el |la )?(?:cuento|relato|prólogo)\b', value)
    if not prefix:
        return text
    start = re.search(r'(?im)^\s*(?:La novela|El libro|La obra|El argumento)(?: principal)?\s+'
                      r'(?:comienza|se inicia|empieza|narra|relata|sigue)\b', value[prefix.end():])
    return '== Argumento ==\n'+value[prefix.end()+start.start():].strip() if start else ''


def _plot_selection(section, maximum):
    """Bounded literal sampling across paragraphs, not only the opening.

    Distributed excerpts are a retrieval property, not a claim to know every
    event. Explicit ending sections and sentences announcing an ending stay out.
    """
    from .literary_quality import factual_statements
    section = main_work_plot(section)
    ending = re.search(r'(?im)^\s*={2,}\s*(?:el fin|final|desenlace|epílogo|ending|conclusion)\s*={2,}',section)
    if ending:
        section = section[:ending.start()]
    paragraphs = [line.strip() for line in section.splitlines() if line.strip()
                  and not re.match(r'^\s*={2,}',line)]
    candidates = []
    for index, paragraph in enumerate(paragraphs):
        lines = factual_statements(paragraph,strip_markers=False)
        if not lines:
            continue
        first = lines[0]
        value = normalized(first)
        if (not first.endswith(('.', '!', '?')) or not 30 <= len(first) <= 700
                or re.match(r'^(?:se expone un resumen|se presenta un resumen|invocacion a|exhortacion a)\b',value)
                or re.search(r'\b(?:finalmente|al final|desenlace|epilogo)\b',value[:100])
                or (not candidates and re.match(r'^(?:ella|ellos|ellas|este|esta|esto|estos|estas|su|sus|alli|entonces)\b',value))
                or (not candidates and re.match(r'^Él\b',first))
                or re.search(r'\b(?:maestria|recepcion|publicada|erudicion|critica literaria)\b',value)
                or re.match(r'^(?:lograr|conseguir|obtener|controlar|transformar|convertir|provocar)\b',value)):
            if candidates:
                break  # Do not splice across a missing antecedent or ending.
            continue
        # Conservar las primeras oraciones de la premisa: la segunda suele
        # presentar el conflicto o los personajes que dan sentido al viaje.
        # El muestreo posterior no debe sustituirlas por escenas aisladas.
        opening = first
        if not candidates:
            for line in lines[1:3]:
                if (line.endswith(('.', '!', '?')) and len(opening)+len(line)<min(900,maximum//2)
                        and not re.search(r'\b(?:finalmente|al final|desenlace|epilogo)\b',normalized(line))):
                    opening += ' ' + line
        candidates.append((index,opening))
    if not candidates:
        return {'passage':'','scope':'premise'}
    # A quick synopsis needs a connected sequence. Quartile sampling preserved
    # isolated facts but omitted their antecedents and causal transitions.
    chosen = []
    for item in candidates:
        proposed = '== Argumento ==\n'+'\n'.join(text for unused,text in [*chosen,item])
        if len(proposed) <= maximum:
            chosen.append(item)
        else:
            break
    if not chosen:
        return {'passage':clean_text(section,maximum),'scope':'premise'}
    passage = '== Argumento ==\n'+'\n'.join(text for unused,text in chosen)
    scope = 'sequential_excerpt' if len(chosen)>=2 else 'premise'
    return {'passage':clean_text(passage,maximum),'scope':scope}


def relevant_passage(text, query, maximum=1800, *, with_details=False):
    """Prioriza la sección pedida por el lector sobre coincidencias del título."""
    text = str(text or '')[:60000]
    if not text.strip():
        return ''
    focus = _detail_focus(query)
    if focus:
        labels = '|'.join(re.escape(label) for label in focus)
        # TextExtracts wiki conserva encabezados; PageText conserva saltos de bloque.
        heading = (re.search(r'(?im)(?:^|\s)={2,}\s*(?:' + labels + r')'
                            r'(?: principales?| de la (?:obra|novela))?\s*={2,}(?=\s|$)',text)
                   or re.search(r'(?im)^\s*(?:={2,}\s*)?(?:' + labels + r')'
                            r'(?: principales?| de la (?:obra|novela))?\s*(?:={2,})?\s*$', text)
                   )
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
            if focus[0] in {'argumento','trama','sinopsis','resumen'}:
                selected = _plot_selection(section,maximum)
                selected['topic']='plot'
                return selected if with_details else selected['passage']
            topic=('historical_context' if focus[0]=='contexto historico' else
                   'adaptations' if focus[0]=='adaptaciones' else 'themes' if focus[0]=='temas' else '')
            selected = {'passage':clean_text(section,maximum),'scope':'premise','topic':topic}
            return selected if with_details else selected['passage']
    terms = [term for term in re.findall(r'\w+', normalized(query))
             if len(term) >= 4 and term not in STOPWORDS]
    windows = [text[start:start+maximum] for start in range(0, len(text), max(300, maximum // 3))]
    def score(block):
        value = normalized(block)
        targeted = sum(value.count(term) for term in focus)
        return targeted * 12 + sum(min(3, value.count(term)) for term in terms)
    passage = clean_text(max(windows, key=score), maximum)
    return {'passage':passage,'scope':'premise'} if with_details else passage


def selected_section_facts(selection):
    """Only a published targeted section labels the topic of literal evidence.

    An arbitrary introductory window (often just title/publication metadata)
    must not become a plot, nor may a themes/context section become a plot.
    """
    if not isinstance(selection,dict) or selection.get('topic') not in {
            'plot','themes','historical_context','adaptations'}:
        return []
    from .literary_quality import factual_statements
    body=re.sub(r'==+[^=]+==+',' ',selection.get('passage','')).strip()
    proof=next((line for line in factual_statements(body) if 30<=len(line)<=1000),'')
    return ([{'topic':selection['topic'],'scope':selection.get('scope','partial'),'evidence':proof}]
            if proof else [])


def character_facts(text):
    """Fichas de nombre/papel publicadas, sin generar relaciones nuevas."""
    heading = re.search(r'(?im)^\s*==\s*(?:Personajes(?: principales)?|(?:Main )?Characters|Character list)\s*==\s*$', text)
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


def _duckduckgo_target(value):
    """Extrae el destino real de un enlace de DuckDuckGo Lite.

    Sólo acepta HTTPS público. Los enlaces patrocinados o internos del
    buscador se descartan antes de llegar a la extracción de la página.
    """
    href = str(value or '').strip()
    if href.startswith('//'):
        href = 'https:' + href
    try:
        parsed = urlsplit(href)
    except ValueError:
        return ''
    host = (parsed.hostname or '').lower()
    if host == 'duckduckgo.com' or host.endswith('.duckduckgo.com'):
        target = parse_qs(parsed.query).get('uddg', [''])
        href = target[0] if target else ''
    return safe_source_url(href)


def _provider_paused(key):
    if cache.get(key):
        return True
    from .ai_concurrency import pause_active
    try:
        return pause_active(key)
    except (OSError,ValueError,sqlite3.Error):
        return False  # La caché local conserva la pausa si el runtime está ocupado.


def _pause_provider(key,status,seconds):
    cache.set(key,status,seconds)
    from .ai_concurrency import pause_provider
    try:
        pause_provider(key,seconds)
    except (OSError,ValueError,sqlite3.Error):
        pass


def search_duckduckgo(query):
    """Buscador web general gratuito, sin clave ni cookies.

    DuckDuckGo Lite publica una página HTML sencilla y su robots.txt permite
    el acceso. Se conserva únicamente título, fragmento y URL; la lectura de
    cada página se hace después con comprobaciones de robots, DNS y tamaño.
    """
    if not getattr(settings, 'LITMATE_AI_USE_WEB', True):
        return SearchResults(status='disabled')
    from .literary_research import bibliographic_web_query, public_research_queries
    public = public_research_queries(query)
    query = bibliographic_web_query(public[0]) if public else ''
    if not query:
        return SearchResults(status='empty')
    key = _cache_key('litmate_ddg_v2:', query + ':es')
    cached = _cached(key)
    if cached is not None:
        return cached
    if _provider_paused('litmate_ddg_cooldown'):
        return SearchResults(status='cooldown')
    from .literary_web import public_text_has_injection, read_public_html
    params = {'q': query, 'kl': 'es-es'}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                             'AppleWebKit/537.36 (KHTML, like Gecko) '
                             'Chrome/124.0 Safari/537.36 LitMate/1.0',
               'Accept-Language': 'es-ES,es;q=0.9,en;q=0.6'}
    try:
        record_research_event('http_request', 'DuckDuckGo', 'started')
        html = read_public_html('https://lite.duckduckgo.com/lite/?' + urlencode(params),
                                headers=headers, timeout=4,
                                allowed_domains=('lite.duckduckgo.com',),
                                maximum=1_000_000)
    except Exception as exc:
        status = 'access_denied' if getattr(exc, 'code', '') == 'http_202' else error_status(exc)
        record_research_event('http_request', 'DuckDuckGo', status)
        _pause_provider('litmate_ddg_cooldown',status,
                        3600 if status=='access_denied' else cooldown_seconds(exc))
        return SearchResults(status=status)
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        if soup.select_one('#challenge-form, .anomaly-modal, form[action*="anomaly.js"]'):
            record_research_event('http_request', 'DuckDuckGo', 'access_denied')
            _pause_provider('litmate_ddg_cooldown','access_denied',3600)
            return SearchResults(status='access_denied', providers={'DuckDuckGo': 'access_denied'})
        # El enlace y su fragmento ocupan filas distintas. No emparejar dos
        # listas tras filtrar URLs: una URL rechazada desalinearía las pruebas.
        links, current = [], None
        for row in soup.select('tr'):
            anchor = row.select_one('a.result-link')
            sponsored = 'result-sponsored' in (row.get('class') or [])
            if anchor is not None or sponsored:
                current = None
            if anchor is not None and not sponsored:
                current = {'url': _duckduckgo_target(anchor.get('href')),
                           'title': clean_text(anchor.get_text(' ', strip=True), 300),
                           'snippet': ''}
                links.append(current)
            cell = row.select_one('td.result-snippet')
            if cell is not None and current is not None and not sponsored:
                current['snippet'] = clean_text(cell.get_text(' ', strip=True), 700)
    except Exception:
        record_research_event('http_request', 'DuckDuckGo', 'invalid_response')
        _pause_provider('litmate_ddg_cooldown','invalid_response',300)
        return SearchResults(status='invalid_response')
    results, seen = [], set()
    for item in links[:20]:
        title, url, snippet = item['title'], item['url'], item['snippet']
        host = (urlsplit(url).hostname or '').lower()
        if (not host or not title or host == 'duckduckgo.com'
                or host.endswith('.duckduckgo.com') or url in seen
                or public_text_has_injection(title + ' ' + snippet)):
            continue
        seen.add(url)
        results.append({
            'title': title, 'author': 'Fuente web',
            'description': snippet or title, 'url': url, 'kind': 'web',
            'source': 'DuckDuckGo', 'site': host,
            'read_mode': 'fragmento del buscador', 'trust': 'untrusted_data',
            'permanent_index_allowed': False,
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
        })
        if len(results) >= 8:
            break
    if not results:
        record_research_event('http_request', 'DuckDuckGo', 'empty')
        return _save(key, SearchResults(status='empty', providers={'DuckDuckGo': 'empty'}))
    record_research_event('http_request', 'DuckDuckGo', 'ok', count=len(results))
    return _save(key, SearchResults(results, status='ok', providers={'DuckDuckGo': 'ok'}))


def search_searx(query, *, web=False):
    # Sin claves. Lista cerrada: ninguna entrada del lector elige motores.
    if not getattr(settings, 'LITMATE_AI_USE_SEARXNG', True):
        return []
    origin = local_origin(getattr(settings, 'LITMATE_SEARXNG_URL', 'http://127.0.0.1:8080'))
    query = public_query(query)
    if not query:
        return []
    allowed = {'wikipedia', 'openlibrary', 'mwmbl', 'wikidata', 'duckduckgo', 'qwant'}
    engines = (getattr(settings, 'LITMATE_SEARXNG_WEB_ENGINES', ('mwmbl', 'duckduckgo'))
               if web else getattr(settings, 'LITMATE_SEARXNG_ENGINES', ('wikipedia', 'openlibrary', 'mwmbl')))
    engines = [engine for engine in engines if engine in allowed]
    if web and _provider_paused('litmate_ddg_cooldown'):
        # La caída del buscador general no elimina los catálogos ya habilitados.
        engines.extend(engine for engine in getattr(settings,'LITMATE_SEARXNG_ENGINES',
            ('wikipedia','openlibrary','mwmbl')) if engine in allowed-{'duckduckgo','qwant'})
    engines=list(dict.fromkeys(engines))
    if not engines:
        return SearchResults(status='disabled')
    key = _cache_key('litmate_searx_json_v2:', origin + ':' + _cache_fingerprint(query) + ':' + ','.join(engines))
    cached = _cached(key)
    if cached is not None:
        return cached
    if cache.get('litmate_searx_cooldown'):
        return SearchResults(status='cooldown')
    engine_pause = lambda engine: _cache_key('litmate_searx_engine_pause:', origin + ':' + engine)
    ready = [engine for engine in dict.fromkeys(engines) if not _provider_paused(engine_pause(engine))
             and not (engine=='duckduckgo' and _provider_paused('litmate_ddg_cooldown'))]
    if not ready:
        return SearchResults(status='cooldown', providers={engine: 'cooldown' for engine in engines})
    params = {'q': query, 'format': 'json', 'language': 'es',
              'engines': ','.join(ready), 'safesearch': 1}
    try:
        record_research_event('http_request', 'SearXNG', 'started')
        data = read_json_url(origin + '/search?' + urlencode(params), timeout=6, local=True)
    except Exception as exc:
        status = error_status(exc)
        record_research_event('http_request', 'SearXNG', status)
        cache.set('litmate_searx_cooldown', status, cooldown_seconds(exc))
        return SearchResults(status=status)
    if (not isinstance(data, dict) or not isinstance(data.get('results'), list)
            or not isinstance(data.get('unresponsive_engines', []), list)):
        record_research_event('http_request', 'SearXNG', 'invalid_response')
        return SearchResults(status='invalid_response')
    record_research_event('http_request', 'SearXNG', 'ok', count=len(data['results']))
    results = []
    for item in (data.get('results') or [])[:20]:
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get('title'), str) or not item['title'].strip():
            continue
        if not isinstance(item.get('content', ''), str) or not isinstance(item.get('url'), str):
            continue
        # La búsqueda web usa la misma admisión HTTPS pública que DuckDuckGo.
        # Mostrar un destino no autoriza su lectura: DNS/IP, redirecciones,
        # robots e inyección se comprueban en el lector público existente.
        url = (safe_source_url(item.get('url')) if web else discovery_url(item.get('url')))
        if not url:
            continue
        results.append({'title': item.get('title'), 'author': 'Fuente web',
                        'description': item.get('content', ''), 'url': url, 'kind': 'web',
                        'source': 'SearXNG (' + urlsplit(url).hostname + ')',
                        'read_mode': 'fragmento del buscador',
                        'search_engines': [name for name in item.get('engines', [])
                                           if isinstance(name, str) and name in allowed]
                        if isinstance(item.get('engines'), list) else []})
    # El orden del metabuscador mezcla catálogos y páginas. Recortar antes de
    # comprobar relevancia ocultaba páginas útiles detrás de cinco fichas sin
    # descripción. El ranking sólo elige candidatos; nunca prueba su contenido.
    terms={word for word in re.findall(r'\w{3,}',normalized(query))
           if word not in STOPWORDS|{'argumento','trama','sinopsis','personajes','contenido'}}
    def relevance(source):
        title_words=set(re.findall(r'\w{3,}',normalized(source['title'])))
        body_words=set(re.findall(r'\w{3,}',normalized(source['description'])))
        return len(terms&title_words)*4+len(terms&body_words),len(source['description'])>=60
    if terms:
        results.sort(key=relevance,reverse=True)
    chosen,seen,catalogue_count=[],set(),0
    has_readable_candidate=any(urlsplit(s['url']).hostname!='openlibrary.org'
                              and (not terms or relevance(s)[0]) for s in results)
    for source in results:
        if source['url'] in seen:
            continue
        catalogue=urlsplit(source['url']).hostname=='openlibrary.org'
        if catalogue and catalogue_count>=2 and has_readable_candidate:
            continue
        chosen.append(source);seen.add(source['url']);catalogue_count+=int(catalogue)
        if len(chosen)==5:
            break
    results=chosen
    failures = data.get('unresponsive_engines') or []
    for item in failures:
        if not isinstance(item, list) or len(item) < 2 or item[0] not in allowed:
            continue
        reason = str(item[1]).lower()
        seconds = 3600 if 'captcha' in reason else 180 if any(
            word in reason for word in ('denied','too many','toomanyrequests','429')) else 30
        _pause_provider(engine_pause(item[0]),str(item[1])[:60],seconds)
        if item[0] == 'duckduckgo':
            # No volver a probar otro endpoint de ese mismo proveedor tras un
            # CAPTCHA/rechazo; el fallback debe usar un proveedor distinto.
            _pause_provider('litmate_ddg_cooldown',str(item[1])[:60],seconds)
    result = SearchResults(results, status='partial' if failures and results else
                         'unavailable' if failures else 'ok' if results else 'empty',
                         providers={str(item[0])[:40]: str(item[1])[:60]
                                    for item in failures if isinstance(item, list) and len(item) >= 2})
    if failures:
        # Preserve usable hits without hiding an engine's recovery for a day.
        if results:
            cache.set(key, result, 30)
        return result
    return _save(key, result)


def _wikipedia_cooldown_key(host):
    return 'litmate_wikipedia_cooldown:' + str(host or 'wikipedia.org')


def _wikipedia_spanish_counterpart(candidate, *, query=''):
    """Follow one official language link, preserving bibliographic identity.

    Never fetch a URL supplied in a page. A bounded title query uses the fixed
    Spanish API, and both pages must identify the same Wikidata item, author
    and literary medium before a cross-language title becomes an alias.
    Missing/ambiguous data simply leaves the English source in use.
    """
    from .literary_identity import _verified_web_work, same_author_name, ambiguous_work_page, published_title_alias
    qid = (candidate.get('pageprops') or {}).get('wikibase_item', '')
    links = candidate.get('langlinks', [])
    title = next((link.get('*', '') for link in links if isinstance(link, dict)
                  and link.get('lang') == 'es'), '') if isinstance(links, list) else ''
    if (not re.fullmatch(r'Q[1-9]\d*', str(qid)) or not isinstance(title, str)
            or not 2 <= len(title) <= 220 or re.search(r'[|#\\/\x00-\x1f]', title)
            or cache.get(_wikipedia_cooldown_key('es.wikipedia.org'))):
        return None
    def identity(page):
        return _verified_web_work({'kind':'web','source':'Wikipedia','title':page.get('title'),
            'url':page.get('fullurl'),'identity_text':page.get('extract'),
            'read_mode':'extracto de introducción',**_wikipedia_storage_metadata(page)})
    original = identity(candidate)
    if not original:
        return None
    endpoint = 'https://es.wikipedia.org/w/api.php?'
    params = {'action':'query','format':'json','titles':title,'redirects':1,
        'prop':'extracts|info|revisions|pageprops','ppprop':'disambiguation|wikibase_item',
        'rvprop':'ids','inprop':'url','explaintext':1,'exintro':1,'exchars':1200}
    if query:
        if not reserve_page():
            return None
        params.pop('exintro')
        params.pop('exchars')
        params['exsectionformat']='wiki'
    payload = _wikipedia_fetch(endpoint + urlencode(params))
    pages = ((payload.get('query') or {}).get('pages') or {}) if isinstance(payload,dict) else {}
    for page in pages.values() if isinstance(pages,dict) else []:
        if (not isinstance(page,dict) or 'missing' in page or ambiguous_work_page(page)
                or (page.get('pageprops') or {}).get('wikibase_item') != qid):
            continue
        intro = re.split(r'(?m)^\s*==+',str(page.get('extract','')),maxsplit=1)[0]
        translated = identity({**page,'extract':intro})
        if not translated or not same_author_name(original['author'],translated['author']):
            continue
        if query:
            selection=relevant_passage(page.get('extract',''),query,with_details=True)
            # A Spanish character list or publication lead is not a plot.
            # Prefer the original English article when the localized article
            # does not contain evidence for this particular question.
            premise=bool(re.search(r'\b(?:narra|relata|trata de|historia de|se centra|sigue)\b',normalized(intro)))
            if selection.get('topic')!='plot' and not premise:
                record_research_event('interlanguage_identity','Wikipedia','insufficient_plot')
                return None
        proof = ('MediaWiki langlinks: title=' + str(candidate['title']) + '; lang=es; title='
            + str(page['title']) + '; wikibase_item=' + qid + '; revisions='
            + str(candidate['revisions'][0]['revid']) + ',' + str(page['revisions'][0]['revid']))
        aliases=[{'title':candidate['title'],'source_url':candidate['fullurl'],'evidence':proof}]
        hint=re.search(r'[«“"]([^»”"\n]{2,180})[»”"]',query)
        original_page={'kind':'web','source':'Wikipedia','title':candidate['title'],
            'url':candidate['fullurl'],'identity_text':candidate.get('extract',''),
            **_wikipedia_storage_metadata(candidate)}
        if hint and published_title_alias(original_page,hint[1]):
            # Preserve the explicit published subtitle, not an inferred prefix
            # equivalence. Keep both the original lead and cross-language IDs
            # in the structured proof rather than fabricating a quotation.
            aliases.append({'title':hint[1],'source_url':candidate['fullurl'],
                'evidence':proof.replace('; lang=es;', '; published_title='+hint[1]
                    +'; lead='+clean_text(candidate.get('extract'),700)+'; lang=es;',1)})
        record_research_event('interlanguage_identity','Wikipedia','ok',count=1)
        return {**page,'confirmed_aliases':aliases,**({'_prefetched_document':True,
            'identity_text':clean_text(intro,1200)} if query else {})}
    return None


def search_wikipedia(query):
    """API oficial: español primero; inglés solo si falta una página utilizable."""
    # Sólo se conserva durante un turno real. Los comandos y las pruebas deben
    # observar cada petición y no recibir páginas de otra consulta/contexto.
    active = current_deadline() is not None
    cache_name = _cache_key('litmate_local_wikipedia_v5:', _cache_fingerprint(query) + ':pages='
                            + str(getattr(settings, 'LITMATE_RESEARCH_MAX_PAGES', 3)))
    if active:
        cached = _cached(cache_name)
        if cached is not None:
            return cached

    def finish(result):
        return _save(cache_name, result) if active else result

    statuses, spanish_alternatives = {}, []
    query_terms = {word for word in re.findall(r'\w+', normalized(query)) if len(word) >= 3
                   and word not in STOPWORDS | {'the', 'with', 'of', 'una', 'del',
                       'personajes', 'principales', 'argumento', 'trama', 'sinopsis'}}
    for language in ('es', 'en'):
        # El límite es por host: un 429 en español no impide probar inglés.
        if cache.get(_wikipedia_cooldown_key(language + '.wikipedia.org')):
            statuses[language] = 'cooldown'
            continue
        try:
            result = _search_wikipedia(query, language=language)
            statuses[language] = 'ok' if result else 'empty'
            if result:
                from .literary_identity import published_title_alias, _literal_title, _verified_web_work
                title_hint=re.search(r'[«“"]([^»”"\n]{2,180})[»”"]',query)
                def same_article_title(source):
                    if not title_hint or not _verified_web_work(source):
                        return False
                    bare=lambda label:re.sub(r'^(?:el|la|los|las|the)\s+','',normalized(_literal_title(label)))
                    return bare(source.get('title'))==bare(title_hint[1])
                # La API puede devolver artículos tangenciales aun sin ninguna
                # palabra identificativa del título. No cerrar por eso la etapa
                # multilingüe (p. ej. artículo sobre una ceremonia en vez del libro).
                usable = (any(normalized(_literal_title(source.get('title'))).replace(' ','')
                              == normalized(_literal_title(title_hint[1])).replace(' ','')
                              or published_title_alias(source,title_hint[1]) or same_article_title(source) for source in result)
                          if title_hint else any(query_terms & set(re.findall(r'\w+', normalized(source.get('title'))))
                              or normalized(source.get('title')).replace(' ', '') in query_terms for source in result))
                if language == 'es' and query_terms and not usable:
                    spanish_alternatives = result
                    continue
                return finish(SearchResults(result, status='partial' if any(
                    value not in {'ok', 'empty'} for value in statuses.values()) else 'ok',
                    providers={'Wikipedia (' + key + ')': value for key, value in statuses.items()}))
        except Exception as exc:
            statuses[language] = error_status(exc)
    failed = any(value not in {'ok', 'empty'} for value in statuses.values())
    if (not spanish_alternatives and 'cooldown' in statuses.values()
            and all(value in {'cooldown', 'empty'} for value in statuses.values())):
        status = 'cooldown'
    elif failed:
        status = 'partial' if spanish_alternatives else 'unavailable'
    else:
        status = 'ok' if spanish_alternatives else 'empty'
    return finish(SearchResults(spanish_alternatives, status=status,
                         providers={'Wikipedia (' + key + ')': value for key, value in statuses.items()}))


def _wikipedia_fetch(url):
    record_research_event('http_request', 'Wikipedia', 'started')
    try:
        result = read_json_url(url, headers={'User-Agent': _agent()}, timeout=6)
    except Exception as exc:
        status = error_status(exc)
        if status == 'rate_limited':
            # Un 429 sostenido no debe convertirse en una ráfaga de reintentos
            # dentro del mismo turno ni en la siguiente pregunta del lector.
            # La pausa se limita al host afectado: la Wikipedia inglesa sigue
            # disponible aunque la española haya agotado su cupo.
            cache.set(_wikipedia_cooldown_key(urlsplit(url).hostname), status,
                      cooldown_seconds(exc))
        record_research_event('http_request', 'Wikipedia', status)
        raise
    record_research_event('http_request', 'Wikipedia', 'ok')
    return result


def _wikipedia_appendix_links(html, work_title, *, current_title=''):
    """Anexos de personajes enlazados por el artículo de la obra.

    Sólo acepta enlaces internos cuyo título sea un anexo de personajes de
    esa misma obra. Un enlace a una adaptación, a una saga o a una página de
    desambiguación no se convierte en una segunda obra.
    """
    from bs4 import BeautifulSoup
    from urllib.parse import unquote
    soup = BeautifulSoup(str(html or ''), 'html.parser')
    work = normalized(work_title)
    work = re.sub(r'^(?:el|la|los|las|the)\s+', '', work)
    if not work:
        return []
    current = normalized(current_title)
    links, seen = [], set()
    for anchor in soup.find_all('a', href=True):
        href = str(anchor.get('href') or '')
        if not href.startswith('/wiki/'):
            continue
        target = unquote(href[len('/wiki/'):].split('#', 1)[0]).replace('_', ' ')
        norm = normalized(target)
        if not norm or norm == current or norm in seen:
            continue
        match = re.match(r'^(?:anexo\s*:\s*)?(?:lista de )?(?:personajes|characters)\s+'
                         r'(?:de|del|of|in)\s+(.+)$', norm)
        if not match:
            continue
        rest = match.group(1).strip()
        rest = re.sub(r'^(?:la |el |los |las )?(?:novela|obra|libro|serie|saga|historia)\s+',
                      '', rest)
        bare = re.sub(r'^(?:el|la|los|las|the)\s+', '', rest)
        if bare != work:
            continue
        seen.add(norm)
        links.append(target)
    return links


def _wikipedia_parse_document(candidate, page_id, endpoint, *, query=''):
    """Lee la página completa por Parse y conserva listas y tablas."""
    parsed = _wikipedia_fetch(endpoint + urlencode({'action': 'parse', 'format': 'json',
        'pageid': page_id, 'prop': 'text|revid', 'disableeditsection': 1, 'disabletoc': 1}))
    article = parsed.get('parse') if isinstance(parsed, dict) else None
    if (not isinstance(article, dict) or str(article.get('pageid')) != page_id
            or normalized(article.get('title')) != normalized(candidate.get('title'))):
        return None
    from .literary_web import character_content
    html = article.get('text')
    html = html.get('*') if isinstance(html, dict) else html
    title = article.get('title') or candidate.get('title', '')
    content = character_content(html, context=candidate.get('extract', '') + '\n' + query,
                                title=title)
    revision = article.get('revid')
    return {**candidate,
            'extract': content['passage'],
            'character_facts': content['character_facts'],
            'parse_read': True,
            'appendix_titles': _wikipedia_appendix_links(html, candidate.get('title', ''),
                                                          current_title=title),
            'revisions': ([{'revid': revision}] if type(revision) is int and revision > 0
                          else candidate.get('revisions', []))}


def _wikipedia_table_page(candidate, page_id, endpoint, *, query=''):
    parsed = _wikipedia_parse_document(candidate, page_id, endpoint, query=query)
    if parsed is None or not parsed.get('character_facts'):
        return parsed
    return parsed


def _wikipedia_appendix_page(title, work_candidate, endpoint, *, query=''):
    """Lee un anexo enlazado y devuelve sólo sus hechos literales de personajes."""
    parsed = _wikipedia_fetch(endpoint + urlencode({'action': 'parse', 'format': 'json',
        'page': title, 'prop': 'text|revid', 'disableeditsection': 1, 'disabletoc': 1}))
    article = parsed.get('parse') if isinstance(parsed, dict) else None
    if (not isinstance(article, dict) or not article.get('title')
            or normalized(article.get('title')) != normalized(title)):
        return None
    from .literary_web import character_content
    html = article.get('text')
    html = html.get('*') if isinstance(html, dict) else html
    content = character_content(html, context=work_candidate.get('extract', '') + '\n' + query,
                                title=article.get('title') or title)
    if not content['character_facts']:
        return None
    host = urlsplit(endpoint).hostname or 'es.wikipedia.org'
    revision = article.get('revid')
    return {**work_candidate,
            'pageid': article.get('pageid', work_candidate.get('pageid')),
            'title': article.get('title') or title,
            'extract': content['passage'],
            'character_facts': content['character_facts'],
            'character_appendix': True,
            'work_title': work_candidate.get('title', ''),
            'fullurl': 'https://' + host + '/wiki/' + quote(
                str(article.get('title') or title).replace(' ', '_'), safe=':'),
            'revisions': ([{'revid': revision}] if type(revision) is int and revision > 0
                          else [])}


def _search_wikipedia(query, *, language='es'):
    from .literary_research import bibliographic_title_hints, bibliographic_web_query
    query = bibliographic_web_query(query)
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
        # Los verbos de la petición no son palabras del título. Solo se retiran
        # del prefijo de conversación y fuera de un título entrecomillado.
        remaining = re.sub(r'(?i)^\s*(?:por favor[,\s]+)?(?:dime|dame|busca|búscame|buscame|'
            r'encuentra|muéstrame|muestrame|describe|háblame|hablame|cuéntame|cuentame)\b\s*', '', remaining)
        identity_query = re.sub(r'(?i)\b(?:personajes?|protagonistas?|antagonistas?|villanos?|'
            r'secundarios?|femeninos?|principales?|descripci[oó]n|'
            r'describe|caracter[ií]sticas?|argumento|trama|sinopsis|resumen|temas?|an[aá]lisis|'
            r'ideas?|interpreta(?:ci[oó]n)?|acontecimientos?|escenas?|desenlace|final|relaci[oó]n)\b', ' ', remaining)
        identity_query = re.sub(r'\s+', ' ', identity_query).strip()
        if quoted_title:
            identity_query = 'intitle:"' + quoted_title.group(1) + '" ' + identity_query
        if not identity_query:
            identity_query = query
    params = {'action': 'query', 'format': 'json', 'generator': 'search',
              # Una consulta de detalle necesita varios candidatos: la obra
              # principal puede aparecer después de secuelas o adaptaciones.
              # Diez introducciones acotadas no amplían las lecturas completas.
              'gsrsearch': identity_query, 'gsrlimit': 10 if focus else 2,
              'gsrnamespace': '0|104' if focus else 0, 'prop': 'extracts|info|revisions|pageprops',
              'ppprop': 'disambiguation|wikibase_item', 'rvprop': 'ids',
              'inprop': 'url', 'explaintext': 1, 'exintro': 1, 'exchars': 1200}
    if language not in {'es', 'en'}:
        raise ValueError('unsupported_wikipedia_language')
    if language == 'en':
        params['prop'] += '|langlinks'
        params.update(lllang='es',lllimit=1)
    endpoint = 'https://' + language + '.wikipedia.org/w/api.php?'
    data = _wikipedia_fetch(endpoint + urlencode(params))
    if not isinstance(data, dict) or data.get('error'):
        raise ValueError('invalid_wikipedia_response')
    pages = (data.get('query') or {}).get('pages') or {}
    pages = [page for page in (pages.values() if isinstance(pages, dict) else []) if isinstance(page, dict)]
    from .literary_identity import ambiguous_work_page
    pages = [page for page in pages if not ambiguous_work_page(page)]
    title_hints = [quoted_title.group(1)] if focus and quoted_title else []
    if focus and not title_hints:
        # «X de Autora Apellido» puede nombrar la obra sin comillas. Es sólo
        # una pista para consultar títulos oficiales, nunca una ficha nueva.
        title_hints = bibliographic_title_hints(identity_query)
    if focus and title_hints:
        wanted = {normalized(title) for title in title_hints}
        bare = lambda title: re.sub(r'^(?:el|la|los|las|the)\s+', '', normalized(title))
        def same_work(page):
            title = normalized(page.get('title'))
            from .literary_identity import published_title_alias
            public_page={'kind':'web','source':'Wikipedia','title':page.get('title',''),
                         'identity_text':page.get('extract',''),'url':trusted_url(page.get('fullurl')),
                         **_wikipedia_storage_metadata(page)}
            if any(published_title_alias(public_page,hint) for hint in title_hints):
                return True
            qualifier=re.fullmatch(r'(.+?)\s*\(([^()]+)\)\s*',str(page.get('title','')))
            if qualifier and normalized(qualifier[1]) in wanted:
                from .literary_identity import _identity_author
                author=_identity_author({'identity_text':page.get('extract','')})
                if (author and normalized(qualifier[2])==normalized(author).split()[-1]
                        and normalized(author) in normalized(identity_query)):
                    return True
            title = re.sub(r'\s*\((?:novela|libro|book|novel)\)\s*$', '', title)
            title = re.sub(r'^(?:anexo\s*:\s*)?(?:personajes|characters)\s+(?:de|of)\s+', '', title)
            # Formatting only guides discovery, never merges book identities.
            # Discovery convenience only. Downstream author/medium/saga checks
            # still decide whether this page can support the requested work.
            return (title in wanted or title.replace(' ', '') in {label.replace(' ', '') for label in wanted}
                    or bare(title) in {bare(label) for label in wanted})
        matching = [page for page in pages if same_work(page)]
        if matching:
            # Una secuela o la biografía del autor no demuestra las relaciones
            # de los personajes de la obra concreta que eligió el lector.
            pages = matching
        else:
            # Una búsqueda ordenada por relevancia puede devolver solamente
            # películas o secuelas aunque exista el artículo exacto solicitado.
            # Una sola consulta oficial de título/redirect lo comprueba; no
            # convierte esa coincidencia en una identidad bibliográfica aceptada.
            # MediaWiki sólo normaliza la primera letra: «Guerra y Paz» no
            # necesariamente redirige a «Guerra y paz». Ambas variantes son
            # búsquedas de títulos, no equivalencias bibliográficas inventadas.
            variants = [*title_hints, *(re.sub(r'(?<=[a-záéíóúñ])(?=[A-ZÁÉÍÓÚÑ])', ' ', title)
                                       for title in title_hints)]
            variants.extend(re.sub(r'(?i)^(?:el|la|los|las|the)\s+', '', title) for title in title_hints)
            lookup_titles = list(dict.fromkeys([*variants,
                *(title[:1].upper() + title[1:].casefold() for title in variants)]))
            exact_params = {'action': 'query', 'format': 'json', 'titles': '|'.join(lookup_titles),
                'redirects': 1, 'prop': 'extracts|info|revisions|pageprops', 'ppprop': 'disambiguation|wikibase_item',
                'rvprop': 'ids', 'inprop': 'url',
                'explaintext': 1, 'exintro': 1, 'exchars': 1200}
            if language == 'en':
                exact_params['prop'] += '|langlinks'
                exact_params.update(lllang='es',lllimit=1)
            try:
                exact = _wikipedia_fetch(endpoint + urlencode(exact_params))
                exact_pages = ((exact.get('query') or {}).get('pages') or {}) if isinstance(exact, dict) else {}
                exact_pages = [page for page in exact_pages.values() if isinstance(page, dict)
                    and 'missing' not in page and str(page.get('pageid', '')).isdigit()
                    and not ambiguous_work_page(page)
                    and page.get('extract') and same_work(page)] if isinstance(exact_pages, dict) else []
                if exact_pages:
                    order = [normalized(title) for title in title_hints]
                    exact_pages.sort(key=lambda page: next((index for index, title in enumerate(order)
                        if normalized(page.get('title')) == title), len(order)))
                    pages = exact_pages[:1]
            except Exception as exc:
                logger.warning('IA: título exacto de Wikipedia no disponible (%s)', type(exc).__name__)
    if focus and quoted_title:
        # El nombre que acompaña a un título entrecomillado en el trabajador
        # es una restricción, no otra palabra temática. Descartar homónimos
        # antes de gastar la única lectura permite probar el idioma siguiente.
        author_hint=re.sub(r'^intitle:"[^"]*"\s*','',identity_query).strip()
        if (2<=len(author_hint.split())<=12 and re.fullmatch(r'[\w .()’\'-]+',author_hint)
                and re.search(r'[A-ZÁÉÍÓÚÑ]',author_hint)):
            from .literary_identity import author_name_forms,same_author_name
            def author_present(page):
                words=normalized(page.get('extract','')).split()
                exact=any(same_author_name(form,' '.join(words[i:i+len(form.split())]))
                           for form in author_name_forms(author_hint)
                           for i in range(max(0,len(words)-len(form.split())+1)))
                if exact:
                    return True
                # A detail query can append a character after the author:
                # "Title" Author Surname Character acontecimientos. These
                # extra search terms are not another author surname. This is
                # discovery only; same_work still checks the actual FULL work
                # author before binding, answering or persisting anything.
                if re.search(r'\b(?:acontecimientos|escenas?|relacion|events|scenes?)\b',normalized(query)):
                    from .literary_identity import _identity_author
                    published=_identity_author({'identity_text':page.get('extract','')})
                    return bool(published and any(same_author_name(' '.join(author_hint.split()[:end]),published)
                                for end in range(2,len(author_hint.split()))))
                return False
            pages=[page for page in pages if author_present(page)]
    if not re.search(r'\b(?:pelicula|film|adaptacion|cine|serie)\b', normalized(query)):
        pages = [page for page in pages if not re.search(
            r'\((?:pelicula|film|serie|videojuego)\b', normalized(page.get('title', '')))]
    if focus and pages:
        pages.sort(key=lambda page: _wikipedia_page_rank(page, identity_query, focus), reverse=True)
        candidate = pages[0]
        if language == 'en' and focus[0]=='argumento':
            try:
                counterpart = _wikipedia_spanish_counterpart(candidate,query=query)
                if counterpart:
                    candidate = pages[0] = counterpart
                    endpoint = 'https://es.wikipedia.org/w/api.php?'
            except Exception as exc:
                # One optional metadata lookup cannot discard a usable source
                # or cause a retry loop when a host is unavailable.
                record_research_event('interlanguage_identity','Wikipedia',error_status(exc))
        page_id = str(candidate.get('pageid', ''))
        # El artículo completo es una lectura de evidencia igual que una página
        # HTML. La introducción bibliográfica se conserva si se agotó el cupo.
        if page_id.isdigit() and int(page_id) > 0 and (candidate.get('_prefetched_document') or reserve_page()):
            try:
                from .literary_sources import research_snapshot
                reserved = research_snapshot().get('page_slots_reserved', 0)
                page_limit = max(0, min(int(getattr(settings, 'LITMATE_RESEARCH_MAX_PAGES', 3)),
                                       research_snapshot().get('page_slots_limit', 3), 3))
                if candidate.get('_prefetched_document'):
                    full_page=candidate
                elif focus[0] == 'personajes' and reserved >= page_limit:
                    # Si solo queda una lectura, Parse puede obtener la tabla
                    # que TextExtracts omitiría. No se amplía el presupuesto.
                    full_page = _wikipedia_table_page(candidate, page_id, endpoint, query=query)
                else:
                    details = {'action': 'query', 'format': 'json', 'pageids': page_id,
                               'prop': 'extracts|info|revisions', 'rvprop': 'ids', 'inprop': 'url', 'explaintext': 1,
                               'exsectionformat': 'wiki'}
                    full = _wikipedia_fetch(endpoint + urlencode(details))
                    full_page = ((full.get('query') or {}).get('pages') or {}).get(page_id)
                if isinstance(full_page, dict) and full_page.get('extract'):
                    selection = (relevant_passage(full_page['extract'],query,with_details=True)
                                 if focus[0] != 'personajes' and not full_page.get('parse_read') else None)
                    selected_text = (selection['passage'] if selection is not None else
                                     full_page['extract'] if full_page.get('parse_read') else
                                     relevant_passage(full_page['extract'],query))
                    plot_facts = []
                    if selection is not None:
                        plot_facts = selected_section_facts(selection)
                    pages[0] = {**candidate, **full_page,
                                'identity_text': candidate.get('identity_text') or clean_text(candidate.get('extract'), 1200),
                                'character_facts': (full_page.get('character_facts') or
                                    character_facts(full_page['extract'])) if focus[0] == 'personajes' else [],
                                'extract': selected_text,'literary_facts':plot_facts,
                                'literary_section_read': True}
                    # TextExtracts omite tablas y la estructura de listas. Los
                    # anexos pueden usar un subtítulo por personaje en vez de
                    # un capítulo literal «Personajes». Parse conserva ambos
                    # formatos con el mismo pageid/título y cupo compartido.
                    # Se relee siempre en consultas de personajes: el heurístico
                    # de texto plano no distingue una lista de una mención.
                    if (focus[0] == 'personajes' and full_page.get('parse_read') is not True
                            and reserve_page()):
                        try:
                            table = _wikipedia_table_page(candidate, page_id, endpoint, query=query)
                            if table and table.get('character_facts'):
                                pages[0] = {**candidate, **table,
                                            'identity_text': clean_text(candidate.get('extract'), 1200),
                                            'extract': table['extract'],
                                            'literary_section_read': True}
                            elif table and table.get('appendix_titles'):
                                # La obra principal puede no tener sección de
                                # personajes y remitir a un anexo oficial.
                                for appendix_title in table['appendix_titles'][:2]:
                                    if not reserve_page():
                                        break
                                    appendix = _wikipedia_appendix_page(
                                        appendix_title, candidate, endpoint, query=query)
                                    if appendix:
                                        pages[0] = {**appendix,
                                                    'identity_text': clean_text(
                                                        candidate.get('extract'), 1200),
                                                    'extract': relevant_passage(
                                                        appendix['extract'], query),
                                                    'literary_section_read': True}
                                        break
                        except Exception as exc:
                            logger.warning('IA: tabla de Wikipedia no disponible (%s)',
                                           type(exc).__name__)
            except Exception as exc:
                logger.warning('IA: sección de Wikipedia no disponible (%s)', type(exc).__name__)
    return [{'title': page.get('title'), 'author': 'Fuente web', 'description': page.get('extract'),
             # La introducción identifica la obra aunque no se haya reservado
             # una lectura completa. Nunca se usa el pasaje temático como
             # identidad: para eso está identity_text.
             'identity_text': page.get('identity_text') or clean_text(page.get('extract'), 1200),
             'character_facts': page.get('character_facts', []),
             'confirmed_aliases': page.get('confirmed_aliases', []),
             # Un anexo conserva la obra de la que fue descubierto para que la
             # validación posterior pueda vincularlo sin confundirlo con una
             # secuela o una adaptación.
             **({'work_title': page['work_title'], 'character_appendix': True}
                if page.get('character_appendix') is True and page.get('work_title') else {}),
             'kind': 'web', 'url': trusted_url(page.get('fullurl')),
             **_wikipedia_storage_metadata(page),
             'source': 'Wikipedia', 'read_mode': 'pasaje de sección de artículo público' if page.get(
                 'literary_section_read') else 'extracto de introducción',
             # Mantener también los acontecimientos literales: los seguimientos
             # «¿qué sucede con X?» los consultan por entidad. El atributo plot
             # describe alcance de recuperación, no sustituye ese contrato.
             'literary_facts': (page.get('literary_facts') or []) + ([{'topic': 'events', 'subject': page.get('title'),
                                 'evidence': page.get('extract'), 'scope': 'partial'}]
                 if page.get('literary_section_read') and re.search(
                     r'(?i)(?:^|\s)(?:argumento|trama|plot)(?:\s|=|:)', str(page.get('extract', ''))) else [])}
            for page in pages[:2] if page.get('extract')]


def _wikipedia_storage_metadata(page):
    """Permiso explícito sólo para pasajes oficiales con revisión y atribución.

    La identidad bibliográfica se valida posteriormente, antes de persistir.
    Las páginas públicas generales siguen sin permiso de indexación permanente.
    """
    revisions = page.get('revisions')
    revision_id = revisions[0].get('revid') if isinstance(revisions, list) and revisions else None
    url = safe_source_url(page.get('fullurl'))
    if not (type(revision_id) is int and revision_id > 0 and url
            and urlsplit(url).hostname in {'es.wikipedia.org', 'en.wikipedia.org'}):
        return {}
    return {'license': 'CC-BY-SA-4.0', 'storage_policy': 'wikipedia-cc-by-sa-4.0-v1',
            'permanent_index_allowed': True, 'attribution': {'authors': 'Wikipedia contributors',
                'title': str(page.get('title', '')), 'url': url, 'revision_id': str(revision_id),
                'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/'}}


@timed_stage('web_search')
def retrieve_web(query):
    from .literary_research import bibliographic_web_query, public_research_queries
    public_queries = public_research_queries(query)
    query = bibliographic_web_query(public_queries[0]) if public_queries else ''
    if not query:
        return []
    from .ai_budget import request_budget
    from .literary_sources import research_scope, reserve_search, account_research
    with research_scope(getattr(settings, 'LITMATE_RESEARCH_MAX_SEARCHES', 2),
                        getattr(settings, 'LITMATE_RESEARCH_TIMEOUT', 15),
                        getattr(settings, 'LITMATE_RESEARCH_MAX_PAGES', 3)):
        cached = _cached(_web_cache_key(query))
        if cached is not None:
            record_research_event('cache_hit', 'web', 'cached', count=len(cached))
            return cached
        remaining = reserve_search()
        if not remaining:
            return SearchResults(status='budget_exhausted')
        started = time.monotonic()
        try:
            with request_budget(started + remaining):
                return _retrieve_web(query)
        finally:
            account_research(time.monotonic() - started)


def _web_cache_key(query):
    engines = getattr(settings, 'LITMATE_SEARXNG_ENGINES', ('wikipedia', 'openlibrary', 'mwmbl'))
    return _cache_key('litmate_local_web_v15:', query + ':es,en:' + repr(engines) + ':'
                     + str(getattr(settings, 'LITMATE_AI_USE_SEARXNG', True))
                     + ':' + str(getattr(settings, 'LITMATE_AI_USE_WEB', True)))


def _retrieve_web(query):
    key = _web_cache_key(query)
    cached = _cached(key)
    if cached is not None:
        return cached
    groups, statuses, providers = [], {}, [
        ('Wikipedia', search_wikipedia),
        ('DuckDuckGo', search_duckduckgo),
    ]
    # Wikipedia y el buscador general comparten reloj: uno lento no retrasa al
    # otro. SearXNG queda como último recurso local, nunca como cuello de botella.
    with pool_in_budget(len(providers)) as pool:
        futures = {submit_with_budget(pool, searcher, query): name
                   for name, searcher in providers}
        pending = set(futures)
        deadline = time.monotonic() + budget_timeout(5)
        while pending:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            done, pending = wait(pending, timeout=left, return_when=FIRST_COMPLETED)
            if not done:
                break
            for future in done:
                name = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    statuses[name] = error_status(exc)
                    logger.warning('IA: búsqueda=%s estado=%s', name, statuses[name])
                    continue
                groups.append(result)
                statuses[name] = getattr(result, 'status', 'ok' if result else 'empty')
        for future in pending:
            statuses[futures[future]] = 'timeout'
            future.cancel()
    results = [item for group in groups for item in group]
    if not results and getattr(settings, 'LITMATE_AI_USE_SEARXNG', True):
        try:
            result = search_searx(query,web=True)
            groups.append(result)
            statuses['SearXNG'] = getattr(result, 'status', 'ok' if result else 'empty')
            results.extend(result)
        except Exception as exc:
            statuses['SearXNG'] = error_status(exc)
            logger.warning('IA: búsqueda=SearXNG estado=%s', statuses['SearXNG'])
    if not results and getattr(settings, 'LITMATE_AI_USE_WIKIDATA', False):
        from .literary_wikidata import search_wikidata
        fallback = search_wikidata(query)
        results.extend(fallback)
        statuses['Wikidata'] = fallback.status
    # Relevancia y procedencia, no simplemente posición del buscador.
    terms = [term for term in re.findall(r'\w+', normalized(query)) if len(term) >= 4 and term not in STOPWORDS]
    def rank(source):
        text = normalized(str(source.get('title', '')) + ' ' + str(source.get('description', '')))
        authority = 6 if trusted_url(source.get('url')) else 3 if source.get('source') == 'DuckDuckGo' else 2
        title = normalized(source.get('title'))
        return authority + sum(6 if term in title else 2 if term in text else 0
                               for term in terms)
    results.sort(key=rank, reverse=True)
    unique, seen_passages = [], set()
    for source in results:
        # Dos páginas distintas pueden tener un fragmento vacío o genérico.
        # El destino es la unidad de lectura; no descartar su URL por compartir
        # un texto breve con una ficha de catálogo que no se puede leer por HTML.
        signature = safe_source_url(source.get('url','')) or normalized(source.get('description',''))
        if signature and signature not in seen_passages:
            unique.append(source)
            seen_passages.add(signature)
    sources = canonical_sources(unique, 6)
    for source in sources:
        source['retrieved_at'] = datetime.now(timezone.utc).isoformat()
    # Se extrae solo un pasaje relevante de tres páginas públicas como máximo.
    def enrich(source):
        if source.get('read_mode') != 'fragmento del buscador':
            return source
        url = safe_source_url(source.get('url'))
        if not url:
            return source
        trusted = bool(trusted_url(url))
        # Los resultados del SearXNG local pasan por el mismo lector con SSRF,
        # robots, límites y control de inyección que los de DuckDuckGo. La
        # procedencia debe incluir un motor realmente aceptado del adaptador.
        searx_discovery=(str(source.get('source','')).startswith('SearXNG (')
            and bool(set(source.get('search_engines') or [])&{'mwmbl','duckduckgo','openlibrary','wikipedia','wikidata'}))
        if not trusted and source.get('source') != 'DuckDuckGo' and not searx_discovery:
            return source
        if not reserve_page():
            return source
        try:
            extracted = (read_public_page(url, query, details=True) if trusted
                         else read_public_web_page(url, query, details=True))
            body = extracted.get('description', '') if isinstance(extracted, dict) and extracted.get('status') == 'ok' else ''
            record_research_event('page_read', 'web', extracted.get('status', 'unavailable')
                                  if isinstance(extracted, dict) else 'unsupported_type', count=int(bool(body)))
            if body:
                source = {**source, 'description': body, 'read_mode': 'pasaje de página pública',
                          'identity_text': extracted.get('identity_text') or
                              str(extracted.get('title', '')) + ' ' + body[:1000],
                          'trust': 'untrusted_data', 'permanent_index_allowed': False}
                for field in ('extraction_method', 'headings', 'character_mentions',
                              'character_facts', 'injection_detected', 'site'):
                    source[field] = extracted.get(field)
        except Exception as exc:
            record_research_event('page_read', 'web', error_status(exc))
            logger.warning('IA: página no disponible (%s)', type(exc).__name__)
        return source
    maximum = max(0, min(int(getattr(settings, 'LITMATE_RESEARCH_MAX_PAGES', 3)), 3))
    candidates = [source for source in sources if source.get('read_mode') == 'fragmento del buscador'
                  and not _catalogue_api_only(source.get('url',''))]
    # Primero editoriales y fuentes de confianza; después páginas generales.
    candidates.sort(key=lambda source: 0 if trusted_url(source.get('url')) else 1)
    with pool_in_budget(max(1, maximum)) as pool:
        futures = {source['id']: submit_with_budget(pool, enrich, source)
                   for source in candidates[:maximum]}
        for identifier, future in futures.items():
            try:
                updated = future.result(timeout=budget_timeout(6))
            except Exception as exc:
                logger.warning('IA: lectura web no disponible (%s)', type(exc).__name__)
                continue
            for index, source in enumerate(sources):
                if source['id'] == identifier:
                    sources[index] = updated
                    break
    failed = any(status not in {'ok', 'empty', 'disabled'}
                 for status in statuses.values())
    status = 'partial' if failed and sources else 'unavailable' if failed else 'ok' if sources else 'empty'
    return _save(key, SearchResults(sources, status=status, providers=statuses))
