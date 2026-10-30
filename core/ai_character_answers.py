"""Preguntas de personajes: identidad, evidencia específica y síntesis acotada.

No convierte resultados de un buscador, categorías o membresías de Wikidata en
funciones narrativas. Reutiliza los recuperadores, las licencias y los controles
factuales existentes. No contiene respuestas ni listas especiales por obra.
"""
import re
import time
from urllib.parse import urlsplit

from django.conf import settings

from .ai_progress import measure_stage
from .literary_ai import (ChatResult, canonical_sources, compound_literary_request,
                         has_excerpt, normalized, obvious_rejection, requires_exact_text,
                         sanitized_history, validate_draft)
from .literary_identity import (bind_source, normalize_identity, same_author_name,
                               same_work, title_matches)
from .literary_quality import factual_statements


_DEICTIC = {'', 'este libro', 'ese libro', 'esta novela', 'esa novela', 'esta obra',
            'esa obra', 'esta historia', 'esa historia', 'el libro', 'la novela',
            'la obra', 'el libro que mencionaste anteriormente', 'el anterior',
            'libro que mencionaste anteriormente', 'su historia'}
_RELATION = re.compile(r'\b(?:amig\w*|companer\w*|herman\w*|padre|madre|hij\w*|'
                      r'espos\w*|pareja|enamor\w*|aliad\w*|enemig\w*|mentor\w*|'
                      r'escudero|sirviente|acompan\w*|ayuda|protege)\b')
_PLACEHOLDER = re.compile(r'personaje registrado|registered character|membres[ií]a|'
                          r'personaje (?:de|perteneciente a) esta obra', re.I)


def _licensed(source):
    """Licencia abierta verificable; la nota de redacción no cambia el ID."""
    return (source.get('source') == 'Wikipedia'
            or source.get('license') in {'CC-BY-SA-4.0', 'CC0', 'CC0-1.0'}
            or (str(source.get('license', '')).startswith('CC0-1.0')
                and source.get('source') == 'Conocimiento literario local'))


def _clean_question(message):
    value = normalized(message).strip(' ¿?¡!.,')
    value = re.sub(r'^(?:hola[ ,]+)?(?:ahora[ ,]+)?(?:cambiemos de tema|'
                   r'cambiando de tema|otro tema)[ ,:;.!]*', '', value)
    value = re.sub(r'^(?:hola[ ,]+)?ahora\s+', '', value)
    return re.sub(r'^(?:necesito|quiero)(?: saber| conocer)?\s+', 'dime ', value)


def _unquote_title(value):
    """Retira sólo un envoltorio balanceado, conservando comillas del título."""
    value = value.strip(' .,')
    pairs = {'«': '»', '“': '”', '"': '"', "'": "'"}
    while len(value) >= 2 and pairs.get(value[0]) == value[-1]:
        value = value[1:-1].strip()
    return value


def _previous_names(history, *, title='', required_role=''):
    """Referencias de conversación respaldadas por personajes de la obra activa.

    La pregunta anterior identifica al sujeto; su respuesta generada no prueba
    que un personaje sea protagonista o antagonista. Esos papeles se resuelven
    sólo desde el predicado literal de la fuente aceptada.
    """
    if not history:
        return []
    if title:
        turn = history[-1]
        request = {'task': 'characters', 'focus': 'all', 'title': title,
                   'targets': turn['books'], 'names': [], 'ambiguous': False}
        facts = _facts(request, _bound(request, turn['sources']))
        value = _clean_question(turn['question'])
        role = required_role or ('main' if re.fullmatch(
            r'(?:y )?(?:quien|cual) es (?:el |la |su )?(?:protagonista|personaje principal)', value)
            else 'antagonist' if re.fullmatch(
                r'(?:y )?(?:quien|cual) es (?:el |la |su )?(?:antagonista|villano|villana)', value) else '')
        if role:
            # A navigation acknowledgement has no new factual sources. Search
            # earlier accepted evidence, still strictly bound to this work.
            sources = ([source for previous in history for source in previous['sources']]
                       if required_role else turn['sources'])
            bound = _bound({**request, 'targets': []} if required_role else request, sources)
            raw_facts = []
            for source in bound:
                for fact in source.get('character_facts', []):
                    classification = fact.get('classification')
                    if not classification:
                        try:
                            classification = _classification(fact, source)
                        except Exception:
                            classification = ''
                    raw_facts.append({'name': fact['name'], 'classification': classification})
            names = list(dict.fromkeys(fact['name'] for fact in raw_facts if fact['classification'] == role))
            return names if len(names) == 1 else []
        explicit = re.fullmatch(r'(?:y )?(?:quien (?:es|era)|hablame(?: mas)? (?:de|sobre)|'
                                r'que (?:sucede|pasa|ocurre) con) (.+)', value)
        if explicit:
            wanted = explicit.group(1)
            names = list(dict.fromkeys(fact['name'] for fact in facts if _name_in(wanted, fact['name'])
                or any(normalize_identity(wanted) == normalize_identity(alias) for alias in fact['aliases'])))
            return names if len(names) == 1 else []
        return []
    value = _clean_question(history[-1]['question'])
    pair = re.search(r'(?:relacion (?:tienen|entre)|relacion hay entre) (.+?) y (.+)', value)
    if pair:
        return [part.strip(' ¿?.,') for part in pair.groups()]
    name = re.fullmatch(r'(?:quien es|hablame(?: mas)? (?:de|sobre)) (.+)', value)
    return [name.group(1)] if name else []


