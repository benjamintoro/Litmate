"""Adaptador único de candidatos para identificar obras recordadas.

Combina las fichas incluidas, el conocimiento local, el catálogo Django y,
sólo cuando hace falta, la memoria bibliográfica ya existente. No inventa
obras ni crea índices: devuelve fuentes reales para que el motor de
identificación decida entre coincidencia, hipótesis y sugerencia.
"""
from difflib import SequenceMatcher
import re

from .literary_identity import normalize_identity, same_work, work_identity
from .literary_research import is_topic_recommendation, rank_candidates


FOLLOWUP_START = re.compile(
    r'^(?:y|e|ademas|tambien|pero|su|sus|el|la|los|las|otro|otra|ahora|'
    r'entonces|despues|luego|en (?:el|la) (?:libro|novela|historia))\b')
NON_IDENTIFICATION = re.compile(
    r'\b(?:quien (?:escribio|ha escrito|fue el autor|es el autor)|de quien es|'
    r'resume|resumen|sinopsis|argumento|personajes?|protagonistas?|'
    r'explica|analiza|compara|desenlace|final de (?:la|el|del) (?:obra|novela|libro|historia)|'
    r'autor(?:a)? de|recomienda|recomiendame|sugiere|sugiereme|que puedo leer)\b')
SOCIAL = re.compile(
    r'\b(?:hola|buenas|gracias|adios|como estas|me siento|estoy triste|'
    r'estoy cansad[oa]|me gustan|conversemos|charlar)\b')


def contextual_query(message, history=None):
    """Incorpora pistas de un turno de identificación anterior.

    No fusiona preguntas de autor, resumen, recomendación ni correcciones
    negativas. Devuelve ``(consulta, usó_contexto)`` para que la respuesta
    pueda informar que revisó el recuerdo anterior.
    """
    current = str(message or '')
    if not isinstance(history, list) or not history:
        return current, False
    value = normalize_identity(current).strip(' ¿?¡!.,;:')
    if (not value or is_topic_recommendation(current)
            or NON_IDENTIFICATION.search(value)
            or SOCIAL.search(value)
            or re.match(r'^(?:no|ya no)\s+(?:es|era|se trata de)\b', value)):
        return current, False
    # Una continuación explícita, no cualquier frase corta de conversación,
    # reutiliza el recuerdo anterior.
    clue_like = bool(FOLLOWUP_START.match(value)
                     or re.search(r'\b(?:familia|amigo|amiga|hermano|hermana|'
                                  r'padre|madre|hijo|hija|protagonista|personaje|'
                                  r'tiene|tenia|hay|era|es|se llama|llamado|llamada|'
                                  r'final|escena|recuerdo|no recuerdo|no me acuerdo|'
                                  r'tambien|ademas)\b', value))
    if not clue_like:
        return current, False
    for turn in reversed(history):
        if not isinstance(turn, dict) or turn.get('accepted') is not True:
            continue
        if turn.get('intent') != 'identify':
            # Una conversación posterior sobre otra tarea corta este recuerdo.
            return current, False
        previous = str(turn.get('question') or '').strip()
        if not previous or len(previous) > 500:
            continue
        # Una aclaración sin candidato conserva las pistas del lector, no una
        # identidad inventada. El turno ya está aceptado y marcado identify.
        return previous + ' ' + current, True
    return current, False


def _same_candidate_work(left, right):
    """Une la misma obra entre fuentes, incluso si varía la forma del autor."""
    if same_work(left, right):
        return True
    title_left = normalize_identity(left.get('title'))
    title_right = normalize_identity(right.get('title'))
    if not title_left or title_left != title_right:
        return False
    author_left = normalize_identity(left.get('author'))
    author_right = normalize_identity(right.get('author'))
    if not author_left or not author_right:
        return False
    if author_left == author_right:
        return True
    # «Fiódor M. Dostoievski» y «Fiódor Dostoyevski» son variantes de autor
    # de la misma ficha, no dos obras distintas. Se exige un apellido o una
    # similitud alta para no unir homónimos por el título.
    if (set(author_left.split()) & set(author_right.split())
            and SequenceMatcher(None, author_left, author_right).ratio() >= .86):
        return True
    return False


