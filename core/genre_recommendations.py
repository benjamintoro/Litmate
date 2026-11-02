"""Recomendaciones por materias existentes; comparte identidad, sesión y auditoría."""
import re
from .literary_genres import requested_categories,matches_categories,classify_categories,excluded_categories
from .literary_identity import normalize_identity,same_work,work_identity,same_author_name


def excluded_authors(message):
    from .books_google import public_query
    match=re.search(r'(?:que no sea(?:n)? de|no me recomiendes (?:a|libros de)|excepto (?:el autor )?)\s*(.{2,100})',message,re.I)
    if not match:return []
    value=match[1].strip('¿?¡!., ')
    return [value] if public_query(value)==value and len(value.split())<=6 else []


def rejected_titles(message):
    from .books_google import public_query
    match=re.fullmatch(r'ya le[ií]\s+(.{2,180})',message.strip('¿?¡!., '),re.I)
    if not match or normalize_identity(match[1]) in {'ese','esa','esos','esas'}:return []
    return [match[1]] if public_query(match[1])==match[1] else []


def local_genre_sources(codes):
    from urllib.parse import urlencode
    from .models import Libro,Genero
    names=[name for name in Genero.objects.values_list('nombre',flat=True) if matches_categories({'categories':[name]},codes)]
    if not names:return []
    rows=Libro.objects.filter(generos__nombre__in=names).distinct().select_related('autor').prefetch_related('generos').order_by('id')[:60]
    return [{'kind':'book','title':b.titulo,'author':b.autor.nombre,'book_id':'db_'+str(b.id),
        'source':'Catálogo LitMate','description':b.sinopsis,'synopsis':b.sinopsis,
        'categories':[g.nombre for g in b.generos.all()]+([b.genero] if b.genero else []),
        'language':b.idioma,'year':str(b.fecha_publicacion.year) if b.fecha_publicacion else '',
        'image_url':b.portada_url or '', 'url':'',
        'preview_url':'https://books.google.com/books?'+urlencode({'q':b.titulo+' '+b.autor.nombre})}
        for b in rows]


def feedback_books(message, history):
    """Preferencias explícitas privadas, resueltas contra la lista anterior."""
    from .literary_identity import resolve_followup_context
    clauses = re.split(r'\s+y\s+(?=no me|ya lei)', normalize_identity(message))
    feedback = {'read': [], 'rejected': []}
    for clause in clauses:
        match = re.fullmatch(r'(ya lei|no me interesa|no me gusto|rechazo) (?:el|la) '
            r'(primero|primera|segundo|segunda|tercero|tercera|cuarto|cuarta|quinto|quinta)', clause)
        if not match:
            return None
        selected = resolve_followup_context('el ' + match[2], history)
        if selected.get('ambiguous') or len(selected.get('books', [])) != 1:
            return {'read': [], 'rejected': []}
        key = 'read' if match[1] == 'ya lei' else 'rejected'
        feedback[key].append(selected['books'][0])
    return feedback


def reading_feedback_answer(message, history):
    from .literary_ai import ChatResult
    feedback = feedback_books(message, history)
    if feedback is None:
        return None
    if not any(feedback.values()):
        return ChatResult('¿Qué libro quieres marcar como leído o descartar? No tengo una lista '
            'anterior que permita resolver esa posición.', 'clarification', intent='conversation')
    return ChatResult('Lo tendré en cuenta: excluiré esas lecturas de las próximas recomendaciones '
        'de esta conversación.', 'social', intent='conversation', diagnostics={'reading_feedback': True})


