"""Decisiones de recuperación locales: evidencia por pregunta, sin inferencias de hechos.

Este módulo no consulta redes ni genera respuestas. Un marcador de suficiencia
solo evita herramientas innecesarias; nunca sustituye la auditoría del asistente.
"""
import re
from collections import defaultdict
from difflib import SequenceMatcher

from .ai_privacy import excerpt_marker
from .books_google import public_query
from .literary_identity import (BIBLIOGRAPHIC_ORIGINS, normalize_identity,
                                same_work, work_identity)


STOP = set('a al algo alguien algun alguna algunos algunas ante aparece aparecia aquel aquella '
           'asi aun autor autores busco buscar buscaba cada como con cual cuales cuando de del '
           'decian decir donde el ella ellas ellos en era eran es ese esa eso esta estaba este '
           'estos fue fui habia hace hacia hasta historia la las le libro libros lo los me '
           'mi muy no nombre nos o obra obras para pero por porque puedo que quien recuerdo '
           'recordar recuerda se sea si sin sobre solo son su sus tambien tenia tiene titulo '
           'un una unos unas vivia y ya yo'.split())
VAGUE = set('escena escenas mujer hombre persona protagonista protagonistas personaje personajes '
            'viaje viajaba viajaban viajando viajero viajera despues antes joven niño niña niños '
            'niñas pequeño pequeña hermana hermano bosque'.split())
VAGUE = {normalize_identity(item) for item in VAGUE}


def _words(text):
    return re.findall(r'[a-z0-9]+', normalize_identity(text))


def _clues(message):
    result = []
    for token in _words(message):
        if len(token) > 2 and token not in STOP and token not in result:
            result.append(token)
    return result[:32]


def _matches(token, words):
    if token in words:
        return True
    return len(token) >= 6 and any(len(other) >= 6 and abs(len(token) - len(other)) <= 2
        and SequenceMatcher(None, token, other).ratio() >= .85 for other in words)


def _source_text(source):
    return '\n'.join(str(source.get(key) or '') for key in ('title', 'author', 'description', 'identity_text'))


def is_topic_recommendation(message):
    """Reconoce una petición de lecturas por tema, no una obra recordada.

    Es una pista de intención; no autoriza una petición rechazada por el
    clasificador ni reemplaza los controles de ámbito o de privacidad.
    No contiene temas, países o títulos especiales.
    """
    if not isinstance(message, str) or excerpt_marker(message):
        return False
    from .literary_language import request_text
    value = normalize_identity(request_text(message))
    if not value or re.search(
            r'\b(?:recuerdo|recordaba|no recuerdo|no me acuerdo|olvid[eé]|'
            r'como se llama|cual es el titulo|que libro es|en que libro|'
            r'no (?:se|conozco|recuerdo) (?:su |el )?titulo)\b', value):
        return False
    # Las órdenes mezcladas siguen requiriendo rechazo del clasificador. Esta
    # pista tampoco las presenta a otros componentes como una recomendación.
    if re.search(r'\b(?:calcula|resuelve|programa|depura|ejecuta|revela|'
                 r'ignora las reglas|dame una receta|prepara una receta)\b', value):
        return False
    book = r'(?:libros?|novelas?|lecturas?|titulos?|obras?|manual(?:es)?|ensayos?)'
    if re.search(book + r'\s+(?:llamad[oa]|titulad[oa]|de titulo|que se llama)\b', value):
        return False
    request = re.search(r'\b(?:recomiend\w*|recomenda\w*|sugier\w*|sugeri\w*)\b', value)
    if not request:
        request = re.search(r'\b(?:que (?:puedo|podria|me aconsejas|me aconsejarias) leer|'
                            r'que me (?:recomiendas|recomendas) (?:para )?leer|'
                            r'alguna? (?:libro|lectura|novela)|'
                            r'me (?:gustaria|interesa) leer)\b', value)
    if not request:
        request = re.search(
            r'\b(?:quiero|quisiera|busco|buscando|necesito|dame|dime|recomendarme|'
            r'puedes recomendarme|podrias recomendarme)\s+(?:encontrar\s+)?'
            r'(?:(?:un|una|unos|unas|algun|alguna|algunos|algunas|otro|otra|otros|otras|'
            r'dos|tres|cuatro|cinco|[1-5])\s+)?' + book + r'\b', value)
    if not request:
        # Peticiones elípticas habituales: «libros de historia», «novelas
        # sobre viajes». No basta con que una charla mencione un libro.
        request = re.search(r'^' + book + r'\s+(?:sobre|acerca de|de|para)\s+\S', value)
    if not request:
        return False
    # «Busco un libro donde un niño...» describe una obra existente. En
    # cambio «un libro que explique/trate...» expresa un tema de lectura.
    if re.search(book + r'\s+(?:que|donde|en el que|en la que)\s+', value):
        if not re.search(book + r'\s+(?:(?:que|donde)\s+(?:se\s+)?)'
                         r'(?:trate|hable|explique|ense[nñ]e|aborde|describa)\b', value):
            return False
    if re.search(r'\bsobre\s+(?:un|una)\s+(?:ni[nñ]o|ni[nñ]a|hombre|mujer|'
                 r'personaje|familia|joven)\b.{0,100}\b(?:que|donde|viv[ií]a|vive|'
                 r'cuida|cuidaba|viajaba|viaja)\b', value):
        return False
    return True