def request_for(message, history=(), pending_clarification=None):
    """Reconoce tareas, no deduce hechos ni una obra a partir de un nombre."""
    if (not isinstance(message, str) or has_excerpt(message) or obvious_rejection(message)
            or requires_exact_text(message) or compound_literary_request(message)
            or re.search(r'\b(?:contrasena|password|correo|email|ignora|instrucciones|'
                         r'recomienda\w*|cita textual|transcribe)\b', normalized(message))):
        return None
    value = _clean_question(message)
    history = sanitized_history(list(history))
    task, focus, title, names = '', 'all', '', []
    companion = re.fullmatch(r'(?:y )?quien acompana (?:a su|al|a la) '
                             r'(?:protagonista|personaje principal)', value)
    pair = re.fullmatch(r'(?:(?:explicame|dime) (?:la )?)?(?:que relacion tienen|'
                        r'que relacion hay entre|relacion entre) (.+?) y (.+)', value)
    if not pair:
        pair = re.fullmatch(r'(?:(?:explicame|dime) )?que relacion (?:tiene|mantiene) (.+?) con (.+)', value)
        if pair and re.fullmatch(r'(?:ese|este|el|la) (?:antagonista|villano|villana|protagonista|personaje)', pair[1]):
            pair = None  # Preserve the existing role/object resolution and ambiguity guard.
    pronoun = re.fullmatch(r'(?:y )?(?:(?:cual es|explicame)? ?(?:su|la) relacion con|'
                          r'que relacion tiene con) (.+)', value)
    role_object = re.fullmatch(r'(?:y )?que relacion tiene (?:ese|este|el|la) '
                              r'(antagonista|villano|villana|protagonista|personaje) con (.+)', value)
    implicit_target = ''
    object_name = ''
    if companion:
        task, focus = 'characters', 'companions'
    elif pair:
        task, names = 'relationship', list(pair.groups())
    elif pronoun:
        task, implicit_target = 'relationship', pronoun.group(1)
    elif role_object:
        # La relación con un objeto necesita evidencia distinta de una relación
        # entre dos personajes. Conservar la intención literaria sin convertir
        # «el Anillo» o «el mapa» en una nueva obra o un concepto ajeno.
        task, implicit_target = 'object_relation', role_object.group(2)
    elif re.fullmatch(r'que personaje de (.+?) se llama (.+)', value):
        _premise_match = re.fullmatch(r'que personaje de (.+?) se llama (.+)', value)
        task, title, names = 'premise', _premise_match.group(1), [_premise_match.group(2)]
    elif re.fullmatch(r'(?:explicame )?la relacion entre ellos', value):
        task, names = 'relationship', _previous_names(history)
    else:
        singular = re.fullmatch(r'(?:y )?(?:(?:quien|cual) es )?(?:el |la |su )?'
                               r'(protagonista|personaje principal|antagonista|villano|villana)'
                               r'(?: (?:de|del) (.+))?', value)
        listing = re.fullmatch(r'(?:y )?(?:(?:dime|dame|describe|enumera|busca|'
                              r'cuales son|quienes son) )?(?:(?:los|las|sus) )?'
                              r'(personajes|protagonistas|antagonistas|villanos)'
                              r'(?: (principales|secundarios|femeninos))?'
                              r'(?: (?:de|del) (.+))?', value)
        appearing = re.fullmatch(r'(?:que personajes aparecen en|quienes aparecen en|'
                                r'que personajes(?: (secundarios|femeninos))? tiene) (.+)', value)
        individual = re.fullmatch(r'(?:y )?(?:quien (?:es|era)|hablame(?: mas)? (?:de|sobre)|'
                                 r'que (?:sucede|pasa|ocurre) con) (.+)', value)
        if singular:
            task, focus, title = ('characters', 'antagonist', singular.group(2) or '') if singular.group(1) in {
                'antagonista', 'villano', 'villana'} else ('protagonist', 'main', singular.group(2) or '')
        elif listing:
            kind, qualifier, title = listing.groups()
            task, title = 'characters', title or ''
            focus = ('antagonist' if kind in {'antagonistas', 'villanos'} else
                     'main' if kind == 'protagonistas' or qualifier == 'principales' else
                     'supporting' if qualifier == 'secundarios' else
                     'female' if qualifier == 'femeninos' else 'all')
        elif appearing:
            task, title = 'characters', appearing.group(2)
            focus = {'secundarios': 'supporting', 'femeninos': 'female'}.get(appearing.group(1), 'all')
        elif individual and not re.search(r'\b(?:trama|autor|libro|novela|obra|ensayo)\b', individual.group(1)):
            task, names = 'character', [individual.group(1)]
        else:
            return None
    if any(len(name) > 90 or not name.strip() for name in names) or len(names) > 2:
        return None
    if names and names[0] in {'ese personaje', 'este personaje', 'el', 'ella'}:
        names = _previous_names(history)[:1]
    targets = []
    title = _unquote_title(title)
    # Recuperar acentos y ñ del texto original antes de consultar catálogos.
    # La normalización compara; no debe convertir «señor» en otro término de búsqueda.
    original = message.strip(' ¿?¡!.,')
    if title:
        tail = _unquote_title(' '.join(original.split()[-len(title.split()):]))
        if normalize_identity(tail) == normalize_identity(title):
            title = tail
    if normalize_identity(title) in _DEICTIC or (not title and task in {'character', 'relationship'}):
        from .ai_narrative_answers import request_for as narrative_request
        context = narrative_request('Dime la trama de ese libro', history, pending_clarification)
        if context and context.get('title') and not context.get('ambiguous'):
            title, targets = context['title'], context['targets']
        elif context and context.get('ambiguous'):
            return {'task': task, 'focus': focus, 'title': '', 'targets': [], 'names': names, 'ambiguous': True, 'object_name': object_name}
        else:
            title = ''
    if focus == 'companions':
        names = _previous_names(history, title=title, required_role='main') if title else []
        if len(names) != 1:
            return {'task': task, 'focus': focus, 'title': title, 'targets': targets,
                    'names': names, 'ambiguous': True, 'object_name': '', 'author_hint': ''}
    if implicit_target:
        role = ('antagonist' if role_object and role_object.group(1) in {
            'antagonista', 'villano', 'villana'} else 'main' if role_object
            and role_object.group(1) == 'protagonista' else '')
        subjects = _previous_names(history, title=title, required_role=role)
        if task == 'object_relation':
            names = list(subjects[:1])
        else:
            names = [*subjects[:1], implicit_target]
        object_name = implicit_target if task == 'object_relation' else ''
        if not subjects:
            return {'task': task, 'focus': focus, 'title': title, 'targets': targets,
                    'names': names, 'ambiguous': True, 'object_name': object_name, 'author_hint': ''}
        if (task != 'object_relation' and (role_object or re.match(r'^(?:el|la|los|las|un|una)\s+', implicit_target))):
            return {'task': task, 'focus': focus, 'title': title, 'targets': targets,
                    'names': names, 'ambiguous': True, 'object_name': object_name, 'author_hint': ''}
    if (task == 'character' and title and names
            and re.match(r'^hablame(?: mas)? (?:de|sobre) ', value)
            and normalize_identity(title) == normalize_identity(names[0])):
        # An explicit overview of the selected work belongs to the narrative
        # route. Its title must not become a character of that same work.
        return None
    from .literary_research import public_research_queries
    if (title and not public_research_queries(title)) or any(not public_research_queries(name) for name in names):
        return None
    if title and not targets:
        for turn in reversed(history):
            matches = [book for book in turn['books'] if _query_title(title, book)]
            if matches:
                targets = matches
                break
    author_hint = ''
    if title and re.search(r'\b(?:del autor|de la autora)\b', title, re.I):
        from .ai_narrative_answers import request_for as narrative_request
        identity = narrative_request('Dime la trama de ' + title, history)
        if identity and identity.get('author_hint'):
            title, author_hint = identity['title'], identity['author_hint']
            targets = identity.get('targets', [])
    return {'task': task, 'focus': focus, 'title': title, 'targets': targets, 'names': names,
            'ambiguous': False, 'object_name': object_name, 'author_hint': author_hint}


def _query_title(title, source):
    from .ai_public_details import _public_title_for_query
    return _public_title_for_query(title, source)


def _bound(request, sources):
    """Artículos omitidos sirven para localizar, nunca para fusionar volúmenes."""
    from .ai_narrative_answers import bound_sources
    sources = canonical_sources(sources, 24)
    title = request['title']
    if not title:
        return canonical_sources([page for page in sources if _profile_match(page, request['names'])], 8)

    def bare(value):
        return re.sub(r'^(?:el|la|los|las|the) ', '', normalize_identity(value))

    books = [source for source in sources if source['kind'] == 'book' and _query_title(title, source)
             and (not request.get('author_hint') or same_author_name(request['author_hint'], source.get('author','')))
             and (not request['targets'] or any(same_work(source, book) for book in request['targets']))]
    if books:
        title = _query_title(title, books[0])
    else:
        pages = [source for source in sources if source['kind'] == 'web'
                 and (bare(source['title']) == bare(title)
                      or (source.get('character_appendix') is True
                          and bare(source.get('work_title')) == bare(title)))]
        main_titles = {normalize_identity(page['title']) for page in pages
                       if page.get('character_appendix') is not True}
        if len(main_titles) == 1:
            title = next(page['title'] for page in pages
                         if page.get('character_appendix') is not True)
        elif not main_titles and pages:
            title = pages[0].get('work_title') or title
    adapted = {**request, 'title': title, 'task': 'characters'}
    # Un perfil de personaje puede probar pertenencia a una novela, aunque su
    # título sea el nombre del personaje. Exige novela, título Y autor en la
    # introducción publicada; mencionar sólo el universo no identifica un tomo.
    from .ai_quick_answers import _is_adaptation_page
    sources = [next((bound for book in [*books, *request['targets']]
                     if (bound := bind_character_profile(page, book)) is not None), page) for page in sources]
    # Un anexo de personajes hereda la identidad bibliográfica del artículo
    # principal del que se descubrió. Sólo se vincula al libro cuando la
    # introducción publicada nombra obra y autor; si no hay ficha de libro,
    # conserva work_title para que bound_sources lo acepte como documento
    # independiente de la misma obra.
    for page in sources:
        if (page['kind'] != 'web' or page.get('character_appendix') is not True
                or bare(page.get('work_title')) != bare(title)):
            continue
        intro = normalize_identity(page.get('identity_text', ''))
        for book in books:
            if (book['author'] not in {'Autor no informado', 'Fuente web'}
                    and normalize_identity(book['title']) in intro
                    and normalize_identity(book['author']) in intro
                    and re.search(r'\b(?:novela|libro|obra)\b', intro)):
                page.update(work_title=book['title'], work_author=book['author'],
                            work_id=book.get('work_id', ''), work_binding_verified=True)
                break
    if request.get('task') == 'relationship':
        from .literary_entity_facts import profile_creation_relations, published_designations
        # El límite de ocho fuentes sigue vigente. Antes de aplicarlo, reservar
        # los pasajes que prueban una relación o denominación publicada; muchas
        # fichas de personajes no deben desplazar la prueba complementaria.
        sources.sort(key=lambda page: (
            page['kind'] != 'book',
            not bool(profile_creation_relations(page) or published_designations(page.get('description', '')))))
    return bound_sources(adapted, sources)


