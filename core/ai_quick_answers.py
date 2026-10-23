"""Respuestas breves por extracción de fichas, sin inventar con otro modelo.

Las fichas originales incluidas permiten arrancar sin Internet ni preparar una
base. No se escriben en datos de usuario. Fuera de este alcance acotado continúa
el pipeline existente con sus verificaciones y el mismo presupuesto temporal.
"""
import json
import re
import hashlib
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from .literary_ai import (ChatResult, canonical_sources, has_excerpt, normalized,
                          obvious_rejection, requires_exact_text, requested_book_count,
                          sanitized_history, validate_draft, validate_recommendation_text)
from .literary_language import request_text


# La envoltura de una referencia parcial no forma parte de las frases
# auditadas. El caché la retira antes de volver a validar el mismo contenido.
REFERENCE_PREFIX = 'Encontré estas referencias relacionadas con tu consulta:\n\n'
REFERENCE_SUFFIX = ('\n\nSon pasajes atribuidos a sus fuentes, no fichas bibliográficas ni una verificación '
                    'independiente de todos sus datos. No puedo confirmar con ellos todas las partes de tu consulta.')


@lru_cache(maxsize=1)
def _bundled():
    from .literary_identity import stable_work_id
    from .literary_knowledge import seed_works
    data = json.loads((Path(__file__).parent / 'data' / 'verified_readings.json').read_text(encoding='utf-8'))
    result = []
    for work in [*seed_works(), *data['works']]:
        result.append({**work, 'kind': 'book', 'source': 'Conocimiento literario local',
            'work_id': stable_work_id(work['title'], work['author']),
            'synopsis': work['description'], 'read_mode': 'ficha factual original; no texto de la obra',
            'license': work.get('license', data['license']),
            'provenance': 'litmate_verified_readings_v1'})
    return result


def quick_knowledge_sources(query, maximum=8):
    """Recupera fichas de arranque con el mismo ranking léxico de la biblioteca.

    Superposición de solo lectura: no importa fichas automáticamente a SQLite
    ni sustituye una ficha propia con una versión incluida en el programa.
    """
    from .literary_knowledge import search_knowledge, _score, knowledge_sources
    from .literary_identity import same_work
    local = search_knowledge(query, maximum=maximum)
    # El índice persistente devuelve evidencia pública vigente, nunca textos
    # generados ni respuestas de otro lector. La suficiencia se verifica después.
    from .literary_memory import retrieve_evidence
    from .ai_progress import measure_stage
    try:
        with measure_stage('knowledge_lookup'):
            books, sources = retrieve_evidence(query, limit=maximum)
            # No fusionar una redacción original con la URL de otra ficha.
            # Los metadatos mínimos no desplazan una sinopsis ya revisada.
            protected = [s for s in local if s.get('kind') == 'book'] + list(_bundled())
            extra = [s for s in sources if not (s.get('kind') == 'book'
                and any(same_work(s, old) for old in protected))]
            local.extend(extra)
    except (OSError, ValueError):
        pass
    ranked = []
    for work in _bundled():
        if any(source.get('kind') == 'book' and same_work(source, work) for source in local):
            continue
        facts = work.get('facts') or [{'topic': 'identification', 'source_url': work['url'],
            'text': work['description'], 'character_facts': work.get('character_facts', [])}]
        facts = [{**fact, 'fact_id': hashlib.sha256((work['work_id'] + fact['text']).encode()).hexdigest()[:32]}
                 for fact in facts]
        score = _score(query, work, facts)
        if score > 0:
            ranked.append((score, work, facts))
    ranked.sort(key=lambda item: -item[0])
    for _, work, facts in ranked[:3]:
        local.extend(knowledge_sources(work, facts))
    return canonical_sources(local, maximum)