def _merge_metadata(previous, candidate):
    """Conserva la descripción más rica y la procedencia de ambas fuentes."""
    old_description = str(previous.get('description') or '')
    new_description = str(candidate.get('description') or '')
    if len(new_description) > len(old_description):
        previous['description'] = candidate['description']
    if candidate.get('synopsis') and not previous.get('synopsis'):
        previous['synopsis'] = candidate['synopsis']
    for key in ('url', 'image_url', 'preview_url', 'license', 'book_id', 'year',
                'read_mode', 'work_id', 'synopsis_source_url'):
        if candidate.get(key) and not previous.get(key):
            previous[key] = candidate[key]
    origin = str(candidate.get('source') or '').strip()
    if origin and origin not in str(previous.get('source') or '').split(' / '):
        previous['source'] = ((str(previous.get('source') or '') + ' / ' + origin)
                              .strip(' / ')[:180])


def merge_candidates(sources):
    """Agrupa fuentes por obra sin convertir una página web en otro libro."""
    merged = []
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, dict) or not source.get('title'):
            continue
        if not work_identity(source):
            continue
        existing = next((item for item in merged if _same_candidate_work(item, source)), None)
        if existing is None:
            merged.append(dict(source))
        else:
            _merge_metadata(existing, source)
    return merged


def _excluded_works(message, history):
    """Obras que el lector acaba de descartar en una corrección negativa."""
    value = normalize_identity(message)
    if not re.match(r'^(?:no|ya no)\s+(?:es|era|se trata de)\b', value):
        return []
    excluded = []
    for turn in history if isinstance(history, list) else []:
        if not isinstance(turn, dict) or turn.get('accepted') is not True:
            continue
        books = turn.get('books') if isinstance(turn.get('books'), list) else []
        for book in books:
            title = normalize_identity(book.get('title')) if isinstance(book, dict) else ''
            if title and re.search(r'(?<!\w)' + re.escape(title) + r'(?!\w)', value):
                excluded.append(book)
    return excluded


def _bundled_candidates():
    """Todas las fichas verificadas incluidas; el ranking decide su pertinencia."""
    from .ai_quick_answers import _bundled
    result = []
    for work in _bundled():
        if not isinstance(work, dict) or not work.get('title'):
            continue
        source = dict(work)
        source.setdefault('kind', 'book')
        source.setdefault('source', 'Conocimiento literario local')
        if not source.get('description'):
            continue
        result.append(source)
    return result


def _memory_candidates(query):
    """Memoria local de sólo lectura, reservada para cuando no hay candidatos."""
    try:
        from .literary_memory import retrieve_evidence
        books, evidence = retrieve_evidence(query, limit=6)
    except (OSError, ValueError, TypeError):
        return []
    return [source for source in [*books, *evidence] if isinstance(source, dict)]


def candidate_sources(message, *, history=None, maximum=40, include_memory=True):
    """Devuelve fuentes candidatas reales y la consulta contextual usada.

    El catálogo se amplía únicamente en esta ruta de identificación. Las
    fichas incluidas se incorporan completas para que obras como *La
    metamorfosis* no desaparezcan por un top-k pensado para recomendaciones.
    """
    query, used_context = contextual_query(message, history)
    sources = []
    try:
        from .literary_knowledge import search_knowledge
        sources.extend(search_knowledge(query, maximum=8))
    except (OSError, ValueError, TypeError):
        pass
    sources.extend(_bundled_candidates())
    try:
        from .literary_search import search_catalog
        catalog_sources = search_catalog(query, limit=24, expand=True)
        for source in catalog_sources:
            if isinstance(source, dict):
                source['candidate_origin'] = 'catalog'
        sources.extend(catalog_sources)
    except (OSError, ValueError, TypeError):
        pass
    merged = merge_candidates(sources)
    excluded = _excluded_works(message, history)
    if excluded:
        merged = [source for source in merged
                  if not any(same_work(source, book) for book in excluded)]
    if include_memory and not rank_candidates(query, merged, maximum=5):
        merged = merge_candidates([*merged, *_memory_candidates(query)])
        if excluded:
            merged = [source for source in merged
                      if not any(same_work(source, book) for book in excluded)]
    # Aplicar el límite después de priorizar coincidencias; las fichas incluidas
    # no deben desplazar una obra pertinente sólo por llegar antes del catálogo.
    ranked = rank_candidates(query, merged, maximum=3)
    relevant = [source for source in merged
                if any(same_work(source, candidate) for candidate in ranked)]
    others = [source for source in merged if source not in relevant]
    return (relevant + others)[:maximum], query, used_context
