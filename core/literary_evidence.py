"""Comprobaciones observables de citas; no prueban la verdad de todo el análisis."""
import re
import unicodedata
from .ai_privacy import user_excerpt


def _text(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value or '')).strip()


def _user_excerpt(message):
    return _text(user_excerpt(message))


def _attributed_recollection(quote, answer, message):
    """Citar lo que recuerda el lector no certifica las palabras de una novela.

    Exige tanto la coincidencia con su mensaje como una atribución inmediata;
    una afirmación posterior de literalidad o presencia en el libro la invalida.
    """
    if not quote or _text(quote).casefold() not in _text(message).casefold():
        return False
    position = answer.find(quote)
    if position < 0:
        return False
    before = re.split(r'[.!?\n]', answer[:position])[-1][-140:]
    after = re.split(r'[.!?\n]', answer[position + len(quote):])[0]
    if re.search(r'(?i)\b(?:cita|literal|textual|original|exacta)\b', before):
        return False
    attributed = re.search(r'(?i)\b(?:tu recuerdo(?: de(?: que)?)?|lo que recuerdas|'
                           r'(?:la )?(?:idea|frase) que recuerdas|seg[uú]n recuerdas)'
                           r'\s*[,;:\x27«“"]?\s*$', before)
    certified = re.search(r'(?i)\b(?:aparece|figura|se lee|dice|escribe|original|'
                          r'literal|textual|mandamiento)\b', after)
    return bool(attributed and not certified)


def exact_context_available(message, sources):
    """Una página del PDF no se presenta como la página de una edición impresa."""
    value = unicodedata.normalize('NFD', message.lower())
    value = ''.join(c for c in value if unicodedata.category(c) != 'Mn')
    if re.search(r'\bcapitulo\s+(?:numero\s+)?(?:\d+|[ivxlcdm]+)\b', value):
        return False  # Unos pocos fragmentos no representan un capítulo completo.
    if re.search(r'\b(?:copiame|transcribe|reproduce)\b', value):
        return False
    excerpts = [s for s in sources if s.get('kind') == 'excerpt']
    page = re.search(r'\bpagina\s+(?:numero\s+)?(\d+)\b', value)
    if page:
        return any(re.search(r'^página\s+' + re.escape(page.group(1)) + r'\s+del PDF$',
                             s.get('locator', ''), re.I) for s in excerpts)
    return bool(excerpts)


def validate_evidence(draft, sources, message):
    if draft.get('status') != 'answer':
        return
    lookup = {s['id']: s for s in sources}
    cited = [lookup[i] for i in draft['citations'] if i in lookup]
    user_excerpt = _user_excerpt(message)
    if draft['basis'] == 'excerpt' and not user_excerpt and not any(
            s.get('kind') == 'excerpt' for s in cited):
        raise ValueError('Para basis=excerpt cita el fragmento local que realmente utilizaste.')
    exact_quote = bool(re.search(r'\bcita(?:s)?\s+(?:textual(?:es)?|exacta(?:s)?)\b|\btextualmente\b',
                                message, re.I))
    quotes = [next(part for part in group if part) for group in re.findall(
        r'«([^»\n]+)»|“([^”\n]+)”|"([^"\n]+)"|‘([^’\n]+)’|(?:^|(?<=[\s(]))\x27([^\x27\n]+)\x27(?=$|[\s.,;:!?])', draft['text'])]
    # Títulos y términos breves entre comillas no son necesariamente citas.
    # Una frase de tres palabras sí exige evidencia, aunque no se pidiera citar.
    book_titles = {_text(s.get('title', '')).casefold() for s in sources if s.get('kind') == 'book'}
    book_titles.update(_text(book.get('title', '')).casefold() for book in draft.get('books', [])
                       if isinstance(book, dict))
    relevant = [q for q in quotes if exact_quote or (len(q.split()) >= 3 and _text(q).casefold() not in book_titles)]
    if exact_quote and not relevant:
        raise ValueError('La cita solicitada debe aparecer entre comillas y provenir de un texto recibido; si falta, acláralo.')
    web_words = {}
    for quote in relevant:
        if not exact_quote and _attributed_recollection(quote, draft['text'], message):
            continue
        quote = _text(quote)
        if quote and user_excerpt and quote.casefold() in user_excerpt.casefold():
            continue
        matches = [s for s in cited if quote and quote in _text(s.get('description', ''))]
        if not matches:
            raise ValueError('Una cita textual no coincide con ningún fragmento recibido: quítala o solicita el texto.')
        source = next((s for s in matches if s.get('kind') == 'excerpt'), matches[0])
        if re.search(r'\bresumen\s+(?:factual\s+)?original\b', str(source.get('read_mode', '')).lower()):
            # Una redacción propia para identificar una obra no prueba la
            # literalidad de la frase en una traducción de la novela.
            if not re.search(r'(?i)par[aá]frasis|parafrase|no .{0,30}cita textual|'
                             r'sin .{0,30}(?:edici[oó]n|traducci[oó]n|literalidad).{0,20}confirm', draft['text']):
                raise ValueError('La fuente es un resumen original, no una cita de la novela. Presenta la frase como recuerdo o paráfrasis, sin certificar su literalidad.')
        if source.get('kind') == 'web':
            web_words[source['id']] = web_words.get(source['id'], 0) + len(quote.split())
            if web_words[source['id']] > 25:
                raise ValueError('Reduce las citas web a un máximo de 25 palabras por fuente.')
    available_pages = {int(m.group(1)) for s in cited for m in [re.match(
        r'página\s+(\d+)\s+del PDF', s.get('locator', ''), re.I)] if m}
    for page in re.findall(r'\bp[aá]gina\s+(\d+)\b', draft['text'], re.I):
        if int(page) not in available_pages and not user_excerpt:
            raise ValueError('No atribuyas una página concreta que no aparece en los fragmentos citados.')
    # Un ISBN identifica una edición: no se reconstruye de memoria. No se
    # confunde con años o números de capítulo porque exige la etiqueta ISBN.
    evidence_text = ' '.join(s.get('description', '') + ' ' + ' '.join(s.get('isbns', []))
                             for s in cited) + ' ' + user_excerpt
    for isbn in re.findall(r'\bISBN(?:-1[03])?\s*:?\s*([\dXx][\dXx\s-]{8,24}[\dXx])', draft['text'], re.I):
        number = re.sub(r'[\s-]', '', isbn).upper()
        available = re.sub(r'[\s-]', '', evidence_text).upper()
        valid = (len(number) == 13 and number.isdigit()
                 and sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(number)) % 10 == 0)
        if len(number) == 10 and number[:9].isdigit() and (number[-1].isdigit() or number[-1] == 'X'):
            valid = sum((10 if c == 'X' else int(c)) * (10 - i)
                        for i, c in enumerate(number)) % 11 == 0
        if not valid or number not in available:
            raise ValueError('El ISBN de la edición debe aparecer en una fuente recibida; si falta, omítelo.')