def _character_detail(message, targets, sources):
    """Reutiliza solo un papel literal de un personaje de la obra activa."""
    from .literary_identity import same_work
    from .literary_quality import required_fact_statements, validate_audit
    from .literary_evidence import validate_evidence
    value = request_text(message).strip('¿?¡!., ')
    if len(targets) != 1 or not re.match(r'^(?:y )?(?:quien (?:es|era)|'
            r'que (?:sucede|pasa|ocurre) con|hablame de)\b', value):
        return None
    books = [source for source in sources if source['kind'] == 'book' and same_work(source, targets[0])]
    if not books:
        return None
    matches = []
    for source in sources:
        if source['kind'] != 'web' or source.get('injection_detected') or not same_work(source, books[0]):
            continue
        for fact in source.get('character_facts', []):
            name, role = fact['name'], fact['role']
            if (re.search(r'(?<!\w)' + re.escape(normalized(name)) + r'(?!\w)', value)
                    and normalized(name) in normalized(source['description'])
                    and role in source['description']):
                matches.append((source, name, role))
    if len({(normalized(name), normalized(role)) for _, name, role in matches}) != 1:
        return None
    page, name, role = matches[0]
    selected = canonical_sources([books[0], page])
    book, page = selected
    text = f'**{name}**, en **{book["title"]}**, de **{book["author"]}**: {role}'
    draft = {'status': 'answer', 'basis': 'sources', 'text': text,
        'citations': [book['id'], page['id']], 'needs_web': False,
        'books': [{'title': book['title'], 'author': book['author'], 'source_id': book['id']}]}
    plan = {'questions': [message], 'search_queries': [], 'needs_contents': False,
            'needs_fresh_sources': False, 'spoilers_requested': False}
    audit = {'decision': 'approve', 'only_books': True,
        'coverage': [{'question_id': 1, 'status': 'answered'}],
        'claims': [{'statement': statement, 'verdict': 'supported', 'source_id': page['id'], 'evidence': role}
                   for statement in required_fact_statements(text)], 'search_queries': [], 'issues': []}
    try:
        validate_draft(draft, selected)
        validate_evidence(draft, selected, message)
        validate_audit(audit, plan, draft, selected, message, strict_facts=True)
    except (ValueError, TypeError):
        return None
    return ChatResult(text + '\n\nFuente de la ficha: ' + page['url'], 'answered', True, selected,
                      draft['books'], 'sources', 'analysis', {'verified_character_followup': True, 'audit': audit})


def _validated_result(message, chosen, *, recommendation=False):
    """Audita cada frase copiada; los enlaces nunca se presentan como lectura nueva."""
    from .literary_quality import required_fact_statements, validate_audit
    from .literary_evidence import validate_evidence
    sources = canonical_sources(chosen, 5)
    lines = ['¡Claro!'] if recommendation else []
    books, claims = [], []
    for index, source in enumerate(sources, 1):
        title = f'**{source["title"]} — {source["author"]}**:'
        text = source['description']
        if not text or len(text) > 600:
            return None
        lines.append((f'{index}. ' if recommendation else '') + title + ' ' + text)
        books.append({'title': source['title'], 'author': source['author'], 'source_id': source['id']})
        for statement in required_fact_statements(title + ' ' + text):
            proof = text
            if not proof or len(proof) > 300:
                return None
            claims.append({'statement': statement, 'verdict': 'supported',
                           'source_id': source['id'], 'evidence': proof})
    draft = {'status': 'answer', 'basis': 'sources', 'text': '\n\n'.join(lines),
             'citations': [source['id'] for source in sources], 'books': books, 'needs_web': False}
    plan = {'questions': [message], 'search_queries': [], 'needs_contents': False,
            'needs_fresh_sources': False, 'spoilers_requested': False}
    audit = {'decision': 'approve', 'only_books': True,
             'coverage': [{'question_id': 1, 'status': 'answered'}],
             'claims': claims, 'search_queries': [], 'issues': []}
    try:
        validate_draft(draft, sources)
        validate_recommendation_text(draft, sources)
        validate_evidence(draft, sources, message)
        validate_audit(audit, plan, draft, sources, message, strict_facts=True)
    except (ValueError, TypeError):
        return None
    text = draft['text'] + '\n\nFuentes de las fichas:\n' + '\n'.join(source['url'] for source in sources)
    return ChatResult(text, 'answered', True, sources, books, 'sources',
                      'recommend' if recommendation else 'summary',
                      {'verified_quick_answer': True, 'claim_checks': len(claims), 'audit': audit})


