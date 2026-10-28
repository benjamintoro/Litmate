"""Pistas bibliográficas literales de páginas públicas, confirmadas en catálogos.

Este módulo no lee URLs, no llama al modelo y no convierte páginas en libros.
El callback consulta los recuperadores existentes con su caché y presupuesto.
Un título/autor extraído sólo orienta esa consulta: el resultado publicado debe
ser una ficha independiente, de la misma obra y con materias pertinentes.
"""
import re
from urllib.parse import urlsplit

from .ai_budget import BudgetExpired, check_budget
from .books_google import public_query, topic_matches
from .literary_ai import safe_source_url
from .literary_identity import normalize_identity, same_work
from .literary_web import public_text_has_injection


_MAX_CANDIDATES = 3
_MAX_PAGES = 5
_MAX_PASSAGE = 4000
_NAME_WORD = r"(?:[A-ZÀ-ÖØ-Þ]\.|[A-ZÀ-ÖØ-Þ][^\W\d_]*(?:[’'-][^\W\d_]+)*)"
_AUTHOR = _NAME_WORD + r'(?:[ \t]+(?:' + _NAME_WORD + r'|de|del|la|las|los|y|van|von|da|dos|di|le|du)){0,7}'
_END_AUTHOR = r'(?=\s*(?:[.,;:!?]|\n|$))'
_QUOTED_PAIR = re.compile(
    r'[«“"](?P<title>[^»”"\r\n]{2,180})[»”"]\s*,?\s+(?:de|por)\s+'
    r'(?P<author>' + _AUTHOR + r')' + _END_AUTHOR)
_LIST_PAIR = re.compile(
    r'^\s*(?:(?:[-*•]|\d{1,2}[.)])\s+)?(?P<title>[^\r\n]{2,180}?)'
    r'(?:\s+[—–-]\s+|,\s+(?:de|por)\s+)(?P<author>' + _AUTHOR + r')' + _END_AUTHOR,
    re.MULTILINE)
_INLINE_NUMBERED_PAIR = re.compile(
    r'(?<!\w)\d{1,2}[.)]\s+(?P<title>[^\r\n]{2,180}?)'
    r'(?:\s+[—–-]\s+|,\s+(?:de|por)\s+)(?P<author>' + _AUTHOR + r')' + _END_AUTHOR)


def _public_url(value):
    """Filtro sintáctico, sin resolver DNS ni acceder a la URL del artículo.

    Las páginas que llegan aquí deben venir de los lectores públicos actuales,
    que ya verifican DNS, redirecciones y robots. Nunca se envía esta URL al
    callback: únicamente título y autor pasan a APIs de catálogos conocidas.
    """
    url = safe_source_url(value)
    if not url:
        return False
    host = (urlsplit(url).hostname or '').lower()
    return bool('.' in host and not host.endswith(
        ('.local', '.localhost', '.localdomain', '.internal', '.test', '.invalid')))


def _candidate_pairs(pages):
    seen = set()
    for page in pages[:_MAX_PAGES]:
        if (not isinstance(page, dict) or page.get('kind') != 'web'
                or page.get('injection_detected') or page.get('conflicts_with')
                or page.get('user_provided') or page.get('private') or page.get('is_private')
                or not _public_url(page.get('url'))):
            continue
        raw_body = page.get('description')
        if not isinstance(raw_body, str):
            continue
        body = raw_body[:_MAX_PASSAGE]
        if not body or public_text_has_injection(str(page.get('title', '')) + ' ' + body):
            continue
        matches = [match for pattern in (_QUOTED_PAIR, _LIST_PAIR, _INLINE_NUMBERED_PAIR)
                   for match in pattern.finditer(body)]
        for match in sorted(matches, key=lambda item: item.start()):
            title, author = (re.sub(r'\s+', ' ', match.group(key)).strip() for key in ('title', 'author'))
            if match.re is _LIST_PAIR and re.search(r'(?<!\w)\d{1,2}[.)]\s+', title):
                continue  # Introductory prose before a compacted numbered item.
            if len(title) >= 2 and (title[0], title[-1]) in {('«', '»'), ('“', '”'), ('"', '"')}:
                title = title[1:-1].strip()
            candidate = {'title': title, 'author': author}
            key = normalize_identity(title), normalize_identity(author)
            if key not in seen:
                seen.add(key)
                yield candidate


def resolve_recommendation_candidates(message, pages, search):
    """Devuelve hasta tres fichas verificadas, nunca los artículos de origen.

    Las restricciones no reconocidas siguen por el pipeline general: encontrar
    un género amplio no certifica su subgénero, idioma, autoría o época. Los
    fallos y el agotamiento de tiempo no se transforman en resultados vacíos
    inventados ni permiten publicar una pareja sólo por aparecer en una web.
    """
    from .ai_catalog_fallback import _topic_catalogue_origin
    from .ai_quick_answers import _simple_topic_request
    from .literary_constraints import constraints_match, recommendation_constraints
    from .literary_research import public_research_queries

    if (not isinstance(message, str) or not isinstance(pages, (list, tuple))
            or not callable(search) or not public_research_queries(message)
            or not _simple_topic_request(message, message)):
        return []
    constraints = recommendation_constraints(message)
    confirmed, lookups = [], 0
    for candidate in _candidate_pairs(pages):
        if lookups >= _MAX_CANDIDATES:
            break
        label = candidate['title'] + ' ' + candidate['author']
        # Do not turn redaction into permission to send the rest of a secret.
        # Truncation or removal of sensitive/personal content rejects the pair.
        if (not public_research_queries(label) or public_query(label) != label):
            continue
        query = ('intitle:"' + candidate['title'].replace('"', ' ') + '" '
                 'inauthor:"' + candidate['author'].replace('"', ' ') + '"')
        if public_query(query) != query or not public_research_queries(query):
            continue
        try:
            check_budget()
            lookups += 1
            sources = search(query)
        except BudgetExpired:
            break
        except (OSError, TimeoutError, ValueError, TypeError):
            continue
        if not isinstance(sources, (list, tuple)):
            continue
        for source in sources[:12]:
            if not isinstance(source, dict) or not _topic_catalogue_origin(source):
                continue
            categories = source.get('categories')
            text = ' '.join(str(source.get(field) or '') for field in
                            ('title', 'author', 'description', 'synopsis', 'research_summary'))
            if (not isinstance(categories, list) or not any(isinstance(item, str) and item.strip() for item in categories)
                    or source.get('conflicts_with') or public_text_has_injection(text)
                    or (source.get('url') and not _public_url(source['url']))
                    or not same_work(source, candidate) or not topic_matches(source, message)
                    or not constraints_match(source, constraints)
                    or any(same_work(source, previous) for previous in confirmed)):
                continue
            confirmed.append(dict(source))
            # Further editions of this literal title/author are not additional
            # recommendations; the next query must concern another candidate.
            break
    return confirmed
