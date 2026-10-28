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
            'literatura', 'general', 'books', 'book', 'libros', 'libro', 'romans'}


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
            key = normalize_identity(part)
            if key and not set(key.split()) <= _GENERIC and len(part.strip()) <= 80:
                result.setdefault(key, part.strip())
    return result


def _pure_request(message):
    from .literary_ai import has_excerpt, obvious_rejection, requires_exact_text
    from .literary_language import request_text
    from .literary_research import public_research_queries
    if (not isinstance(message, str) or has_excerpt(message) or obvious_rejection(message)
            or requires_exact_text(message) or not public_research_queries(message)):
        return None
    value = request_text(message).strip(' ¿?¡!.,')
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


def related_recommendation_answer(message, history, search):
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
    request = _pure_request(message)
    if request is None or not isinstance(history, (list, tuple)) or not callable(search):
        return None
    relation, requested = request
    turns = sanitized_history(list(history))
    reference = resolve_followup_context(message, turns)
    bases = reference.get('books', [])
    if reference.get('ambiguous') or reference.get('reason') != relation or not bases:
        return None
    identity = work_identity(bases[0])
    if not identity or (len(bases) > 1 and (relation != 'same_author' or any(
            not same_author_name(identity['author'], book.get('author')) for book in bases))):
        return None
    base_sources = [source for turn in turns for source in turn['sources']
                    if _topic_catalogue_origin(source) and same_work(source, identity)
                    and not source.get('conflicts_with') and not source.get('injection_detected')]
    if not base_sources:
        return None
    topics = {}
    for source in base_sources:
        topics.update(_topics(source))
    if relation == 'similar' and not topics:
        return None
    if relation == 'same_author':
        queries = ['inauthor:"' + identity['author'].replace('"', ' ') + '"']
    else:
        # Broad catalogue components precede long, work-specific place labels.
        queries = ['subject:"' + topics[key].replace('"', ' ') + '"' for key in
                   sorted(topics, key=lambda key: (len(key.split()), len(key), key))[:2]]
    excluded = [*bases, *(book for turn in turns for book in turn['books'])]
    constraints = recommendation_constraints(message)
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
                    or any(same_work(source, old) for old in [*excluded, *chosen])):
                continue
            if relation == 'same_author':
                if not same_author_name(source.get('author'), identity['author']):
                    continue
            elif not set(topics) & set(_topics(source)):
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
            if len(chosen) >= requested:
                break
        if len(chosen) >= requested:
            break
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
