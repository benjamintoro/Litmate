"""Diccionario local de materias para resolver consultas sin esperar a la red.

El archivo ``data/topic_reference.json`` contiene alias en español e inglés,
materias de catálogo y etiquetas legibles. La búsqueda se hace sobre tokens ya
normalizados y con supresión de coincidencias solapadas: «segunda guerra
mundial» gana a «guerra» y no añade materias que el lector no pidió.

No consulta Internet, no genera hechos y no sustituye la verificación
bibliográfica. Solo acelera la interpretación de la petición y la construcción
de consultas de catálogo.
"""
import json
import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger('litmate')

DATA_FILE = Path(__file__).with_name('data') / 'topic_reference.json'
_TOKEN_RE = re.compile(r'[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñªº]+')
# Las clases incluyen variantes acentuadas para que un patrón construido con
# texto normalizado siga funcionando sobre la petición original del lector.
_ACCENT_CLASSES = {
    'a': 'aáàäâãª', 'e': 'eéèëê', 'i': 'iíìïî', 'o': 'oóòöôõ',
    'u': 'uúùüû', 'n': 'nñ', 'c': 'cç', 's': 'sß',
}
_SEPARATOR = r'[\s.\-_,;:]+'


def fold(value):
    """Minúsculas, sin tildes y con separadores convertidos en espacios."""
    value = str(value or '').replace('ª', 'a').replace('º', 'o')
    value = unicodedata.normalize('NFKD', value.casefold())
    value = ''.join(character for character in value
                    if not unicodedata.combining(character))
    return re.sub(r'[^0-9a-z]+', ' ', value).strip()


def _tokenize(value):
    """Tokens normalizados con sus posiciones literales en el texto."""
    result = []
    for match in _TOKEN_RE.finditer(str(value or '')):
        token = fold(match.group())
        if token:
            result.append((match.start(), match.end(), token))
    return result


def _token_pattern(token):
    parts = []
    for character in token:
        if character in _ACCENT_CLASSES:
            parts.append('[' + _ACCENT_CLASSES[character] + ']')
        else:
            parts.append(re.escape(character))
    return ''.join(parts)


def _alias_pattern(alias):
    """Patrón tolerante a mayúsculas, tildes y puntuación entre palabras."""
    return _SEPARATOR.join(_token_pattern(token) for token in alias)


def _combined_pattern(aliases):
    alternatives = sorted({_alias_pattern(alias) for alias in aliases},
                          key=len, reverse=True)
    if not alternatives:
        return r'(?!x)x'
    return r'(?i)(?<!\w)(?:' + '|'.join(alternatives) + r')(?!\w)'


@lru_cache(maxsize=1)
def _reference():
    """Carga una sola vez el diccionario; un error no tumba el chat."""
    empty = {'facets': {}, 'topics': {}, 'aliases': {}, 'maximum': 0}
    try:
        data = json.loads(DATA_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError) as exc:
        logger.warning('Referencia temática local no disponible (%s)', type(exc).__name__)
        return empty
    if not isinstance(data, dict):
        return empty
    facets = {}
    raw_facets = data.get('facets')
    if isinstance(raw_facets, dict):
        for key, raw in raw_facets.items():
            if not isinstance(key, str) or not key.strip() or not isinstance(raw, dict):
                continue
            label = str(raw.get('label') or key).strip()
            catalog = str(raw.get('catalog') or key).strip()
            terms = tuple(dict.fromkeys(str(term).strip() for term in raw.get('terms', [])
                                        if isinstance(term, str) and str(term).strip()))
            article = str(raw.get('article') or '').strip()
            if label and catalog and terms:
                facets[key] = {'label': label, 'catalog': catalog,
                               'terms': terms, 'article': article}
    topics = {}
    aliases = {}
    raw_topics = data.get('topics')
    if isinstance(raw_topics, list):
        for raw in raw_topics:
            if not isinstance(raw, dict):
                continue
            identifier = str(raw.get('id') or '').strip()
            label = str(raw.get('label') or identifier).strip()
            subjects = tuple(str(item) for item in raw.get('subjects', [])
                             if isinstance(item, str) and item in facets)
            places = tuple(str(item) for item in raw.get('places', [])
                           if isinstance(item, str) and item in facets)
            if not identifier or not label or not (subjects or places):
                continue
            topics[identifier] = {'id': identifier, 'label': label,
                                  'subjects': subjects, 'places': places}
            raw_aliases = raw.get('aliases')
            if not isinstance(raw_aliases, list):
                continue
            for item in raw_aliases:
                if not isinstance(item, str):
                    continue
                key = tuple(fold(item).split())
                if not key or len(key) > 8:
                    continue
                aliases.setdefault(key, []).append(identifier)
    maximum = max((len(key) for key in aliases), default=0)
    return {'facets': facets, 'topics': topics,
            'aliases': {key: tuple(dict.fromkeys(value)) for key, value in aliases.items()},
            'maximum': maximum}


