"""Recuperación progresiva sin LLM para tareas bibliográficas inequívocas.

Los proveedores sólo recuperan candidatos: las rutas extractivas existentes
siguen comprobando identidad, autor y evidencia específica de la pregunta.
"""
import re
import time
from concurrent.futures import FIRST_COMPLETED, wait

from django.conf import settings
from .ai_budget import budget_timeout, pool_in_budget, request_budget, submit_with_budget
from .ai_progress import measure_stage
from .literary_ai import (canonical_sources, compound_literary_request, has_excerpt,
                          obvious_rejection, requires_exact_text)
from .literary_identity import bind_source, resolve_followup_context, same_work
from .literary_language import request_text


def persist_sources(sources):
    """Guarda pruebas del recuperador, nunca una respuesta redactada por IA."""
    from .literary_memory import remember_evidence
    # Leer del índice no constituye una verificación nueva de la fuente.
    sources = [s for s in sources if not s.get('memory_verified')]
    books = [s for s in sources if s.get('kind') == 'book']
    bound = [bind_source(s, book) for s in sources for book in books if same_work(s, book)]
    if books and bound:
        return remember_evidence(books, bound)
    return {}


def indexed_answer(message, history, *, topic_context=None):
    from .ai_quick_answers import quick_answer, quick_knowledge_sources, catalogue_lookup_answer
    from .ai_public_details import character_answer
    if compound_literary_request(message):
        return None
    result = quick_answer(message, history, topic_context=topic_context)
    if result is not None:
        return result
    reference = resolve_followup_context(message, history)
    query = message + ' ' + ' '.join(book['title'] for book in reference['books'])
    with measure_stage('knowledge_lookup'):
        known = quick_knowledge_sources(query, maximum=16)
    result = catalogue_lookup_answer(message, history, lambda query: known)
    if result is None:
        result = character_answer(message, history, lambda query: known, lambda query: known)
    return result


def _work_title(value):
    """Normaliza un título para comparar páginas, sin fusionar identidades."""
    from .literary_ai import normalized
    value = normalized(value).strip(' ¿?¡!.,:;-')
    return re.sub(r'\s*\((?:novela|novel|book|libro|obra|pelicula|film|serie|'
                  r'videojuego)[^)]*\)\s*$', '', value).strip()


def _work_web_pages(sources, title):
    """Sólo páginas cuyo título identifica la obra pedida.

    Una biografía del autor o una noticia tangencial pueden mencionar el
    título, pero no responden por la obra concreta. Tampoco se usa una
    adaptación cinematográfica, un manga o una canción como si fueran la
    novela. Un título de una sola palabra exige además una señal literaria
    explícita en el pasaje.
    """
    from .literary_ai import normalized
    wanted = _work_title(title)
    if not wanted:
        return []
    wanted_words = set(re.findall(r'\w{3,}', wanted))
    pages = []
    for source in sources:
        if source.get('kind') != 'web' or not source.get('url'):
            continue
        raw_title = normalized(source.get('title', ''))
        disambiguation = re.search(r'\(([^)]*)\)\s*$', raw_title)
        base_title = raw_title
        if disambiguation:
            label = disambiguation.group(1).strip()
            # «(manga)», «(película)» o «(canción)» son otras obras, no la
            # novela pedida. «(novela)» identifica el mismo tipo de obra y un
            # apellido («Nana (Zola)») desambigua por autoría. En este último
            # caso el vínculo todavía debe probarse con una ficha y su autor.
            if re.fullmatch(r'(?:novela|novel|book|libro|obra)', label):
                base_title = raw_title[:disambiguation.start()].strip()
            elif re.search(r'\b(?:manga|anime|pelicula|film|serie|videojuego|'
                           r'album|sencillo|cancion|musical|opera|ballet|adaptacion|'
                           r'comic|historieta|novela grafica|miniserie|telenovela|'
                           r'desambiguacion)\b', label):
                continue
            else:
                base_title = raw_title[:disambiguation.start()].strip()
        if not base_title:
            continue
        if not (base_title == wanted
                or (len(wanted_words) >= 2 and wanted in base_title)
                or base_title.startswith(wanted + ':')
                or base_title.startswith(wanted + ' -')):
            continue
        text = normalized(str(source.get('title', '')) + ' ' + str(source.get('description', '')))
        identity = normalized(str(source.get('identity_text', '')))
        # Una página de desambiguación puede titularse igual que la obra y
        # ofrecer un pasaje centrado en la novela; su introducción delata que
        # no es el artículo de la obra. No se usa como si fuera una ficha.
        if re.search(r'\b(?:puede(?:n)? referirse a|may refer to|can refer to|'
                     r'desambiguacion)\b', identity):
            continue
        page_words = set(re.findall(r'\w{3,}', text))
        if wanted_words and not (wanted_words & page_words):
            continue
        if re.search(r'\b(?:manga|anime|pelicula|film|serie de television|videojuego|'
                     r'album|sencillo|musical|opera|ballet|adaptacion|comic|historieta|'
                     r'novela grafica|miniserie|telenovela|desambiguacion)\b', text[:700]):
            continue
        if len(wanted_words) <= 1 and not re.search(
                r'\b(?:novelas?|libros?|novels?|books?|obras?|cuentos?|poemas?|ensayos?|'
                r'teatro|tragedias?|comedias?|dramas?|publicada?|escritor(?:a)?)\b',
                text[:700]):
            continue
        pages.append({**source, 'work_title_hint': base_title})
    return pages


