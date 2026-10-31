"""Restricciones explícitas del lector; nunca se deducen del título de una obra."""
import re
import unicodedata
from .literary_identity import normalize_identity


LANGUAGES = {
    'es': ('espanol', 'castellano', 'spanish', 'spa', 'es'),
    'en': ('ingles', 'english', 'eng', 'en'),
    'fr': ('frances', 'french', 'fra', 'fre', 'fr'),
    'de': ('aleman', 'german', 'deu', 'ger', 'de'),
    'pt': ('portugues', 'portuguese', 'por', 'pt'),
    'ja': ('japones', 'japanese', 'jpn', 'ja'),
}


def _normal(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or ''))
                   if not unicodedata.combining(c)).casefold().strip()


def requested_language(message):
    # «Un libro titulado En inglés» no expresa preferencia de idioma.
    text = re.sub(r'[«“\"]([^»”\"\n]{1,300})[»”\"]', '', str(message or ''))
    value = _normal(text)
    for language, names in LANGUAGES.items():
        if re.search(r'\b(?:en|idioma)\s+(?:' + '|'.join(map(re.escape, names[:3])) + r')\b', value):
            return language
    return ''


def language_matches(source, language):
    if not language or source.get('kind', 'book') not in {'book', 'excerpt'}:
        return True
    value = _normal(source.get('language'))
    return value in LANGUAGES.get(language, ())


def explicit_author(message):
    """Solo fórmulas inequívocas o un nombre propio completo tras «de»."""
    text = re.sub(r'[«“\"]([^»”\"\n]{1,300})[»”\"]', '', str(message or ''))
    cue = re.search(r'\b(?:del autor|de la autora|escrit[oa]s? por)\s+(.+)', text, re.I)
    if cue:
        name = re.split(r'[.!?;,]|\s+(?:sobre|acerca|en|publicad\w*|escrit\w*|pero|que|y que)\b',
                        cue.group(1), maxsplit=1, flags=re.I)[0].strip()
        return name if 1 <= len(name.split()) <= 6 and len(name) <= 150 else ''
    proper = r'[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+(?:[-\x27][A-ZÁÉÍÓÚÑa-záéíóúñü]+)?'
    cue = re.search(r'\b(?i:libros?|novelas?|obras?)\s+(?i:de)\s+('
                    + proper + r'(?:\s+(?:(?:de|del|la|y)\s+)?' + proper + r'){1,4})', text)
    if not cue:
        return ''
    name = cue.group(1).strip()
    # Las mayúsculas de «libros de Segunda Guerra Mundial» o «Historia de
    # Corea» no convierten una materia completa en un nombre de autor. Solo se
    # descarta esta inferencia si todo el nombre coincide con materias/lugares
    # reconocidos; «del autor ...» sigue siendo explícito y prevalece arriba.
    from .books_google import book_topic_profile
    profile = book_topic_profile('libros sobre ' + name)
    remaining = _normal(name)
    for row in (*profile['subjects'], *profile['places']):
        remaining = re.sub(row[1], ' ', remaining)
    if profile['structured'] and not re.sub(r'\b(?:de|del|la|el|y)\b|\W', '', remaining):
        return ''
    return name


def publication_range(message):
    value = _normal(re.sub(r'[«“\"]([^»”\"\n]{1,300})[»”\"]', '', str(message or '')))
    cue = r'\b(?:publicad[oa]s?|escrit[oa]s?|publicacion)\s+'
    between = re.search(cue + r'entre\s+(1\d{3}|20\d{2})\s+(?:y|a|hasta)\s+(1\d{3}|20\d{2})\b', value)
    if between:
        low, high = map(int, between.groups())
        return (low, high) if low <= high else (1, 0)
    year = re.search(cue + r'en\s+(1\d{3}|20\d{2})\b', value)
    if year:
        return int(year.group(1)), int(year.group(1))
    bound = re.search(cue + r'(antes|despues) de\s+(1\d{3}|20\d{2})\b', value)
    if bound:
        year = int(bound.group(2))
        return (1, year - 1) if bound.group(1) == 'antes' else (year + 1, 9999)
    century = re.search(r'(?:' + cue + r'en el|\b(?:novelas?|obras?|libros?) del)\s+siglo\s+'
                        r'(xxi|xx|xix|xviii|xvii|xvi|xv|xiv|xiii|xii|xi|x|ix|viii|vii|vi|v|iv|iii|ii|i)\b', value)
    if century:
        roman = century.group(1)
        numerals = {'i': 1, 'v': 5, 'x': 10}
        number = sum(-numerals[c] if index + 1 < len(roman) and numerals[c] < numerals[roman[index + 1]]
                     else numerals[c] for index, c in enumerate(roman))
        return (number - 1) * 100 + 1, number * 100
    return None


def recommendation_constraints(message):
    result = {'language': requested_language(message), 'author': explicit_author(message),
              'publication_range': publication_range(message)}
    value = normalize_identity(message)
    if re.search(r'\bpara (?:lectores )?adultos\b', value):
        result['audience'] = 'adult'
    if re.search(r'\bsin (?:sagas|series)\b|\bautoconclusiv[oa]s?\b', value):
        result['standalone'] = True
    return result


def constraints_match(source, constraints):
    if source.get('kind', 'book') not in {'book', 'excerpt'}:
        return True
    metadata = normalize_identity(' '.join(str(category) for category in source.get('categories', [])))
    prose = normalize_identity(str(source.get('synopsis', '')) + ' ' + str(source.get('description', '')))
    if constraints.get('audience') == 'adult':
        if re.search(r'\b(?:juvenile|juvenil|children|childrens|infantil|young adult)\b', metadata):
            return False
        if not re.search(r'\b(?:adultos|adult|profesionales|universitarios)\b', prose + ' ' + metadata):
            return False
    if constraints.get('standalone'):
        if source.get('series') or re.search(r'\bno (?:es|se considera) (?:una novela )?autoconclusiva\b', prose):
            return False
        if not re.search(r'\b(?:autoconclusiv[oa]|stand alone|standalone|novela independiente|'
                         r'no forma parte de (?:una |ninguna )?(?:saga|serie))\b', prose):
            return False
    if not language_matches(source, constraints['language']):
        return False
    if constraints['author']:
        from .literary_identity import same_author_name
        if not same_author_name(source.get('author'), constraints['author']):
            return False
    period = constraints['publication_range']
    if period:
        # Los años genéricos de una edición de Books no prueban cuándo se
        # escribió/publicó originalmente la obra. No mezclarlos con los de OL.
        origins = str(source.get('source', '')).split(' / ')
        if not ('Open Library' in origins or 'Catálogo LitMate' in origins
                or source.get('publication_scope') == 'work'):
            return False
        match = re.fullmatch(r'(\d{1,4})', str(source.get('year', '')))
        if not match or not period[0] <= int(match.group(1)) <= period[1]:
            return False
    return True