def resolve_verified_request(message, sources):
    """Ancla una petición explícita a una ficha comprobada, no a pistas del LLM.

    Solo considera títulos escritos en este mensaje y alias con procedencia.
    No resuelve pronombres ni utiliza un libro de un turno anterior como si el
    lector lo hubiera nombrado. Las recomendaciones conservan su recorrido.
    """
    empty = {'books': [], 'intent': ''}
    if not isinstance(message, str) or excerpt_marker(message):
        return empty
    value = normalize_identity(message)
    if not value or is_topic_recommendation(message) or re.search(r'\b(?:recomienda|recomiendame|recomiendanos|parecidos a|similares a|compara|comparacion|diferencias entre|pelicula|adaptacion cinematografica)\b', value):
        return empty
    sources = sources if isinstance(sources, list) else []
    matched = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        origins = str(source.get('source', '')).split(' / ')
        if (source.get('kind', 'book') not in {'book', 'excerpt'}
                or not any(origin in BIBLIOGRAPHIC_ORIGINS for origin in origins)):
            continue
        identity = work_identity(source)
        if not identity:
            continue
        titles = {normalize_identity(identity['title'])} | {
            normalize_identity(alias['title']) for alias in identity.get('confirmed_aliases', [])}
        literals = [title for title in titles if len(title) >= 4
                    and re.search(r'(?<!\w)' + re.escape(title) + r'(?!\w)', value)]
        if literals:
            matched.append((source, identity, literals))
    if not matched:
        return empty
    # Si hay dos volúmenes y uno contiene el título del otro, prevalece el más
    # específico escrito por el lector; no una simple palabra de la colección.
    matched = [item for item in matched if not all(any(
        title != other_title and title in other_title
        for other in matched for other_title in other[2]) for title in item[2])]
    # Un título entre comillas desconocido no se sustituye por una referencia
    # incidental a otra obra conocida dentro del mismo mensaje.
    quoted = re.findall(r'[«“"]([^»”"\n]{2,180})[»”"]', message)
    literal_titles = {title for _, identity, _ in matched for title in
                      [normalize_identity(identity['title'])] + [normalize_identity(alias['title'])
                          for alias in identity.get('confirmed_aliases', [])]}
    if any(normalize_identity(title) not in literal_titles for title in quoted):
        return empty
    unique = []
    for source, identity, titles in matched:
        if not any(same_work(source, item[0]) for item in unique):
            unique.append((source, identity, titles))
    if len(unique) > 1:
        # Un autor explícito puede resolver homónimos. Dos obras distintas no
        # se convierten en una única obra activa por aparecer en la búsqueda.
        authored = [item for item in unique if normalize_identity(item[1]['author']) in value]
        if len(authored) != 1:
            return empty
        unique = authored
    if len(unique) != 1:
        return empty
    _, identity, titles = unique[0]
    # «Papelucho» no identifica «Papelucho y ...» sin un alias confirmado.
    subject = re.search(r'\b(?:(?:personajes?|protagonistas?)(?: principales?)?\s+(?:de|del)|'
                        r'hablame de|cuentame de(?: que trata)?|de que trata|'
                        r'resumen de|sinopsis de|argumento de|final de|'
                        r'(?:sucede|pasa|ocurre)(?:\s+con\s+\w+(?:\s+\w+){0,2})?\s+en)\s+(?:el libro\s+)?(.+)', value)
    if subject:
        target = subject.group(1)
        exact = any(target == title or target.startswith(title + ' de ' + normalize_identity(identity['author']))
                    or target.startswith(title + ' y sus ') or target.startswith(title + ' y su ')
                    or target.startswith(title + ' sin spoilers') or target.startswith(title + ' con spoilers')
                    for title in titles)
        if not exact:
            return empty
    memory = bool(re.search(r'\b(?:recuerdo|no recuerdo|busco un libro|en que libro|a que obra|como se llama el libro)\b', value))
    content_action = bool(re.search(r'\b(?:personajes?|protagonistas?|quien es|quien era|quienes aparecen|relacion|sucede|paso|pasa|ocurre|escena|final|termina|analiza|cita|pasaje|capitulo|pagina)\b', value))
    author_action = bool(re.search(r'\b(?:autor|autora|quien escribio|biografia)\b', value))
    summary_action = bool(re.search(r'\b(?:hablame|cuentame|resume|resumen|sinopsis|trama|argumento|de que trata|que sabes sobre|que sabes de)\b', value))
    title_only = value in titles or any(value == title + ' de ' + normalize_identity(identity['author']) for title in titles)
    # Una mención incidental durante una charla no cambia su intención social.
    if not (memory or content_action or author_action or summary_action or title_only):
        return empty
    if memory:
        intent = 'identify'
    elif content_action:
        intent = 'analysis'
    elif author_action:
        intent = 'author'
    else:
        intent = 'summary'
    return {'books': [identity], 'intent': intent}


