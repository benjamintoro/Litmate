"""Propuesta de identidad desde fichas originales locales, sin modelo ni red."""
import re

from .literary_ai import (ChatResult, canonical_sources, has_excerpt, obvious_rejection,
                          requires_exact_text, simple_research_plan, validate_draft)
from .literary_evidence import validate_evidence
from .literary_identity import normalize_identity, same_work
from .literary_knowledge import ORIGINAL_LICENSE, search_knowledge
from .literary_quality import required_fact_statements, validate_audit, validate_plan
from .literary_research import (VAGUE, _matches, _words, assess_evidence,
                               is_topic_recommendation, public_research_queries, rank_candidates)


def identification_answer(message):
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
        return None
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
        raw = search_knowledge(message, maximum=8)
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
        ignored = (VAGUE | set(_words(book['title'] + ' ' + book['author']))
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