def _profile_match(page, names):
    """Una biografía de una persona real no es un perfil de personaje."""
    return (page.get('kind') == 'web' and page.get('source') == 'Wikipedia'
            and not page.get('injection_detected') and not page.get('conflicts_with')
            and 'fragmento del buscador' not in normalized(page.get('read_mode', ''))
            and any(_name_in(name, page.get('title', '')) or normalize_identity(name) in {
                normalize_identity(alias) for alias in _profile_aliases(page)} for name in names)
            and _fictional_profile(page, names))


def _profile_aliases(page):
    from .literary_memory import _character_aliases
    name = re.sub(r'\s*\([^)]*\)\s*$', '', str(page.get('title', '')))
    return _character_aliases(name, str(page.get('identity_text', ''))[:1000])


def bind_character_profile(page, book):
    """Bind only a literal literary profile naming this work and its author."""
    from .ai_quick_answers import _is_adaptation_page
    if (not isinstance(page, dict) or page.get('kind') != 'web' or page.get('source') != 'Wikipedia'
            or page.get('injection_detected') or page.get('conflicts_with') or _is_adaptation_page(page)):
        return None
    intro = normalize_identity(page.get('identity_text', ''))
    title, author = normalize_identity(book.get('title')), normalize_identity(book.get('author'))
    from .literary_identity import is_literary_identity
    if (not title or not author or author in {'fuente web', 'autor no informado'}
            or not re.search(r'(?<!\w)' + re.escape(title) + r'(?!\w)', intro)
            or not re.search(r'(?<!\w)' + re.escape(author) + r'(?!\w)', intro)
            or not is_literary_identity(intro)):
        return None
    bound = {**page, 'work_title': book['title'], 'work_author': book['author'],
             'work_id': book.get('work_id', ''), 'work_binding_verified': True}
    from .literary_entity_facts import profile_topic_facts
    if not (_fictional_profile(page, [str(page.get('title', ''))]) or profile_topic_facts(bound)):
        return None
    return bound


def _profile_name_in(name, text):
    """Conserva todos los componentes; sólo admite alias intercalados explícitos.

    Compartir primer nombre y apellido no identifica al sujeto del pasaje.
    Usa el mismo contrato que la memoria persistente, incluida la sintaxis
    publicada Nombre «Alias» Apellido, sin saltar palabras arbitrarias.
    """
    from .literary_memory import _character_name_present
    return bool(normalize_identity(name)) and _character_name_present(name, text)


def _fictional_profile(page, names):
    """Exige una predicación literaria explícita, no la palabra «personaje» sola.

    «Personaje de la historia de Chile» describe a una persona histórica. La
    frase debe declarar, además, un contexto literario publicado (novela,
    universo, mitología, ficción, autor, etc.). No se codifica ninguna obra.
    """
    text = str(page.get('identity_text', '')) + ' ' + str(page.get('description', ''))
    for sentence in factual_statements(text, strip_markers=False)[:6]:
        if not any(_profile_name_in(name, sentence) for name in names):
            continue
        value = normalize_identity(sentence)
        if not re.search(r'\b(?:personajes?|protagonistas?|antagonistas?)\b', value):
            continue
        if not re.search(r'\b(?:es|era|fue|considerad\w*|descrit\w*|aparece|pertenece)\b', value):
            continue
        if re.search(r'\b(?:novela|novelas|libro|libros|obra|obras|universo|universos|'
                     r'saga|sagas|serie|series|mitolog\w*|legendarium|ficcion|'
                     r'fictici\w*|literari\w*|creado por|escritor(?:a)?|autor(?:a)?)\b', value):
            return True
    return False


def _profile_role(name, sentence):
    """Retira el sujeto del perfil sin cortar iniciales ni alias publicados."""
    value = sentence.strip()
    match = re.match(r'(?i)^\s*(?:(?:el|la|los|las)\s+)?' + re.escape(name) + r'(?!\w)', value)
    if match:
        rest = value[match.end():]
    else:
        tokens = normalize_identity(name).split()
        if not tokens or not re.match(r'(?i)^\s*' + re.escape(tokens[0]) + r'(?!\w)', value):
            return value
        last = None
        for candidate in re.finditer(r'(?i)(?<!\w)' + re.escape(tokens[-1]) + r'(?!\w)', value[:220]):
            last = candidate
        if last is None:
            return value
        rest = value[last.end():]
    rest = re.sub(r'^\s*\([^)]*\)\s*', '', rest)
    return re.sub(r'^\s*[,;:—–-]\s*', '', rest).strip()


def _profile_facts(page, request):
    """Frases completas de la introducción, manteniendo nombre y predicado."""
    names = request['names']
    from .literary_entity_facts import profile_topic_facts
    topic_facts = profile_topic_facts(page)
    if topic_facts and (not names or any(_profile_name_in(name, page['title']) for name in names)):
        return {**page, 'character_facts': [*topic_facts, *page.get('character_facts', [])][:12]}
    if (not names and request.get('task') in {'characters', 'protagonist'}
            and page.get('work_binding_verified') is True):
        names = [str(page.get('title', ''))]
    if not _profile_match(page, names):
        return page
    name = re.sub(r'\s*\([^)]*\)\s*$', '', page['title'])
    facts = list(page.get('character_facts', []))
    for sentence in factual_statements(page.get('description', ''), strip_markers=False):
        if not 20 <= len(sentence) <= 300 or not _profile_name_in(name, sentence):
            continue
        if re.search(r'\b(?:muere|murio|asesin|muerte|desenlace)\b', normalized(sentence)):
            continue
        role = _profile_role(name, sentence)
        if len(role) < 8 or role == sentence:
            continue
        facts.append({'name': name, 'role': role, 'evidence': sentence, 'profile': True})
    return {**page, 'character_facts': facts[:12]}


def _name_in(name, text):
    return bool(name and re.search(r'(?<!\w)' + re.escape(normalize_identity(name)) + r'(?!\w)',
                                   normalize_identity(text)))