def _bound_work_pages(sources, title):
    """Vincula las páginas a una ficha bibliográfica de la misma obra.

    Un título puede nombrar una novela, un manga o una canción. Cuando hay
    fichas con autores distintos no se elige la primera: se devuelve vacío.
    Sin ficha disponible sólo se acepta un título de varias palabras cuya
    página coincida exactamente, nunca una página de otro medio.
    """
    from .literary_ai import normalized
    from .literary_identity import same_work
    pages = _work_web_pages(sources, title)
    if not pages:
        return []
    wanted = _work_title(title)
    books = [source for source in sources
             if source.get('kind') == 'book'
             and _work_title(source.get('title')) == wanted
             and normalized(source.get('author')) not in {'', 'autor no informado'}]
    if books:
        pairs = []
        for book in books:
            for page in pages:
                # «Nana (Zola)» desambigua por autoría: para comprobar la
                # identidad se compara el título base, nunca el paréntesis.
                comparable = {**page, 'title': page.get('work_title_hint') or page.get('title')}
                if same_work(comparable, book):
                    pairs.append((book, page))
        authors = {normalized(book.get('author')) for book, _ in pairs}
        if len(authors) != 1:
            return []
        chosen = []
        for _, page in pairs:
            if page not in chosen:
                chosen.append(page)
        return chosen
    if len(wanted.split()) < 2:
        return []
    return [page for page in pages if _work_title(page.get('title')) == wanted]


def _author_mentioned(author, text):
    """Comprueba una autoría completa o, al menos, un apellido inequívoco."""
    from .literary_ai import normalized
    author = normalized(author)
    text = normalized(text)
    if not author or not text:
        return False
    if author in text:
        return True
    tokens = author.split()
    return len(tokens) >= 2 and len(tokens[-1]) >= 4 and tokens[-1] in text