def remember_recommendations(state,message,context,result):
    from .literary_focus import focus_history
    feedback = feedback_books(message, focus_history(state))
    if context.get('intent')!='recommend' and result.intent!='recommend' and feedback is None:return
    previous=state.get('recommendations',{})
    seen=list(previous.get('seen',[]))[-195:]
    names=list(previous.get('excluded_authors',[]))[-20:]
    names.extend(name for name in excluded_authors(message) if name not in names)
    rejected=list(previous.get('rejected_titles',[]))[-20:]
    read=list(previous.get('read_titles',[]))[-20:]
    if feedback:
        read.extend(book['title'] for book in feedback['read'] if book['title'] not in read)
        rejected.extend(book['title'] for book in feedback['rejected'] if book['title'] not in rejected)
    if feedback is None:
        rejected.extend(title for title in rejected_titles(message) if title not in rejected)
    if result.status=='answered' and result.intent=='recommend':
        lookup={s.get('id'):s for s in result.sources}
        for card in result.books:
            raw=lookup.get(card.get('source_id'),card)
            identity=work_identity(raw)
            if identity and not any(same_work(identity,old) for old in seen):seen.append(identity)
    from .literary_constraints import recommendation_constraints
    from .literary_research import publication_lookup_target
    constraints = dict(previous.get('constraints', {}))
    if context.get('reset_work_context') or publication_lookup_target(message) or (
            context.get('subject') and not context.get('followup')):
        constraints = {}
    constraints.update({key: value for key, value in recommendation_constraints(message).items() if value})
    from .literary_identity import resolve_followup_context
    reference = resolve_followup_context(message, focus_history(state))
    related_reference = previous.get('related_reference')
    if reference.get('reason') == 'similar' and len(reference.get('books', [])) == 1:
        related_reference = reference['books'][0]
    if context.get('reset_work_context') or publication_lookup_target(message):
        related_reference = None
    state['recommendations']={'seen':seen[-200:],'excluded_authors':names[-20:],
                             'rejected_titles':rejected[-20:],'read_titles':read[-20:],
                             'constraints':constraints, 'related_reference':related_reference}