def _simple_topic_request(message, query):
    """No perder filtros/subtemas desconocidos por reconocer solo una palabra."""
    from .books_google import book_topic_profile
    from .literary_research import is_topic_recommendation, evidence_requirements
    if not is_topic_recommendation(query) or evidence_requirements(message, 'recommend') != ['recommendation']:
        return False
    value = request_text(message).strip('¿?¡!., ')
    if re.search(r'[;\n]|[.!?]\s+\S', value) or re.search(
            r'\b(?:no|sin|excepto|publicad\w*|recientes?|novedades?|actuales?|'
            r'breves?|cortos?|largos?|infantil\w*|juvenil\w*|principiantes?|'
            r'paginas?|siglo|autor|autora|similares?|parecidos?|personajes?|'
            r'compara\w*|explica\w*|resume\w*|analiza\w*)\b', value):
        return False
    profile = book_topic_profile(query)
    if not profile['structured']:
        return False
    # Elimina únicamente materias reconocidas y palabras de petición. Un
    # subtema no cubierto («submarinos», «frente oriental») conserva el flujo normal.
    residue = request_text(query)
    for row in (*profile['subjects'], *profile['places']):
        residue = re.sub(row[1], ' ', residue)
    residue = re.sub(r'\b(?:en|idioma) (?:espanol|castellano|ingles|frances|aleman|portugues|japones)\b', ' ', residue)
    allowed = set('hola por favor recomiendame recomienda recomiendas recomendas recomendarme '
                  'recomendar recomendarias recomendases sugiereme sugieres sugeris que puedo podria '
                  'puedes podrias me aconsejas aconsejarias quiero quisiera gustaria interesa '
                  'leer lectura lecturas libros libro novelas novela obras obra titulos titulo '
                  'opciones opcion ensayos ensayo algo algun alguna algunos algunas necesito '
                  'busco buscando estoy dame dime aprender entender sobre acerca de del el la los '
                  'las en y para a un una uno dos tres cuatro cinco mas otros otras otro otra '
                  'distintos diferentes autores son sean seanme tambien también ademas además'.split())
    return all(word in allowed or word in {'1', '2', '3', '4', '5'}
               for word in re.findall(r'\w+', residue))


def quick_answer(message, history=None, *, topic_context=None, search=None):
    """Primero fichas locales; opcionalmente catálogos para una materia conocida."""
    if (not isinstance(message, str) or has_excerpt(message) or obvious_rejection(message)
            or requires_exact_text(message)):
        return None
    history = sanitized_history(history or [])
    from .literary_ai import contradiction_correction
    correction = contradiction_correction(message, history)
    if correction is not None:
        return correction
    topic_context = topic_context or {}
    query = topic_context.get('query') or message
    value = request_text(message).strip('¿?¡!., ')
    bundled = _bundled()
    if _simple_topic_request(message, query):
        from .books_google import rank_book_sources
        from .literary_constraints import recommendation_constraints, constraints_match
        from .literary_identity import same_work
        from .literary_ai import recommendation_sources
        constraints = recommendation_constraints(query)
        constraints.update({key: val for key, val in recommendation_constraints(message).items() if val})
        requested = requested_book_count(message)
        if requested is None and re.search(r'\b(?:otro|otra|algun|alguna)\s+(?:libro|obra|lectura|novela|opcion)\b', value):
            requested = 1
        limit = requested or 3
        different_authors = bool(re.search(r'\b(?:distintos?|diferentes?) autores?\b', value))
        previous = ([book for turn in history for book in turn['books']]
                    if re.search(r'\b(?:otros?|otras?|mas)\b', value) else [])
        sources = rank_book_sources(bundled, query, distinct_works=True)
        sources = [source for source in sources if constraints_match(source, constraints)]
        sources = recommendation_sources(canonical_sources(sources), limit,
                                         different_authors=different_authors, excluded=previous)
        if sources and (not requested or len(sources) >= requested):
            result = _validated_result(message, sources[:limit], recommendation=True)
            if result is not None:
                return result
        if search is not None:
            from .ai_catalog_fallback import grounded_topic_fallback
            from .ai_budget import BudgetExpired
            try:
                # La consulta conserva cantidad y filtros explícitos originales.
                found = search(query)
                filtered = rank_book_sources([source for source in found if constraints_match(source, constraints)],
                                             query, distinct_works=True)
                filtered = recommendation_sources(canonical_sources(filtered), limit,
                                                  different_authors=different_authors, excluded=previous)
                from .ai_catalog_fallback import _topic_catalogue_origin
                from .books_google import source_synopsis
                # Descripción literal de fichas, sin pasar por answer/audit del
                # modelo cuando la tarea solo pide opciones de lectura.
                descriptive = [{**source, 'description': source_synopsis(source)} for source in filtered
                    if _topic_catalogue_origin(source) and source_synopsis(source)
                    and source_synopsis(source) in source.get('description', '')
                    and len(source_synopsis(source)) <= 300]
                if descriptive and (not requested or len(descriptive) >= requested):
                    result = _validated_result(message, descriptive[:limit], recommendation=True)
                    if result is not None:
                        return result
                if requested:
                    query += f', {requested} libros'
                return grounded_topic_fallback(query, filtered)
            except (BudgetExpired, TimeoutError, OSError, ValueError):
                return None
        return None
    # Solo una sinopsis o autoría simple; no responder a «el final» con la ficha.
    clauses = re.sub(r'^y\s+', '', value)
    if re.search(r'[.!?]\s+\S|[;\n]', clauses) or re.search(
            r'\b(?:y|e|ademas|tambien)\s+(?:(?:sus?|los?|las?|el|de)\s+)?'
            r'(?:dime|explica|resume|que|quien|quienes|como|cual|cuales|quiero|'
            r'personajes?|argumento|trama|relaciones?|enfoques?|diferencias?)\b', clauses):
        return None
    if re.search(r'\b(?:final|despues|spoiler\w*|premios?|ano|fecha|capitulo|pagina|'
                 r'compara\w*|analiza\w*|simbol\w*|interpreta\w*)\b', value):
        return None
    from .literary_identity import resolve_followup_context, same_work
    from .literary_research import resolve_verified_request
    context_query = message + ' ' + ' '.join(book['title'] for book in
        resolve_followup_context(message, history)['books'])
    local = quick_knowledge_sources(context_query, maximum=12)
    local_books = [source for source in local if source['kind'] == 'book']
    extra = [source for source in bundled if not any(same_work(source, book) for book in local_books)]
    # canonical_sources elige la descripción más larga al fusionar fichas.
    # Aquí una ficha propia tiene prioridad aunque sea más breve: no mezclar
    # una redacción incluida en el programa con su URL/procedencia diferente.
    known = canonical_sources([*local, *extra], 32)
    verified = resolve_verified_request(message, known)
    reference = resolve_followup_context(message, history)
    targets = verified['books'] or (reference['books'] if not reference['ambiguous'] else [])
    detail = _character_detail(message, targets, known)
    if detail is not None:
        return detail
    summary = re.search(r'\b(?:cuentame|hablame|resume|resumen|sinopsis|de que trata|'
                        r'que trata|mas del|mas sobre)\b', value)
    author = re.match(r'^(?:quien escribio|quien es (?:el autor|la autora))\b', value)
    if len(targets) != 1 or not (summary or author or verified['intent'] == 'summary'):
        return None
    candidates = [source for source in known if source['kind'] == 'book' and same_work(source, targets[0])]
    if not candidates:
        return None
    if author:
        source = candidates[0]
        result = ChatResult(f'**{source["title"]}** es una obra de **{source["author"]}**.', 'answered', True, [source],
                            [{'title': source['title'], 'author': source['author'], 'source_id': source['id']}],
                            'sources', 'author', {'verified_quick_answer': True})
        validate_draft({'status': 'answer', 'basis': 'sources', 'text': result.text,
                        'citations': [source['id']], 'books': result.books, 'needs_web': False}, [source])
        result.text += '\n\nFuente de la ficha: ' + source['url']
        return result
    narrative = [source for source in candidates if source.get('policy') != 'openlibrary-minimal-metadata-v1'
                 and 'metadatos bibliogr' not in source.get('read_mode', '').lower()
                 and source.get('source') != 'Wikidata']
    return _validated_result(message, narrative[:1]) if narrative else None


