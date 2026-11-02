"""Enrutamiento literal de preguntas breves sobre personajes ya documentados.

No contesta preguntas, recupera fuentes ni autoriza por una palabra suelta. Una
coincidencia permite omitir exclusivamente el clasificador: la recuperación,
generación, auditoría y validación factual posteriores siguen siendo necesarias.
"""
import re
import unicodedata

from .literary_identity import normalize_identity, same_work, work_identity


_NAME_WORD = r"[^\W\d_]+(?:[-'’][^\W\d_]+)*"
_QUESTION = re.compile(
    r"¿?(?:(?:y +)?qu[eé] +(?:sucede|pasa|pas[oó]|ocurre) +con|"
    r"qui[eé]n +es) +(?P<name>" + _NAME_WORD + r"(?: +" + _NAME_WORD
    + r"){0,5}) *\??", re.IGNORECASE)
_PRONOUNS = {'el', 'ella', 'ellos', 'ellas', 'eso', 'ese', 'esa', 'este', 'esta',
             'yo', 'tu', 'usted', 'ustedes', 'nosotros', 'nosotras'}
# Una etiqueta manipulada no convierte una orden en un nombre de personaje.
# Los falsos negativos conservan el clasificador habitual; no rechazan la tarea.
_INSTRUCTION_WORDS = {
    'ignora', 'ignorar', 'olvida', 'olvidar', 'desobedece', 'instrucciones',
    'restricciones', 'sistema', 'prompt', 'revela', 'revelar', 'muestra',
    'ejecuta', 'ejecutar', 'calcula', 'programa', 'script', 'codigo',
    'contrasena', 'password', 'secretos', 'credenciales', 'token',
}


def literal_followup_route(message, followup, history):
    """Devuelve una ruta factual cerrada o None para el circuito completo.

    Solo admite una pregunta literal sobre el nombre completo de un personaje
    presente en character_facts y en el pasaje de su fuente, para una única obra
    aceptada. No utiliza la respuesta previa del modelo como prueba ni agrega
    conocimiento narrativo. No hay acceso a red, modelos ni bases de datos.
    """
    if (not isinstance(message, str) or not 0 < len(message) <= 160
            or any(unicodedata.category(char) in {'Cc', 'Cf', 'Zl', 'Zp'}
                   for char in message)
            or not isinstance(followup, dict) or followup.get('ambiguous') is not False
            or followup.get('reason') not in {'active_work', 'remembered_entity'}
            or not isinstance(history, list)):
        return None
    match = _QUESTION.fullmatch(unicodedata.normalize('NFC', message).strip())
    if not match:
        return None
    name = normalize_identity(match.group('name'))
    if not name or name in _PRONOUNS or set(name.split()) & _INSTRUCTION_WORDS:
        return None
    books = followup.get('books')
    if not isinstance(books, list) or len(books) != 1:
        return None
    identity = work_identity(books[0])
    if not identity:
        return None
    for turn in reversed(history):
        if not isinstance(turn, dict) or turn.get('accepted') is not True:
            continue
        accepted_books = turn.get('books')
        if (not isinstance(accepted_books, list)
                or not any(same_work(book, books[0]) for book in accepted_books)):
            continue
        sources = turn.get('sources')
        if not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict) or not same_work(source, books[0]):
                continue
            facts = source.get('character_facts')
            if not isinstance(facts, list):
                continue
            if not isinstance(source.get('description'), str):
                continue
            passage = normalize_identity(source['description'])
            for fact in facts[:15]:
                if (not isinstance(fact, dict) or not isinstance(fact.get('name'), str)
                        or not isinstance(fact.get('role'), str)):
                    continue
                fact_name = normalize_identity(fact['name'])
                role = normalize_identity(fact.get('role'))
                if (fact_name == name and role and role in passage
                        and re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', passage)):
                    return {'decision': 'allow', 'intent': 'analysis', 'queries': [],
                            'candidates': [{'title': identity['title'],
                                            'author': identity['author']}],
                            'followup': True, 'clarification': ''}
    return None
