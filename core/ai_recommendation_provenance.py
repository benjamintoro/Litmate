"""Detecta referencias narrativas omitidas sin decidir si una trama es cierta.

Esta comprobación es previa y complementaria a la auditoría: sólo produce una
corrección estructural cuando ya existe un pasaje web vinculado a la obra. No
agrega citas, no genera pruebas y no sustituye los validadores semánticos.
"""
import re

from .literary_ai import recommendation_evidence_sources
from .literary_identity import normalize_identity, same_work, work_identity
from .literary_quality import (_catalogue_only_proof_for_narrative,
                               _claim_has_wrong_work, _literal,
                               _numbered_description_work, required_fact_statements)


_PUBLIC_PASSAGES = {'pasaje de página pública', 'extracto de introducción',
                    'pasaje de sección de artículo público'}


def _describes_book(statement, book, sources, draft_text):
    entry = _numbered_description_work(statement, draft_text, sources)
    if entry:
        return same_work(entry, book)
    identity = work_identity(book)
    if not identity:
        return False
    text = normalize_identity(_literal(statement))
    titles = [identity['title']] + [alias['title'] for alias in identity['confirmed_aliases']]
    if not any(re.search(r'(?<!\w)' + re.escape(normalize_identity(title)) + r'(?!\w)', text)
               for title in titles if normalize_identity(title)):
        return False
    return not _claim_has_wrong_work(statement, book, sources, draft_text=draft_text)


def _narrative_passage(source, book, statement):
    if source.get('injection_detected') is True or not same_work(source, book):
        return False
    description = source.get('description')
    if not isinstance(description, str) or len(description.strip()) < 8:
        return False
    if _catalogue_only_proof_for_narrative(statement, source, description):
        return False
    if source.get('kind') == 'web':
        return (source.get('work_binding_verified') is True
                and source.get('read_mode') in _PUBLIC_PASSAGES
                and len(description.strip()) >= 60)
    if source.get('kind') == 'excerpt':
        # Coincide con los fragmentos que entrega el recuperador local. Una
        # etiqueta excerpt colocada en un snippet no certifica procedencia.
        return (source.get('read_mode') == 'fragmento recuperado'
                and str(source.get('source', '')).startswith('Colección local: ')
                and isinstance(source.get('book_id'), str) and bool(source['book_id'].strip()))
    return False


def validate_recommendation_provenance(draft, sources):
    """Señala el pasaje disponible que una explicación narrativa no ha citado.

    Devuelve None si no aparece este fallo estructural concreto. Eso no aprueba
    el contenido: la auditoría posterior sigue comprobando cada afirmación y
    sus pruebas literales, incluidas las fuentes contradictorias.
    """
    if (not isinstance(draft, dict) or draft.get('status') != 'answer'
            or not isinstance(draft.get('text'), str)
            or not isinstance(draft.get('books'), list)
            or not isinstance(draft.get('citations'), list)
            or not isinstance(sources, list)):
        return None
    current = [source for source in sources if isinstance(source, dict)
               and type(source.get('id')) is int]
    lookup = {source['id']: source for source in current}
    mappings = recommendation_evidence_sources(current)
    selected = {book['source_id'] for book in draft['books']
                if isinstance(book, dict) and type(book.get('source_id')) is int
                and book['source_id'] in lookup and same_work(lookup[book['source_id']], book)}
    cited = {identifier for identifier in draft['citations'] if type(identifier) is int}
    statements = required_fact_statements(draft['text'])
    for book_id in dict.fromkeys(pair['book_source_id'] for pair in mappings):
        if book_id not in selected:
            continue
        book = lookup[book_id]
        narrative_statements = [statement for statement in statements
                                if _describes_book(statement, book, current, draft['text'])
                                and _catalogue_only_proof_for_narrative(
                                    statement, book, book.get('description', ''))]
        if not narrative_statements:
            continue
        if any(source['id'] in cited and any(_narrative_passage(source, book, statement)
                                            for statement in narrative_statements)
               for source in current):
            continue
        pages = [pair['web_source_id'] for pair in mappings if pair['book_source_id'] == book_id]
        page_ids = ', '.join(str(identifier) for identifier in dict.fromkeys(pages))
        raise ValueError(
            f'La explicación de «{book["title"]}» incluye acontecimientos de la trama, '
            f'pero la ficha {book_id} sólo aporta materias de catálogo. '
            f'El pasaje narrativo verificado de esa obra está disponible en la fuente web '
            f'{page_ids}. Si usas hechos de ese pasaje, cita su ID junto al de la ficha '
            f'{book_id}; si no lo usas, limita la explicación al alcance bibliográfico '
            'comprobado. No añadas una referencia sin utilizar y verificar su contenido.')
    return None
