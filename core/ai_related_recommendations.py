"""Otras lecturas por autor o materias recibidas; sin generación de metadatos."""
import re

from .ai_budget import BudgetExpired, check_budget
from .literary_identity import normalize_identity, same_author_name, same_work, work_identity


_COUNTS = {'1': 1, 'un': 1, 'una': 1, 'uno': 1, '2': 2, 'dos': 2, '3': 3,
           'tres': 3, '4': 4, 'cuatro': 4, '5': 5, 'cinco': 5}
_WORDS = set(('recomiendame recomienda recomiendas sugiereme sugiere quiero quisiera busco dame '
              'otro otra otros otras mas algo algun alguna algunos algunas libros libro novelas novela '
              'obras obra lecturas lectura opciones opcion titulos titulo parecidos parecido parecida '
              'parecidas similar similares del de a al el la los las ese esa este esta esos esas estos '
              'estas anterior anteriores ultimo ultima primero primer primera segundo segunda tercero '
              'tercer tercera cuarto cuarta quinto quinta mismo misma autor autora que lei leido '
              'mencionaste recomendaste anteriormente por favor').split()) | set(_COUNTS)
_GENERIC = {'fiction', 'ficcion', 'novel', 'novels', 'novela', 'novelas', 'literature',
            'literatura', 'general', 'books', 'book', 'libros', 'libro', 'romans',
            'juvenile', 'juvenil', 'young', 'adult', 'children', 'childrens',
            'infantil', 'nonfiction', 'non', 'no'}
_UMBRELLA = {'science', 'ciencia', 'ciencias', 'history', 'historia', 'art', 'arte',
             'nonfiction', 'non fiction', 'no ficcion', 'reference', 'referencia',
             'manga', 'comics', 'graphic novels'}


def is_related_continuation(message, context):
    """Elipsis acotada; la referencia procede de la sesión, nunca del buscador."""
    memory = (context or {}).get('recommendation_state', {})
    return bool(memory.get('related_reference') and re.fullmatch(
        r'(?:dame|recomiendame) otr[oa]s? (?:(?:dos|tres|cuatro|cinco|[1-5]) )?'
        r'(?:opciones|libros|lecturas)', normalize_identity(message)))


def _subject_key(value):
    """Reutiliza alias de materias; no infiere contenidos de títulos."""
    from . import topic_reference
    normalized = normalize_identity(value)
    for key in topic_reference.known_facets():
        facet = topic_reference.facet(key)
        if normalized in {normalize_identity(term) for term in
                          (*facet.get('terms', ()), facet.get('catalog', ''))}:
            return key
    return normalized


def _topics(source):
    """Partes literales de materias jerárquicas, sin géneros codificados."""
    result = {}
    categories = source.get('categories')
    for category in categories[:12] if isinstance(categories, list) else []:
        if not isinstance(category, str) or len(category) > 180:
            continue
        value = normalize_identity(category)
        if (re.search(r'\b(?:literature|literatura|reviewed|bestseller|bestsellers)\b', value)
                or re.match(r'^(?:nyt|award|identifier|isbn)\s*:', category, re.I)):
            continue
        for part in re.split(r'[,;/|>]', category):
            key = _subject_key(part)
            if key and not set(key.split()) <= _GENERIC and len(part.strip()) <= 80:
                result.setdefault(key, part.strip())
    if not (set(result) - _UMBRELLA):
        # An umbrella-only record may have a useful genuine synopsis. Use its
        # dominant explicit subject as a retrieval signal, never as a new fact
        # or a generated category written back into the catalogue.
        from .books_google import source_synopsis
        from . import topic_reference
        synopsis = source_synopsis(source)
        resolved = topic_reference.resolve(synopsis)
        scored = [(len(re.findall(pattern, synopsis)), key)
                  for key, pattern, _ in resolved['subjects'] if key not in _UMBRELLA]
        if scored:
            _, dominant = max(scored)
            result[dominant] = topic_reference.catalog_subject(dominant)
    if 'philosophy' in result and set(result) - _UMBRELLA - {'philosophy'}:
        result.pop('philosophy')
    # Una etiqueta padre no compite con su hijo más preciso (Fantasy frente
    # a Dark fantasy). La relación se limita a componentes literales recibidos.
    return {key: label for key, label in result.items() if not any(
        set(key.split()) < set(other.split()) for other in result)}


