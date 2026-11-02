"""Propuesta de identidad desde fichas originales locales, sin modelo ni red."""
import re

from .literary_ai import (ChatResult, canonical_sources, has_excerpt, obvious_rejection,
                          requires_exact_text, simple_research_plan, validate_draft)
from .literary_evidence import validate_evidence
from .literary_identity import normalize_identity, same_work
from .literary_knowledge import ORIGINAL_LICENSE, search_knowledge
from .literary_quality import required_fact_statements, validate_audit, validate_plan
from .literary_research import (VAGUE, _matches, _words, assess_evidence,
                               is_plot_description, is_topic_recommendation,
                               public_research_queries, rank_candidates)


def identification_explanation_answer(message, history):
    """Reutiliza las pistas y descripciones recibidas; no afirma unicidad universal."""
    from .literary_ai import sanitized_history
    from .ai_quick_answers import _validated_result
    from .literary_quality import factual_statements
    from .literary_research import _clues
    value = normalize_identity(message)
    if not re.fullmatch(r'que pistas (?:te hicieron pensar en ese libro|coinciden|usaste|'
                        r'permiten identificarlo)', value):
        return None
    turns = sanitized_history(list(history or []))
    turn = next((turn for turn in reversed(turns) if turn.get('intent') == 'identify' and turn['books']), None)
    if not turn or len(turn['books']) != 1:
        return None
    clues = _clues(turn['question'])
    for source in turn['sources']:
        if source['kind'] != 'book' or not same_work(source, turn['books'][0]):
            continue
        for sentence in factual_statements(source['description'], strip_markers=False):
            if (8 <= len(sentence) <= 300 and sentence in source['description'] and
                    sum(_matches(clue, set(_words(sentence))) for clue in clues) >= 2):
                result = _validated_result(message, [{**source, 'description': sentence}])
                if result is not None:
                    result.text = '**Coincidencias con tu recuerdo**\n\n' + result.text
                    result.intent = 'identify'
                    result.diagnostics.update(identification_explanation=True, model_calls=0)
                    return result
    return None


