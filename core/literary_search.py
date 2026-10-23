"""Google Books, catálogo, archivos locales y fuentes públicas complementarias."""
import hashlib
import ipaddress
import logging
import re
import socket
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qs
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
                          'bibliotecanacional.gob.cl')
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
        # Una caída se gestiona con cooldown; no se anuncia como búsqueda vacía.
        if getattr(result, 'status', 'ok') not in {'unavailable', 'timeout', 'rate_limited', 'invalid_response'}:
            cache.set(key, result, int(getattr(settings, 'LITMATE_RESEARCH_CACHE_SECONDS', 86400)) if result else 60)
    except Exception:
        pass
    return result


@timed_stage('local_search')
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
        return []


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
    return '' if normalized(value).strip(' .') in {
        'publisher description', 'no description available',
        'sin descripcion', 'sin descripcion disponible'} else value


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
    key = _cache_key('litmate_hybrid_books_v11:', query + ':' + revision + ':' + knowledge_revision(settings) + ':' + google_revision + ':'
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
    if not database.is_file():
        return facts
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


def read_public_page(url, query, *, details=False):
    """Extractor controlado; nunca navega por una URL aportada por el modelo."""
    url = trusted_url(url)
    if not url:
        return ''
    host = urlsplit(url).hostname
    # Open Library solicita usar su API. Google Books suele requerir JS:
    # en ambos casos conservamos el fragmento del buscador.
    if host.endswith('openlibrary.org') or host.startswith('books.google.'):
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
    DuckDuckGo. Aun así se exige HTTPS, host público, robots y tamaño máximo.
    """
    url = safe_source_url(url)
    if not url:
        return ''
    host = (urlsplit(url).hostname or '').lower()
    if host.endswith('openlibrary.org') or host.startswith('books.google.'):
        return ''
    from .literary_web import extract_public_page
    with measure_stage('extraction'):
        result = extract_public_page(url, query, allowed_domains=('*',),
                                     timeout=budget_timeout(5))
    if details:
        return result
    return result.get('description', '') if result.get('status') == 'ok' else ''


def _detail_focus(query):
    value = normalized(query)
    if re.search(r'\bpersonajes?|\bprotagonistas?|\bcharacters?|\bcaracterizacion', value):
        return ('personajes', 'protagonistas', 'characters', 'main characters', 'character list')
    if re.search(r'\bargumento|\btrama|\bresumen|\bsinopsis|\bdesenlace|\bfinal\b', value):
        return ('argumento', 'trama', 'sinopsis', 'plot', 'resumen', 'desenlace', 'final')
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
    if cache.get('litmate_ddg_cooldown'):
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
        cache.set('litmate_ddg_cooldown', status, cooldown_seconds(exc))
        return SearchResults(status=status)
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        if soup.select_one('#challenge-form, .anomaly-modal, form[action*="anomaly.js"]'):
            record_research_event('http_request', 'DuckDuckGo', 'access_denied')
            cache.set('litmate_ddg_cooldown', 'access_denied', 180)
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
        cache.set('litmate_ddg_cooldown', 'invalid_response', 300)
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


def search_searx(query):
    # Sin claves. Lista cerrada: ninguna entrada del lector elige motores.
    if not getattr(settings, 'LITMATE_AI_USE_SEARXNG', True):
        return []
    origin = local_origin(getattr(settings, 'LITMATE_SEARXNG_URL', 'http://127.0.0.1:8080'))
    query = public_query(query)
    if not query:
        return []
    allowed = {'wikipedia', 'openlibrary', 'mwmbl', 'wikidata'}
    engines = getattr(settings, 'LITMATE_SEARXNG_ENGINES', ('wikipedia', 'openlibrary', 'mwmbl'))
    engines = [engine for engine in engines if engine in allowed]
    if not engines:
        return SearchResults(status='disabled')
    if cache.get('litmate_searx_cooldown'):
        return SearchResults(status='cooldown')
    params = {'q': query, 'format': 'json', 'language': 'es',
              'engines': ','.join(engines), 'safesearch': 1}
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
        url = discovery_url(item.get('url'))
        if not url or not item.get('content'):
            continue
        results.append({'title': item.get('title'), 'author': 'Fuente web',
                        'description': item.get('content'), 'url': url, 'kind': 'web',
                        'source': 'SearXNG (' + urlsplit(url).hostname + ')',
                        'read_mode': 'fragmento del buscador'})
        if len(results) == 5:
            break
    failures = data.get('unresponsive_engines') or []
    return SearchResults(results, status='partial' if failures and results else
                         'unavailable' if failures else 'ok',
                         providers={str(item[0])[:40]: str(item[1])[:60]
                                    for item in failures if isinstance(item, list) and len(item) >= 2})


def search_wikipedia(query):
    """API oficial: español primero; inglés solo si falta una página utilizable."""
    # Sólo se conserva durante un turno real. Los comandos y las pruebas deben
    # observar cada petición y no recibir páginas de otra consulta/contexto.
    active = current_deadline() is not None
    cache_name = _cache_key('litmate_local_wikipedia_v2:', normalized(query) + ':pages='
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
        try:
            result = _search_wikipedia(query, language=language)
            statuses[language] = 'ok' if result else 'empty'
            if result:
                # La API puede devolver artículos tangenciales aun sin ninguna
                # palabra identificativa del título. No cerrar por eso la etapa
                # multilingüe (p. ej. artículo sobre una ceremonia en vez del libro).
                if language == 'es' and query_terms and not any(query_terms & set(
                        re.findall(r'\w+', normalized(source.get('title')))) for source in result):
                    spanish_alternatives = result
                    continue
                return finish(SearchResults(result, status='partial' if any(
                    value not in {'ok', 'empty'} for value in statuses.values()) else 'ok',
                    providers={'Wikipedia (' + key + ')': value for key, value in statuses.items()}))
        except Exception as exc:
            statuses[language] = error_status(exc)
    failed = any(value not in {'ok', 'empty'} for value in statuses.values())
    return finish(SearchResults(spanish_alternatives, status=('partial' if spanish_alternatives else 'unavailable')
                         if failed else 'ok' if spanish_alternatives else 'empty',
                         providers={'Wikipedia (' + key + ')': value for key, value in statuses.items()}))


def _wikipedia_fetch(url):
    record_research_event('http_request', 'Wikipedia', 'started')
    try:
        result = read_json_url(url, headers={'User-Agent': _agent()}, timeout=6)
    except Exception as exc:
        record_research_event('http_request', 'Wikipedia', error_status(exc))
        raise
    record_research_event('http_request', 'Wikipedia', 'ok')
    return result


def _wikipedia_table_page(candidate, page_id, endpoint):
    parsed = _wikipedia_fetch(endpoint + urlencode({'action': 'parse', 'format': 'json',
        'pageid': page_id, 'prop': 'text', 'disableeditsection': 1, 'disabletoc': 1}))
    article = parsed.get('parse') if isinstance(parsed, dict) else None
    if (not isinstance(article, dict) or str(article.get('pageid')) != page_id
            or normalized(article.get('title')) != normalized(candidate.get('title'))):
        return None
    from .literary_web import character_table_passage
    html = article.get('text')
    html = html.get('*') if isinstance(html, dict) else html
    passage = character_table_passage(html, context=candidate.get('extract', ''))
    facts = character_facts(passage)
    return {**candidate, 'extract': passage, 'character_facts': facts} if len(facts) >= 2 else None


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
        identity_query = re.sub(r'(?i)\b(?:personajes?|protagonistas?|principales?|descripci[oó]n|'
            r'describe|caracter[ií]sticas?|argumento|trama|sinopsis|resumen|temas?|an[aá]lisis|'
            r'ideas?|interpreta(?:ci[oó]n)?|acontecimientos?|escenas?|desenlace|final|relaci[oó]n)\b', ' ', remaining)
        identity_query = re.sub(r'\s+', ' ', identity_query).strip()
        if quoted_title:
            identity_query = 'intitle:"' + quoted_title.group(1) + '" ' + identity_query
        if not identity_query:
            identity_query = query
    params = {'action': 'query', 'format': 'json', 'generator': 'search',
              'gsrsearch': identity_query, 'gsrlimit': 2,
              'gsrnamespace': '0|104' if focus else 0, 'prop': 'extracts|info|revisions', 'rvprop': 'ids',
              'inprop': 'url', 'explaintext': 1, 'exintro': 1, 'exchars': 1200}
    if language not in {'es', 'en'}:
        raise ValueError('unsupported_wikipedia_language')
    endpoint = 'https://' + language + '.wikipedia.org/w/api.php?'
    data = _wikipedia_fetch(endpoint + urlencode(params))
    if not isinstance(data, dict) or data.get('error'):
        raise ValueError('invalid_wikipedia_response')
    pages = (data.get('query') or {}).get('pages') or {}
    pages = [page for page in (pages.values() if isinstance(pages, dict) else []) if isinstance(page, dict)]
    title_hints = [quoted_title.group(1)] if focus and quoted_title else []
    if focus and not title_hints:
        # «X de Autora Apellido» puede nombrar la obra sin comillas. Es sólo
        # una pista para consultar títulos oficiales, nunca una ficha nueva.
        title_hints = bibliographic_title_hints(identity_query)
    if focus and title_hints:
        wanted = {normalized(title) for title in title_hints}
        def same_work(page):
            title = normalized(page.get('title'))
            title = re.sub(r'\s*\((?:novela|libro|book|novel)\)\s*$', '', title)
            title = re.sub(r'^(?:anexo\s*:\s*)?(?:personajes|characters)\s+(?:de|of)\s+', '', title)
            return title in wanted
        matching = [page for page in pages if same_work(page)]
        if matching:
            # Una secuela o la biografía del autor no demuestra las relaciones
            # de los personajes de la obra concreta que eligió el lector.
            pages = matching
        elif pages:
            # Una búsqueda ordenada por relevancia puede devolver solamente
            # películas o secuelas aunque exista el artículo exacto solicitado.
            # Una sola consulta oficial de título/redirect lo comprueba; no
            # convierte esa coincidencia en una identidad bibliográfica aceptada.
            # MediaWiki sólo normaliza la primera letra: «Guerra y Paz» no
            # necesariamente redirige a «Guerra y paz». Ambas variantes son
            # búsquedas de títulos, no equivalencias bibliográficas inventadas.
            lookup_titles = list(dict.fromkeys([*title_hints,
                *(title[:1].upper() + title[1:].casefold() for title in title_hints)]))
            exact_params = {'action': 'query', 'format': 'json', 'titles': '|'.join(lookup_titles),
                'redirects': 1, 'prop': 'extracts|info|revisions', 'rvprop': 'ids', 'inprop': 'url',
                'explaintext': 1, 'exintro': 1, 'exchars': 1200}
            try:
                exact = _wikipedia_fetch(endpoint + urlencode(exact_params))
                exact_pages = ((exact.get('query') or {}).get('pages') or {}) if isinstance(exact, dict) else {}
                exact_pages = [page for page in exact_pages.values() if isinstance(page, dict)
                    and 'missing' not in page and str(page.get('pageid', '')).isdigit()
                    and page.get('extract') and same_work(page)] if isinstance(exact_pages, dict) else []
                if exact_pages:
                    order = [normalized(title) for title in title_hints]
                    exact_pages.sort(key=lambda page: next((index for index, title in enumerate(order)
                        if normalized(page.get('title')) == title), len(order)))
                    pages = exact_pages[:1]
            except Exception as exc:
                logger.warning('IA: título exacto de Wikipedia no disponible (%s)', type(exc).__name__)
    if not re.search(r'\b(?:pelicula|film|adaptacion|cine|serie)\b', normalized(query)):
        pages = [page for page in pages if not re.search(
            r'\((?:pelicula|film|serie|videojuego)\b', normalized(page.get('title', '')))]
    if focus and pages:
        pages.sort(key=lambda page: (any(word in normalized(page.get('title')) for word in focus),
                                    '(novela)' in normalized(page.get('title'))), reverse=True)
        candidate = pages[0]
        page_id = str(candidate.get('pageid', ''))
        # El artículo completo es una lectura de evidencia igual que una página
        # HTML. La introducción bibliográfica se conserva si se agotó el cupo.
        if page_id.isdigit() and int(page_id) > 0 and reserve_page():
            try:
                from .literary_sources import research_snapshot
                reserved = research_snapshot().get('page_slots_reserved', 0)
                page_limit = max(0, min(int(getattr(settings, 'LITMATE_RESEARCH_MAX_PAGES', 3)), 3))
                if focus[0] == 'personajes' and reserved >= page_limit:
                    # Si solo queda una lectura, Parse puede obtener la tabla
                    # que TextExtracts omitiría. No se amplía el presupuesto.
                    full_page = _wikipedia_table_page(candidate, page_id, endpoint)
                else:
                    details = {'action': 'query', 'format': 'json', 'pageids': page_id,
                               'prop': 'extracts|info|revisions', 'rvprop': 'ids', 'inprop': 'url', 'explaintext': 1,
                               'exsectionformat': 'wiki'}
                    full = _wikipedia_fetch(endpoint + urlencode(details))
                    full_page = ((full.get('query') or {}).get('pages') or {}).get(page_id)
                if isinstance(full_page, dict) and full_page.get('extract'):
                    pages[0] = {**candidate, **full_page,
                                'identity_text': clean_text(candidate.get('extract'), 1200),
                                'character_facts': character_facts(full_page['extract']) if focus[0] == 'personajes' else [],
                                'extract': relevant_passage(full_page['extract'], query),
                                'literary_section_read': True}
                    # TextExtracts omite tablas: una sección de personajes puede
                    # contener solo su encabezado. Parse es otra API oficial y
                    # se consulta únicamente para recuperar esa evidencia.
                    if (focus[0] == 'personajes' and not pages[0]['character_facts']
                            and re.match(r'(?i)^==\s*(?:Personajes|Characters|Main characters|Character list)\b', pages[0]['extract'])
                            and reserve_page()):
                        try:
                            table = _wikipedia_table_page(candidate, page_id, endpoint)
                            if table:
                                pages[0]['extract'] = table['extract']
                                pages[0]['character_facts'] = table['character_facts']
                        except Exception as exc:
                            logger.warning('IA: tabla de Wikipedia no disponible (%s)', type(exc).__name__)
            except Exception as exc:
                logger.warning('IA: sección de Wikipedia no disponible (%s)', type(exc).__name__)
    return [{'title': page.get('title'), 'author': 'Fuente web', 'description': page.get('extract'),
             # La introducción identifica la obra aunque no se haya reservado
             # una lectura completa. Nunca se usa el pasaje temático como
             # identidad: para eso está identity_text.
             'identity_text': page.get('identity_text') or clean_text(page.get('extract'), 1200),
             'character_facts': page.get('character_facts', []),
             'kind': 'web', 'url': trusted_url(page.get('fullurl')),
             **_wikipedia_storage_metadata(page),
             'source': 'Wikipedia', 'read_mode': 'pasaje de sección de artículo público' if page.get(
                 'literary_section_read') else 'extracto de introducción',
             'literary_facts': [{'topic': 'events', 'subject': page.get('title'),
                                 'evidence': page.get('extract'), 'scope': 'partial'}]
                 if page.get('literary_section_read') and re.search(
                     r'(?i)(?:^|\s)(?:argumento|trama|plot)(?:\s|=|:)', str(page.get('extract', ''))) else []}
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
    return _cache_key('litmate_local_web_v14:', query + ':es,en:' + repr(engines) + ':'
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
            result = search_searx(query)
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
        signature = normalized(source.get('description', ''))
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
        # Un resultado general se lee sólo si procede de DuckDuckGo; una tienda
        # descubierta por él conserva el fragmento si su robots no lo permite.
        if not trusted and source.get('source') != 'DuckDuckGo':
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
                          'identity_text': str(extracted.get('title', '')) + ' ' + body[:1000],
                          'trust': 'untrusted_data', 'permanent_index_allowed': False}
                for field in ('extraction_method', 'headings', 'character_mentions', 'injection_detected', 'site'):
                    source[field] = extracted.get(field)
        except Exception as exc:
            record_research_event('page_read', 'web', error_status(exc))
            logger.warning('IA: página no disponible (%s)', type(exc).__name__)
        return source
    maximum = max(0, min(int(getattr(settings, 'LITMATE_RESEARCH_MAX_PAGES', 3)), 3))
    candidates = [source for source in sources if source.get('read_mode') == 'fragmento del buscador']
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