def catalogue_lookup_answer(message, history, search):
    """Autoría/sinopsis desde una identidad exacta, también sin Google Books.

    No elige el primer resultado de una búsqueda vaga ni usa la descripción de
    una edición como prueba de páginas, citas textuales, finales o publicación.
    """
    if (has_excerpt(message) or obvious_rejection(message) or requires_exact_text(message)
            or re.search(r'\b(?:ademas|tambien|despues|premio|ano|fecha|'
                         r'capitulo|pagina|isbn|compara|analiza|interpreta)\b|[;\n]', request_text(message))):
        return None
    if re.search(r'\by\s+(?:(?:su|sus|el|la|los|las)\s+)?(?:dime|describe|explica|'
                 r'cuentame|resume|recomienda\w*|que|quien|como|cuando|cual|'
                 r'personajes|argumento|trama|final)\b', request_text(message)):
        return None
    value = request_text(message).strip('¿?¡!., ')
    author = re.fullmatch(r'(?:quien (?:escribio|es (?:el autor|la autora)))(?: de)?\s+(.+)', value)
    summary = re.fullmatch(r'(?:de que trata|hablame de|cuentame (?:sobre|de)|'
                           r'resume|resumen de|sinopsis de)\s+(.+)', value)
    from .literary_identity import resolve_followup_context, title_matches
    reference = resolve_followup_context(message, sanitized_history(history))
    if reference['ambiguous']:
        return None
    if reference['books']:
        book = reference['books'][0]
        title, query = book['title'], book['title'] + ' ' + book['author']
    elif author or summary:
        title = re.sub(r'^(?:el libro|la novela|la obra)\s+', '', (author or summary).group(1)).strip('«»“”" ')
        query = title
    else:
        return None
    if not (author or summary) or len(query) > 220:
        return None
    found = canonical_sources(search(query))
    from .ai_catalog_fallback import _topic_catalogue_origin
    candidates = [source for source in found if _topic_catalogue_origin(source) and title_matches(title, source)
                  and (not reference['books'] or normalized(source['author']) == normalized(book['author']))]
    # Open Library puede devolver ediciones con traductores o ilustradores en
    # el campo de autoría. Para una pregunta de autoría, Wikidata aporta una
    # identidad estructurada y evita que esas ediciones conviertan una obra
    # conocida en ambigua. Si Wikidata también discrepa, no se elige por mayoría.
    if author:
        structured = [source for source in candidates
                      if 'Wikidata' in str(source.get('source', '')).split(' / ')]
        if structured and len({normalized(source['author']) for source in structured}) == 1:
            candidates = structured
    if len({normalized(source['author']) for source in candidates}) != 1:
        return None
    source = canonical_sources(candidates[:1])[0]
    if author:
        draft = {'status': 'answer', 'basis': 'sources',
                 'text': f'**{source["title"]}** es una obra de **{source["author"]}**.',
                 'citations': [source['id']], 'needs_web': False,
                 'books': [{'title': source['title'], 'author': source['author'], 'source_id': source['id']}]}
        validate_draft(draft, [source])
        return ChatResult(draft['text'] + '\n\nFuente: ' + source['url'], 'answered', True,
                          [source], draft['books'], 'sources', 'author', {'catalogue_quick_lookup': True})
    from .books_google import source_synopsis
    if (source.get('policy') == 'openlibrary-minimal-metadata-v1'
            or 'metadatos bibliogr' in source.get('read_mode', '').lower()
            or source.get('source') == 'Wikidata'):
        return None
    description = source_synopsis(source)
    if description and description in source['description'] and len(description) <= 300:
        return _validated_result(message, [{**source, 'description': description}])
    return None