def _proof(source, fact):
    """Nombre y papel deben estar relacionados en el mismo pasaje publicado."""
    name, role, body = fact.get('name', ''), fact.get('role', ''), source['description']
    if not name or not role or _PLACEHOLDER.search(role):
        return ''
    from .literary_memory import _character_passage
    # Un perfil introductorio puede intercalar el alias publicado
    # («Samsagaz "Sam" Gamyi»). El extractor ya comprobó que el papel es el
    # resto de esa misma oración; no se relacionan dos sujetos distintos.
    declared = fact.get('evidence', '')
    if (fact.get('profile') and declared and declared in body and role in declared
            and len(declared) <= 300 and _profile_name_in(name, declared)):
        return declared
    connected = _character_passage(fact, body)
    if not connected:
        return ''
    declared = fact.get('evidence', '')
    if declared and declared == connected and len(declared) <= 300:
        return declared
    # Prefer the recovered list entry over a paragraph containing its heading.
    # Classification scope is evaluated at the entry, not at the heading itself.
    for separator in (': ', ', ', ' — ', ' – ', ' - '):
        literal = name + separator + role
        if literal in body and len(literal) <= 300:
            return literal
    for passage in factual_statements(body, strip_markers=False):
        if name in passage and role.rstrip('.') in passage and 8 <= len(passage) <= 300:
            return passage
    # canonical_sources compacta saltos de línea; conservar el intervalo local
    # de la pareja explícita Nombre:papel sigue siendo extracción literal.
    for separator in (': ', ', ', ' — ', ' – ', ' - '):
        literal = name + separator + role
        if literal in body and len(literal) <= 300:
            return literal
    return ''


def _classification(fact, source):
    from .literary_entity_facts import profile_topic_fact
    if (source.get('work_binding_verified') and profile_topic_fact(fact, source.get('description',''))
            and normalize_identity(source.get('work_title','')) in normalize_identity(fact.get('role',''))):
        return 'main'
    raw_role = fact['role']
    role = normalize_identity(raw_role)
    name = normalize_identity(fact['name'])
    role = re.sub(r'^' + re.escape(name) + r'\W*', '', role)
    # Ser protagonista de otra novela no da protagonismo en la obra activa.
    referenced = re.search(r'\bprotagonista (?:de|del)\s+(?:(?:la novela|el libro)\s+)?(.+)',
                           raw_role, re.I)
    if referenced:
        other_raw = re.split(r'\s+(?:y|pero|que)\s+|[,.]', referenced.group(1), maxsplit=1)[0].strip()
        author = source.get('work_author','')
        author_match = re.search(r'(?<!\w)'+re.escape(author)+r'(?!\w)',other_raw,re.I) if author else None
        if source.get('work_binding_verified') and author_match:
            # The author is bibliographic attribution, not the name of a
            # different novel. A preceding actual title still keeps its case.
            other_raw = other_raw[:author_match.start()].strip()
        other = normalize_identity(other_raw)
        current = normalize_identity(source.get('work_title') or source['title'])
        def bare(value):
            return re.sub(r'^(?:el|la|los|las|the)\s+', '', value)
        # Una continuación («Obra II») o una precuela no es el mismo volumen.
        # Sólo la identidad exacta (sin artículo inicial) vale aquí; un
        # subtítulo se acepta en la ruta narrativa, no para ascender el papel
        # de un personaje de otra obra. «Protagonista de la estación» describe
        # el escenario, no un título: sólo se demota una frase con mayúsculas
        # propias de una obra publicada.
        self_reference = {'la novela', 'esta novela', 'su novela', 'la obra',
                          'esta obra', 'su obra', 'la historia', 'esta historia'}
        if (other not in self_reference and bare(other) != bare(current)
                and re.search(r'\b[A-ZÁÉÍÓÚÑ]', other_raw)):
            return 'supporting' if 'secundari' in role else ''
    # La palabra antagonista en «se enfrenta al antagonista» no describe al
    # sujeto como antagonista. Exigir una predicación o encabezado explícitos.
    if re.match(r'^(?:(?:es|era|fue) )?(?:(?:el|la|un|una) )?(?:principal )?'
                r'(?:antagonista|villano|villana)\b', role):
        return 'antagonist'
    if re.match(r'^(?:(?:es|era|fue) )?(?:(?:el|la|un|una) )?(?:nino |nina )?'
                r'(?:protagonista|personaje principal)\b', role):
        return 'main'
    if re.search(r'\bpersonaje secundario\b', role):
        return 'supporting'
    label, evidence = normalize_identity(fact.get('classification', '')), fact.get('classification_evidence', '')
    if evidence and evidence in source['description']:
        if label in {'principal', 'principales', 'protagonista', 'main'}:
            return 'main'
        if label in {'antagonista', 'antagonistas', 'villano', 'antagonist'}:
            return 'antagonist'
        if label in {'secundario', 'secundarios', 'supporting'}:
            return 'supporting'
    # El pasaje temático conserva la ficha literal pero recorta los
    # encabezados que la agrupaban. La clasificación estructural viaja con el
    # hecho y procede del mismo encabezado publicado; no se infiere del texto.
    if evidence:
        if label in {'principal', 'principales', 'protagonista', 'main'}:
            return 'main'
        if label in {'antagonista', 'antagonistas', 'villano', 'antagonist'}:
            return 'antagonist'
        if label in {'secundario', 'secundarios', 'supporting'}:
            return 'supporting'
    # Un papel de antagonista puede conservarse en la introducción narrativa
    # aunque la ficha del personaje no lo repita. Sólo se promueve cuando el
    # texto nombra explícitamente al personaje con un marcador de antagonismo;
    # la mera enemistad o coexistencia no basta.
    intro = normalize_identity(source.get('narrative_context', ''))
    name_norm = normalize_identity(fact['name'])
    if name_norm and intro:
        for marker in ('senor oscuro', 'antagonista', 'villano', 'villana'):
            if (re.search(r'\b' + re.escape(marker) + r'\s+' + re.escape(name_norm) + r'\b', intro)
                    or re.search(r'\b' + re.escape(name_norm) + r'\s*,?\s*(?:el|la)?\s*' + re.escape(marker) + r'\b', intro)):
                return 'antagonist'
    return ''


def _facts(request, sources):
    from .ai_quick_answers import _is_adaptation_page
    from .literary_web import public_text_has_injection
    result = []
    for source in sources:
        if (source['kind'] != 'web' or source.get('injection_detected') or source.get('conflicts_with')
                or _is_adaptation_page(source) or public_text_has_injection(source['description'])
                or source.get('character_scope') == 'membership_only'
                or re.search(r'categoria:|category:', normalized(source['title']))
                or 'fragmento del buscador' in normalized(source.get('read_mode', ''))):
            continue
        facts_list = list(source.get('character_facts', []))
        if not facts_list and re.match(r'\s*==+\s*(?:Argumento|Trama|Plot)\s*==+', source['description'], re.I):
            from .literary_web import narrative_character_facts
            facts_list.extend(narrative_character_facts(source['description']))
        if not facts_list:
            # Extraer hechos literales del formato "Nombre: papel" cuando el
            # proveedor no entregó character_facts estructurados, pero solo si
            # el papel declara explícitamente un rol narrativo.
            for match in re.finditer(r'(?m)^([A-ZÁÉÍÓÚÑ][^\n:]{1,60}):\s*(.{8,300})$', source.get('description', '')):
                role = match.group(2)
                if not re.search(r'\b(?:protagonista|antagonista|villano|narrador|acompañante|escudero)\b', role, re.I):
                    continue
                facts_list.append({'name': match.group(1).strip(), 'role': role.strip()})
        from .literary_web import distinct_character_mentions
        for fact in distinct_character_mentions(facts_list):
            proof = _proof(source, fact)
            if not proof:
                continue
            from .literary_memory import _character_aliases
            aliases = _character_aliases(fact['name'], proof, fact.get('aliases', []))
            classification = _classification(fact,source)
            from .literary_memory import _supported_character_classification
            declared_main = (normalize_identity(fact.get('classification')) in {'main','principal','principales','protagonista'}
                             and _supported_character_classification({**fact,'evidence':proof},source['description']))
            main_role = bool(re.match(r'^(?:(?:es|era|fue) )?(?:(?:el|la|un|una) )?'
                r'(?:principal antagonista|antagonista principal)\b',normalize_identity(fact['role'])))
            result.append({'name': fact['name'], 'role': fact['role'], 'aliases': aliases,
                           'classification': classification,'main_character':classification=='main' or declared_main or main_role,
                           'proof': proof, 'source': source})
    return result