def related_relevance(source, bases):
    """Afinidad trazable de materias; una etiqueta paraguas nunca basta.

    Las geografías explícitas deben conservarse. Las coincidencias bilingües
    usan el diccionario local existente, sin inventar relaciones entre obras.
    """
    from . import topic_reference
    from .ai_narrative_answers import work_type
    def catalogue_type(records):
        kind = work_type(records)
        if kind != 'unknown':
            return kind
        # Published scientific/technical disciplines describe nonfiction;
        # an incidental subject in a novel cannot override its Fiction tag.
        metadata = normalize_identity(' '.join(str(category) for record in records
            for category in record.get('categories', [])))
        if re.search(r'\b(?:medical|medicine|medicina|science|ciencia|cooking|cocina|'
                     r'chemistry|quimica|microbiology|microbiologia|astronomy|astronomia|'
                     r'physics|fisica|engineering|ingenieria)\b', metadata):
            return 'nonfiction'
        return 'unknown'
    reference_type, candidate_type = catalogue_type(bases), catalogue_type([source])
    if reference_type == 'nonfiction' and candidate_type == 'fiction':
        return 0
    topics = {key: label for base in bases for key, label in _topics(base).items()}
    anchors = set(topics) - _UMBRELLA
    candidate = _topics(source)
    shared = anchors & set(candidate)
    if not shared:
        return 0
    specific_length = max(len(key.split()) for key in anchors)
    if specific_length > 1 and not any(len(key.split()) == specific_length for key in shared):
        return 0
    def places(records):
        return {row[0] for record in records for row in topic_reference.resolve(
            ' '.join(str(item) for item in record.get('categories', [])))['places']}
    if not places(bases) <= places([source]):
        return 0
    # A place without its explicit discipline is not sufficient: a romance
    # set in Peru cannot replace a documented history of that country.
    required_roots = set(topics) & {'history'}
    if required_roots and not required_roots <= set(candidate):
        return 0
    if 'science' in topics:
        from .books_google import source_synopsis
        scientific_text = normalize_identity(' '.join([
            *[str(item) for item in source.get('categories', [])],
            source_synopsis(source)]))
        # An interdisciplinary scientific reference needs an actual scientific
        # signal as well as its narrow subject, not just generic recipes/art.
        from . import topic_reference
        scientific_facets = {'science', 'chemistry', 'physics', 'biology', 'astronomy',
                             'mathematics', 'geology', 'medicine'}
        received = {row[0] for row in topic_reference.resolve(scientific_text)['subjects']}
        if not (received & scientific_facets or re.search(
                r'\b(?:scientific|scientifique|cientific[oa]s?)\b', scientific_text)):
            return 0
    return sum(1 + len(key.split()) for key in shared) / max(1, len(anchors))


def _pure_request(message):
    from .literary_ai import has_excerpt, obvious_rejection, requires_exact_text
    from .literary_language import request_text
    from .literary_research import public_research_queries
    if (not isinstance(message, str) or has_excerpt(message) or obvious_rejection(message)
            or requires_exact_text(message) or not public_research_queries(message)):
        return None
    value = request_text(message).strip(' ¿?¡!.,')
    value = re.sub(r'\b(?:en|idioma) (?:espanol|castellano|ingles|frances|aleman|portugues|japones)\b', '', value).strip()
    if re.search(r'[;:\n.!?]|\by\b', value) or any(word not in _WORDS for word in re.findall(r'\w+', value)):
        return None
    similar = bool(re.search(r'\b(?:parecid[oa]s?|similar(?:es)?)\b', value))
    author = bool(re.search(r'\b(?:mismo|misma) autor(?:a)?\b', value))
    if similar == author or not re.search(r'\b(?:recomiend\w*|sugier\w*|quiero|quisiera|busco|dame|otr[oa]s?|mas)\b', value):
        return None
    counts = [_COUNTS[word] for word in re.findall(r'\w+', value) if word in _COUNTS]
    if len(counts) > 1:
        return None
    requested = counts[0] if counts else (1 if re.search(r'\botr[oa]\b', value) else 3)
    return ('similar' if similar else 'same_author'), requested