def rank_candidates(message, sources, maximum=3):
    """Ordena obras por pistas realmente presentes; no contiene respuestas por título.

    La puntuación es interna, no una probabilidad de certeza. Las páginas sin
    identidad bibliográfica no se convierten en libros candidatos por sí solas.
    """
    clues, groups = _clues(message), []
    if not clues:
        return []
    valid = [source for source in sources if isinstance(source, dict)] if isinstance(sources, list) else []
    for source in valid:
        if source.get('kind') not in {'book', 'excerpt'} and not source.get('work_binding_verified'):
            continue
        identity = work_identity(source)
        if not identity:
            continue
        if not any(same_work(source, group['book']) for group in groups):
            groups.append({'book': source, 'identity': identity})
    results = []
    for group in groups:
        evidence_sources = [source for source in valid if same_work(source, group['book'])]
        texts = [_source_text(source) for source in evidence_sources]
        words = set(_words('\n'.join(texts)))
        matched = [clue for clue in clues if _matches(clue, words)]
        meaningful = [clue for clue in matched if clue not in VAGUE]
        if not matched or not meaningful:
            continue
        evidence = []
        for source, text in zip(evidence_sources, texts):
            # Muestra contexto real, nunca una explicación fabricada de la coincidencia.
            passages = re.split(r'(?<=[.!?])\s+|\n+', text)
            for passage in passages:
                if any(_matches(clue, set(_words(passage))) for clue in meaningful):
                    evidence.append({'source_id': source.get('id', 0), 'url': str(source.get('url') or ''),
                                     'text': passage[:500]})
                    break
        identity = group['identity']
        missing = [clue for clue in clues if clue not in matched]
        results.append({'title': identity['title'], 'author': identity['author'],
            'work_id': identity['work_id'], 'matched_clues': matched, 'missing_clues': missing,
            'confidence': 'supported' if len(meaningful) >= 2 and len(matched) >= max(2, len(clues) // 2) else 'possible',
            'evidence': evidence[:3], 'source_ids': [source.get('id', 0) for source in evidence_sources],
            '_score': len(meaningful) * 3 + len(matched) - len(missing) * .2})
    results.sort(key=lambda item: (-item['_score'], normalize_identity(item['title']), item['author']))
    # Una coincidencia incidental («planeta») no crea ambigüedad frente a una
    # obra que respalda esa pista y además la rosa, el zorro y el niño. Conserva
    # alternativas con pistas propias o respaldo comparable; no es un umbral
    # de probabilidad ni una excepción escrita para determinados títulos.
    supported = [set(item['matched_clues']) for item in results if item['confidence'] == 'supported']
    results = [item for item in results if item['confidence'] == 'supported' or not any(
        set(item['matched_clues']) < clues for clues in supported)]
    for result in results:
        result.pop('_score')
    return results[:max(1, min(int(maximum), 3))]


def evidence_requirements(message, intent=''):
    value = normalize_identity(message)
    requirements = []
    topic_recommendation = is_topic_recommendation(message)
    # «Libros sobre personajes históricos / el final de la guerra» nombra
    # materias de no ficción. Solo una acción adicional pide los personajes
    # o el desenlace de una obra recomendada.
    secondary = re.search(r'\b(?:y|ademas|tambien)\s+(?:dime|explica|cuentame|'
                          r'describe|analiza|resume|enumera|identifica)\b.*', value)
    detail_value = (secondary.group(0) if secondary else '') if topic_recommendation else value
    memory = bool(re.search(
        r'\b(?:recuerdo|no recuerdo|busco un libro|en que libro|a que obra|como se llama el libro)\b', value)) and not topic_recommendation
    explicit_characters = bool(re.search(r'\b(?:personajes|protagonistas)\b', detail_value)) and not memory
    identifying = memory or (intent == 'identify' and not explicit_characters and not topic_recommendation)
    if identifying:
        requirements.append('identification')
    if re.search(r'\b(?:personajes|protagonistas|quienes aparecen)\b', detail_value) and not identifying:
        requirements.append('characters')
    if re.search(r'\b(?:relacion|relacionan|parentesco|amigo de|hermano de|padre de|madre de)\b', detail_value):
        requirements.append('relationships')
    if re.search(r'\b(?:que sucede|que paso|que pasa|ocurre|acontecimiento|como termina|final|muere)\b', detail_value):
        requirements.append('events')
    if not identifying and re.search(r'\b(?:final|desenlace|como termina|como acaba)\b', detail_value):
        requirements.append('ending')
    if re.search(r'\b(?:escena|escenas)\b', detail_value) and not identifying:
        requirements.append('scenes')
    if not identifying and re.search(r'\b(?:cita textual|cita exacta|pagina exacta|en que pagina|capitulo exacto|pasaje exacto|transcribe)\b', value):
        requirements.append('exact_passage')
    if (intent == 'summary' and not topic_recommendation) or re.search(r'\b(?:sinopsis|trama|argumento|de que trata|resume|resumen)\b', detail_value):
        requirements.append('synopsis')
    if re.search(r'\b(?:compara|diferencias|comparacion)\b', value):
        requirements.append('comparison')
    if topic_recommendation or intent == 'recommend' or re.search(r'\b(?:recomienda|recomiendame|recomiendanos)\b', value):
        requirements.append('recommendation')
    if not requirements:
        if re.search(r'\b(?:quien es|quien era)\b', value):
            requirements.append('character_detail')
        elif intent in {'analysis', 'author'}:
            requirements.append('content' if intent == 'analysis' else 'bibliography')
        elif intent in {'conversation', 'concept'}:
            return []
        else:
            requirements.append('bibliography')
    return requirements


def _grounded_facts(source):
    description = normalize_identity(source.get('description'))
    result = []
    for key in ('literary_facts', 'facts'):
        facts = source.get(key, [])
        for fact in facts[:30] if isinstance(facts, list) else []:
            if not isinstance(fact, dict):
                continue
            evidence = normalize_identity(fact.get('evidence') or fact.get('text'))
            if evidence and len(evidence) >= 8 and evidence in description:
                result.append(fact)
    return result


def _contradictions(sources):
    claims = defaultdict(set)
    for source in sources:
        identity = work_identity(source)
        # Roles de parentesco incompatibles requieren contrastar fuentes. Una
        # ocupación complementaria o una lista parcial no contradice otra.
        text = normalize_identity(source.get('description'))
        facts = source.get('character_facts', [])
        for fact in facts[:15] if isinstance(facts, list) else []:
            if not isinstance(fact, dict) or not identity.get('work_id'):
                continue
            name, role = normalize_identity(fact.get('name')), normalize_identity(fact.get('role'))
            if not name or name not in text or not role or role not in text:
                continue
            kinship = re.fullmatch(r'(?:es |era )?(?:el |la )?'
                r'(madre|padre|hijo|hija|hermano|hermana) de (.{1,120})', role)
            if kinship:
                claims[(identity['work_id'], name, 'kinship', kinship.group(2))].add(kinship.group(1))
        # Una lista incompleta no contradice una lista más larga.
        for fact in _grounded_facts(source):
            subject = normalize_identity(fact.get('subject'))
            relation = normalize_identity(fact.get('relation') or fact.get('predicate'))
            value = normalize_identity(fact.get('value') or fact.get('object'))
            if subject and relation and value and relation in {
                    'author', 'autor', 'death', 'muerte', 'ending', 'desenlace', 'identity', 'identidad'}:
                claims[(identity.get('work_id', ''), subject, relation)].add(value)
    return any(len(values) > 1 for values in claims.values())


def public_research_queries(message, selected_books=None, requirements=None):
    """Construye consultas bibliográficas, nunca envía pasajes privados o historial."""
    if excerpt_marker(message):
        return []
    requirements = requirements or evidence_requirements(message)
    labels = {'characters': 'personajes', 'character_detail': 'personaje', 'relationships': 'relación personajes',
              'events': 'argumento acontecimientos', 'ending': 'desenlace final', 'scenes': 'escena argumento', 'synopsis': 'sinopsis',
              'exact_passage': 'cita edición', 'content': 'argumento', 'comparison': 'sinopsis'}
    books = selected_books if isinstance(selected_books, list) else []
    queries, alternatives = [], []
    for book in books[:2]:
        identity = work_identity(book)
        if not identity:
            continue
        base = public_query(identity['title'] + ' ' + identity['author'])
        if not base:
            continue
        label = next((labels[requirement] for requirement in requirements if requirement in labels), '')
        # Solo nombres ya presentes en la evidencia de la obra se añaden al buscar detalles.
        entities = []
        facts = book.get('character_facts', [])
        for fact in facts if isinstance(facts, list) else []:
            if isinstance(fact, dict) and normalize_identity(fact.get('name')) in normalize_identity(message):
                entities.append(str(fact.get('name', '')))
        # Una pregunta sobre Det conserva ese nombre si la ficha ya lo menciona.
        # Nunca se reenvía un nombre personal ajeno a la evidencia bibliográfica.
        description_words = set(_words(book.get('description', '')))
        identity_words = set(_words(base))
        for name in re.findall(r'\b[A-ZÁÉÍÓÚÜÑ][\wáéíóúüñÁÉÍÓÚÜÑ-]{2,}\b', message):
            token = normalize_identity(name)
            if token in description_words and token not in identity_words and token not in STOP:
                if name not in entities:
                    entities.append(name)
        query = public_query(' '.join([base, *entities[:2], label]))
        if query and query not in queries:
            queries.append(query)
        for alias in identity.get('confirmed_aliases', []):
            alternative = public_query(' '.join(['"' + alias['title'].replace('"', ' ') + '"',
                                                identity['author'], *entities[:2], label]))
            if alternative and alternative not in queries and alternative not in alternatives:
                alternatives.append(alternative)
    if queries:
        # Cada obra tiene prioridad sobre variantes de otra. Una sola obra puede
        # usar el segundo turno para un alias bibliográfico realmente confirmado.
        return (queries + alternatives)[:2]
    # Recuerdos de libros públicos pueden compartirse; datos personales se rechazan
    # antes de limpiar la consulta, para no convertir una confidencia en búsqueda.
    if re.search(r'(?i)\b(?:mi nombre|me llamo|mi direccion|mi dirección|mi telefono|mi teléfono|mi contraseña|mi password|mi correo|mi secreto|mi amigo|mi amiga|mi familia|mi pareja|mi hermana|mi hermano|contrase[nñ]a|password|api[ _-]*key|bearer|token)\b', message):
        return []
    query = public_query(message)
    return [query] if query else []


def assess_evidence(message, sources, selected_books=None, intent=''):
    """Decide si hay respaldo pertinente; no considera una sinopsis prueba universal."""
    requirements = evidence_requirements(message, intent)
    sources = [source for source in sources if isinstance(source, dict)] if isinstance(sources, list) else []
    books = [book for book in (selected_books or []) if work_identity(book)]
    if books:
        relevant = [source for source in sources if any(same_work(source, book) for book in books)]
    else:
        relevant = sources
    candidates = rank_candidates(message, relevant) if 'identification' in requirements else []
    missing = []
    for requirement in requirements:
        enough = False
        if requirement == 'identification':
            enough = (len(candidates) == 1 and candidates[0]['confidence'] == 'supported')
            # Un nombre propio distintivo también basta para proponer, nunca certificar.
            if len(candidates) == 1 and re.search(r'(?i)\b(?:personaje llamado|en que libro aparece)\b', normalize_identity(message)):
                enough = bool(candidates[0]['matched_clues'])
        elif requirement == 'bibliography':
            enough = any(work_identity(source) for source in relevant)
        elif requirement in {'synopsis', 'recommendation', 'comparison'}:
            enough = any(work_identity(source) and len(str(source.get('description') or '').strip()) >= 60 for source in relevant)
            if requirement == 'comparison' and books:
                enough = len(books) >= 2 and all(any(same_work(source, book) and len(str(source.get('description') or '')) >= 60
                                                       for source in relevant) for book in books)
        elif requirement in {'characters', 'character_detail', 'relationships'}:
            for source in relevant:
                text = normalize_identity(source.get('description'))
                raw_facts = source.get('character_facts', [])
                facts = [fact for fact in (raw_facts if isinstance(raw_facts, list) else []) if isinstance(fact, dict)
                         and normalize_identity(fact.get('name')) and normalize_identity(fact.get('name')) in text
                         and normalize_identity(fact.get('role')) and normalize_identity(fact.get('role')) in text]
                if requirement == 'characters' and len(facts) >= 2:
                    enough = True
                if requirement == 'character_detail' and any(normalize_identity(fact['name']) in normalize_identity(message) for fact in facts):
                    enough = True
                if requirement == 'relationships' and any(re.search(r'\b(?:madre|padre|herman|amig|hij|parentesco|relacion)', normalize_identity(fact['role'])) for fact in facts):
                    enough = True
                enough = enough or any(normalize_identity(fact.get('topic') or fact.get('type')) in {
                    requirement, 'personajes' if requirement == 'characters' else requirement} for fact in _grounded_facts(source))
        elif requirement == 'ending':
            enough = any(normalize_identity(fact.get('topic') or fact.get('type')) in
                         {'ending', 'desenlace', 'final'}
                         for source in relevant for fact in _grounded_facts(source))
        elif requirement in {'events', 'scenes', 'content'}:
            for source in relevant:
                facts = _grounded_facts(source)
                # Un acontecimiento sobre otro personaje no cubre la pregunta.
                target = re.search(r'\b(?:con|a)\s+([A-ZÁÉÍÓÚÜÑ][\wáéíóúüñÁÉÍÓÚÜÑ-]{2,}(?:\s+[A-ZÁÉÍÓÚÜÑ][\wáéíóúüñÁÉÍÓÚÜÑ-]+){0,2})', message)
                if target:
                    name = normalize_identity(target.group(1))
                    facts = [fact for fact in facts if name in normalize_identity(
                        str(fact.get('subject') or '') + ' ' + str(fact.get('evidence') or fact.get('text') or ''))]
                enough = enough or any(normalize_identity(fact.get('topic') or fact.get('type')) in {
                    requirement, 'event', 'scene', 'acontecimientos', 'escenas'} for fact in facts)
                if source.get('kind') == 'excerpt' and len(str(source.get('description') or '')) >= 80:
                    clues = [clue for clue in _clues(message) if clue not in VAGUE]
                    words = set(_words(source.get('description', '')))
                    enough = enough or len([clue for clue in clues if _matches(clue, words)]) >= 2
        elif requirement == 'exact_passage':
            enough = any(source.get('kind') == 'excerpt' and source.get('verbatim_verified') is True
                         and source.get('edition') and source.get('description') for source in relevant)
        if not enough:
            missing.append(requirement)
    contradictory = _contradictions(relevant)
    vague = 'identification' in requirements and len([clue for clue in _clues(message) if clue not in VAGUE]) < 2
    named = bool(re.search(r'\b(?:personaje llamado|en que libro aparece)\b', normalize_identity(message)))
    needs_clarification = bool(vague and not named)
    if contradictory and 'contradiction' not in missing:
        missing.append('contradiction')
    return {'sufficient': not missing and not contradictory, 'missing': missing,
            'contradictory': contradictory, 'requirements': requirements,
            'queries': [] if not missing or needs_clarification else public_research_queries(message, books, requirements),
            'needs_clarification': needs_clarification, 'candidates': candidates}