def genre_answer(message,history,context,*,candidates=None):
    from .literary_ai import (ChatResult,canonical_sources,requested_book_count,
                             validate_draft,validate_recommendation_text,has_excerpt,requires_exact_text)
    from .literary_research import evidence_requirements,is_topic_recommendation
    if has_excerpt(message) or requires_exact_text(message):return None
    codes=requested_categories(context.get('subject') or message)
    if not codes or not (context.get('intent')=='recommend' or is_topic_recommendation(message)):return None
    from .literary_genres import TAXONOMY
    remainder=normalize_identity(context.get('subject') or message)
    aliases=sorted({alias for row in TAXONOMY.values() for alias in row['aliases']},key=len,reverse=True)
    for alias in aliases:remainder=re.sub(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',' ',remainder)
    remainder=re.sub(r'\b(?:recomiendame|recomienda|quiero|dame|busco|necesito|libros?|novelas?|obras?|'
        r'de|sobre|del|la|el|los|las|y|o|en|sin|excepto|tres|cuatro|cinco|algunos|mas|otros?|otras?|'
        r'espanol|ingles|frances|aleman|portugues|japones)\b|\d+',' ',remainder)
    if remainder.strip():return None  # No borrar un calificador como «psicológico».
    if evidence_requirements(message,'recommend')!=['recommendation'] and not context.get('followup'):return None
    from .ai_quick_answers import _bundled
    from .bibliographic_repository import genre_sources,digest
    from .literary_constraints import recommendation_constraints,constraints_match
    memory=context.get('recommendation_state',{})
    previous=[*memory.get('seen',[]),*(book for turn in history for book in turn.get('books',[]))]
    repeated=context.get('followup') or bool(re.search(r'\b(?:mas|otro|otra|otros|otras|diferentes|lei|ninguno)\b',normalize_identity(message)))
    from urllib.parse import urlsplit
    excluded_ids=set()
    for book in previous if repeated else ():
        parts=urlsplit(str(book.get('url','')))
        if parts.hostname=='www.gutenberg.org' and re.fullmatch(r'/ebooks/\d+',parts.path):
            excluded_ids.add(digest('gutenberg',parts.path.rsplit('/',1)[-1]))
    pool=(list(candidates) if candidates is not None else [*local_genre_sources(codes),
          *genre_sources(codes,exclude_records=tuple(sorted(excluded_ids))[:200]),*_bundled()])
    query=context.get('query') or message
    constraints=recommendation_constraints(query)
    constraints.update({key:value for key,value in recommendation_constraints(message).items() if value})
    forbidden=excluded_categories(query)|excluded_categories(message)
    rejected=[*memory.get('excluded_authors',[]),*excluded_authors(message)]
    rejected_labels={normalize_identity(title) for title in
        [*memory.get('rejected_titles',[]),*memory.get('read_titles',[]),*rejected_titles(message)]}
    count=requested_book_count(message) or (1 if re.match(r'^otr[oa]\b',normalize_identity(message)) else 3)
    count=min(5,count)
    valid=[]
    for source in pool:
        if (source.get('kind','book')!='book' or not matches_categories(source,codes)
                or forbidden & set(classify_categories(source.get('categories',[])))
                or not constraints_match(source,constraints) or any(same_author_name(source.get('author'),name) for name in rejected)
                or normalize_identity(source.get('title')) in rejected_labels
                or (repeated and any(same_work(source,old) for old in previous))):continue
        if any(same_work(source,old) for old in valid):continue
        valid.append(source)
    from .books_google import content_coverage
    valid.sort(key=lambda s:(-content_coverage(s),{'es':0,'en':1}.get(s.get('language'),2),not bool(s.get('image_url')),
                             not bool(s.get('synopsis')),normalize_identity(s.get('title'))))
    # Primera pasada por autores; sólo usa más obras del mismo autor si faltan opciones.
    chosen=[]
    for diversity in (2,1,0):
        for source in valid:
            if source in chosen:continue
            if diversity and any(same_author_name(source['author'],book['author']) for book in chosen):continue
            if diversity==2 and repeated and any(same_author_name(source['author'],book.get('author')) for book in previous):continue
            chosen.append(source)
            if len(chosen)>=count:break
        if len(chosen)>=count:break
    if not chosen:
        return ChatResult('No encontré otras obras con una clasificación comprobada que cumpla lo que buscas. '
            '¿Quieres probar con un género cercano?','unavailable',False,intent='recommend')
    sources=canonical_sources(chosen,5)
    lines=[f'{index}. **{s["title"]}** — {s["author"]}.' for index,s in enumerate(sources,1)]
    cards=[{'title':s['title'],'author':s['author'],'source_id':s['id']} for s in sources]
    text='¡Claro!\n\n'+'\n\n'.join(lines)
    if len(chosen)<count:text+='\n\nPude verificar '+str(len(chosen))+' opciones que cumplen esos criterios.'
    text+='\n\n¿Cuál te interesa más?'
    draft={'status':'answer','basis':'sources','text':'\n\n'.join(lines),'citations':[s['id'] for s in sources],
        'books':cards,'needs_web':False}
    from .literary_quality import validate_audit,required_fact_statements
    from .literary_evidence import validate_evidence
    plan={'questions':[message],'search_queries':[],'needs_contents':False,'needs_fresh_sources':False,'spoilers_requested':False}
    claims=[]
    for source,line in zip(sources,lines):
        # Un título corto («1984», «Dune») sigue siendo identidad bibliográfica,
        # pero no alcanza el mínimo literal del auditor. Usar el campo de
        # identidad más largo disponible sin inventar contenido.
        proof=next((str(source.get(field) or '') for field in ('title','author','description')
                    if 8<=len(str(source.get(field) or ''))<=300),'')
        if not proof:
            return None
        claims.extend({'statement':statement,'verdict':'supported','source_id':source['id'],'evidence':proof}
                      for statement in required_fact_statements(line) or [line])
    audit={'decision':'approve','only_books':True,'coverage':[{'question_id':1,'status':'uncertain' if len(chosen)<count else 'answered'}],
        'claims':claims,'search_queries':[],'issues':[]}
    try:
        validate_draft(draft,sources);validate_recommendation_text(draft,sources)
        validate_evidence(draft,sources,message);validate_audit(audit,plan,draft,sources,message,strict_facts=True)
    except (ValueError,TypeError) as error:
        import logging
        logging.getLogger(__name__).warning('Clasificación: lista no publicable (%s)',str(error))
        return None
    from .literary_genres import VERSION
    return ChatResult(text,'answered',True,sources,cards,'sources','recommend',{
        'genre_recommendation':True,'audit':audit,'taxonomy_version':VERSION,'candidates':len(valid),
        'classification_evidence':[{'title':s['title'],'source':s.get('url'),
            'original_categories':s.get('categories',[]),'classification':classify_categories(s.get('categories',[]))} for s in sources]})
