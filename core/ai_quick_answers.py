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

from .literary_ai import (ChatResult, canonical_sources, has_excerpt, normalized,
                          obvious_rejection, requires_exact_text, requested_book_count,
                          sanitized_history, validate_draft, validate_recommendation_text)
from .literary_language import request_text


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
    return _validated_result(message, candidates[:1])


def catalogue_lookup_answer(message, history, search):
    """Autoría/sinopsis desde una identidad exacta, también sin Google Books.

    No elige el primer resultado de una búsqueda vaga ni usa la descripción de
    una edición como prueba de páginas, citas textuales, finales o publicación.
    """
    if (has_excerpt(message) or obvious_rejection(message) or requires_exact_text(message)
            or re.search(r'\b(?:y|ademas|tambien|final|despues|premio|ano|fecha|'
                         r'capitulo|pagina|isbn|compara|analiza|interpreta)\b|[;\n]', request_text(message))):
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
    description = source_synopsis(source)
    if description and description in source['description'] and len(description) <= 300:
        return _validated_result(message, [{**source, 'description': description}])
    return None