def isbn_lookup_answer(message, *, search=None):
    """Identifica un ISBN sólo si el registro recibido contiene ese número."""
    if (not isinstance(message, str) or has_excerpt(message) or obvious_rejection(message)
            or requires_exact_text(message) or re.search(r'[;\n]|[.!?]\s+\S', message)
            or re.search(r'\b(?:y|e|ademas|tambien|compara\w*|analiza\w*|resume\w*|'
                         r'sinopsis|trata|paginas|publicad\w*|precio|cuesta)\b', request_text(message))):
        return None
    from .literary_research import public_research_queries
    if not public_research_queries(message):
        return None
    match = re.search(r'\bISBN(?:-1[03])?\s*:?\s*([\dXx][\dXx -]{8,22}[\dXx])', message, re.I)
    if not match:
        return None
    from .literary_identity import _isbn_values
    numbers = _isbn_values({'isbns': [match.group(1)]})
    if not numbers:
        return None
    query = 'isbn:' + numbers[0]
    if search is None:
        from .literary_search import retrieve_discovery_books
        search = retrieve_discovery_books
    from .ai_catalog_fallback import _topic_catalogue_origin
    number = query[5:]
    found = canonical_sources(search(query))
    matches = [source for source in found if _topic_catalogue_origin(source)
               and number in source.get('isbns', [])
               and ('ISBN registrado: ' + number + '.') in source['description']]
    if len({(normalized(source['title']), normalized(source['author'])) for source in matches}) != 1:
        return None
    source = matches[0]
    result = _validated_result(message, [{**source, 'description': 'ISBN registrado: ' + number + '.'}])
    if result is not None:
        result.intent = 'identify'
        result.diagnostics['isbn_lookup_quick_answer'] = True
    return result


