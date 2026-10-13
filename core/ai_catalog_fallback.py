"""Respuesta bibliográfica honesta cuando el modelo generativo no está disponible."""
import re
from django.conf import settings
from .books_google import public_query, rank_book_sources, source_synopsis, get_volume, volume_source, BooksUnavailable
from .literary_ai import (ChatResult, canonical_sources, has_excerpt, looks_literary,
                         obvious_rejection, requires_exact_text, sanitized_history, normalized)


def catalog_fallback(message, history, search, *, failure_reason=''):
    history = sanitized_history(history)
    if (obvious_rejection(message) or has_excerpt(message) or requires_exact_text(message)
            or not looks_literary(message, history)):
        return None
    from .literary_quality import resolve_followup_books
    selected = resolve_followup_books(message, history)
    quoted = re.findall(r'[«“\"]([^»”\"\n]{2,180})[»”\"]', message)
    if selected:
        query = selected[0]['title'] + ' ' + selected[0]['author']
    elif quoted:
        query = quoted[0]
    else:
        # Conserva "novelas" y el género: quitarlos hace que Google devuelva
        # textos escolares que sólo mencionan la ciencia ficción en un ejercicio.
        query = message
    query = public_query(query)
    if not query:
        return None
    try:
        found = search(query)
    except Exception:
        return None
    found = [s for s in found if isinstance(s, dict) and s.get('kind', 'book') == 'book'
             and 'Google Books' in str(s.get('source', ''))]
    found = rank_book_sources(found, message, distinct_works=True)
    requested = _requested_count(message)
    # En una recomendación general preferimos variedad de autores, sin crear obras.
    if not selected and not quoted:
        diverse, repeated, authors = [], [], set()
        for source in found:
            author = normalized(source.get('author'))
            if author and author not in authors:
                diverse.append(source)
                authors.add(author)
            else:
                repeated.append(source)
        found = diverse + repeated
    supporting = []
    attempted_ids = set()
    chosen = found[:requested]
    if getattr(settings, 'LITMATE_AI_USE_WEB', True) and any(not source_synopsis(source) for source in chosen):
        from .literary_search import enrich_book_sources
        attempted_ids = {source.get('book_id') for source in chosen if not source_synopsis(source)}
        enriched = enrich_book_sources(chosen, message)
        supporting = [source for source in enriched if source.get('kind') == 'web']
        chosen = rank_book_sources([source for source in enriched if source.get('kind', 'book') == 'book'],
                                  message, distinct_works=True)
    sources = canonical_sources(chosen + supporting, requested + min(3, len(supporting)))
    books_sources = [source for source in sources if source['kind'] == 'book']
    if not books_sources:
        return None
    count = {1: 'una opción', 2: 'dos opciones', 3: 'tres opciones', 4: 'cuatro opciones', 5: 'cinco opciones'}[len(books_sources)]
    basis = 'las sinopsis y fuentes públicas consultadas' if supporting else 'sus sinopsis'
    lines = [f'Encontré {count} en Google Books. Te cuento de qué trata cada una según {basis}:']
    books = []
    for index, source in enumerate(books_sources, 1):
        lines.append(f'\n{index}. **{source["title"]} — {source["author"]}**')
        synopsis = source_synopsis(source)
        researched = source.get('research_summary') and not source.get('synopsis')
        label = 'Sobre la obra, según una fuente pública: ' if researched else 'Trama: '
        if synopsis:
            summary = ' '.join(synopsis.split()[:25]) if researched else _brief_synopsis(synopsis)
            lines.append(label + summary)
        elif source.get('book_id') in attempted_ids:
            lines.append('Busqué también información sobre esta obra, pero no encontré una descripción fiable; '
                         'podemos explorar otra edición o elegir una de las otras historias.')
        else:
            lines.append('No encontré una descripción fiable de su trama; podemos explorar otra edición o elegir otra historia.')
        if researched and source.get('synopsis_source_url'):
            lines.append('Más sobre esta obra: ' + source['synopsis_source_url'])
        books.append({'title': source['title'], 'author': source['author'], 'source_id': source['id']})
    if re.search(r'\bdiferencias?|compar\w*|disting\w*\b', normalized(message)) and len(books_sources) > 1:
        lines.extend(_synopsis_differences(books_sources))
    if failure_reason in {'ollama_no_iniciado', 'ollama_no_disponible', 'modelo_no_descargado',
                          'modelo_sin_chat', 'configuracion_local_invalida', 'se_requiere_modelo_descargado_localmente'}:
        lines.append('\nNo pude conectar con el chat ahora; te dejo estas opciones del catálogo mientras tanto.')
    else:
        lines.append('\nEsta vez te comparto las sinopsis del catálogo; si quieres, podemos seguir por una de estas historias.')
    intent = 'recommend' if re.search(r'\brecomiend\w*|\bsugier\w*', normalized(message)) else 'identify'
    return ChatResult('\n'.join(lines), 'answered', True, sources, books, 'sources', intent,
                      {'catalog_fallback': True, 'google_books_results': len(books_sources)})


