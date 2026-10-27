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


def _previous_names(history):
    if not history:
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
    pair = re.fullmatch(r'(?:(?:explicame|dime) (?:la )?)?(?:que relacion tienen|'
                        r'que relacion hay entre|relacion entre) (.+?) y (.+)', value)
    pronoun = re.fullmatch(r'(?:y )?(?:cual es|explicame)? ?(?:su|la) relacion con (.+)', value)
    if pair:
        task, names = 'relationship', list(pair.groups())
    elif pronoun:
        task, names = 'relationship', [*_previous_names(history)[:1], pronoun.group(1)]
    elif re.fullmatch(r'(?:explicame )?la relacion entre ellos', value):
        task, names = 'relationship', _previous_names(history)
    else:
        singular = re.fullmatch(r'(?:y )?(?:(?:quien|cual) es )?(?:el |su )?'
                               r'(?:protagonista|personaje principal)(?: (?:de|del) (.+))?', value)
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
            task, focus, title = 'protagonist', 'main', singular.group(1) or ''
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
    title = title.strip(' «»".,')
    # Recuperar acentos y ñ del texto original antes de consultar catálogos.
    # La normalización compara; no debe convertir «señor» en otro término de búsqueda.
    original = message.strip(' ¿?¡!.,')
    if title:
        tail = ' '.join(original.split()[-len(title.split()):])
        if normalize_identity(tail) == normalize_identity(title):
            title = tail
    if normalize_identity(title) in _DEICTIC or (not title and task in {'character', 'relationship'}):
        from .ai_narrative_answers import request_for as narrative_request
        context = narrative_request('Dime la trama de ese libro', history, pending_clarification)
        if context and context.get('title') and not context.get('ambiguous'):
            title, targets = context['title'], context['targets']
        elif context and context.get('ambiguous'):
            return {'task': task, 'focus': focus, 'title': '', 'targets': [], 'names': names, 'ambiguous': True}
        else:
            title = ''
    from .literary_research import public_research_queries
    if (title and not public_research_queries(title)) or any(not public_research_queries(name) for name in names):
        return None
    if title and not targets:
        for turn in reversed(history):
            matches = [book for book in turn['books'] if _query_title(title, book)]
            if matches:
                targets = matches
                break
    return {'task': task, 'focus': focus, 'title': title, 'targets': targets, 'names': names,
            'ambiguous': False, 'author_hint': ''}


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
    for page in sources:
        intro = normalize_identity(page.get('identity_text', ''))
        if (page['kind'] != 'web' or page.get('injection_detected') or _is_adaptation_page(page)
                or not re.search(r'\bpersonaje(?:s)? fictici\w*\b', intro)):
            continue
        for book in books:
            if (normalize_identity(book['title']) in intro and normalize_identity(book['author']) in intro
                    and re.search(r'\b(?:novela|novelas|libro|libros)\b', intro)):
                page.update(work_title=book['title'], work_author=book['author'],
                            work_id=book.get('work_id', ''), work_binding_verified=True)
                break
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
    return bound_sources(adapted, sources)


def _profile_match(page, names):
    """Una biografía de una persona real no es un perfil de personaje."""
    return (page.get('kind') == 'web' and page.get('source') == 'Wikipedia'
            and not page.get('injection_detected') and not page.get('conflicts_with')
            and 'fragmento del buscador' not in normalized(page.get('read_mode', ''))
            and any(_name_in(name, page.get('title', '')) for name in names)
            and _fictional_profile(page, names))


