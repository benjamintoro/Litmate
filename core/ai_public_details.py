"""Datos públicos de personajes para preguntas sencillas, sin inventar con un LLM."""
import re
from .literary_ai import (ChatResult, canonical_sources, clean_text, normalized,
                         has_excerpt, obvious_rejection, requires_exact_text, forbidden_output,
                         sanitized_history)
from .literary_quality import resolve_followup_books
from .books_google import public_query
from .literary_identity import same_work, resolve_followup_context


def _title_query_matches(query, book):
    """Tolera un artículo omitido al buscar, sin crear un alias de identidad."""
    return bool(_public_title_for_query(query, book))


def _public_title_for_query(query, book):
    """Usa la variante bibliográfica comprobada que coincide con la pregunta."""
    from .literary_identity import work_identity
    identity = work_identity(book)
    titles = [identity.get('title', '')] + [
        alias['title'] for alias in identity.get('confirmed_aliases', [])]
    def without_article(value):
        return re.sub(r'^(?:el|la|los|las|the)\s+', '', normalized(value)).strip()
    value = without_article(query)
    return next((title for title in titles if identity and value
                 and value == without_article(title)), '')


def character_answer(message, history, search_books, search_public):
    value = normalized(message).strip('¿?¡! ')
    request = re.sub(r'[«“\"]([^»”\"\n]{2,180})[»”\"]', '', value)
    if (has_excerpt(message) or obvious_rejection(message) or requires_exact_text(message)
            or not re.search(r'\b(?:personajes?|protagonistas?)\b', value)
            or re.search(r'\b(?:compara|analiza|interpreta|simbolismo|evolucion|spoilers?|final|muere|resume)\b', value)
            or re.search(r'\b(?:paginas?|isbn|autor|editorial|publicacion|clima|temperatura|impuestos|codigo|receta)\b', request)
            or not re.match(r'^(?:y\s+)?(?:quienes|cuales|dime|dame|describe|busca(?:me|r)?|averigua|personajes|hablame|sus personajes|los personajes)\b', value)):
        return None
    history = sanitized_history(history)
    context = resolve_followup_context(message, history)
    if context['ambiguous']:
        return None
    selected = context['books']
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
        remembered = [source for turn in reversed(history) for source in turn.get('sources', [])
                      if isinstance(source, dict) and selected and same_work(source, selected[0])]
        reusable = [source for source in remembered if source.get('character_facts')]
        found = canonical_sources(remembered if reusable else search_books(book_query))
        books = [book for book in found if book['kind'] == 'book'
                 and book['source'] in {'Google Books API', 'Catálogo LitMate', 'Open Library',
                                       'Conocimiento literario local', 'Biblioteca literaria local'}
                 and _title_query_matches(query, book) and book['author'] != 'Autor no informado'
                 and (not selected or normalized(book['author']) == normalized(selected[0]['author']))]
        if not books:
            return None
        unique_author = len({normalized(book['author']) for book in books}) == 1
        author_query = ' ' + books[0]['author'] if unique_author else ''
        local_facts = [source for source in found if source.get('kind') == 'web'
                       and source.get('character_facts') and any(same_work(source, book) for book in books)]
        # La consulta flexible solo localiza fichas: la lectura y sus hechos
        # siguen vinculados al título bibliográfico completo y a su autor.
        variants = [_public_title_for_query(query, book) for book in books]
        public_title = (variants[0] if len({normalized(title) for title in variants}) == 1 else query)
        raw_public = reusable or local_facts or search_public('"' + public_title.replace('"', ' ') + '"' + author_query + ' personajes')
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
            if (source['kind'] == 'web' and trusted_url(source['url']) and source.get('character_facts')
                    and same_work(source, book)):
                matches.append((book, source))
    if not matches or len({normalized(book['author']) for book, _ in matches}) != 1:
        return None
    book, source = matches[0]
    # La ruta rápida tampoco elige silenciosamente la primera página cuando
    # los hechos estructurados recibidos se contradicen sobre esta misma obra.
    from .literary_identity import bind_source
    from .literary_research import assess_evidence
    relevant = [bind_source(page, book) for page in public if same_work(page, book)]
    if assess_evidence(message, [book, *relevant], [book], 'analysis')['contradictory']:
        return None
    roles = {}
    for page in relevant:
        description = normalized(page.get('description', ''))
        for fact in page.get('character_facts', []):
            name, role = normalized(fact.get('name', '')), normalized(fact.get('role', ''))
            if name and role and name in description and role in description:
                roles.setdefault(name, set()).add(role)
    if any(len(values) > 1 for values in roles.values()):
        # Descripciones distintas pueden complementarse; esta ruta sin modelo
        # no elige una de ellas. El flujo normal conserva ambas para evaluarlas.
        return None
    description = normalized(source.get('description', ''))
    facts = [fact for fact in source['character_facts'] if not forbidden_output(fact['role'])
             and normalized(fact['name']) in description and normalized(fact['role']) in description][:5]
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