def identification_answer(message, *, search=None):
    """Propone solo una identidad o devuelve None para el recorrido normal.

    Solo lee el SQLite auxiliar mediante search_knowledge. No accede al
    catálogo Django, Internet, embeddings ni proveedores conversacionales.
    """
    if (not isinstance(message, str) or not 0 < len(message) <= 200
            or has_excerpt(message) or obvious_rejection(message)
            or requires_exact_text(message) or is_topic_recommendation(message)):
        return None
    plan = simple_research_plan(message, 'identify')
    if plan is None:
        # «Recuerdo un burro llamado ...; ¿cuál es?» es una sola petición,
        # aunque use punto y coma o sitúe la pregunta después de la escena.
        value = normalize_identity(message)
        if not re.search(r'\b(?:libro|novela|obra|cuento)\b', value) or not re.search(
                r'\b(?:recuerdo|recordaba|que libro es|cual es|cual era|como se llama)\b', value):
            return None
        plan = {'questions': [message], 'search_queries': [], 'needs_contents': False,
                'needs_fresh_sources': False, 'spoilers_requested': False}
    value = normalize_identity(message)
    # Esta ruta sin clasificador no autoriza tareas adicionales ni usa
    # confidencias personales como pistas de una obra pública.
    if (not public_research_queries(message)
            or re.search(r'\b(?:calcula|resuelve|programa|depura|ejecuta|revela|ignora|'
                         r'codigo|script|receta|asesorame|diagnostica|prescribe|'
                         r'analiza|resume|resumeme|resumen|explica|explicame|describe|'
                         r'compara|recomienda|recomiendame|cuentame|transcribe|traduce|'
                         r'cita textual|cita exacta|pagina exacta|capitulo exacto)\b', value)
            or re.search(r'\b(?:y|ademas|tambien)\s+(?:(?:sus|los|las|el|la)\s+)?'
                         r'(?:personajes?|final|argumento|trama|autor|resumen|temas?)\b', value)):
        return None
    try:
        raw = (search or search_knowledge)(message, maximum=8)
        licensed = [source for source in raw if isinstance(source, dict)
                    and source.get('source') == 'Conocimiento literario local'
                    and source.get('license') == ORIGINAL_LICENSE]
        sources = canonical_sources(licensed)
        if not sources or any(not source.get('url') for source in sources):
            return None
        candidates = rank_candidates(message, sources)
        assessment = assess_evidence(message, sources, intent='identify')
        if (len(candidates) != 1 or candidates[0]['confidence'] != 'supported'
                or not assessment.get('sufficient') or assessment.get('contradictory')):
            return None
        candidate = candidates[0]
        books = [source for source in sources if source['kind'] == 'book'
                 and source.get('work_id') == candidate['work_id']]
        if len(books) != 1:
            return None
        book = books[0]
        related = [source for source in sources if same_work(source, book)]
        documented_names = {word for source in related for fact in source.get('character_facts', [])
                            for word in _words(fact['name'])}
        ignored = (VAGUE | (set(_words(book['title'] + ' ' + book['author'])) - documented_names)
                   | {'todos', 'todas', 'todo', 'toda', 'menciona', 'mencionaba'})
        meaningful = {clue for clue in candidate['matched_clues'] if clue not in ignored}
        # Las pistas deben constar en descripciones con procedencia; título,
        # autor y palabras clave invisibles no bastan para esta ruta rápida.
        documented = {clue for clue in meaningful if any(
            _matches(clue, set(_words(source.get('description', '')))) for source in related)}
        if len(documented) < 2 or not candidate.get('evidence'):
            return None
        sources = canonical_sources(related)
        book = next(source for source in sources if source['kind'] == 'book')
        statement = (f'Por tus pistas, podrías estar buscando **{book["title"]}**, '
                     f'de **{book["author"]}**.')
        text = statement + ' ¿Te suena?'
        draft = {'status': 'answer', 'basis': 'sources', 'text': text,
                 'citations': [book['id']], 'needs_web': False,
                 'books': [{'title': book['title'], 'author': book['author'], 'source_id': book['id']}]}
        # La prueba de identidad se copia de la ficha, nunca se fabrica una
        # explicación de la trama ni se trata la puntuación como certeza.
        proof = next((book[field] for field in ('title', 'author', 'description')
                      if 8 <= len(book.get(field, '').strip()) <= 300), '')
        if not proof or required_fact_statements(text) != [statement]:
            return None
        plan = validate_plan(plan)
        audit = {'decision': 'approve', 'only_books': True,
                 'coverage': [{'question_id': 1, 'status': 'answered'}],
                 'claims': [{'statement': statement, 'verdict': 'supported',
                             'source_id': book['id'], 'evidence': proof}],
                 'search_queries': [], 'issues': []}
        validate_draft(draft, sources)
        validate_evidence(draft, sources, message)
        validate_audit(audit, plan, draft, sources, message, strict_facts=True)
    except (OSError, ValueError, TypeError, KeyError, StopIteration):
        return None
    return ChatResult(text, 'answered', True, sources, draft['books'], 'sources', 'identify',
                      {'local_identification_fast_path': True, 'candidate_confidence': 'supported',
                       'matched_clues': sorted(documented), 'claim_checks': len(audit['claims'])})


def _recall_plan(message):
    """Plan mínimo para una respuesta local que no pasó por el clasificador."""
    plan = simple_research_plan(message, 'identify')
    if plan is None:
        plan = {'questions': [message], 'search_queries': [], 'needs_contents': False,
                'needs_fresh_sources': False, 'spoilers_requested': False}
    return validate_plan(plan)


def _recall_book(sources, candidate):
    for source in sources:
        if source.get('kind') == 'book' and same_work(source, candidate):
            return source
    return None


def _recall_proof(book):
    for field in ('description', 'title', 'author'):
        value = str(book.get(field) or '').strip()
        if 8 <= len(value) <= 300:
            return value
    return ''


def _recall_documented(candidate, related, *, include_title=False):
    documented = set()
    for source in related:
        words = set(_words(source.get('description', '')))
        if include_title:
            words |= set(_words(source.get('title', '')))
        documented.update(clue for clue in candidate.get('matched_clues', [])
                          if clue not in VAGUE and _matches(clue, words))
    return documented