def _profile_name_in(name, text):
    """Tolera un alias intercalado en el nombre publicado («Sam»)."""
    if _name_in(name, text):
        return True
    tokens = normalize_identity(name).split()
    if not 2 <= len(tokens) <= 6:
        return False
    pattern = (r'(?<!\w)' + re.escape(tokens[0]) + r'\s+'
               + r'(?:\w+\s+){0,3}' + re.escape(tokens[-1]) + r'(?!\w)')
    return bool(re.search(pattern, normalize_identity(text)))


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
        if not re.search(r'\bpersonajes?\b', value):
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
    match = re.match(r'(?i)^\s*' + re.escape(name) + r'(?!\w)', value)
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
    if not _profile_match(page, request['names']):
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
    raw_role = fact['role']
    role = normalize_identity(raw_role)
    name = normalize_identity(fact['name'])
    role = re.sub(r'^' + re.escape(name) + r'\W*', '', role)
    # Ser protagonista de otra novela no da protagonismo en la obra activa.
    referenced = re.search(r'\bprotagonista (?:de|del)\s+(?:(?:la novela|el libro)\s+)?(.+)',
                           raw_role, re.I)
    if referenced:
        other_raw = re.split(r'\s+(?:y|pero|que)\s+|[,.]', referenced.group(1), maxsplit=1)[0].strip()
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
        for fact in source.get('character_facts', []):
            proof = _proof(source, fact)
            if not proof:
                continue
            explicit = re.findall(r'(?:llamado|llamada|conocido como|conocida como)\s+[«"“]?'
                                  r'([A-ZÁÉÍÓÚÑ][\wáéíóúüñ-]{1,69})(?=[,»"”\s]|$)', proof)
            from .literary_memory import _supported_character_alias
            aliases = [alias for alias in [*fact.get('aliases', []), *explicit] if _name_in(alias, proof)
                       and re.search(r'\([^)]*' + re.escape(alias) + r'[^)]*\)|'
                                     r'(?:llamad[oa]|conocid[oa] como)\s+' + re.escape(alias), proof, re.I)
                       and (_supported_character_alias(fact['name'], alias, proof)
                            or re.search(re.escape(fact['name']) + r'\s*\([^)]*' + re.escape(alias), proof))]
            result.append({'name': fact['name'], 'role': fact['role'], 'aliases': aliases,
                           'classification': _classification(fact, source), 'proof': proof, 'source': source})
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
    # Sólo el predicado del sujeto. Una cláusula sobre Aragorn no describe
    # por extensión la relación entre los dos oyentes del relato.
    if not re.match(r'^(?:(?:es|era|fue) )?(?:(?:el|la|un|una|fiel|leal) )?'
                    r'(?:amig\w*|companer\w*|herman\w*|padre|madre|hij\w*|'
                    r'espos\w*|pareja|aliad\w*|enemig\w*|mentor\w*|escudero|'
                    r'sirviente|protector|jardinero|acompana|ayuda|protege|se casa|se caso|'
                    r'se enamora|se enamoro)\b', value):
        return False
    # La relación tiene que predicar algo del sujeto y el otro personaje,
    # no describir una tercera pareja mencionada en el mismo pasaje.
    return bool(re.search(r'\b(?:amig\w*|companer\w*|herman\w*|padre|madre|hij\w*|'
        r'espos\w*|pareja|aliad\w*|enemig\w*|mentor\w*|escudero|sirviente|protector)'
        r'(?:\s+y\s+\w+)?\s+(?:de|del|con)\s+(?:su amo\s+)?' + other + r'(?!\w)', value)
        or re.search(r'\b(?:acompana|ayuda|protege)\s+(?:a\s+)?' + other + r'(?!\w)', value)
        or re.search(r'\b(?:se casa|se caso|se enamora|se enamoro)\s+(?:con|de)\s+' + other + r'(?!\w)', value))


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
    books = [source for source in bound if source['kind'] == 'book']
    if len({normalize_identity(book['author']) for book in books}) > 1:
        return None
    if assess_evidence(message, bound, books, 'analysis')['contradictory']:
        return None
    facts = _facts(request, bound)
    task, focus = request['task'], request['focus']
    if task == 'relationship':
        names = request['names']
        if len(names) != 2:
            return None
        facts = [fact for fact in facts if all(_name_in(name, fact['proof']) for name in names)
                 and _relationship_fact(fact, names)]
    elif task == 'character':
        facts = [fact for fact in facts if any(_name_in(name, fact['name'])
                 or any(normalize_identity(name) == normalize_identity(alias) for alias in fact['aliases'])
                 for name in request['names'])]
        if len({normalize_identity(fact['name']) for fact in facts}) > 1:
            return None
    elif task == 'protagonist':
        explicit = [fact for fact in facts if fact['classification'] == 'main'
                    and re.search(r'\b(?:protagonista|personaje principal)\b', normalize_identity(fact['role']))]
        # Una sección publicada «Principales» acredita la categoría sin repetir
        # la palabra en cada ficha. Sólo se usa como respaldo cuando la fuente
        # no declara un protagonista explícito; nunca se presenta como si lo
        # hiciera.
        facts = explicit or [fact for fact in facts if fact['classification'] == 'main']
    elif focus in {'main', 'antagonist', 'supporting'}:
        facts = [fact for fact in facts if fact['classification'] == focus]
    elif focus == 'female':
        facts = [fact for fact in facts if re.match(r'^(?:(?:es|era|fue) )?(?:(?:una|la) )?'
                  r'(?:mujer|personaje femenino|princesa|elfa|hechicera|matriarca|hija|esposa|'
                  r'sobrina|hermana)\b', normalize_identity(fact['role']))]
    # La extracción de fuentes con derechos reservados se parafrasea mediante
    # la síntesis/auditoría; la vía literal se reserva a conocimiento abierto.
    facts = [fact for fact in facts if _licensed(fact['source'])]
    unique, selected = set(), []
    for fact in facts:
        name = normalize_identity(fact['name'])
        if name not in unique:
            selected.append(fact)
            unique.add(name)
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
    if result is not None:
        result.diagnostics['character_trace'] = [{'stage': 'stored_content', 'facts': result.diagnostics['character_count']}]
        return result
    from .ai_library_router import character_answer_from_library
    local = character_answer_from_library(message, request, config)
    if local is not None and local.status == 'answered':
        return local
    if request['task'] == 'character' and not getattr(settings, 'LITMATE_AI_USE_WEB', True):
        return None  # Sin evidencia de personaje, conservar la ruta de autores.
    if getattr(settings, 'LITMATE_AI_USE_WEB', True):
        from .ai_budget import pool_in_budget, submit_with_budget
        from concurrent.futures import wait
        query = (request['title'].replace('"', ' ') + ' personajes ' + ' '.join(request['names'])
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
        if result is not None:
            persist_sources(result.sources)
            result.diagnostics['character_trace'] = trace
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
    bound = _bound(request, known)
    if config and any(source['kind'] == 'web' and _facts(request, [source]) for source in bound):
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