def repeated_recommendation(source, previous):
    """Excluye variantes probables de la lista, sin fusionar identidades.

    Un título bilingüe con la misma autoría y el mismo componente literal
    no se presenta como otra lectura. No se persiste un alias ni una relación.
    """
    if same_work(source, previous):
        return True
    if not same_author_name(source.get('author'), previous.get('author')):
        return False
    def components(record):
        values = {tuple(word for word in normalize_identity(part).split() if word not in {'y', 'and'})
                  for part in re.split(r'\s+/\s+', str(record.get('title', '')))}
        return {value for value in values if value}
    return bool(components(source) & components(previous))


def related_explanation_answer(message, history):
    """Explica la selección ordinal anterior; nunca inicia otra lista."""
    from .literary_ai import ChatResult, canonical_sources, sanitized_history
    from .literary_language import request_text
    from .literary_identity import resolve_followup_context
    from .books_google import source_synopsis
    from .literary_quality import factual_statements
    from .ai_quick_answers import _validated_result
    value = request_text(message).strip(' ¿?¡!.,')
    match = re.fullmatch(r'por que (?:se parece|es similar|es parecido) (?:el|la) '
        r'(primero|primera|segundo|segunda|tercero|tercera|cuarto|cuarta|quinto|quinta)'
        r'(?: libro| obra| novela)?', value)
    if not match:
        return None
    turns = sanitized_history(list(history or []))
    index = {'primero': 0, 'primera': 0, 'segundo': 1, 'segunda': 1,
             'tercero': 2, 'tercera': 2, 'cuarto': 3, 'cuarta': 3, 'quinto': 4, 'quinta': 4}[match.group(1)]
    for position in range(len(turns) - 1, -1, -1):
        request = _pure_request(turns[position]['question'])
        if not request or request[0] != 'similar':
            continue
        selected = turns[position]['books'][index:index + 1]
        reference = resolve_followup_context(turns[position]['question'], turns[:position])
        if not selected or reference.get('ambiguous') or len(reference['books']) != 1:
            break
        identities = [reference['books'][0], selected[0]]
        if repeated_recommendation(selected[0], reference['books'][0]):
            return ChatResult('Esa opción podría ser otra edición de la obra de referencia; '
                'no puedo justificarla como una lectura distinta.', 'clarification', intent='analysis',
                diagnostics={'related_explanation': True, 'model_calls': 0, 'evidence_state': 'insufficient'})
        sources = []
        for identity in identities:
            candidates = [source for turn in turns[:position + 1] for source in turn['sources']
                          if same_work(source, identity) and not source.get('conflicts_with')
                          and not source.get('injection_detected')]
            source = next((source for source in candidates if source_synopsis(source)), None)
            if source is None:
                break
            synopsis = source_synopsis(source)
            passage = next((sentence for sentence in factual_statements(synopsis, strip_markers=False)
                            if 8 <= len(sentence) <= 300 and sentence in source.get('description', '')
                            and not sentence.lstrip().startswith('¿') and not sentence.rstrip().endswith('?')
                            and not sentence.startswith('Temas del catálogo:')), '')
            if not passage:
                break
            sources.append({**source, 'description': passage})
        if len(sources) == 2 and related_relevance(sources[1], [sources[0]]):
            result = _validated_result(message, canonical_sources(sources, 2))
            if result is not None:
                result.intent = 'analysis'
                result.diagnostics.update(related_explanation=True, model_calls=0)
                return result
        return ChatResult('La sugerencia se basó en coincidencias temáticas de las fichas. '
            'No tengo descripciones verificadas suficientes para justificar una semejanza más precisa.',
            'clarification', intent='analysis', diagnostics={'related_explanation': True,
                'model_calls': 0, 'evidence_state': 'partial'})
    return ChatResult('¿Qué dos libros quieres comparar? No encuentro una recomendación anterior '
        'que permita identificar esa semejanza.', 'clarification', intent='analysis',
        diagnostics={'related_explanation': True, 'model_calls': 0, 'evidence_state': 'insufficient'})