def _recall_result(*, message, query, related, text, statements, candidates,
                   confidence, diagnostics, used_context):
    """Valida y construye una respuesta local con una o varias fichas reales."""
    sources = canonical_sources(related)
    books = []
    for candidate in candidates:
        book = _recall_book(sources, candidate)
        if book is None or book['id'] in {item['id'] for item in books}:
            return None
        books.append(book)
    if not books or len(statements) != len(books):
        return None
    # Las frases auditadas deben ser exactamente las que se publican.
    if required_fact_statements(text) != statements:
        return None
    claims = []
    for statement, book in zip(statements, books):
        proof = _recall_proof(book)
        if not proof:
            return None
        claims.append({'statement': statement, 'verdict': 'supported',
                       'source_id': book['id'], 'evidence': proof})
    draft = {'status': 'answer', 'basis': 'sources', 'text': text,
             'citations': [book['id'] for book in books], 'needs_web': False,
             'books': [{'title': book['title'], 'author': book['author'],
                        'source_id': book['id']} for book in books]}
    plan = _recall_plan(query)
    audit = {'decision': 'approve', 'only_books': True,
             'coverage': [{'question_id': 1, 'status': 'answered'}],
             'claims': claims, 'search_queries': [], 'issues': []}
    try:
        validate_draft(draft, sources)
        validate_evidence(draft, sources, message)
        validate_audit(audit, plan, draft, sources, message, strict_facts=True)
    except (OSError, ValueError, TypeError, KeyError, StopIteration):
        return None
    details = {'local_identification_fast_path': True,
               'candidate_confidence': confidence,
               'used_conversation_context': bool(used_context),
               'claim_checks': len(claims), **diagnostics}
    return ChatResult(text, 'answered', True, sources, draft['books'], 'sources',
                      'identify', details)


def _recall_supported(message, query, sources, candidates, used_context):
    supported = [item for item in candidates if item.get('confidence') == 'supported']
    if len(supported) != 1:
        return None
    candidate = supported[0]
    book = _recall_book(sources, candidate)
    if book is None:
        return None
    related = [source for source in sources if same_work(source, book)]
    documented = _recall_documented(candidate, related)
    if len(documented) < 2 or not candidate.get('evidence'):
        return None
    statement = (f'Por tus pistas, podrías estar buscando **{book["title"]}**, '
                 f'de **{book["author"]}**.')
    text = statement + ' ¿Te suena?'
    return _recall_result(message=message, query=query, related=related, text=text,
                          statements=[statement], candidates=[candidate],
                          confidence='supported',
                          diagnostics={'matched_clues': sorted(documented)},
                          used_context=used_context)


def _recall_ambiguous(message, query, sources, candidates, used_context):
    supported = [item for item in candidates if item.get('confidence') == 'supported'][:2]
    if len(supported) != 2:
        return None
    books = [_recall_book(sources, candidate) for candidate in supported]
    if any(book is None for book in books):
        return None
    related = [source for source in sources
               if any(same_work(source, book) for book in books)]
    statements = [
        f'Una posibilidad es **{books[0]["title"]}**, de **{books[0]["author"]}**.',
        f'Otra posibilidad es **{books[1]["title"]}**, de **{books[1]["author"]}**.',
    ]
    text = ' '.join(statements) + ' ¿Cuál de las dos recuerdas?'
    documented = sorted({clue for candidate in supported
                         for clue in _recall_documented(candidate, related)})
    return _recall_result(message=message, query=query, related=related, text=text,
                          statements=statements, candidates=supported,
                          confidence='ambiguous',
                          diagnostics={'matched_clues': documented,
                                       'hypothesis_count': 2},
                          used_context=used_context)


def _recall_hypothesis(message, query, sources, candidates, used_context):
    possible = [item for item in candidates if item.get('confidence') == 'possible']
    if not possible:
        return None
    candidate = possible[0]
    book = _recall_book(sources, candidate)
    if book is None:
        return None
    related = [source for source in sources if same_work(source, book)]
    documented = _recall_documented(candidate, related, include_title=True)
    if not documented:
        return None
    statement = (f'Mi mejor hipótesis es **{book["title"]}**, de **{book["author"]}**; '
                 'las pistas no bastan para confirmarlo.')
    text = statement + ' ¿Te suena?'
    return _recall_result(message=message, query=query, related=related, text=text,
                          statements=[statement], candidates=[candidate],
                          confidence='possible',
                          diagnostics={'matched_clues': sorted(documented),
                                       'hypothesis': True},
                          used_context=used_context)