def verified_book_list_answer(message, sources, *, history=None, topic_context=None, limit=3):
    """Lista las fichas ya verificadas cuando no hay una sinopsis publicable.

    No añade argumentos ni sinopsis inventadas: sólo título, autor y la ficha
    real recuperada. Evita que una lista de libros válida dependa del modelo
    lento o de una segunda búsqueda web.
    """
    if (not isinstance(message, str) or has_excerpt(message)
            or obvious_rejection(message) or requires_exact_text(message)):
        return None
    query = (topic_context or {}).get('query') or message
    if not _simple_topic_request(message, query):
        return None
    from .ai_catalog_fallback import _topic_catalogue_origin
    from .books_google import topic_matches
    from .literary_constraints import constraints_match, recommendation_constraints
    from .literary_ai import recommendation_sources
    constraints = recommendation_constraints(query)
    constraints.update({key: value for key, value in recommendation_constraints(message).items() if value})
    books = [source for source in canonical_sources(sources, 32)
             if _topic_catalogue_origin(source) and topic_matches(source, query)
             and constraints_match(source, constraints)]
    requested = requested_book_count(message)
    previous = ([book for turn in sanitized_history(history or []) for book in turn['books']]
                if re.search(r'\b(?:otros?|otras?|mas)\b', request_text(message)) else [])
    chosen = recommendation_sources(books, min(5, requested or limit),
        different_authors=bool(re.search(r'\b(?:distintos?|diferentes?) autores?\b', request_text(message))),
        excluded=previous)
    chosen = canonical_sources(chosen, 5)
    if not chosen:
        return None
    from .literary_quality import required_fact_statements, validate_audit
    from .literary_evidence import validate_evidence
    lines, claims = [], []
    for index, source in enumerate(chosen, 1):
        identity = f'**{source["title"]}** — {source["author"]}'
        proof = next((source[field] for field in ('title', 'author', 'description')
                      if 8 <= len(source.get(field, '')) <= 300), '')
        if not proof:
            return None
        lines.append(f'{index}. {identity}')
        claims.extend({'statement': statement, 'verdict': 'supported',
                       'source_id': source['id'], 'evidence': proof}
                      for statement in required_fact_statements(identity) or [identity])
    cards = [{'title': source['title'], 'author': source['author'],
              'source_id': source['id']} for source in chosen]
    draft = {'status': 'answer', 'text': '\n\n'.join(lines), 'basis': 'sources',
             'citations': [source['id'] for source in chosen], 'books': cards, 'needs_web': False}
    plan = {'questions': [message], 'search_queries': [], 'needs_contents': False,
            'needs_fresh_sources': False, 'spoilers_requested': False}
    audit = {'decision': 'approve', 'only_books': True, 'claims': claims,
             'coverage': [{'question_id': 1, 'status': 'uncertain' if requested and len(chosen) < requested else 'answered'}],
             'search_queries': [], 'issues': []}
    try:
        validate_draft(draft, chosen)
        validate_recommendation_text(draft, chosen)
        validate_evidence(draft, chosen, message)
        validate_audit(audit, plan, draft, chosen, message, strict_facts=True)
    except (ValueError, TypeError):
        return None
    text = 'Estas son las obras cuyas fichas pude verificar:\n\n' + draft['text']
    if requested and len(chosen) < requested:
        text += f'\n\nPude confirmar {len(chosen)} de las {requested} opciones solicitadas.'
    text += '\n\nNo dispongo de una sinopsis verificada para todas; no añado detalles sobre su contenido.'
    text += '\n\nFuentes de las fichas:\n' + '\n'.join(source['url'] for source in chosen if source['url'])
    return ChatResult(text, 'answered', True, sources=chosen,
                      books=cards, basis='sources', intent='recommend',
                      diagnostics={'verified_book_list_quick_answer': True, 'audit': audit})


def _is_adaptation_page(source):
    """Detecta una página sobre la película, serie o musical, no sobre la obra."""
    host = (urlsplit(str(source.get('url', ''))).hostname or '').lower()
    if any(host == domain or host.endswith('.' + domain) for domain in (
            'primevideo.com', 'netflix.com', 'filmaffinity.com', 'imdb.com',
            'disneyplus.com', 'max.com', 'hulu.com', 'rtve.es', 'ecartelera.com',
            'sensacine.com', 'letterboxd.com', 'rottentomatoes.com', 'tomatazos.com')):
        return True
    title = normalized(source.get('title', ''))
    if re.search(r'\b(?:filmaffinity|imdb|sensacine|ecartelera|letterboxd|'
                 r'rottentomatoes|tomatazos|prime video|netflix)\b', title):
        return True
    if re.search(r'\((?:pelicula|film|serie|miniserie|telenovela|musical|'
                 r'opera|ballet|adaptacion|videojuego|album|sencillo|cancion|'
                 r'band|banda|grupo musical|music group|song)\b', title):
        return True
    introduction = normalized(source.get('identity_text') or source.get('description', ''))[:700]
    if re.search(r'\b(?:es|son|fue|is|are|was)\s+(?:un|una|an?|the)\s+'
                 r'(?:\w+\s+){0,5}(?:band|banda|grupo musical|music group)\b', introduction):
        return True
    return bool(re.search(r'\b(?:pelicula|film|serie de television|miniserie|'
                          r'telenovela|musical|adaptacion cinematografica|videojuego)\b', title))