def _requested_count(message):
    numbers = {'un': 1, 'una': 1, 'uno': 1, 'dos': 2, 'tres': 3, 'cuatro': 4, 'cinco': 5}
    match = re.search(r'\b([1-9]|uno?|una|dos|tres|cuatro|cinco)\s+(?:novelas?|libros?|titulos?|obras?|opciones?)\b',
                      normalized(message))
    return min(5, int(match.group(1)) if match.group(1).isdigit() else numbers[match.group(1)]) if match else 3


def _brief_synopsis(synopsis, maximum=460):
    if len(synopsis) <= maximum:
        return synopsis
    shortened = synopsis[:maximum]
    sentences = re.findall(r'.*?[.!?](?=\s|$)', shortened)
    return ''.join(sentences).strip() if sentences else shortened.rsplit(' ', 1)[0] + '…'


def _synopsis_differences(sources):
    # Etiquetas descriptivas ligadas a palabras realmente presentes en la sinopsis,
    # nunca opiniones sobre estilo, calidad, finales o hechos no recuperados.
    features = (
        ('robots e inteligencia artificial', ('robot', 'inteligencia artificial', 'artificial intelligence')),
        ('viajes en el tiempo', ('viaje en el tiempo', 'viajes en el tiempo', 'time travel')),
        ('un escenario espacial', ('nave espacial', 'planeta', 'galaxia', 'galactic', 'espacial')),
        ('vigilancia y control social', ('vigilancia', 'control social', 'sociedad totalitaria', 'surveillance')),
        ('imperios y conflictos de poder', ('imperio', 'emperador', 'empire', 'conflicto politico')),
        ('encuentros con seres extraterrestres', ('extraterrestre', 'alien', 'otras civilizaciones')),
        ('supervivencia', ('supervivencia', 'survival', 'sobrevivir')),
        ('magia y seres fantásticos', ('magia', 'hechicer', 'dragon')),
        ('un misterio o una investigación', ('misterio', 'detective', 'investigacion', 'mystery')),
    )
    observed = [[label for label, terms in features if any(term in normalized(source_synopsis(source))
                 for term in terms)] for source in sources]
    unique = [[label for label in labels if sum(label in others for others in observed) == 1]
              for labels in observed]
    if not any(unique):
        return ['\nLas sinopsis necesitan más detalle para confirmar diferencias de estilo o profundidad. '
                'Puedes empezar por la trama que más te atraiga.']
    lines = ['\nQué las diferencia, según las sinopsis:']
    for source, labels in zip(sources, unique):
        if labels:
            lines.append(f'- {source["title"]}: su sinopsis menciona ' + ' y '.join(labels[:2]) + '.')
        else:
            lines.append(f'- {source["title"]}: no encontré un rasgo diferenciador suficiente en su sinopsis para compararla con precisión.')
    return lines