def _recall_suggestion(message, query, sources, used_context):
    """Ofrece una obra real del catálogo cuando no hay pistas suficientes.

    La sugerencia no se presenta como identificación: no afirma que sea la obra
    recordada y sirve como punto de partida para seguir conversando.
    """
    source = next((item for item in sources
                   if item.get('kind') == 'book' and item.get('candidate_origin') == 'catalog'
                   and item.get('title') and item.get('author') and item.get('description')), None)
    if source is None:
        return None
    statement = (f'No puedo confirmar una obra concreta; como sugerencia, una obra real '
                 f'relacionada es **{source["title"]}**, de **{source["author"]}**.')
    text = statement + ' ¿Quieres que busque más pistas?'
    return _recall_result(message=message, query=query, related=[source], text=text,
                          statements=[statement],
                          candidates=[{'title': source['title'],
                                       'author': source['author']}],
                          confidence='suggestion',
                          diagnostics={'alternative_suggestion': True,
                                       'matched_clues': []},
                          used_context=used_context)


def identification_recall_answer(message, *, history=None, search=None):
    """Intenta identificar o, si no basta, ofrecer una hipótesis real.

    Conserva la ruta rápida histórica para recuerdos explícitos y añade las
    descripciones narrativas y las continuaciones de conversación. Nunca
    publica una obra que no provenga de una ficha local, del catálogo o de una
    fuente incluida.
    """
    if (not isinstance(message, str) or not 0 < len(message) <= 500
            or has_excerpt(message) or obvious_rejection(message)
            or requires_exact_text(message) or is_topic_recommendation(message)):
        return None
    value = normalize_identity(message)
    if re.search(r'\b(?:recomiend\w*|sugier\w*|aconsej\w*|resume|resumen|sinopsis|'
                 r'argumento|personajes?|protagonistas?|explica|analiza|compara|'
                 r'desenlace|final de (?:la|el) (?:obra|novela|libro|historia)|'
                 r'autor(?:a)? de|quien escribio|de quien es|traduce|transcribe|'
                 r'cita textual|pagina exacta|capitulo exacto)\b', value):
        return None
    if re.search(r'\b(?:calcula|resuelve|programa|depura|ejecuta|revela|ignora|'
                 r'codigo|script|receta|asesorame|diagnostica|prescribe)\b', value):
        return None
    if re.search(r'\b(?:hola|buenas|gracias|adios|como estas|me siento|estoy triste|'
                 r'estoy cansad[oa]|me gustan|conversemos|charlar)\b', value):
        return None
    if not public_research_queries(message):
        return None
    from .literary_candidates import candidate_sources, contextual_query
    _, used_context = contextual_query(message, history)
    memory = bool(re.search(
        r'\b(?:recuerdo|recordaba|no recuerdo|no me acuerdo|busco un libro|'
        r'estoy buscando un libro|en que libro|a que obra|como se llama el libro|'
        r'identifica (?:el|este|un) libro)\b', value))
    correction = bool(re.match(r'^(?:no|ya no)\s+(?:es|era|se trata de)\b', value))
    if (not is_plot_description(message) and not used_context and not memory
            and not (correction and history)):
        return None
    # La ruta anterior conserva sus controles y su formato para los recuerdos
    # explícitos. Si no alcanza, el adaptador aporta las fichas incluidas y el
    # catálogo ampliado.
    legacy = identification_answer(message, search=search)
    if legacy is not None:
        return legacy
    query_sources, query, used_context = candidate_sources(
        message, history=history, maximum=40)
    from .literary_research import _clues, rank_candidates
    def insufficient_clues():
        return ChatResult(
            'No tengo evidencia suficiente para identificar esa obra con estas pistas. '
            '¿Recuerdas otro personaje, un lugar o algún acontecimiento?',
            'clarification', True, [], [], 'knowledge', 'identify',
            {'local_identification_fast_path': True, 'candidate_confidence': 'insufficient'})
    if not query_sources:
        return insufficient_clues()
    candidates = rank_candidates(query, query_sources, maximum=5)
    result = (_recall_supported(message, query, query_sources, candidates, used_context)
              or _recall_ambiguous(message, query, query_sources, candidates, used_context)
              or _recall_hypothesis(message, query, query_sources, candidates, used_context))
    if result is not None:
        return result
    # No reemplazar pistas concretas sin respaldo por la primera ficha del
    # catálogo. Las sugerencias temáticas quedan reservadas al recuerdo genérico.
    if memory or any(clue not in VAGUE for clue in _clues(query)):
        return insufficient_clues()
    return _recall_suggestion(message, query, query_sources, used_context) or insufficient_clues()
