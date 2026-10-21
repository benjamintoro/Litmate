"""Memoria de la petición del lector, separada de respuestas y evidencia.

Un fallo del proveedor no debe borrar «libros sobre arte japonés». Esta memoria
solo guarda el tema explícito solicitado; no certifica títulos, autores o hechos.
"""
import re
import time
import unicodedata

from .literary_constraints import requested_language


TOPIC_LIFETIME = 60 * 60
TOPIC_LIMIT = 140
RECENT_TOPIC_LIMIT = 4
LANGUAGE_QUERIES = {'es': 'en español', 'en': 'en inglés', 'fr': 'en francés',
                    'de': 'en alemán', 'pt': 'en portugués', 'ja': 'en japonés'}


def _safe_language(value):
    return value if isinstance(value, str) and value in LANGUAGE_QUERIES else ''


def _without_language_preference(subject):
    """La materia y el idioma son campos separados, también en sesiones antiguas."""
    value = re.sub(r'\b(?:en|idioma)\s+\w+\b',
                   lambda match: '' if requested_language(match.group(0)) else match.group(0),
                   subject, flags=re.I)
    return re.sub(r'\s+', ' ', value).strip(' ,;')


def _topic_query(subject, language=''):
    query = f'libros sobre {subject}'
    if _safe_language(language):
        query += ', ' + LANGUAGE_QUERIES[language]
    return query


def _language_field(language):
    return {'language': language} if _safe_language(language) else {}


def _normalized(value):
    return ''.join(character for character in unicodedata.normalize('NFKD', str(value or ''))
                   if not unicodedata.combining(character)).casefold()


def _safe_subject(value):
    """No conservar pasajes, direcciones, datos personales ni instrucciones."""
    if not isinstance(value, str):
        return ''
    value = re.sub(r'\s+', ' ', value).strip(' \t.!?¿¡;,:')
    normal = _normalized(value)
    if (not 2 <= len(value) <= TOPIC_LIMIT or len(value.split()) > 20
            or re.search(r'''[<>\[\]{}@"'“”‘’«»\n\r]|https?://|www\.''', value, re.I)
            or re.search(r'\b(?:mi|mis|nuestro|nuestra|contrasena|password|secreto|'
                         r'token|bearer|api\s*key|correo|telefono|direccion|rut|dni|'
                         r'ignora|instrucciones|sistema|prompt|ejecuta)\b', normal)
            or re.search(r'\d{5,}', value)):
        return ''
    return value


def _explicit_subject(message):
    value = str(message or '').strip()
    # Un tema expresado con «sobre» es distinto de una obra titulada «Sobre...»:
    # no extraer títulos citados ni pasajes aportados por el lector.
    if re.search(r'''["'“”‘’«»]''', value):
        return ''
    match = re.search(r'\b(?:libros?|lecturas?|novelas?|ensayos?|bibliograf[ií]a|'
                      r'obras?)\s+(?:sobre|acerca de|de|del)\s+(.+)', value, re.I)
    if not match:
        match = re.search(r'\b(?:recomi[eé]nda(?:me)?|recomendar|busc(?:o|ando)|'
                          r'quiero|necesito)\b.*?\b(?:sobre|acerca de)\s+(.+)', value, re.I)
    if not match:
        return ''
    subject = re.split(r'[;.!?\n]|\s+(?:por favor|recomi[eé]nda(?:me)?|quiero|necesito)\b',
                       match.group(1), maxsplit=1, flags=re.I)[0].strip()
    normal = _normalized(subject)
    if re.fullmatch(r'(?:(?:distintos|diferentes|varios|otros|esos|estos|cualesquiera)\s+)?'
                    r'(?:artistas|autores|generos|estilos|temas|libros|obras)(?:\s+distintos)?', normal):
        return ''
    if normal in {'cualquier tema', 'cualquier genero', 'cualquier tipo', 'lo que sea',
                  'cualquiera', 'todo', 'todos', 'ellos', 'ellas', 'esos', 'estos'}:
        return ''
    return _safe_subject(subject)


def _validated_topic(topic, now):
    if not isinstance(topic, dict) or topic.get('intent') != 'recommend':
        return None
    subject = _safe_subject(topic.get('subject'))
    stamp = topic.get('updated_at')
    if (not subject or isinstance(stamp, bool) or not isinstance(stamp, (int, float))
            or not 0 <= now - stamp <= TOPIC_LIFETIME):
        return None
    language = _safe_language(topic.get('language')) or requested_language(subject)
    subject = _safe_subject(_without_language_preference(subject))
    if not subject:
        return None
    return {'subject': subject, 'intent': 'recommend', 'updated_at': stamp,
            **_language_field(language)}


def _current_topic(state, now):
    return _validated_topic(state.get('topic'), now) if isinstance(state, dict) else None