def _literal_snippet(text, terms):
    """Elige una oración literal relevante sin parafrasear ni mezclar pasajes."""
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    if not text:
        return ''
    best = None
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        words = set(re.findall(r'\w{3,}', normalized(sentence)))
        matched = words & terms
        # Preferir la oración que responde al término específico («protagonista»)
        # antes que una mención genérica del título («Nana»).
        score = (len(matched), sum(len(word) for word in matched))
        if matched and (best is None or score > best[0]):
            best = (score, sentence)
    snippet = best[1] if best else text
    words = list(re.finditer(r'\S+', snippet))[:25]
    snippet = snippet[:words[-1].end()] if words else ''
    if len(snippet) > 230:
        snippet = snippet[:230].rsplit(' ', 1)[0]
    return snippet


def _explicit_reference_target(message):
    """Ancla el respaldo a un título literal; no es un clasificador ni un hecho.

    Sólo reconoce preguntas bibliográficas/de personajes con un sujeto escrito
    por el lector. No convierte pronombres, recuerdos o materias en títulos.
    La intención puede conservar varias tareas y seguir en el pipeline completo.
    """
    value = request_text(message).lstrip(' ¿¡')
    first = re.split(r'[?!]|\.\s', value, maxsplit=1)[0].strip(' .')
    match = re.match(r'^(?:quien escribio|(?:en que ano|cuando) se publico)\s+(.+)$', first)
    if match is None:
        match = re.match(r'^(?:y\s+)?(?:quien(?:es)?|cual(?:es)?|dime|dame)\b.*?'
                         r'\b(?:personajes?|protagonistas?|personaje principal)'
                         r'(?: principales)?\s+(?:de|del)\s+(.+)$', first)
    if match is None:
        return ''
    title = re.sub(r'^(?:el|la)\s+(?:libro|novela|obra)\s+', '', match.group(1))
    title = title.strip(' «»“”"\'')
    if (not 2 <= len(title) <= 180 or re.search(r'\b(?:ese|esa|este|esta|su|sus|'
            r'anterior|primero|segundo|tercero|mismo|ultima|ultimo)\b', title)
            or re.search(r'\b(?:y|pero|ademas)\s+(?:dime|explica|quien|que)\b', title)):
        return ''
    return title