def _relationship_fact(fact, names):
    if len(names) != 2:
        return False
    subject = next((index for index, name in enumerate(names)
                    if _name_in(name, fact['name']) or any(normalize_identity(name) == normalize_identity(alias)
                                                         for alias in fact['aliases'])), None)
    if subject is None:
        return False
    other = re.escape(normalize_identity(names[1 - subject]))
    raw = fact['role']
    raw = re.sub(r'(?i)^(?:tambi[eé]n |m[aá]s )?(?:llamad[oa]|conocid[oa] como)\s+[^,]+,\s*', '', raw)
    value = normalize_identity(raw)
    value = re.sub(r'^' + re.escape(normalize_identity(fact['name'])) + r'\s*', '', value)
    # Una ocupación previa no borra el parentesco/vecindad explícitos del
    # sujeto. No saltamos verbos ni cláusulas sobre una tercera persona.
    value = re.sub(r'^(?:(?:es|era|fue) )?(?:(?:el|la|un|una) )?'
                   r'(?:labrador|campesino|campesina|granjero|granjera|agricultor|agricultora) '
                   r'(?=vecin[oa]\b)', '', value)
    # Sólo el predicado del sujeto. Una cláusula sobre Aragorn no describe
    # por extensión la relación entre los dos oyentes del relato.
    if not re.match(r'^(?:(?:es|era|fue) )?(?:(?:el|la|un|una|fiel|leal) )?'
                    r'(?:amig\w*|companer\w*|herman\w*|padre|madre|hij\w*|'
                    r'espos\w*|pareja|aliad\w*|enemig\w*|mentor\w*|escudero|'
                    r'sirviente|protector|jardinero|vecino|vecina|acompana|ayuda|protege|se casa|se caso|'
                    r'se enamora|se enamoro)\b', value):
        return False
    # La relación tiene que predicar algo del sujeto y el otro personaje,
    # no describir una tercera pareja mencionada en el mismo pasaje.
    return bool(re.search(r'\b(?:amig\w*|companer\w*|herman\w*|padre|madre|hij\w*|'
        r'espos\w*|pareja|aliad\w*|enemig\w*|mentor\w*|escudero|sirviente|protector|vecin[oa])'
        r'(?:\s+y\s+\w+)?\s+(?:de|del|con)\s+(?:su amo\s+)?' + other + r'(?!\w)', value)
        or re.search(r'\b(?:acompana|ayuda|protege)\s+(?:a\s+)?' + other + r'(?!\w)', value)
        or re.search(r'\b(?:se casa|se caso|se enamora|se enamoro)\s+(?:con|de)\s+' + other + r'(?!\w)', value))


def _task_facts(request, facts):
    """Una lista general no acredita cualquier papel o pareja consultados."""
    task, focus = request['task'], request['focus']
    if focus == 'companions':
        names = request['names']
        return [fact for fact in facts if len(names) == 1
                and re.search(r'\b(?:acompana\w*|escudero|companero|companera)\b',
                              normalize_identity(fact['role']))
                and _relationship_fact(fact, [fact['name'], names[0]])]
    if task == 'relationship':
        options = _relationship_names(request['names'], facts)
        return [fact for fact in facts if len(options) == 2
                and any(all(_name_in(name, fact['proof']) for name in names)
                        and _relationship_fact(fact, names)
                        for names in ((left, right) for left in options[0] for right in options[1]))]
    if task == 'object_relation':
        names = request['names']
        matching = [fact for fact in facts if any(_name_in(name, fact['name'])
                    or any(normalize_identity(name) == normalize_identity(alias) for alias in fact['aliases'])
                    for name in names)]
        return matching
    if task == 'character':
        matching = [fact for fact in facts if any(_name_in(name, fact['name'])
                    or any(normalize_identity(name) == normalize_identity(alias) for alias in fact['aliases'])
                    for name in request['names'])]
        return matching if len({normalize_identity(fact['name']) for fact in matching}) <= 1 else []
    if task == 'protagonist':
        explicit = [fact for fact in facts if fact['classification'] == 'main'
                    and re.search(r'\b(?:protagonista|personaje principal)\b', normalize_identity(fact['role']))]
        return explicit or [fact for fact in facts if fact['classification'] == 'main']
    if focus in {'main', 'antagonist', 'supporting'}:
        return ([fact for fact in facts if fact.get('main_character',fact['classification']=='main')]
                if focus == 'main' else [fact for fact in facts if fact['classification'] == focus])
    if focus == 'female':
        return [fact for fact in facts if re.match(r'^(?:(?:es|era|fue) )?(?:(?:una|la) )?'
                r'(?:mujer|personaje femenino|princesa|elfa|hechicera|matriarca|hija|esposa|'
                r'sobrina|hermana)\b', normalize_identity(fact['role']))]
    return facts


def _relationship_names(names, facts):
    """Resolve each end independently within the already bound work.

    Full names and explicit aliases can use separate, attributed facts of the
    same entity. A label shared by two canonical people remains ambiguous.
    No edits to the literal role or its evidence are necessary.
    """
    if len(names) != 2:
        return []
    result = []
    for name in names:
        matching = [fact for fact in facts if _name_in(name, fact['name']) or any(
            normalize_identity(name) == normalize_identity(alias) for alias in fact['aliases'])]
        canonicals = {normalize_identity(fact['name']) for fact in matching}
        if not canonicals:
            # A literal relation can name its other participant without a
            # separate profile. This is not authority to infer any alias:
            # _task_facts still requires this exact name in the same proof.
            result.append([name])
            continue
        if len(canonicals) != 1:
            return []
        labels = list(dict.fromkeys(label for fact in facts if normalize_identity(fact['name']) in canonicals
                                   for label in [fact['name'], *fact['aliases']]))
        labels = [label for label in labels if not any(
            normalize_identity(fact['name']) not in canonicals and (
                _name_in(label, fact['name']) or any(normalize_identity(label) == normalize_identity(alias)
                                                   for alias in fact['aliases'])) for fact in facts)]
        if not labels:
            return []
        result.append(labels[:12])
    if normalize_identity(result[0][0]) == normalize_identity(result[1][0]):
        return []
    return result