def _topic_words(subject):
    ignored = set('el la los las un una unos unas de del al en sobre acerca para por '
                  'tema temas asunto asuntos libros libro lecturas lectura obras obra '
                  'recomendaciones recomendaciones anterior anteriores antes primero '
                  'primera ultimo ultima nuevo nueva ese esa eso este esta esto lo y a'.split())
    return {word for word in re.findall(r'[a-z0-9]+', _normalized(subject))
            if len(word) >= 3 and word not in ignored}


def _recent_topics(state, now):
    """Solo peticiones saneadas, sin títulos aceptados, fuentes ni respuestas."""
    if not isinstance(state, dict):
        return []
    raw = state.get('recent_topics', [])
    values = list(raw[-RECENT_TOPIC_LIMIT:]) if isinstance(raw, list) else []
    current = _current_topic(state, now)
    if current:
        values.append(current)
    recent, seen = [], set()
    for item in reversed(values):
        topic = _validated_topic(item, now)
        if not topic:
            continue
        identity = frozenset(_topic_words(topic['subject']))
        if not identity or identity in seen:
            continue
        seen.add(identity)
        recent.append(topic)
    return list(reversed(recent[:RECENT_TOPIC_LIMIT]))


def _returning_topic(message, state, now):
    """Un retorno explícito necesita pistas que seleccionen un solo tema."""
    match = re.match(r'(?i)^\s*(?:(?:y|ahora|mejor|bueno)\s+)?'
                     r'(?:volvamos|regresemos|retomemos|vuelve|regresa|retoma)\b\s*'
                     r'(?:(?:a|al|sobre|con)\s+)?(?:(?:el|la|los|las)\s+)?'
                     r'(?:(?:tema|asunto)\s+(?:de|del|sobre)\s+)?(.+)', str(message or ''))
    if not match:
        return None, False
    requested = re.split(r'\s+(?:y\s+)?(?:recomi[eé]nda(?:me)?|quiero|necesito)\b',
                         match.group(1), maxsplit=1, flags=re.I)[0]
    requested = _without_language_preference(requested)
    requested = _safe_subject(requested)
    words = _topic_words(requested)
    if not requested or not words:
        return None, True
    def compatible(word, candidates):
        return any(word == other or (min(len(word), len(other)) >= 4
                   and (word.startswith(other) or other.startswith(word))) for other in candidates)
    matches = [topic for topic in _recent_topics(state, now)
               if all(compatible(word, _topic_words(topic['subject'])) for word in words)]
    return matches[0] if len(matches) == 1 else None, True


