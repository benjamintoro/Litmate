"""Google Books compartido por el catálogo y la IA, sin exponer credenciales.

La API devuelve fichas y sinopsis, no el texto íntegro de cada obra.
"""
import hashlib
import html
import re
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote, urlsplit

from django.conf import settings
from django.core.cache import cache
from .ai_http import read_json_url
from .ai_budget import BudgetExpired, budget_timeout, check_budget
from .ai_privacy import excerpt_marker


class BooksUnavailable(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def public_query(value):
    """No envía pasajes, URLs, correos, teléfonos ni credenciales al buscador."""
    if not isinstance(value, str):
        return ''
    identifier = re.sub(r'[\s-]', '', re.sub(r'^isbn(?:-1[03])?\s*:?\s*', '', value.strip(), flags=re.I)).upper()
    valid_isbn = (len(identifier) == 13 and identifier.isdigit() and sum(
        int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(identifier)) % 10 == 0)
    if len(identifier) == 10 and identifier[:9].isdigit() and identifier[-1] in '0123456789X':
        valid_isbn = sum((10 if c == 'X' else int(c)) * (10 - i)
                         for i, c in enumerate(identifier)) % 11 == 0
    if valid_isbn:
        return 'isbn:' + identifier
    marker = excerpt_marker(value)
    if marker:
        value = value[:marker.start()]
    if value.count('\n') > 2:
        return ''
    value = re.sub(r'https?://\S+|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b', ' ', value)
    value = re.sub(r'\b(?:sk-|AIza)[A-Za-z0-9_-]{12,}|\bBearer\s+\S+', ' ', value, flags=re.I)
    value = re.sub(r'\b(?:contrase[nñ]a|password|api[ _-]*key|token|secreto)\s*[:=]\s*\S+',
                   ' ', value, flags=re.I)
    value = re.sub(r'(?<!\w)(?:\+?\d[\d .()-]{7,}\d)(?!\w)',
                   lambda m: m.group(0) if re.fullmatch(r'\d{10}|\d{13}', m.group(0))
                   and re.search(r'ISBN\s*:?\s*$', value[:m.start()], re.I) else ' ', value)
    value = re.sub(r'[<>`{}|!]', ' ', value)
    value = re.sub(r'\s+', ' ', value).strip()[:240]
    return value if any(c.isalpha() for c in value) or re.fullmatch(r'\d{1,6}|\d{10}|\d{13}', value) else ''


def _cache_get(key):
    try:
        return cache.get(key)
    except Exception:
        return None


def _cache_set(key, data, seconds):
    try:
        cache.set(key, data, timeout=seconds)
    except Exception:
        pass


def _request(path, params, *, fetch=None):
    if not getattr(settings, 'LITMATE_USE_GOOGLE_BOOKS_API', True):
        raise BooksUnavailable('disabled')
    key = str(getattr(settings, 'GOOGLE_BOOKS_API_KEY', '')).strip()
    if not key or key.startswith(('tu_', 'YOUR_')):
        raise BooksUnavailable('missing_key')
    params = {**params, 'key': key}
    headers = {'User-Agent': 'LitMate/2.0', 'Accept': 'application/json'}
    for attempt in range(2):
        try:
            data = (fetch or read_json_url)(
                'https://www.googleapis.com/books/v1/' + path + '?' + urlencode(params),
                headers=headers, timeout=int(getattr(settings, 'GOOGLE_BOOKS_TIMEOUT', 8)))
            break
        except BudgetExpired:
            raise
        except HTTPError as exc:
            if attempt == 0 and exc.code in {500, 502, 503, 504}:
                # Una sola repetición para fallos transitorios, dentro del
                # presupuesto de la consulta; nunca reintenta claves ni cuotas.
                time.sleep(min(0.15, budget_timeout(0.15)))
                check_budget()
                continue
            raise BooksUnavailable({400: 'invalid_query', 401: 'invalid_key',
                                    403: 'access_or_quota', 404: 'not_found',
                                    429: 'quota_exceeded'}.get(exc.code, 'unavailable')) from None
        except (URLError, OSError, TimeoutError, ValueError, TypeError):
            raise BooksUnavailable('unavailable') from None
    if not isinstance(data, dict) or data.get('error'):
        raise BooksUnavailable('invalid_response')
    return data


def search_volumes(query, max_results=8, language=None, *, fetch=None, use_cache=None):
    """Retorna volúmenes originales; no almacena ni devuelve la clave de API."""
    query = public_query(query)
    if not query:
        return []
    if not getattr(settings, 'LITMATE_USE_GOOGLE_BOOKS_API', True):
        raise BooksUnavailable('disabled')
    maximum = max(1, min(int(max_results), 40))
    params = {'q': query, 'maxResults': maximum, 'printType': 'books',
              'projection': 'full', 'orderBy': 'relevance'}
    language = language if language is not None else getattr(settings, 'GOOGLE_BOOKS_LANGUAGE', '')
    if language:
        params['langRestrict'] = str(language)[:10]
    # Cambiar clave/configuración invalida también las respuestas vacías anteriores.
    fingerprint = hashlib.sha256(str(getattr(settings, 'GOOGLE_BOOKS_API_KEY', '')).encode()).hexdigest()[:12]
    cache_key = 'google_books_v2:' + hashlib.sha256((repr(params) + fingerprint).encode()).hexdigest()
    cached = _cache_get(cache_key)
    cache_enabled = fetch is None if use_cache is None else use_cache is True
    if isinstance(cached, list) and cache_enabled:
        return cached
    data = _request('volumes', params, fetch=fetch)
    items = data.get('items') or []
    if not isinstance(items, list):
        raise BooksUnavailable('invalid_response')
    items = [item for item in items[:maximum] if isinstance(item, dict)
             and isinstance(item.get('volumeInfo'), dict)
             and isinstance(item['volumeInfo'].get('title'), str) and item['volumeInfo']['title'].strip()]
    if cache_enabled:
        _cache_set(cache_key, items, 900 if items else 45)
    return items


def get_volume(volume_id, *, fetch=None, use_cache=None):
    if not getattr(settings, 'LITMATE_USE_GOOGLE_BOOKS_API', True):
        raise BooksUnavailable('disabled')
    if not isinstance(volume_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', volume_id):
        raise BooksUnavailable('invalid_id')
    cache_key = 'google_book_volume_v2:' + hashlib.sha256((volume_id + str(
        getattr(settings, 'GOOGLE_BOOKS_API_KEY', ''))).encode()).hexdigest()
    cached = _cache_get(cache_key)
    cache_enabled = fetch is None if use_cache is None else use_cache is True
    if isinstance(cached, dict) and cache_enabled:
        return cached
    data = _request('volumes/' + quote(volume_id, safe=''), {'projection': 'full'}, fetch=fetch)
    if (not isinstance(data.get('volumeInfo'), dict)
            or not isinstance(data['volumeInfo'].get('title'), str) or not data['volumeInfo']['title'].strip()):
        raise BooksUnavailable('invalid_response')
    if cache_enabled:
        _cache_set(cache_key, data, 3600)
    return data


def _text(value, maximum=1000):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', str(value or '')))).strip()[:maximum]


def _google_link(value):
    from .literary_ai import safe_source_url
    value = str(value or '').replace('http://', 'https://', 1)
    safe = safe_source_url(value)
    if not safe:
        return ''
    host = urlsplit(safe).hostname
    allowed = {'books.google.com', 'books.google.es', 'books.google.cl', 'books.google.com.ar',
               'books.google.com.mx', 'books.google.co.uk', 'play.google.com'}
    return safe if host in allowed else ''


def safe_cover_url(value):
    """Sólo miniaturas de Google, sin credenciales, puertos ni hosts arbitrarios."""
    from .literary_ai import safe_source_url
    safe = safe_source_url(str(value or '').replace('http://', 'https://', 1))
    if not safe:
        return ''
    host = urlsplit(safe).hostname
    allowed = {'books.google.com', 'books.google.es', 'books.google.cl',
               'books.google.com.ar', 'books.google.com.mx', 'books.google.co.uk',
               'books.googleusercontent.com'}
    return safe if host in allowed or host.endswith('.googleusercontent.com') else ''


def _normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFD', str(value or '').lower())
                   if unicodedata.category(c) != 'Mn')


_SPACE_NARRATIVE = (r'\b(?:tematica|ambientacion) espacial\b|'
                    r'\baventuras? espaciales?\b|\bspace opera\b|'
                    r'\b(?:novelas?|cuentos?|relatos?|historias?)\b.{0,45}'
                    r'\b(?:en el espacio|viajes? espaciales?|viajes? interplanetarios?)\b')
_SPACE_TOPIC = (_SPACE_NARRATIVE + r'|\bespacio exterior\b|'
                r'\bviajes? (?:espaciales?|interplanetarios?)\b|'
                r'\bexploracion espacial\b')


GENRES = (
    ('science_fiction', r'\bciencia ficcion\b|\bscience fiction\b|\bsci[ -]?fi\b|'
                       + _SPACE_NARRATIVE,
     'Science Fiction', ('ciencia ficcion', 'science fiction', 'sci-fi', 'nave espacial',
                        'viaje en el tiempo', 'viajes en el tiempo', 'extraterrestre',
                        'interplanetari', 'distopi', 'space opera')),
    ('fantasy', r'\bfantasia\b|\bfantasy\b', 'Fantasy',
     ('fantasia', 'fantasy', 'magia', 'hechicer', 'dragon', 'reino magico')),
    ('horror', r'\bterror\b|\bhorror\b', 'Horror',
     ('terror', 'horror', 'sobrenatural', 'fantasma')),
    ('mystery', r'\bmisterio\b|\bpoliciac\w*\b|\bthriller\b|\bsuspense\b', 'Mystery',
     ('mystery', 'misterio', 'policiac', 'thriller', 'detective', 'suspense')),
    ('romance', r'\bromanticas?\b|\bromance\b', 'Romance',
     ('romance', 'romantic', 'historia de amor')),
)

# Las exclusiones usan nombres de género, no sinónimos de ambientación. Así
# «temática espacial sin ciencia ficción» conserva el espacio sin reactivar
# el género excluido mediante el alias narrativo positivo.
_GENRE_EXCLUSION_NAMES = {
    'science_fiction': r'ciencia\s*ficcion|science fiction|sci[ -]?fi|space opera',
    'fantasy': r'fantasia|fantasy', 'horror': r'terror|horror',
    'mystery': r'misterio|mystery|thriller|suspense',
    'romance': r'romance|romanticas?',
}
_GENRE_EXCLUSION_PREFIX = (r'\b(?:no(?:\s+(?:sean?|quiero|incluyas?))?|sin|excepto|'
                           r'excluye|excluding|not)\s+'
                           r'(?:(?:libros?|novelas?|obras?)\s+)?(?:de\s+)?')


def _genre_exclusions(value):
    # Los nombres de obras entrecomillados no expresan un filtro del lector.
    value = re.sub(r'[«“"]([^»”"\n]{1,300})[»”"]', '', value)
    if re.search(r'\b(?:isbn|intitle|lccn|oclc):', value):
        return ()
    return tuple(code for code, names in _GENRE_EXCLUSION_NAMES.items()
                 if re.search(_GENRE_EXCLUSION_PREFIX + '(?:' + names + r')\b', value))


def book_search_profile(query):
    """Reconoce filtros de lectura; no genera títulos ni hechos de una obra."""
    query = public_query(query)
    value = _normalized(query)
    excluded = _genre_exclusions(value)
    # No transforma una exclusión en una búsqueda positiva del mismo género.
    for code in excluded:
        value = re.sub(_GENRE_EXCLUSION_PREFIX + '(?:' + _GENRE_EXCLUSION_NAMES[code] + r')\b',
                       '', value)
    precise = bool(re.search(r'\b(?:isbn|intitle|inauthor|inpublisher|lccn|oclc):', value))
    studies = bool(re.search(r'\b(?:estudios?|ensayos?|teoria|critica|manuales?|textos? escolares|'
                             r'libros? de texto|libros? cientificos|historia del genero|'
                             r'divulgacion)\b', value))
    genre = next((row for row in GENRES if row[0] not in excluded and re.search(row[1], value)), None)
    novels = bool(re.search(r'\bnovelas?\b|\bnovels?\b', value))
    fiction = (novels or genre is not None) and not studies and not precise
    return {'query': query, 'genre': genre, 'fiction': fiction, 'novels': novels,
            'precise': precise, 'studies': studies, 'excluded_genres': excluded}


# Traduce materias del catálogo, no títulos ni información sobre las obras.
# Las variantes se comprueban también contra los metadatos devueltos: una
# búsqueda que incluya Japón no demuestra por sí sola que un resultado trate
# sobre arte japonés.
_TOPIC_SUBJECTS = (
    ('history', r'\bhistoria\b|\bhistoric[oa]s?\b|\bhistory\b',
     ('historia', 'history', 'historical', 'histoire')),
    ('art', r'\barte\b|\bartes\b|\bart\b|\bartistic[oa]s?\b',
     ('art', 'arte', 'arts', 'pintura', 'painting', 'sculpture', 'escultura', 'estampas', 'prints', 'ukiyo')),
    ('philosophy', r'\bfilosofia\b|\bphilosophy\b', ('filosofia', 'philosophy', 'philosophie')),
    ('architecture', r'\barquitectura\b|\barchitecture\b', ('arquitectura', 'architecture')),
    ('poetry', r'\bpoesia\b|\bpoetry\b', ('poesia', 'poetry', 'poesie')),
    ('cooking', r'\bcocina\b|\bgastronomia\b|\bcooking\b', ('cocina', 'cooking', 'gastronomia', 'cookery')),
    ('space', _SPACE_TOPIC,
     ('space', 'outer space', 'spaceflight', 'space travel', 'space exploration',
      'space colonies', 'space warfare', 'space opera', 'interplanetary voyages',
      'extraterrestrial beings', 'life on other planets', 'nave espacial',
      'viajes espaciales', 'viajes interplanetarios', 'tematica espacial',
      'aventura espacial', 'astronomy', 'astronomia', 'astrophysics', 'astrofisica', 'cosmology', 'cosmologia')),
)
_TOPIC_PLACES = (
    ('south korea', r'\bcorea del sur\b|\bsurcorean\w*\b|\bsouth korea\b',
     ('south korea', 'corea del sur', 'korea (south)', 'korea south', 'korean republic')),
    ('north korea', r'\bcorea del norte\b|\bnorcorean\w*\b|\bnorth korea\b',
     ('north korea', 'corea del norte', 'korea (north)', 'korea north')),
    ('korea', r'\bcorea\b|\bcorean\w*\b|\bkorea\b|\bkorean\w*\b',
     ('korea', 'koreas', 'korean', 'corea', 'coreano', 'coreana', 'coree')),
    ('japan', r'\bjapon\b|\bjapones\w*\b|\bjapan\b|\bjapanese\b',
     ('japan', 'japanese', 'japon', 'japones', 'japonais')),
    ('china', r'\bchina\b|\bchino\w*\b|\bchinese\b', ('china', 'chinese', 'chino', 'chines', 'chinois')),
    ('chile', r'\bchile\b|\bchilen\w*\b', ('chile', 'chilean', 'chileno', 'chilena')),
    ('peru', r'\bperu\b|\bperuan\w*\b', ('peru', 'peruvian', 'peruano', 'peruana')),
    ('mexico', r'\bmexico\b|\bmexican\w*\b', ('mexico', 'mexican', 'mexicano', 'mexicana')),
    ('spain', r'\bespana\b|\bespanol\w*\b|\bspain\b', ('spain', 'spanish', 'espana', 'espanol')),
    ('italy', r'\bitalia\b|\bitalian\w*\b|\bitaly\b', ('italy', 'italian', 'italia')),
    ('france', r'\bfrancia\b|\bfrances\w*\b|\bfrance\b', ('france', 'french', 'francia', 'frances')),
)


def book_topic_profile(query):
    """Materias explícitas para buscar y verificar recomendaciones temáticas.

    No traduce un título entre comillas ni una consulta de identidad. Los
    ámbitos desconocidos conservan el texto del lector, sin adivinar materias.
    """
    query = public_query(query)
    value = _normalized(query)
    if re.search(r'\b(?:isbn|intitle|inauthor|inpublisher|lccn|oclc):', value) or re.search(r'[«“"]', query):
        return {'subjects': (), 'places': (), 'query': query, 'structured': False}
    subjects = tuple(row for row in _TOPIC_SUBJECTS if re.search(row[1], value))
    reading = book_search_profile(query)
    if reading['fiction'] and reading['genre']:
        genre = reading['genre']
        subjects += ((genre[2].lower(), genre[1], genre[3]),)
    elif reading['fiction'] and subjects:
        subjects += (('fiction', r'\bfiction\b|\bficcion\b|\bnovelas?\b', ('fiction', 'ficcion', 'novela')),)
    geography = re.sub(r'\b(?:en|idioma|al)\s+espanol\b', '', value)
    place = next((row for row in _TOPIC_PLACES if re.search(row[1], geography)), None)
    places = (place,) if place else ()
    # Solo activar restricciones de materia ante un tema explícito. "¿Quién
    # escribió El arte de la guerra?" continúa siendo una búsqueda de título.
    requested = bool(re.search(r'\b(?:recomiend\w*|busc\w*|libros?|obras?|books?|sobre)\b', value))
    standalone = bool(subjects and places and len(value.split()) <= 8)
    structured = bool(subjects and (requested or standalone))
    if structured:
        terms = [f'subject:"{row[0]}"' for row in (*subjects, *places)]
        terms.extend(f'-subject:"{row[2].lower()}"' for row in GENRES
                     if row[0] in reading['excluded_genres'])
        public = ' '.join(terms)
    else:
        public = re.sub(r'^(?:por favor\s+)?(?:estoy buscando|estoy buscando un libro|busco|buscame|'
            r'recomiendame|recomienda|recomendar|quiero|necesito)\s+', '', value)
        public = re.sub(r'^(?:(?:un|una|unos|unas|dos|tres|cuatro|cinco|algunos|algunas)\s+)?'
                        r'(?:libros?|obras?|novelas?)\s+(?:sobre\s+|acerca de\s+|de\s+)?', '', public).strip()
        public = public or query
    return {'subjects': subjects if structured else (), 'places': places if structured else (),
            'query': public, 'structured': structured}


def topic_matches(source, query):
    """Cada materia y lugar pedidos necesita respaldo en título o metadatos."""
    profile = book_topic_profile(query)
    if source.get('kind', 'book') != 'book':
        return True
    reading = book_search_profile(query)
    categories = source.get('categories') or []
    category_text = _normalized(' '.join(str(item) for item in categories if isinstance(item, str)))
    genre_metadata = category_text + ' ' + _normalized(source.get('title'))
    if any(re.search(r'(?<!\w)(?:' + _GENRE_EXCLUSION_NAMES[code] + r')(?!\w)', genre_metadata)
           for code in reading['excluded_genres']):
        return False
    if not profile['structured']:
        return True
    text = _normalized(' '.join([str(source.get('title') or ''), str(source.get('subtitle') or ''),
                                str(source.get('synopsis') or ''),
                                category_text]))
    if (not book_search_profile(query)['fiction'] and not any(row[0] == 'poetry' for row in profile['subjects'])
            and not re.search(r'\b(?:novelas?|ficcion|fiction)\b', _normalized(query)) and re.search(
            r'\b(?:fiction|ficcion|novela)\b', category_text)):
        return False
    if any(row[0] == 'art' for row in profile['subjects']):
        text = re.sub(r'\b(?:language arts(?: and| &) disciplines|language arts|martial arts)\b', '', text)
    if any(row[0] == 'space' for row in profile['subjects']) and book_search_profile(query)['fiction']:
        # La mención de ciencia ficción en un estudio sobre el género no lo
        # convierte en una aventura espacial. Se aplica también a fichas del
        # catálogo local, que pueden llegar sin pasar por rank_book_sources.
        if (re.search(r'\b(?:nonfiction|non-fiction|no ficcion|study aids|literary criticism|'
                      r'social science|textbooks?|manuales?|divulgacion)\b', category_text)
                or re.search(r'\b(?:manual|tratado|estudio de|sociologia|study guide|textbook)\b',
                             _normalized(source.get('title')))):
            return False
    if not all(any(re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', text) for term in row[2])
               for row in (*profile['subjects'], *profile['places'])):
        return False
    if any(row[0] == 'art' for row in profile['subjects']) and re.search(
            r'\b(?:martial arts?|military|militar|bushido|warfare|arte de la guerra)\b', text):
        # La palabra "arte" en un tratado militar no lo convierte en un libro
        # de artes visuales. Exigir una materia visual independiente.
        if not any(re.search(r'(?<!\w)' + term + r'(?!\w)', category_text)
                   for term in ('painting', 'pintura', 'sculpture', 'escultura', 'prints', 'ukiyo', 'fine arts', 'art history')):
            return False
    return True


def book_search_queries(query):
    """Dos consultas acotadas de categoría/tema en vez de enviar todo el pedido."""
    profile = book_search_profile(query)
    if profile['fiction'] and profile['genre']:
        genre = profile['genre']
        spanish = {'science_fiction': 'ciencia ficción', 'fantasy': 'fantasía',
                   'horror': 'terror', 'mystery': 'misterio', 'romance': 'romance'}[genre[0]]
        return [f'subject:fiction novela "{spanish}"', f'{spanish} novela']
    if profile['fiction']:
        theme = re.sub(r'\b(?:recomiendame|recomienda|novelas?|novels?|libros?|books?|'
                       r'una?|unos?|unas?|dos|tres|cuatro|cinco|sobre|de|y|explica|sus|diferencias)\b',
                       ' ', _normalized(profile['query']))
        theme = re.sub(r'\s+', ' ', theme).strip()
        return [(theme + ' subject:fiction').strip()]
    return [profile['query']] if profile['query'] else []


def source_synopsis(source):
    """Separa la sinopsis editorial de ISBN, fechas y otros datos de la edición."""
    synopsis = source.get('synopsis')
    if isinstance(synopsis, str) and synopsis.strip():
        return _text(synopsis, 1600)
    research = source.get('research_summary')
    if isinstance(research, str) and research.strip():
        return _text(research, 1200)
    description = str(source.get('description') or '')
    if description.startswith('Temas del catálogo:'):
        return ''
    marker = re.search(r'sinopsis editorial\s*:\s*', description, re.I)
    if marker:
        return _text(description[marker.end():], 1600)
    if not re.search(r'\b(?:ISBN|Editorial|Publicaci[oó]n|P[aá]ginas|Idioma)\s*:', description, re.I):
        return _text(description, 1600)
    return ''


def rank_book_sources(sources, query, *, distinct_works=False):
    """Descarta material escolar cuando se pide narrativa y ordena por evidencia."""
    profile = book_search_profile(query)
    fiction = profile['fiction']
    genre = profile['genre']
    topic = book_topic_profile(query)
    ranked = []
    for position, source in enumerate(sources):
        if not isinstance(source, dict):
            continue
        if not topic_matches(source, query):
            continue
        if source.get('kind') == 'excerpt':
            ranked.append((100, position, source))
            continue
        title = _normalized(source.get('title'))
        categories = source.get('categories') or []
        categories = _normalized(' '.join(str(c) for c in categories)) if isinstance(categories, list) else ''
        synopsis = _normalized(source_synopsis(source))
        text = title + ' ' + categories + ' ' + synopsis
        school_title = re.search(r'\b(?:cuadernos?|bachillerato|secundaria|primaria|'
            r'texto escolar|taller de lectura|lengua castellana|actividades|'
            r'guia de (?:lectura|estudio)|manual de|workbook|study guide)\b', title)
        non_fiction = re.search(r'\b(?:study aids|education|language arts|literary criticism|'
                               r'juvenile nonfiction|nonfiction|non-fiction|no ficcion|performing arts|'
                               r'science fiction films|computers|book covers|mexican essays|science|'
                               r'biology in literature)\b', categories)
        # "Science Fiction" es narrativa; "Science" a secas suele ser divulgación.
        if non_fiction and non_fiction.group(0) == 'science' and 'science fiction' in categories:
            non_fiction = None
        criticism = (re.search(r'\b(?:el cine|cine mexicano|philosophy of .*film|science fiction prototyping)\b', title)
                     or re.search(r'\b(?:un ensayo|este ensayo|an essay|este libro (?:analiza|estudia))\b', synopsis))
        if fiction and (school_title or non_fiction or criticism):
            continue
        if (profile['novels'] and genre and re.fullmatch(r'(?:la |el )?(?:ciencia ficcion|science fiction)', title)
                and not re.search(r'\bnovela\b|\bnovel\b', synopsis)):
            continue
        if profile['novels'] and (re.search(r'\b(?:cuentos?|relatos?|antologia|anthology|short stories)\b', title)
                                  or 'comics' in categories or re.search(
                                      r'\b(?:antologia|anthology|coleccion de (?:\w+ ){0,2}(?:cuentos|relatos))\b', synopsis)):
            continue
        category_match = bool(genre and any(word in categories for word in genre[3][:3]))
        genre_match = bool(genre and any(word in text for word in genre[3]))
        if fiction and genre and not genre_match:
            continue
        if fiction and not genre and not re.search(r'\bfiction\b|\bficcion\b|\bnovela\b', text):
            continue
        score = (12 if category_match else 6 if genre_match else 0)
        score += (3 if synopsis else 0) + (2 if source.get('author') else 0)
        score += (2 if source.get('language') == 'es' else 0)
        score += (1 if 'Google Books' in str(source.get('source')) else 0)
        if topic['structured']:
            for facet in topic['subjects']:
                if any(re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', title) for term in facet[2]):
                    score += 7
            for facet in topic['places']:
                if any(re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', title) for term in facet[2]):
                    score += 3
            if any(facet[0] == 'history' for facet in topic['subjects']) and re.search(
                    r'\b(?:biography|memoirs?|autobiography|biografia)\b', categories):
                score -= 3
        ranked.append((score, position, source))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    if distinct_works:
        # Una edición en español de la misma obra evita recomendar primero
        # su edición inglesa sólo por tener categorías editoriales más completas.
        spanish = {(_normalized(row[2].get('title')), _normalized(row[2].get('author')))
                   for row in ranked if row[2].get('language') == 'es'}
        ranked = [row for row in ranked if row[2].get('language') == 'es' or
                  (_normalized(row[2].get('title')), _normalized(row[2].get('author'))) not in spanish]
    selected, seen = [], set()
    for score, position, source in ranked:
        identity = (_normalized(source.get('title')), _normalized(source.get('author')))
        if distinct_works and identity in seen:
            continue
        seen.add(identity)
        selected.append(source)
    return selected


def volume_source(item):
    """Metadata explícita para responder sin confundir una sinopsis con la obra."""
    info = item.get('volumeInfo') or {}
    access = item.get('accessInfo') if isinstance(item.get('accessInfo'), dict) else {}
    volume_id = str(item.get('id', ''))[:100]
    authors = info.get('authors') or []
    identifiers = info.get('industryIdentifiers') if isinstance(info.get('industryIdentifiers'), list) else []
    isbns = [_text(i.get('identifier'), 20) for i in identifiers
             if isinstance(i, dict) and i.get('type') in {'ISBN_10', 'ISBN_13'}]
    metadata = []
    for label, value in [('Editorial', info.get('publisher')), ('Publicación', info.get('publishedDate')),
                         ('Páginas', info.get('pageCount')), ('Idioma', info.get('language'))]:
        if value:
            metadata.append(label + ': ' + _text(value, 120))
    if isbns:
        metadata.append('ISBN: ' + ', '.join(isbns))
    description = _text(info.get('description'), 1600)
    if _normalized(description).strip(' .') in {'publisher description', 'no description available',
                                                'sin descripcion', 'sin descripcion disponible'}:
        description = ''
    if description:
        metadata.append('Sinopsis editorial: ' + description)
    link = _google_link(info.get('canonicalVolumeLink')) or (
        'https://books.google.com/books?' + urlencode({'id': volume_id}) if volume_id else '')
    images = info.get('imageLinks') if isinstance(info.get('imageLinks'), dict) else {}
    image_url = next((url for url in [safe_cover_url(images.get(name))
                     for name in ('thumbnail', 'smallThumbnail', 'small', 'medium', 'large')] if url), '')
    return {'title': _text(info.get('title'), 220), 'subtitle': _text(info.get('subtitle'), 220),
            'author': ', '.join(_text(a, 120) for a in authors[:5]) if isinstance(authors, list) else '',
            'description': '\n'.join(metadata), 'synopsis': description, 'image_url': image_url,
            'year': str(info.get('publishedDate', ''))[:4],
            'source': 'Google Books API', 'book_id': volume_id, 'kind': 'book', 'url': link,
            'publisher': _text(info.get('publisher'), 120),
            'published_date': _text(info.get('publishedDate'), 30),
            'language': _text(info.get('language'), 10),
            'page_count': info.get('pageCount') if type(info.get('pageCount')) is int and info['pageCount'] >= 0 else None,
            'isbns': isbns, 'categories': [_text(c, 100) for c in (info.get('categories')
                if isinstance(info.get('categories'), list) else [])[:5] if isinstance(c, str)],
            'preview_url': _google_link(info.get('previewLink')),
            'read_url': _google_link(access.get('webReaderLink')),
            'viewability': _text(access.get('viewability'), 30),
            'public_domain': access.get('publicDomain') is True,
            'read_mode': 'ficha y sinopsis; vista previa externa' if access.get('viewability') in {
                'PARTIAL', 'ALL_PAGES'} else 'ficha y sinopsis bibliográfica'}