def research_answer(message, history):
    """Una ronda concurrente acotada, sólo si el índice no resolvió la tarea.

    No investiga saludos, fragmentos privados, citas exactas ni recomendaciones:
    conservan sus rutas específicas. Cada proveedor respeta su limitador actual.
    Si no hay una ficha suficiente, publica únicamente pasajes atribuidos de la
    obra pedida; nunca convierte una página tangencial en una sinopsis.
    """
    from .ai_quick_answers import catalogue_lookup_answer, reference_answer
    from .ai_public_details import character_answer
    from .literary_search import search_openlibrary, search_wikipedia
    from .literary_wikidata import search_wikidata
    from .literary_research import public_research_queries
    value = request_text(message).strip('¿?¡!., ')
    if (compound_literary_request(value)
            or has_excerpt(message) or obvious_rejection(message) or requires_exact_text(message)
            or re.search(r'[;\n]|[.!?]\s+\S', message)):
        return None
    reference = resolve_followup_context(message, history)
    if reference['ambiguous']:
        return None
    author = re.fullmatch(r'quien (?:escribio|es (?:el autor|la autora))(?: de)?\s+(.+)', value)
    characters = re.search(r'\b(?:personajes?|protagonistas?|personaje principal)\b', value)
    summary = re.fullmatch(r'(?:de que trata|sinopsis de|resumen de|resume)\s+(.+)', value)
    if reference['books'] and (author or characters or summary):
        book = reference['books'][0]
        title, query = book['title'], book['title'] + ' ' + book['author']
    elif author or summary:
        title = re.sub(r'^(?:el libro|la novela|la obra)\s+', '', (author or summary).group(1))
        query = title
    elif characters:
        match = re.search(r'\b(?:personajes?|protagonistas?|personaje principal)'
                          r'(?: principales)?\s+(?:de|del|de la|de los|de las)\s+(.+)$', value)
        if not match:
            return None
        title = re.sub(r'^(?:el libro|la novela|la obra)\s+', '', match.group(1))
        query = title
    else:
        return None
    title = title.strip(' ¿?¡!.,')
    # Una pregunta general sobre una materia no se convierte en el argumento
    # de una obra sólo porque un buscador devuelva una página con ese título.
    if summary and re.match(
            r'^(?:la |el |los |las )?(?:historia|vida|filosofia|ciencia|economia|'
            r'politica|geografia|cocina|programacion|matematicas|biologia|fisica|'
            r'quimica|literatura|arte|musica)\s+(?:de|del|de la)\b', title):
        return None
    if (not title or len(title) < 2 or len(title.split()) > 14
            or re.match(r'^(?:y|e|o|pero|ademas|tambien|luego|despues|que|como|'
                        r'por que|cuando|donde|quien|cual)\b', title)):
        return None
    if not public_research_queries(query) or len(query) > 220:
        return None
    characters = bool(characters)
    from .ai_quick_answers import quick_knowledge_sources
    found = quick_knowledge_sources(query, maximum=12)
    jobs = []
    if getattr(settings, 'LITMATE_AI_USE_OPENLIBRARY', True):
        jobs.append(lambda: search_openlibrary(query, details=False))
    if getattr(settings, 'LITMATE_AI_USE_WIKIDATA', True):
        jobs.append(lambda: search_wikidata(title))
    if (characters or summary) and getattr(settings, 'LITMATE_AI_USE_WEB', True):
        # Un título de una sola palabra necesita el medio para no confundir
        # «Nana» (novela) con el manga homónimo. No se añade a títulos ya
        # distintivos ni a preguntas que ya nombran el tipo de obra.
        medium = ' novela' if len(title.split()) == 1 else ''
        suffix = medium + (' personajes' if characters else ' argumento')
        jobs.append(lambda: search_wikipedia(query + suffix))
    if not jobs:
        return None

    def fallback(known):
        if not (summary or characters):
            return None
        pages = _bound_work_pages(known, title)
        if not pages:
            return None
        result = reference_answer(message, pages, query=message,
                                  intent='summary' if summary else 'analysis')
        if result is not None:
            result.diagnostics['progressive_reference'] = True
        return result

    def web_fallback(known):
        """Segunda ruta acotada si la API de Wikipedia no devolvió la ficha.

        Se usa la misma auditoría extractiva y se exige el autor cuando las
        fichas ya lo conocen, para no publicar una obra homónima (por ejemplo,
        el manga «Nana» en vez de la novela de Zola).
        """
        if not (summary or characters):
            return None
        from .ai_quick_answers import web_reference_answer
        from .literary_ai import normalized
        books = [source for source in known if source.get('kind') == 'book'
                 and _work_title(source.get('title')) == _work_title(title)]
        authors = {normalized(source.get('author')) for source in books
                   if normalized(source.get('author')) not in {'', 'autor no informado'}}
        author = next(iter(authors)) if len(authors) == 1 else ''
        # Un título de una sola palabra sin autoría comprobada no distingue
        # «Nana» (novela) del manga homónimo. En ese caso no se publica.
        if len(title.split()) == 1 and not author:
            return None
        if re.search(r'\bprotagonistas?\b', value):
            focus = ' protagonista'
        elif characters:
            focus = ' personajes'
        else:
            focus = ' sinopsis'
        query = title + (' ' + author if author else '') + focus
        with request_budget(time.monotonic() + budget_timeout(7)):
            result = web_reference_answer(message, query=query, limit=3)
        if result is None:
            return None
        if author and not all(_author_mentioned(author, source.get('title', '') + ' '
                                                + source.get('description', ''))
                              for source in result.sources):
            return None
        result.diagnostics['progressive_reference'] = True
        result.diagnostics['progressive_web_fallback'] = True
        return result

    with measure_stage('retrieval'), request_budget(time.monotonic() + budget_timeout(6)):
        with pool_in_budget(len(jobs)) as pool:
            pending = {submit_with_budget(pool, function) for function in jobs}
            while pending:
                done, pending = wait(pending, timeout=budget_timeout(6), return_when=FIRST_COMPLETED)
                if not done:
                    break
                for future in done:
                    try:
                        found.extend(future.result())
                    except (OSError, ValueError, TimeoutError):
                        pass
                known = canonical_sources(found, 20)
                result = catalogue_lookup_answer(message, history, lambda query: known)
                if result is None and characters:
                    result = character_answer(message, history, lambda query: known, lambda query: known)
                if result is None:
                    result = fallback(known)
                if result is not None:
                    persist_sources(known)
                    result.diagnostics['persistent_research_route'] = True
                    return result
            for future in pending:
                future.cancel()
    known = canonical_sources(found, 20)
    result = fallback(known)
    if result is None:
        result = web_fallback(known)
    if result is not None:
        persist_sources(known)
        result.diagnostics['persistent_research_route'] = True
        return result
    persist_sources(known)
    return None