def resolve_topic_context(message, state, *, now=None):
    """Resuelve el tema sin modificar la sesión ni transformar fallos en fuentes.

    ``query`` sirve exclusivamente para recuperación bibliográfica. El modelo
    recibe además el mensaje original; este objeto nunca es evidencia factual.
    """
    now = time.time() if now is None else now
    message = str(message or '')
    normal = _normalized(message)
    previous = _current_topic(state, now)
    from .literary_research import is_topic_recommendation
    subject = _explicit_subject(message) if is_topic_recommendation(message) else ''
    if subject:
        subject = _safe_subject(_without_language_preference(subject))
    requested_locale = requested_language(message)
    empty = {'subject': '', 'intent': '', 'query': '', 'followup': False,
             'explicit_change': False, 'reset_work_context': False}
    # Una referencia a una ficha aceptada tiene prioridad sobre la memoria
    # genérica de materia. Reescribir «otro del mismo autor» como «libros sobre
    # arte» borraría tanto la referencia como el historial antes de resolverla.
    # La ambigüedad también pertenece al resolvedor de obras: no debe ocultarse
    # eligiendo de nuevo el tema anterior.
    from .literary_identity import resolve_followup_context
    work_reference = resolve_followup_context(message,
        state.get('turns', []) if isinstance(state, dict) else [])
    if (work_reference.get('reason') in {'same_author', 'similar', 'ordinal'}
            and (work_reference.get('books') or work_reference.get('ambiguous'))):
        return empty
    returning, requested_return = _returning_topic(message, state, now)
    if returning:
        subject = returning['subject']
        changed = bool(previous and _normalized(previous['subject']) != _normalized(subject))
        language = requested_locale or returning.get('language', '')
        return {'subject': subject, 'intent': 'recommend', 'query': _topic_query(subject, language),
                'followup': True, 'explicit_change': changed, 'reset_work_context': True,
                **_language_field(language)}
    if requested_return:
        return {**empty, 'ambiguous_topic_return': True}
    if subject:
        changed = bool(previous and _normalized(previous['subject']) != _normalized(subject))
        same_subject = bool(previous and _topic_words(previous['subject']) == _topic_words(subject))
        language = requested_locale or (previous.get('language', '') if same_subject else '')
        return {'subject': subject, 'intent': 'recommend', 'query': _topic_query(subject, language),
                'followup': False, 'explicit_change': changed, 'reset_work_context': True,
                **_language_field(language)}
    # Referencias a un título, otro ámbito explícito o recuerdos nuevos no heredan
    # el tema de una recomendación previa. La identidad bibliográfica tiene su
    # propio resolvedor y sus propias fuentes.
    if (re.search(r'''["'“”‘’«»]''', message)
            or re.search(r'\b(?:cambiemos|otro tema|cualquier genero|cualquier tema|'
                         r'sin importar el (?:genero|tema)|recuerdo|recordaba|'
                         r'libro (?:titulado|llamado)|personajes? de|trama de|'
                         r'argumento de|final de|quien escribio|quien es el autor)\b', normal)):
        return {**empty, 'explicit_change': True, 'reset_work_context': True}
    # Solo trasladar un tema cuando la continuación pide más opciones o ajusta
    # esa recomendación. «¿Y sus personajes?» sigue la obra, no el tema genérico.
    recommendation = re.search(r'\b(?:recomiend\w*|recomenda\w*|sugier\w*)\b', normal)
    if recommendation:
        # «Recomiéndame Dune» y «recomiéndame ciencia ficción» introducen un
        # objetivo distinto. Solo una petición elíptica hereda el tema anterior.
        tail = re.findall(r'[a-z0-9]+', normal[recommendation.end():])
        generic = set('a de del el la los las un una unos unas algun alguna algunos algunas '
                      'otro otra otros otras mas mismo misma mismos mismas cualquiera '
                      'cualquier libro libros obra obras lectura lecturas novela novelas '
                      'opcion opciones titulo titulos autor autores artista artistas '
                      'distinto distinta distintos distintas diferente diferentes '
                      'similar similares algo lo que sea tu quieras quierasme por favor '
                      'me para mi corto corta cortos cortas breve breves ilustrado '
                      'ilustrada ilustrados ilustradas en espanol castellano y dos tres '
                      'cuatro cinco ingles english spanish frances french aleman german '
                      'portugues portuguese japones japanese idioma'.split())
        if any(word not in generic and not word.isdigit() for word in tail):
            return {**empty, 'explicit_change': True, 'reset_work_context': True}
    continuation = bool(recommendation or re.search(
                                  r'\b(?:(?:mas|otras?|algunas?) (?:opciones|obras|libros|lecturas)|'
                                  r'otra opcion|distintos artistas|diferentes artistas|'
                                  r'que sean|prefiero|ilustrados|en espanol)\b', normal)
                        or re.fullmatch(r'[¿¡\s]*(?:y )?(?:mas|otros|otras|cualquiera)[?.!\s]*', normal)
                        or (requested_locale and re.fullmatch(
                            r'[¿¡\s]*(?:(?:y|ahora|mejor|solo)\s+)*(?:en|idioma)\s+\w+'
                            r'(?:[,\s]+por favor)?[?.!\s]*', normal)))
    if previous and continuation:
        subject = previous['subject']
        # No copiar el mensaje nuevo a la consulta: puede contener un secreto o
        # texto personal. Mantener solo el tema ya validado y ajustes acotados.
        constraints = []
        if re.search(r'\b(?:artistas|autores)\b', normal):
            constraints.append('distintos artistas o autores')
        if re.search(r'\bilustrad[oa]s?\b', normal):
            constraints.append('ilustrados')
        language = requested_locale or previous.get('language', '')
        query = _topic_query(subject, language)
        if constraints:
            query += ', ' + ', '.join(constraints)
        return {'subject': subject, 'intent': 'recommend', 'query': query,
                'followup': True, 'explicit_change': False, 'reset_work_context': True,
                **_language_field(language)}
    return empty


def remember_topic(state, message, context=None, *, now=None):
    """Actualiza únicamente la memoria de petición; devuelve si cambió el estado."""
    now = time.time() if now is None else now
    context = resolve_topic_context(message, state, now=now) if context is None else context
    before = state.get('topic')
    before_recent = state.get('recent_topics')
    recent = _recent_topics(state, now)
    previous_active_work = state.get('active_work')
    subject = _safe_subject(context.get('subject')) if isinstance(context, dict) else ''
    if subject and context.get('intent') == 'recommend':
        state['topic'] = {'subject': subject, 'intent': 'recommend', 'updated_at': int(now),
                          **_language_field(context.get('language'))}
        identity = frozenset(_topic_words(subject))
        recent = [topic for topic in recent if frozenset(_topic_words(topic['subject'])) != identity]
        recent.append(state['topic'])
        state.pop('active_work', None)
    elif (isinstance(context, dict) and context.get('explicit_change')) or not _current_topic(state, now):
        state.pop('topic', None)
    if recent:
        state['recent_topics'] = recent[-RECENT_TOPIC_LIMIT:]
    else:
        state.pop('recent_topics', None)
    return (before != state.get('topic') or previous_active_work != state.get('active_work')
            or before_recent != state.get('recent_topics'))