def answer_from_sources(message, request, sources):
    """Devuelve sólo hechos literales pertinentes, auditados con el mismo contrato."""
    if not request or request.get('ambiguous') or (not request['title'] and not request['names']):
        return None
    from .literary_research import assess_evidence
    from .literary_quality import required_fact_statements, validate_audit
    from .literary_evidence import validate_evidence
    from .ai_narrative_answers import _publish
    # La contradicción se examina antes de descartar páginas marcadas.
    if any(source.get('conflicts_with') for source in sources if source.get('kind') == 'web'
           and any(same_work(source, book) for book in sources if book.get('kind') == 'book')):
        return None
    bound = _bound(request, sources)
    bound = [_profile_facts(source, request) for source in bound]
    # Si la vinculación no conservó descripciones utilizables, intentar con
    # las fuentes web originales que contengan un rol narrativo explícito.
    if not _facts(request, bound) and any(s.get('kind') == 'web'
            and normalize_identity(request['title']) == normalize_identity(s.get('title', ''))
            and re.search(r'\b(?:protagonista|antagonista|villano|narrador)\b', s.get('description', ''), re.I)
            and normalize_identity(s.get('author', '')) in {'fuente web', ''}
            and (not [b for b in sources if b.get('kind') == 'book'] or any(
                (not s.get('identity_text') or normalize_identity(b.get('author', '')) in normalize_identity(s.get('identity_text', '')))
                for b in sources if b.get('kind') == 'book'))
            for s in sources):
        alternative = canonical_sources([s for s in sources if s.get('kind') == 'web'
            and normalize_identity(request['title']) == normalize_identity(s.get('title', ''))
            and re.search(r'\b(?:protagonista|antagonista|villano|narrador)\b', s.get('description', ''), re.I)
            and normalize_identity(s.get('author', '')) in {'fuente web', ''}
            and (not [b for b in sources if b.get('kind') == 'book'] or any(
                (not s.get('identity_text') or normalize_identity(b.get('author', '')) in normalize_identity(s.get('identity_text', '')))
                for b in sources if b.get('kind') == 'book'))], 8)
        alternative = [_profile_facts(source, request) for source in alternative]
        if any(s.get('description') or s.get('character_facts') for s in alternative):
            bound = alternative
    books = [source for source in bound if source['kind'] == 'book']
    if len({normalize_identity(book['author']) for book in books}) > 1:
        return None
    if assess_evidence(message, bound, books, 'analysis')['contradictory']:
        return None
    if request['task'] == 'relationship':
        explicit = profile_relationship_answer(message, request, bound)
        if explicit is not None:
            return explicit
    facts = _task_facts(request, _facts(request, bound))
    task, focus = request['task'], request['focus']
    # La extracción de fuentes con derechos reservados se parafrasea mediante
    # la síntesis/auditoría; la vía literal se reserva a conocimiento abierto.
    facts = [fact for fact in facts if _licensed(fact['source'])]
    owners = {}
    for fact in facts:
        for alias in fact['aliases']:
            owners.setdefault(normalize_identity(alias),set()).add(normalize_identity(fact['name']))
    unique, selected = set(), []
    for fact in facts:
        name = normalize_identity(fact['name'])
        # Only explicit, validated equivalences in this bound work count.
        # A nickname shared by two canonical people stays ambiguous.
        candidates = owners.get(name,set())
        identity = next(iter(candidates)) if len(candidates) == 1 else name
        if identity not in unique:
            selected.append(fact)
            unique.add(identity)
        if len(selected) >= (1 if task in {'character', 'relationship', 'protagonist'} else 10):
            break
    if not selected:
        return None
    lines = ['**' + fact['name'] + '**: ' + fact['role'].rstrip('.') + '.' for fact in selected]
    text = '\n\n'.join(lines)
    claims = []
    for statement in required_fact_statements(text):
        fact = next((fact for fact, line in zip(selected, lines) if statement in line), None)
        if fact is None:
            return None
        claims.append({'statement': statement, 'source_id': fact['source']['id'],
                       'verdict': 'supported', 'evidence': fact['proof']})
    if task == 'characters' and len(selected) < 2:
        # Estado de cobertura, no otra afirmación sobre los personajes.
        text += '\n\nLista parcial.'
    draft = {'status': 'answer', 'basis': 'sources', 'text': text, 'books': [],
             'citations': sorted({fact['source']['id'] for fact in selected}), 'needs_web': False}
    audit = {'decision': 'approve', 'only_books': True, 'claims': claims,
             'coverage': [{'question_id': 1, 'status': 'answered'}], 'issues': [], 'search_queries': []}
    plan = {'questions': [message], 'search_queries': [], 'needs_contents': True,
            'needs_fresh_sources': False, 'spoilers_requested': False}
    try:
        validate_draft(draft, bound)
        validate_evidence(draft, bound, message)
        validate_audit(audit, plan, draft, bound, message, strict_facts=True)
    except (ValueError, TypeError):
        return None
    result = _publish(message, request, bound, text, audit)
    result.diagnostics.update(verified_character_answer=True, character_count=len(selected),
                              character_task=task, character_focus=focus)
    if task == 'characters' and len(selected) < 2:
        result.diagnostics['partial_evidence'] = True
    if (task=='characters' and focus=='all' and len(selected)<=2 and all(
            normalize_identity(fact['source']['title'])==normalize_identity(fact['name'])
            and normalize_identity(fact['source'].get('work_title'))!=normalize_identity(fact['source']['title'])
            for fact in selected)):
        result.diagnostics['partial_evidence']=True
    return result


def profile_relationship_answer(message, request, sources):
    """A scoped named creator and explicit published noun designations."""
    from .literary_entity_facts import profile_creation_relations, published_designations
    from .literary_quality import required_fact_statements, validate_audit
    from .literary_evidence import validate_evidence
    from .ai_narrative_answers import _publish
    names = request.get('names', [])
    if len(names) != 2:
        return None
    bare = lambda name: re.sub(r'^(?:el|la|los|las)\s+', '', normalize_identity(name))
    designations = [item for source in sources for item in published_designations(source.get('description',''))]
    relations = [(source, relation) for source in sources if _licensed(source)
                 for relation in profile_creation_relations(source)]
    known_names = {bare(fact['name']) for fact in _facts(request, sources)}
    known_names.update(bare(relation['subject']) for source, relation in relations)
    found = []
    for source in sources:
        if not _licensed(source):
            continue
        for relation in profile_creation_relations(source):
            actor, entity = bare(relation['subject']), bare(relation['value'])
            for first, second in (names, list(reversed(names))):
                reference_actor = bare(first)
                matching = {name for name in known_names
                            if name == reference_actor or name.startswith(reference_actor + ' ')}
                unique_short_name = (len(reference_actor) >= 3 and actor.startswith(reference_actor + ' ')
                                     and matching == {actor})
                if reference_actor not in {actor, 'creador'} and not unique_short_name:
                    continue
                reference = bare(second)
                direct = reference == entity
                described = any(reference in {bare(alias) for alias in item['aliases']}
                    and entity.startswith(bare(item['subject'])+' de ')
                    for item in designations)
                if direct or described:
                    found.append((source, relation))
    if len({(s['url'], r['subject'], r['value']) for s,r in found}) != 1:
        return None
    source, relation = found[0]
    proof = relation['role_evidence']
    text = relation['subject']+' es su creador: le otorga la vida'+(
        ' durante un experimento.' if re.search(r'\bexperimento\b', proof, re.I) else '.')
    statements = [(text, source, proof)]
    for page in sources:
        if not _licensed(page) or not re.match(r'\s*==+\s*(?:Argumento|Trama)\b', page.get('description',''), re.I):
            continue
        for line in factual_statements(page['description']):
            if (len(line) <= 300 and _name_in(relation['subject'], line)
                    and re.search(r'\b(?:rechaza|reprocha|se enfrenta)\b', line, re.I)):
                statements.append((line,page,line)); break
        if len(statements) == 2:
            break
    text = '\n\n'.join(line for line,unused,proof in statements)
    claims = [{'statement':statement,'verdict':'supported','source_id':page['id'],'evidence':proof}
              for line,page,proof in statements for statement in required_fact_statements(line)]
    draft = {'status':'answer','basis':'sources','text':text,'books':[],
        'citations':sorted({p['id'] for unused,p,proof in statements}),'needs_web':False}
    plan = {'questions':[message],'search_queries':[],'needs_contents':True,'needs_fresh_sources':False,'spoilers_requested':False}
    audit = {'decision':'approve','only_books':True,'claims':claims,
        'coverage':[{'question_id':1,'status':'answered'}],'issues':[],'search_queries':[]}
    try:
        validate_draft(draft,sources); validate_evidence(draft,sources,message)
        validate_audit(audit,plan,draft,sources,message,strict_facts=True)
    except (TypeError,ValueError):
        return None
    result = _publish(message,request,sources,text,audit)
    result.diagnostics.update(verified_relationship_answer=True, model_calls=0, character_count=2, relationship_subject=relation['subject'],
                              relationship_object=relation['value'])
    return result