def related_recommendation_answer(message, history, search, *, context=None):
    """Ruta pura y acotada: hasta dos búsquedas, con los mismos validadores.

    La coincidencia de materias no certifica similitud de argumentos. Los
    filtros adicionales y las referencias inciertas conservan el flujo general.
    """
    from .ai_catalog_fallback import _topic_catalogue_origin
    from .ai_quick_answers import _validated_result
    from .books_google import public_query, source_synopsis
    from .literary_ai import canonical_sources, sanitized_history, validate_draft
    from .literary_constraints import constraints_match, recommendation_constraints
    from .literary_evidence import validate_evidence
    from .literary_quality import factual_statements, required_fact_statements, validate_audit
    from .literary_identity import resolve_followup_context
    from .literary_web import public_text_has_injection
    memory = (context or {}).get('recommendation_state', {})
    request = _pure_request(message)
    more = is_related_continuation(message, context)
    if request is None and more and memory.get('related_reference'):
        from .literary_ai import requested_book_count
        request = ('similar', requested_book_count(message) or 3)
    if request is None or not isinstance(history, (list, tuple)) or not callable(search):
        return None
    relation, requested = request
    turns = sanitized_history(list(history))
    reference = resolve_followup_context(message, turns)
    if more and memory.get('related_reference'):
        reference = {'books': [memory['related_reference']], 'ambiguous': False, 'reason': 'similar'}
    bases = reference.get('books', [])
    if reference.get('ambiguous') or reference.get('reason') != relation or not bases:
        return None
    identity = work_identity(bases[0])
    if not identity or (len(bases) > 1 and (relation != 'same_author' or any(
            not same_author_name(identity['author'], book.get('author')) for book in bases))):
        return None
    def reference_origin(source):
        if _topic_catalogue_origin(source):
            return True
        from .ai_quick_answers import _bundled
        from .literary_knowledge import ORIGINAL_LICENSE
        if source.get('source') != 'Conocimiento literario local' or source.get('license') != ORIGINAL_LICENSE:
            return False
        for known in _bundled():
            if not same_work(source, known) or source.get('url') != known.get('url'):
                continue
            approved = [known.get('description', ''), *(fact.get('text', '') for fact in known.get('facts', []))]
            categories = set(source.get('categories', []))
            if (source.get('description') and any(source['description'] in text for text in approved)
                    and categories <= set(known.get('categories', []))):
                return True
        return False
    base_sources = [source for turn in turns for source in turn['sources']
                    if reference_origin(source) and same_work(source, identity)
                    and not source.get('conflicts_with') and not source.get('injection_detected')]
    # La deduplicación puede combinar el rótulo de proveedores. Recuperar la
    # ficha original por identidad Y URL evita perderla y no legitima campos
    # añadidos al registro combinado (materias, sinopsis o licencia).
    from .ai_quick_answers import _bundled
    for known in _bundled():
        if same_work(known, identity) and any(
                same_work(source, known) and source.get('url') == known.get('url')
                and not source.get('conflicts_with') and not source.get('injection_detected')
                for turn in turns for source in turn['sources']):
            base_sources.append(known)
    if not base_sources:
        return None
    # Topics can live in an already read, identity-bound narrative page rather
    # than in a sparse catalogue record. Such a page never becomes a book card.
    base_sources += [source for turn in turns for source in turn['sources']
        if source.get('kind') == 'web' and source.get('work_binding_verified') is True
        and same_work(source, identity) and not source.get('conflicts_with')
        and not source.get('injection_detected') and 'fragmento del buscador' not in
        str(source.get('read_mode', '')).lower() and not public_text_has_injection(source.get('description', ''))]
    topics = {}
    for source in base_sources:
        topics.update(_topics(source))
    if relation == 'similar' and not (set(topics) - _UMBRELLA):
        return None
    if relation == 'same_author':
        queries = ['inauthor:"' + identity['author'].replace('"', ' ') + '"']
    else:
        # Specific subjects precede umbrella disciplines. Keep the original
        # catalogue wording in the query, not a generated title or synopsis.
        queries = ['subject:"' + topics[key].replace('"', ' ') + '"' for key in
                   sorted(set(topics) - _UMBRELLA,
                          key=lambda key: (-len(key.split()), -len(key), key))[:2]]
    from .literary_constraints import requested_language
    language = requested_language(message) or memory.get('constraints', {}).get('language')
    labels = {'es': 'español', 'en': 'inglés', 'fr': 'francés', 'de': 'alemán', 'pt': 'portugués', 'ja': 'japonés'}
    if language in labels:
        queries = [query + ' en ' + labels[language] for query in queries]
    excluded = [*bases, *memory.get('seen', []), *(book for turn in turns for book in turn['books'])]
    constraints = recommendation_constraints(message)
    constraints.update({key: value for key, value in memory.get('constraints', {}).items()
                        if not constraints.get(key)})
    chosen = []
    for query in queries:
        if public_query(query) != query:
            continue
        try:
            check_budget()
            sources = search(query)
        except BudgetExpired:
            break
        except (OSError, TimeoutError, ValueError, TypeError):
            continue
        for source in sources[:20] if isinstance(sources, (list, tuple)) else []:
            if (not isinstance(source, dict) or not _topic_catalogue_origin(source)
                    or source.get('conflicts_with') or not constraints_match(source, constraints)
                    or public_text_has_injection(str(source.get('description', '')))
                    or any(repeated_recommendation(source, old) for old in [*excluded, *chosen])):
                continue
            if relation == 'same_author':
                if not same_author_name(source.get('author'), identity['author']):
                    continue
            elif not related_relevance(source, base_sources):
                continue
            synopsis = source_synopsis(source)
            sentences = factual_statements(synopsis, strip_markers=False) if synopsis else []
            passage = next((sentence for sentence in sentences if 8 <= len(sentence) <= 300
                            and sentence in str(source.get('description', ''))), '')
            if not passage:
                description = str(source.get('description', ''))
                if description.startswith('Temas del catálogo:'):
                    passage = description[:300].rsplit(' ', 1)[0] if len(description) > 300 else description
            if not passage:
                continue
            chosen.append({**source, 'description': passage})
        if relation == 'similar':
            chosen.sort(key=lambda source: related_relevance(source, base_sources), reverse=True)
        if len(chosen) >= requested:
            break
    chosen = chosen[:requested]
    if not chosen:
        return None
    result = _validated_result(message, canonical_sources(chosen, 5), recommendation=True)
    if result is None:
        return None
    note = ('No puedo confirmar una trama semejante; la afinidad se limita a las materias del catálogo.'
            if relation == 'similar' else
            'No puedo confirmar semejanzas de trama; seleccioné las obras por su autoría de catálogo.')
    if len(chosen) < requested:
        note += '\n\nNo pude confirmar todas las opciones solicitadas.'
    _, separator, footer = result.text.partition('\n\nFuentes de las fichas:\n')
    # The cards retain their genuine synopsis, when present. Keep the message
    # readable instead of turning a subject index into an apparent plot.
    lines, identity_claims = ['¡Claro!'], []
    for index, source in enumerate(result.sources, 1):
        identity_text = '**' + source['title'] + '** — ' + source['author']
        proof = next((source[field] for field in ('title', 'author', 'description')
                      if 8 <= len(source.get(field, '')) <= 300), '')
        if not proof:
            return None
        lines.append(str(index) + '. ' + identity_text)
        identity_claims.extend({'statement': statement, 'verdict': 'supported',
            'source_id': source['id'], 'evidence': proof}
            for statement in required_fact_statements(identity_text) or [identity_text])
    body = '\n\n'.join(lines)
    text = body + '\n\n' + note
    audit = {**result.diagnostics['audit'], 'claims': [*identity_claims, *[
        {'statement': statement, 'verdict': 'unverified', 'source_id': 0, 'evidence': ''}
        for statement in factual_statements(note)]],
        'coverage': [{'question_id': 1, 'status': 'uncertain'}]}
    draft = {'status': 'answer', 'basis': 'sources', 'text': text, 'books': result.books,
             'citations': [source['id'] for source in result.sources], 'needs_web': False}
    plan = {'questions': [message], 'search_queries': [], 'needs_contents': False,
            'needs_fresh_sources': False, 'spoilers_requested': False}
    try:
        validate_draft(draft, result.sources)
        validate_evidence(draft, result.sources, message)
        validate_audit(audit, plan, draft, result.sources, message, strict_facts=True)
    except (ValueError, TypeError):
        return None
    result.text = text + (separator + footer if separator else '')
    result.diagnostics.update(audit=audit, verified_related_recommendations=True,
                              related_basis=relation, model_calls=0,
                              shared_catalogue_subjects=sorted(topics) if relation == 'similar' else [])
    return result
