"""Reconciliación puntual de autoría mediante una biografía pública explícita.

No equipara nombres parciales por semejanza ni cambia identidades del catálogo.
Los vínculos resultantes son temporales y conservan la segunda fuente.
"""
import re
import time
from urllib.parse import urlsplit

from .literary_identity import (normalize_identity, _identity_author, same_work,
                               work_identity, title_matches, published_title_alias)


def _licensed_page(page):
    attribution=page.get('attribution',{})
    return (page.get('kind')=='web' and page.get('source')=='Wikipedia'
            and urlsplit(str(page.get('url',''))).scheme=='https'
            and urlsplit(str(page.get('url',''))).hostname in {'es.wikipedia.org','en.wikipedia.org'}
            and page.get('license')=='CC-BY-SA-4.0'
            and not page.get('injection_detected') and not page.get('conflicts_with')
            and attribution.get('authors')=='Wikipedia contributors'
            and attribution.get('url')==page.get('url')
            and attribution.get('title')==page.get('title')
            and attribution.get('license_url')=='https://creativecommons.org/licenses/by-sa/4.0/'
            and str(attribution.get('revision_id','')).isdigit())


def reconcile_web_authors(pages, books, *, search=None):
    """Una consulta adicional como máximo; sólo alias publicados como sujeto.

    El título del artículo de autor y el nombre completo que encabeza su
    biografía identifican a la misma persona. Una mención incidental no basta.
    La página de obra debe declarar también ese autor y el título exacto.
    """
    from .ai_budget import budget_timeout, request_budget
    from .ai_quick_answers import _is_adaptation_page
    from .literary_search import search_wikipedia
    from .literary_web import public_text_has_injection
    from .literary_ai import normalized
    result=list(pages);attempted=False
    for index,page in enumerate(pages):
        if not _licensed_page(page) or _is_adaptation_page(page):continue
        intro=normalize_identity(page.get('identity_text',''))
        if public_text_has_injection(page.get('description','')):continue
        declared=_identity_author(page)
        if len(normalize_identity(declared).split())<2:continue
        for book in books[:2]:
            if book.get('kind')!='book':continue
            title=normalize_identity(book.get('title',''));author=normalize_identity(book.get('author',''))
            if same_work(page,book) or not title or not author or author==normalize_identity(declared):continue
            if not re.search(r'(?<!\w)'+re.escape(title)+r'(?!\w)',intro):continue
            if (not title_matches(page.get('title',''),book)
                    and not published_title_alias(page,book['title']) and not re.search(
                    r'\b(?:novela|libro|obra|poema)\s+'+re.escape(title)
                    +r'(?=\s*[,.;(]|\s+(?:(?:escrit[oa]\s+)?por|de)\s+|$)',intro)):continue
            if not re.search(r'\b(?:novela|libro|obra|poema|novel|book)\b',intro):continue
            if attempted or budget_timeout(4)<1:continue
            attempted=True
            try:
                from .books_google import public_query
                author_query=public_query(book['author'])
                if normalize_identity(author_query)!=author:continue
                with request_budget(time.monotonic()+budget_timeout(4)):
                    authorities=(search or search_wikipedia)(author_query)
            except (OSError,ValueError,TimeoutError):continue
            matches=[]
            for authority in authorities:
                body=normalized(authority.get('identity_text',''))
                if (not _licensed_page(authority) or public_text_has_injection(authority.get('description',''))
                        or normalize_identity(authority.get('title',''))!=normalize_identity(declared)
                        or not re.match(re.escape(author)+r'(?=\s*[(\[,:;—–-]|\s+(?:es|fue)\b|$)',body)
                        or not re.search(r'\b(?:es|fue)\b.{0,100}\b(?:escritor\w*|autor\w*|novelista|poeta|dramaturg\w*)\b',body[:350])):
                    continue
                matches.append(authority)
            if len(matches)!=1:continue
            authority=matches[0];identity=work_identity(book)
            if not identity:continue
            result[index]={**page,'work_title':book['title'],'work_author':book['author'],
                'work_id':identity['work_id'],'work_binding_verified':True,'permanent_index_allowed':False,
                'identity_authority':{'url':authority['url'],'title':authority['title'],
                    'revision_id':authority['attribution']['revision_id'],'subject':book['author'],
                    'license':'CC-BY-SA-4.0'}}
            break
    return result


def verified_work_article(book, *, search=None):
    """Busca una obra ya identificada por título, no por todos los términos AND.

    Una consulta que mezcla título, nombre largo del autor y tarea puede
    ocultar el artículo correcto. No basta encontrarlo: conserva las mismas
    comprobaciones de título, adaptación y autoría.
    """
    from .literary_search import search_wikipedia
    from .books_google import public_query
    from .ai_budget import request_budget,budget_timeout
    from .ai_quick_answers import _is_adaptation_page
    title=public_query(book.get('title',''))
    if book.get('kind')!='book' or not title or budget_timeout(6)<1:return []
    lookup=search or search_wikipedia
    try:
        with request_budget(time.monotonic()+budget_timeout(6)):
            pages=lookup('"'+title.replace('"',' ')+'"')
            pages=reconcile_web_authors(pages,[book],search=lookup)
    except (OSError,ValueError,TimeoutError):return []
    return [page for page in pages if _licensed_page(page) and not _is_adaptation_page(page)
            and same_work(page,book)]