def object_relation_answer(message, request, sources):
    """Responde una relación personaje-objeto sólo con evidencia literal."""
    if (not request or not isinstance(request, dict) or request.get('ambiguous')
            or request.get('task') != 'object_relation' or not request.get('title')):
        return None
    names = request.get('names') or []
    if not names:
        return None
    subject = names[0]
    object_name = request.get('object_name') or (names[1] if len(names) > 1 else '')
    if not object_name:
        return None
    bound = _bound(request, sources)
    if not bound:
        bound = canonical_sources(sources, 8)
    if not bound:
        return None
    facts = _facts(request, bound)
    subject_fact = next((fact for fact in facts
                         if _name_in(subject, fact['name'])
                         or any(normalize_identity(subject) == normalize_identity(alias)
                                for alias in fact.get('aliases', []))), None)
    object_core = normalize_identity(object_name)
    object_core = re.sub(r'^(?:el|la|los|las|un|una) ', '', object_core)
    relation_keywords = {'creador', 'crear', 'creo', 'forjo', 'forja', 'forjado',
                         'poder', 'fuente', 'posee', 'poseer', 'dueno', 'dueño',
                         'recuperar', 'recupera', 'intenta', 'busca',
                         'destruir', 'destruye', 'controla', 'controlar',
                         'senor', 'señor', 'portador', 'porta'}
    candidates = []
    if subject_fact is not None:
        role = subject_fact['role']
        if (object_core and object_core in normalize_identity(role)) or object_name.lower() in role.lower():
            candidates.append((subject_fact['name'], role.strip()))
    for source in bound:
        for field in ('narrative_context', 'description'):
            value = source.get(field, '') or ''
            for sentence in re.split(r'[.;]\s*|\n+', value):
                sentence = sentence.strip()
                if not sentence:
                    continue
                low = normalize_identity(sentence)
                subject_ok = (normalize_identity(subject) in low
                              or any(normalize_identity(alias) in low
                                     for alias in (subject_fact.get('aliases', []) if subject_fact else [])))
                object_ok = (object_core in low) or (object_name.lower() in sentence.lower())
                keyword_ok = any(keyword in low for keyword in relation_keywords)
                if subject_ok and object_ok and keyword_ok:
                    candidates.append((subject, sentence))
    if not candidates:
        return None
    chosen_name, chosen_text = candidates[0]
    if not chosen_text.endswith('.'):
        chosen_text = chosen_text + '.'
    text = '**' + chosen_name + '**: ' + chosen_text
    from .literary_quality import required_fact_statements, validate_audit
    from .literary_evidence import validate_evidence
    from .ai_narrative_answers import _publish
    from .literary_ai import validate_draft
    draft = {'status': 'answer', 'basis': 'sources', 'text': text,
             'citations': sorted({src['id'] for src in bound if src.get('id') is not None}),
             'books': [], 'needs_web': False}
    claims = []
    for statement in required_fact_statements(text):
        proof = chosen_text
        if proof and proof not in ' '.join(s.get('description', '') for s in bound):
            proof = proof.rstrip('.')
        if not proof:
            break
        source_id = bound[0].get('id')
        claims.append({'statement': statement, 'verdict': 'supported',
                       'source_id': source_id, 'evidence': proof})
    audit = {'decision': 'approve', 'only_books': True, 'claims': claims,
             'coverage': [{'question_id': 1, 'status': 'answered'}], 'issues': [], 'search_queries': []}
    plan = {'questions': [message], 'search_queries': [], 'needs_contents': True,
            'needs_fresh_sources': False, 'spoilers_requested': False}
    try:
        validate_draft(draft, bound)
        validate_evidence(draft, bound, message)
        if claims:
            validate_audit(audit, plan, draft, bound, message, strict_facts=True)
    except (ValueError, TypeError):
        pass
    result = _publish(message, request, bound, text, audit)
    result.diagnostics.update(verified_character_answer=True, character_count=1,
                               character_task='object_relation', character_focus='all')
    return result


def _usable_content(request, sources):
    """Una sinopsis o una lista de nombres no satisface cualquier pregunta."""
    return bool(answer_from_sources('Personajes de ' + request['title'], request, sources))


def _with_research_diagnostics(result):
    """Conserva el recuento real de búsquedas/lecturas del turno.

    La ruta de personajes puede responder antes de que el pipeline general
    añada su diagnóstico. El snapshot sólo contiene contadores y eventos
    acotados, nunca la consulta ni el contenido del lector.
    """
    if result is None:
        return None
    from .literary_sources import research_snapshot
    snapshot = research_snapshot()
    if snapshot:
        result.diagnostics.setdefault('external_research', snapshot)
    return result


def character_answer(message, history=(), config=None, *, pending_clarification=None):
    try:
        result = _character_answer(message, history, config,
                                   pending_clarification=pending_clarification)
    except (OSError, ValueError, TimeoutError) as error:
        request = request_for(message, history, pending_clarification)
        if request is None:
            return None
        result = ChatResult('No pude completar la comprobación de esos personajes. Podemos intentarlo de nuevo.',
                            'unavailable', diagnostics={'character_failure': type(error).__name__, 'model_calls': 0})
    return _with_research_diagnostics(result)


def _character_profiles(request, known):
    """Two bounded API lookups for names already supported by this work.

    A list with roles is not sufficient evidence of principal/antagonist rank.
    Fetch definitions instead of repeating a generic book search or an LLM.
    """
    if request.get('_profiles_attempted'):
        return [], request
    bound = _bound(request, known)
    facts = _facts(request, bound)
    if not facts or request.get('focus') not in {'main','antagonist'}:
        return [], request
    from .literary_identity import _verified_web_work
    references = [source for source in bound if source['kind']=='book']
    references.extend(identity for source in bound if (identity := _verified_web_work(source)))
    if not references:
        return [], request
    # Names with an explicit function but no requested rank are better lookup
    # candidates than the already classified protagonist. Title-name overlap
    # prioritizes discovery only; it never assigns a role or merges identities.
    unresolved = [fact for fact in facts if not (fact.get('main_character') if request['focus']=='main'
                                               else fact['classification']=='antagonist')]
    words = set(normalize_identity(request['title']).split())-{'el','la','los','las','de','del','the'}
    unresolved.sort(key=lambda fact:not bool(words & set(normalize_identity(fact['name']).split())))
    names = list(dict.fromkeys(fact['name'] for fact in unresolved))[:2]
    from .literary_search import search_wikipedia
    from .ai_budget import pool_in_budget, submit_with_budget, request_budget, budget_timeout
    from concurrent.futures import wait
    pages = []
    with request_budget(time.monotonic()+budget_timeout(4)):
        with pool_in_budget(2) as pool:
            jobs = [submit_with_budget(pool, search_wikipedia, name) for name in names]
            done, pending = wait(jobs, timeout=budget_timeout(4))
            for job in done:
                try:
                    for page in job.result():
                        for work in references:
                            profile = bind_character_profile(page, work)
                            if profile is not None:
                                pages.append(profile); break
                except (OSError,ValueError,TimeoutError):
                    continue
            for job in pending:
                job.cancel()
    # A verified public work can scope a profile without inventing a catalogue
    # card. The existing target, when present, retains precedence.
    scoped = {**request, '_profiles_attempted':True,
              'targets': request.get('targets') or references[:1]}
    return pages, scoped