def bibliographic_answer(message, history, search):
    """Datos de una ficha: responde directamente sin cuatro inferencias del LLM."""
    if obvious_rejection(message) or has_excerpt(message) or requires_exact_text(message):
        return None
    value = normalized(message)
    request_words = re.sub(r'[«“\"]([^»”\"\n]{2,180})[»”\"]', '', value)
    if re.search(r'\b(?:resume|resumen|analiza|analisis|explica|argumento|trama|tema|personajes?|'
                 r'recomienda|recomiendame|compara|comparacion|por que|porque|como|ideas?)\b', request_words):
        return None
    fields = []
    checks = [('author', r'quien (?:es |fue )?(?:el )?autor|quien escribio'),
              ('page_count', r'cuantas paginas|numero de paginas'),
              ('published_date', r'(?:en que|cual) ano|cuando (?:se )?publico|fecha de publicacion'),
              ('publisher', r'(?:cual|que) (?:es la )?editorial'),
              ('isbns', r'\bisbn\b'),
              ('preview_url', r'vista previa|adelanto|donde (?:puedo )?leer')]
    for name, pattern in checks:
        if re.search(pattern, value):
            fields.append(name)
    if not fields:
        return None
    if (request_words.count('?') > len(fields) or len(re.findall(r'\by\b', request_words)) >= len(fields)
            or re.search(r'\b(?:clima|temperatura|calcula|impuestos|declaracion|receta|programa|codigo)\b', request_words)):
        return None
    history = sanitized_history(history)
    from .literary_quality import resolve_followup_books
    selected = resolve_followup_books(message, history)
    quoted = re.findall(r'[«“\"]([^»”\"\n]{2,180})[»”\"]', message)
    requested_isbn = ''
    match = re.search(r'\bISBN(?:-1[03])?\s*:?\s*([\dXx][\dXx -]{8,22}[\dXx])', message, re.I)
    if match:
        number = re.sub(r'[\s-]', '', match.group(1)).upper()
        if public_query('isbn:' + number) == 'isbn:' + number:
            requested_isbn = number
    if requested_isbn:
        query = 'isbn:' + requested_isbn
    elif selected:
        query = selected[0]['title'] + ' ' + selected[0]['author']
    elif quoted:
        query = quoted[0]
    else:
        query = re.sub(r'(?i)\b(?:quien|qui[eé]n|es|fue|el|la|los|las|autor|escribi[oó]|cu[aá]ntas|'
            r'p[aá]ginas|tiene|n[uú]mero|de|en|qu[eé]|cual|cu[aá]l|a[nñ]o|cuando|cu[aá]ndo|se|public[oó]|'
            r'fecha|publicaci[oó]n|editorial|del|libro|este|ese|esta|esa|obra|dame|su|vista|previa|ISBN|puedo|leer|donde|d[oó]nde)\b',
            ' ', message).strip(' ¿?¡!.,:')
        if not query and history and history[-1]['books']:
            previous = history[-1]['books']
            if len(previous) > 1:
                return ChatResult('¿Cuál de los libros quieres consultar? Indica el título o su posición en la lista.',
                                  'clarification', diagnostics={'bibliographic_fast_path': True})
            query = previous[0]['title'] + ' ' + previous[0]['author']
    query = public_query(query)
    if not query:
        return None
    try:
        sources = canonical_sources(search(query), 4)
    except Exception:
        return None
    sources = [s for s in sources if s['kind'] == 'book' and 'Google Books' in s['source']]
    if not sources:
        return None
    if requested_isbn:
        sources = [s for s in sources if requested_isbn in [re.sub(r'[\s-]', '', value).upper()
                   for value in s.get('isbns', [])]]
        if not sources:
            return None
    identities = {(normalized(s['title']), normalized(s['author'])) for s in sources}
    if len(identities) > 1:
        text = 'Encontré varias obras. Indica el título y autor o ISBN de la edición que quieres consultar:\n'
        text += '\n'.join(f'{i}. {s["title"]} — {s["author"]}' for i, s in enumerate(sources[:3], 1))
        return ChatResult(text, 'clarification', True, sources,
            [{'title': s['title'], 'author': s['author'], 'source_id': s['id']} for s in sources[:3]],
            'sources', 'identify', {'bibliographic_fast_path': True})
    source = sources[0]
    if any(not _field_value(source, field) for field in fields):
        # Antes de declarar un dato ausente revisa el detalle de ESA edición.
        # Nunca mezcla páginas, año o ISBN de otra edición de igual título.
        identifier = source.get('book_id')
        if identifier and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identifier):
            try:
                raw = get_volume(identifier, use_cache=True)
                detail = canonical_sources([volume_source(raw)], 1)[0]
                if (raw.get('id') == identifier and normalized(detail['title']) == normalized(source['title'])
                        and (source['author'] == 'Autor no informado'
                             or normalized(detail['author']) == normalized(source['author']))):
                    source = {**detail, 'id': source['id']}
            except (BooksUnavailable, IndexError, TypeError, ValueError):
                pass
        if any(not _field_value(source, field) for field in fields):
            # El motor puede consultar las fuentes públicas disponibles y explicar
            # qué dato concreto no se pudo confirmar después de buscarlo.
            return None
    lines = []
    for field in fields:
        content = _field_value(source, field)
        if field == 'author':
            lines.append(f'El libro **{source["title"]}** lo escribió **{content}**.' if content else
                         f'La ficha de **{source["title"]}** no identifica al autor.')
        elif field == 'page_count':
            lines.append(f'Esta edición tiene **{content} páginas**.' if content is not None else
                         'La ficha no informa cuántas páginas tiene esta edición.')
        elif field == 'published_date':
            lines.append(f'La fecha de publicación que figura para esta edición es **{content}**.' if content else
                         'La ficha no indica la fecha de publicación de esta edición.')
        elif field == 'publisher':
            lines.append(f'La editorial es **{content}**.' if content else 'La ficha no informa la editorial.')
        elif field == 'isbns':
            lines.append(f'Su ISBN es **{content}**.' if content else 'La ficha no informa un ISBN válido para esta edición.')
        elif field == 'preview_url':
            lines.append('Puedes abrir la vista previa desde la tarjeta del libro.' if content else
                         'La ficha no ofrece un enlace de vista previa.')
    if 'author' not in fields:
        lines.insert(0, f'Sobre **{source["title"]}**, de **{source["author"]}**:')
    return ChatResult('\n'.join(lines), 'answered', True, [source],
        [{'title': source['title'], 'author': source['author'], 'source_id': source['id']}],
        'sources', 'author', {'bibliographic_fast_path': True, 'google_books_results': 1})


def _field_value(source, field):
    content = source.get(field)
    if field == 'author' and content == 'Autor no informado':
        return None
    if field == 'isbns':
        return ', '.join(number for number in (content or [])
            if public_query(number) == 'isbn:' + re.sub(r'[\s-]', '', number).upper())
    return content