def reference_answer(message, sources, *, query=None, intent='recommend', limit=4):
    """Publica pasajes atribuidos y enlaces reales; no los convierte en fichas.

    La auditoría comprueba la copia literal, no certifica la veracidad de una
    página ajena. El alcance parcial se declara y nunca reemplaza citas exactas.
    """
    if has_excerpt(message) or obvious_rejection(message) or requires_exact_text(message):
        return None
    from .literary_ai import LiteraryAssistant, forbidden_output
    from .literary_search import STOPWORDS
    from .literary_web import public_text_has_injection
    terms = set(re.findall(r'\w{3,}', normalized(query or message))) - STOPWORDS - {
        'recomiendame', 'recomiendas', 'puedes', 'podrias', 'cuentame', 'hablame',
        'analiza', 'analisis', 'resume', 'resumen', 'sinopsis', 'trata', 'autor',
        'autora', 'autores', 'escribio', 'obra', 'obras', 'ensayo', 'isbn',
        'cual', 'como', 'informacion', 'lectura', 'lecturas', 'personajes', 'principales'}
    adaptations = bool(re.search(r'\b(?:pelicula|film|adaptacion|cine|serie)\b', normalized(query or message)))
    pages = [source for source in canonical_sources(sources, 16)
             if source['kind'] == 'web' and source['url']
             and not source.get('injection_detected')
             and not public_text_has_injection(source['title'] + ' ' + source['description'])
             and not forbidden_output(source['title'] + ' ' + source['description'])
             and (adaptations or not _is_adaptation_page(source))
             and (not terms or terms & set(re.findall(r'\w{3,}', normalized(
                 source['title'] + ' ' + source['description'] + ' ' + source['url']))))]
    if not pages:
        return None
    target = _explicit_reference_target(message)
    if target:
        # Una coincidencia genérica («año», «novela») no autoriza una página
        # sobre otro escritor. El título debe figurar en el texto de la fuente,
        # no solamente en una URL o en los términos de la consulta del buscador.
        literal = r'(?<!\w)' + re.escape(target) + r'(?!\w)'
        pages = [source for source in pages if re.search(literal, normalized(
            source['title'] + ' ' + source.get('identity_text', '') + ' ' + source['description']))]
        if not pages:
            return None
    pair = re.search(r'\brelacion entre\s+(.+?)\s+y\s+(.+)$',
                     request_text(message).strip(' ¿?¡!.,'))
    if pair and all(2 <= len(name.split()) <= 6 for name in pair.groups()):
        # Un artículo general sobre el tema no responde a la relación entre
        # dos entidades nombradas. No se infiere la relación por compartir tema.
        literals = [r'(?<!\w)' + re.escape(name) + r'(?!\w)' for name in pair.groups()]
        pages = [source for source in pages if all(re.search(literal, normalized(
            source['title'] + ' ' + source['description'])) for literal in literals)]
        if not pages:
            return None
    if re.match(r'^(?:de que trata|cuentame|hablame|resumen|sinopsis)\b', request_text(message).strip(' ¿?¡!.,')):
        from .literary_research import bibliographic_title_hints
        hints = [normalized(title) for title in bibliographic_title_hints(query or message)]
        if hints:
            # Una biografía del autor no responde al argumento de su novela.
            # Si sólo hay una página general, al menos el pasaje que se muestra
            # debe mencionar la obra; no citar un párrafo de otro asunto.
            work_pages = [source for source in pages if any(title in normalized(source['title']) for title in hints)]
            pages = work_pages or [source for source in pages if any(
                title in normalized(source['description'][:230]) for title in hints)]
            if not pages:
                return None
    sources = canonical_sources(pages, limit)
    from .literary_quality import required_fact_statements, validate_audit
    from .literary_evidence import validate_evidence
    lines, claims = [], []
    for source in sources:
        title = '**' + source['title'] + '** [' + str(source['id']) + ']'
        proof = source['title']
        if len(proof) < 8:
            continue
        lines.append(title)
        claims.extend({'statement': statement, 'verdict': 'supported',
                       'source_id': source['id'], 'evidence': proof}
                      for statement in required_fact_statements(title) or [title])
        # Cita corta, literal y atribuida. No presentar el fragmento del
        # buscador como lectura de la página ni como texto de la novela.
        # En preguntas de detalle se elige una oración que contenga el término
        # pedido; en sinopsis se conserva el comienzo del pasaje.
        if intent == 'analysis' and terms:
            # El título aparece en casi todas las oraciones y no distingue la
            # respuesta. Se prioriza el término específico de la pregunta.
            title_words = set(re.findall(r'\w{3,}', normalized(source.get('title', ''))))
            snippet = _literal_snippet(source['description'], terms - title_words or terms)
        else:
            snippet = re.sub(r'\s+', ' ', source['description']).strip()
            words = list(re.finditer(r'\S+', snippet))[:25]
            snippet = snippet[:words[-1].end()] if words else ''
            if len(snippet) > 230:
                snippet = snippet[:230].rsplit(' ', 1)[0]
        if len(snippet) >= 8:
            mode = 'Fragmento del buscador' if source['read_mode'] == 'fragmento del buscador' else 'Pasaje recuperado'
            line = mode + ': «' + snippet + '»'
            lines.append(line)
            claims.extend({'statement': statement, 'verdict': 'supported',
                           'source_id': source['id'], 'evidence': snippet}
                          for statement in required_fact_statements(line) or [line])
    if not claims:
        return None
    draft = {'status': 'answer', 'text': '\n\n'.join(lines), 'basis': 'sources',
             'citations': sorted({claim['source_id'] for claim in claims}), 'books': [], 'needs_web': False}
    plan = {'questions': [message], 'search_queries': [], 'needs_contents': False,
            'needs_fresh_sources': False, 'spoilers_requested': False}
    audit = {'decision': 'approve', 'only_books': True, 'claims': claims,
             'coverage': [{'question_id': 1, 'status': 'uncertain'}], 'search_queries': [], 'issues': []}
    try:
        validate_draft(draft, sources)
        validate_evidence(draft, sources, message)
        validate_audit(audit, plan, draft, sources, message, strict_facts=True)
    except (ValueError, TypeError):
        return None
    draft['text'] = (REFERENCE_PREFIX + draft['text'] + REFERENCE_SUFFIX)
    return LiteraryAssistant._publish(draft, sources, intent,
        {'web_reference_quick_answer': True, 'partial_answer': True, 'reference_audit': audit})


def web_reference_answer(message, *, query=None, search=None, limit=4):
    """Investiga con los mismos límites y filtros de privacidad que el modelo."""
    from django.conf import settings
    from .literary_research import public_research_queries
    if not getattr(settings, 'LITMATE_AI_USE_WEB', True):
        return None
    queries = public_research_queries(query or message)
    if not queries or has_excerpt(message) or obvious_rejection(message) or requires_exact_text(message):
        return None
    if search is None:
        from .literary_search import retrieve_web
        search = retrieve_web
    try:
        found = search(queries[0])
    except (TimeoutError, OSError, ValueError):
        return None
    return reference_answer(message, found, query=queries[0], limit=limit)