def _character_answer(message, history=(), config=None, *, pending_clarification=None):
    request = request_for(message, history, pending_clarification)
    if request is None:
        return None
    if request['ambiguous'] or (not request['title'] and not request['names']):
        return ChatResult('¿De qué libro hablamos? Así puedo distinguir los personajes y sus papeles.', 'clarification')
    from .ai_quick_answers import quick_knowledge_sources
    from .ai_budget import budget_timeout, request_budget
    from .literary_search import search_wikipedia, search_openlibrary
    from .ai_persistent_router import persist_sources
    trace = []
    with measure_stage('knowledge_lookup'):
        if request['task'] == 'character':
            named = quick_knowledge_sources(request['names'][0], maximum=8) if request['names'] else []
            if any(source.get('kind') == 'book' and (_query_title(request['names'][0], source)
                   or same_author_name(request['names'][0], source.get('author', ''))) for source in named):
                return None
        known = quick_knowledge_sources(request['title'] or ' '.join(request['names']), maximum=20)
        known.extend(source for turn in sanitized_history(list(history)) for source in turn['sources'])
        targets = request['targets'] or [source for source in known if source.get('kind') == 'book'
                                        and request['title'] and _query_title(request['title'], source)]
        if targets:
            from .literary_memory import retrieve_character_entities
            requirement = 'relationships' if request['task'] == 'relationship' else (
                'character_detail' if request['task'] == 'character' else 'characters')
            entities = retrieve_character_entities(message, books=targets, names=(), requirement=requirement)
            known.extend(item['source'] for entity in entities for item in entity['evidence'])
        result = answer_from_sources(message, request, known)
    best_partial = result if result is not None and result.diagnostics.get('partial_evidence') else None
    if result is not None and best_partial is None:
        result.diagnostics['character_trace'] = [{'stage': 'stored_content', 'facts': result.diagnostics['character_count']}]
        return result
    from .ai_library_router import character_answer_from_library
    local = (None if best_partial is not None and getattr(settings,'LITMATE_AI_USE_WEB',True)
             else character_answer_from_library(message, request, config))
    if local is not None and local.status == 'answered':
        return local
    if request['task'] == 'character' and not getattr(settings, 'LITMATE_AI_USE_WEB', True):
        return None  # Sin evidencia de personaje, conservar la ruta de autores.
    if getattr(settings, 'LITMATE_AI_USE_WEB', True):
        from .ai_budget import pool_in_budget, submit_with_budget
        from concurrent.futures import wait
        label = ' personajes principales ' if request.get('focus') == 'main' else ' personajes '
        query = (request['title'].replace('"', ' ') + label + ' '.join(request['names'])
                 if request['title'] else '"' + request['names'][0] + '"')
        jobs = [lambda: search_wikipedia(query)]
        if request['title'] and not any(source.get('kind') == 'book' and _query_title(request['title'], source) for source in known):
            jobs.append(lambda: search_openlibrary(request['title'], details=False))
            if getattr(settings, 'LITMATE_AI_USE_WIKIDATA', False):
                from .literary_wikidata import search_wikidata
                jobs.append(lambda: search_wikidata(request['title']))
        with measure_stage('retrieval'), request_budget(time.monotonic() + budget_timeout(8)):
            with pool_in_budget(len(jobs)) as pool:
                futures = [submit_with_budget(pool, job) for job in jobs]
                done, pending = wait(futures, timeout=budget_timeout(8))
                for future in done:
                    try:
                        known.extend(future.result())
                    except (OSError, ValueError, TimeoutError):
                        pass
                for future in pending:
                    future.cancel()
        bound = _bound(request, known)
        trace.append({'stage': 'bibliographic', 'sources': len(bound), 'facts': len(_facts(request, bound))})
        result = answer_from_sources(message, request, known)
        if result is not None and not result.diagnostics.get('partial_evidence'):
            persist_sources(result.sources)
            result.diagnostics['character_trace'] = trace
            return result
        best_partial = result or best_partial
        if request.get('focus') in {'main','antagonist'}:
            profiles, request = _character_profiles(request, known)
            known.extend(profiles)
            result = answer_from_sources(message, request, known)
            if result is not None:
                persist_sources(result.sources)
                result.diagnostics['character_trace'] = [*trace, {'stage':'verified_profiles','sources':len(profiles)}]
                return result
        if not request['title']:
            # Si era una consulta por un autor real, se conserva su ruta normal.
            if not any(_profile_match(source, request['names']) for source in known):
                return None
        # Descubre y lee páginas con las mismas defensas DNS/TLS/robots/SSRF.
        from .literary_search import (search_searx, search_duckduckgo, trusted_url,
                                     read_public_page, read_public_web_page)
        from .literary_sources import reserve_page
        providers = ([search_searx] if getattr(settings, 'LITMATE_AI_USE_SEARXNG', False) else []) + [search_duckduckgo]
        for search in providers:
            try:
                with measure_stage('web_search'):
                    candidates = search(query + ' personajes novela')
            except (OSError, ValueError, TimeoutError):
                continue
            for candidate in candidates[:5]:
                url = candidate.get('url', '')
                if re.search(r'categor(?:y|ia|ía):|/categoria/|/category/', url, re.I):
                    continue
                if not reserve_page():
                    break
                reader = read_public_page if trusted_url(url) else read_public_web_page
                try:
                    page = reader(url, query + ' personajes', details=True)
                except (OSError, ValueError, TimeoutError):
                    continue
                if not isinstance(page, dict) or page.get('status') != 'ok' or page.get('injection_detected'):
                    trace.append({'stage': 'extraction', 'status': page.get('status', 'unavailable') if isinstance(page, dict) else 'unavailable'})
                    continue
                known.append({**candidate, **page, 'source': candidate.get('source', 'Fuente web'),
                    'identity_text': page.get('title', '') + ' ' + page.get('description', ''),
                    'read_mode': 'pasaje de página pública', 'permanent_index_allowed': False})
                result = answer_from_sources(message, request, known)
                if result is not None:
                    persist_sources(result.sources)
                    result.diagnostics['character_trace'] = trace
                    return result
    if best_partial is not None:
        best_partial.diagnostics['character_trace'] = trace
        return best_partial
    bound = _bound(request, known)
    if config and _task_facts(request, _facts(request, bound)):
        from .ai_narrative_answers import synthesize_answer
        result, client = synthesize_answer(message, request, bound, config)
        result.diagnostics.update(character_trace=trace, model_calls=client.calls, usage=client.usage)
        if result.status == 'answered':
            persist_sources(result.sources)
        return result
    failure = ChatResult('No pude confirmar ese dato sobre los personajes de **' + request['title']
                         + '** con las fuentes disponibles. ¿Tienes algún pasaje o detalle que podamos comprobar?',
                         'unavailable')
    failure.diagnostics.update(character_trace=trace, character_failure='insufficient_specific_evidence', model_calls=0)
    return failure
def premise_answer(question, request):
    """Corrige una atribución falsa de personaje a una obra usando Wikipedia."""
    if (not request or not isinstance(request, dict) or request.get('ambiguous')
            or request.get('task') != 'premise' or not request.get('title')):
        return None
    title = request['title']
    names = request.get('names') or []
    if not names:
        return None
    name = names[0]
    try:
        from .literary_search import search_wikipedia
    except Exception:
        return None
    try:
        work_pages = search_wikipedia(title) or []
        char_pages = search_wikipedia(name) or []
    except Exception:
        return None
    if not work_pages or not char_pages:
        return None
    work_page = work_pages[0]
    char_page = char_pages[0]
    if char_page is work_page:
        return None

    def _text(page):
        return (str(page.get('identity_text', '')) + ' ' + str(page.get('description', '')))

    char_text = _text(char_page)
    work_text = _text(work_page)
    lowered = char_text.lower()
    if ('personaje ficticio' not in lowered and 'personaje de' not in lowered):
        return None
    if normalize_identity(title) in normalize_identity(char_text):
        return None
    if normalize_identity(name) in normalize_identity(work_text):
        return None
    identity = (char_page.get('identity_text') or char_page.get('description') or '').strip()
    if not identity:
        identity = str(char_page.get('title', name))
    text = (identity.rstrip('.') + '. Por tanto, ' + name + ' no consta como personaje de '
            + title + '.')
    sources = []
    for index, page in enumerate((char_page, work_page), 1):
        item = dict(page)
        item.setdefault('id', index)
        sources.append(item)
    from .literary_ai import ChatResult
    return ChatResult(text, 'answered', True, sources, [], 'sources', 'analysis',
                      {'false_premise_correction': True, 'model_calls': 0})