@lru_cache(maxsize=4096)
def _matches(query):
    """Coincidencias no solapadas, de la frase más larga a la más corta."""
    reference = _reference()
    aliases, maximum = reference['aliases'], reference['maximum']
    if not aliases or not maximum:
        return ()
    tokens = _tokenize(query)
    if not tokens:
        return ()
    folded = [token for _, _, token in tokens]
    found = {}
    for start in range(len(folded)):
        for length in range(1, min(maximum, len(folded) - start) + 1):
            key = tuple(folded[start:start + length])
            identifiers = aliases.get(key)
            if not identifiers:
                continue
            span = (start, start + length)
            found.setdefault(span, {})
            for identifier in identifiers:
                found[span][identifier] = key
    if not found:
        return ()
    chosen, occupied = [], set()
    for span in sorted(found, key=lambda value: (-(value[1] - value[0]), value[0])):
        positions = set(range(*span))
        if positions & occupied:
            continue
        chosen.append(span)
        occupied.update(positions)
    result = []
    for start, end in sorted(chosen):
        for identifier, alias in found[(start, end)].items():
            result.append((identifier, alias, tokens[start][0], tokens[end - 1][1]))
    return tuple(result)


def resolve(query):
    """Devuelve materias y lugares reconocidos, listos para el catálogo."""
    reference = _reference()
    subject_order, place_order = [], []
    subject_aliases, place_aliases = {}, {}
    for identifier, alias, _, _ in _matches(query):
        topic = reference['topics'].get(identifier)
        if not topic:
            continue
        for key in topic['subjects']:
            if key not in subject_aliases:
                subject_order.append(key)
                subject_aliases[key] = []
            subject_aliases[key].append(alias)
        for key in topic['places']:
            if key not in place_aliases:
                place_order.append(key)
                place_aliases[key] = []
            place_aliases[key].append(alias)

    def rows(order, patterns):
        result = []
        for key in order:
            facet = reference['facets'][key]
            result.append((key, _combined_pattern(patterns[key]), facet['terms']))
        return tuple(result)

    return {'subjects': rows(subject_order, subject_aliases),
            'places': rows(place_order, place_aliases),
            'labels': {key: reference['facets'][key]['label']
                       for key in (*subject_order, *place_order)}}


def facet(key):
    """Ficha de una materia concreta, sin exponer el diccionario mutable."""
    return _reference()['facets'].get(str(key), {})


def label(key, default=''):
    return facet(key).get('label') or default


def catalog_subject(key, default=''):
    return facet(key).get('catalog') or default


def article(key):
    return facet(key).get('article') or ''


def known_facets():
    return tuple(_reference()['facets'])


def known_topics():
    return tuple(_reference()['topics'])


def alias_count():
    return len(_reference()['aliases'])


def clear_cache():
    """Solo para pruebas o para recargar datos editados en desarrollo."""
    _matches.cache_clear()
    _reference.cache_clear()
