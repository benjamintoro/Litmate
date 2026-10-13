"""Datos públicos de personajes para preguntas sencillas, sin inventar con un LLM."""
import re
from .literary_ai import (ChatResult, canonical_sources, clean_text, normalized,
                         has_excerpt, obvious_rejection, requires_exact_text, forbidden_output,
                         sanitized_history)
from .literary_quality import resolve_followup_books
from .books_google import public_query


def character_answer(message, history, search_books, search_public):
    value = normalized(message).strip('¿?¡! ')
    request = re.sub(r'[«“\"]([^»”\"\n]{2,180})[»”\"]', '', value)
    if (has_excerpt(message) or obvious_rejection(message) or requires_exact_text(message)
            or not re.search(r'\b(?:personajes?|protagonistas?)\b', value)
            or re.search(r'\b(?:compara|analiza|interpreta|simbolismo|evolucion|spoilers?|final|muere|resume)\b', value)
            or re.search(r'\b(?:paginas?|isbn|autor|editorial|publicacion|clima|temperatura|impuestos|codigo|receta)\b', request)
            or not re.match(r'^(?:quienes|cuales|dime|dame|describe|personajes|hablame)', value)):
        return None
    history = sanitized_history(history)
    selected = resolve_followup_books(message, history)
    quoted = re.findall(r'[«“\"]([^»”\"\n]{2,180})[»”\"]', message)
    if selected:
        query = selected[0]['title']
    elif quoted:
        query = quoted[0]
    else:
        match = re.search(r'(?i)\b(?:personajes?|protagonistas?)(?: principales?)?\s+(?:de|del)\s+(.+)', message)
        if not match:
            return None
        query = re.split(r'(?i)\s+y\s+(?:que|qué|cual|cuál|como|cómo)\b', match.group(1))[0].strip('¿?¡!. ')
    query = public_query(query)
    if not query:
        return None
    try:
        book_query = query + (' ' + selected[0]['author'] if selected else '')
        found = canonical_sources(search_books(book_query))
        books = [book for book in found if book['kind'] == 'book'
                 and book['source'] in {'Google Books API', 'Catálogo LitMate', 'Open Library'}
                 and normalized(book['title']) == normalized(query) and book['author'] != 'Autor no informado'
                 and (not selected or normalized(book['author']) == normalized(selected[0]['author']))]
        if not books:
            return None
        unique_author = len({normalized(book['author']) for book in books}) == 1
        author_query = ' ' + books[0]['author'] if unique_author else ''
        raw_public = search_public('"' + query.replace('"', ' ') + '"' + author_query + ' personajes')
        # No fusiona dos registros de una misma página antes de detectar una
        # identidad contradictoria: debe poder volver al diálogo normal.
        public = [source for item in (raw_public if isinstance(raw_public, list) else [])[:8]
                  for source in canonical_sources([item])]
    except Exception:
        return None
    from .literary_search import trusted_url
    matches = []
    for book in books:
        for source in public:
            identity = normalized(source.get('identity_text', ''))
            adaptation = re.search(r'\b(?:pelicula|serie de television|adaptacion|film|movie)\b', identity)
            novel = re.search(r'\b(?:novela|libro|novel|book)\b', identity)
            if (source['kind'] == 'web' and trusted_url(source['url']) and source.get('character_facts')
                    and normalized(source['title']) in {normalized(book['title']), normalized(book['title']) + ' (novela)',
                                                        'anexo:personajes de ' + normalized(book['title'])}
                    and normalized(book['author']) in identity
                    and not (adaptation and (not novel or adaptation.start() < novel.start()))):
                matches.append((book, source))
    if not matches or len({normalized(book['author']) for book, _ in matches}) != 1:
        return None
    book, source = matches[0]
    facts = [fact for fact in source['character_facts'] if not forbidden_output(fact['role'])][:5]
    if len(facts) < 2:
        return None
    sources = canonical_sources([book, source])
    lines = [f'En **{book["title"]}**, de **{book["author"]}**, estos personajes ayudan a entender la historia:']
    for index, fact in enumerate(facts, 1):
        lines.append(f'\n{index}. **{fact["name"]}**: {fact["role"].rstrip(".")}.')
    lines.append('\nSi quieres, podemos comentar cómo se relacionan o cuál te llama más la atención.')
    lines.append('\nMás sobre los personajes: ' + source['url'])
    return ChatResult('\n'.join(lines), 'answered', True, sources,
                      [{'title': book['title'], 'author': book['author'], 'source_id': sources[0]['id']}],
                      'sources', 'analysis', {'public_details_fast_path': True, 'character_count': len(facts)})
