"""Normalización de peticiones, no de títulos ni de evidencia del lector.

Solo corrige formas frecuentes de las órdenes. El mensaje original siempre se
conserva para la generación, la auditoría y la memoria; no se corrigen pasajes.
"""
import re
import unicodedata


def request_text(message):
    value = ''.join(char for char in unicodedata.normalize('NFKD', str(message or ''))
                    if not unicodedata.combining(char)).casefold()
    # No reinterpretar palabras dentro de un título o texto proporcionado.
    if re.search(r'[«»“”"\n]', value):
        return value
    value = re.sub(r'^\s*[¡¿]*(?:hola|holaa|buenas|buenos dias|buenas tardes|buenas noches|oye|hey)'
                   r'\b[\s,!.:;]*(?:litmate[\s,!.:;]*)?', '', value)
    value = re.sub(r'\b(?:recomendame|recomiendame|recomiendeme|recomiendanos|'
                   r'recomiendemen|recomiendaman|recomiedame|recominedame)\b', 'recomiendame', value)
    value = re.sub(r'\b(?:porfa|porfis|porfavor)\b', 'por favor', value)
    return re.sub(r'\s+', ' ', value).strip()


def response_language(message):
    """Idioma de la respuesta, distinto del idioma de la edición solicitada."""
    value = request_text(re.sub(r'«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', str(message or '')))
    names = {'es': 'espanol|castellano|spanish', 'en': 'ingles|english',
             'fr': 'frances|french', 'pt': 'portugues|portuguese',
             'de': 'aleman|german', 'it': 'italiano|italian'}
    for code, variants in names.items():
        if re.fullmatch(r'(?:en|in)\s+(?:' + variants + r')(?:,? por favor| please)?[.!?]*', value):
            return code
        if re.search(r'\b(?:responde(?:me)?|contesta(?:me)?|explica(?:melo|me)?|'
                     r'escribe|habla(?:me)?|answer|reply|respond|write)\s+'
                     r'(?:(?:por favor|please)\s+)?(?:en|in)\s+(?:' + variants + r')\b', value):
            return code
    return 'es'


def narrative_language(text):
    """Detección conservadora sin dependencias; no usa el idioma de la edición.

    No considera URLs, títulos en negrita ni citas literales como prosa a
    traducir. Un idioma desconocido nunca se certifica como español.
    """
    value = re.sub(r'https?://\S+|\*\*[^*]+\*\*|«[^»]*»|“[^”]*”|"[^"\n]*"', ' ', str(text))
    value = request_text(value)
    words = re.findall(r'[^\W\d_]+', value)
    vocab = {
        'es': 'el la los las de del al un una unos unas es son que para por sobre historia obra sus su se trata cuenta joven con entre quien este esta autor personajes te tu tus mi mis como puedo podemos conversar quieres gustaria dia mas libro libros novela narra escrito escrita relata sigue presenta describe aborda explora estudia mundo tambien aunque pero porque cuando donde sin hasta desde fueron fue habia yo me nos lo le les',
        'en': 'the a an of and in is are this that with from for to his her their its tells story history introduction early novel follows young book explores medieval',
        'fr': 'le les du des une est sont dans avec pour ses son histoire roman raconte',
        'pt': 'os uma são não dos das pelo pela história livro conta seus',
        'de': 'der die das ein eine und ist sind mit von für geschichte buch',
        'it': 'il gli della delle uno sono nella con storia libro racconta',
    }
    markers = {code: set(request_text(terms).split()) for code, terms in vocab.items()}
    scores = {code: sum(word in terms for word in words) for code, terms in markers.items()}
    best = max(scores, key=scores.get)
    if scores[best] >= 2:
        return best
    if re.search(r'[\u3040-\u30ff\u3400-\u9fff\u0400-\u04ff]', value):
        return 'unknown'
    # Sin señales suficientes no reinterpretar nombres ni frases españolas
    # breves como prosa extranjera (y no abrir inferencias innecesarias).
    return ''
