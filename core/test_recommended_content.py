"""Regresiones de contenido recomendado, sin red ni almacenes compartidos."""
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from .books_google import volume_source, topic_matches
from .ai_narrative_answers import request_for, bound_sources, _task_content


class RecommendedContentTests(SimpleTestCase):
    def test_a_novels_chapter_titles_alone_do_not_prove_its_plot(self):
        source={'kind':'web','title':'Luz de invierno','categories':['Fiction'],
                'description':'Table of Contents:\n1. La puerta\n2. El bosque\n3. El regreso',
                'extraction_method':'trafilatura+structured_contents'}
        self.assertFalse(_task_content({'task':'summary'},source))

    @override_settings(LITMATE_AI_USE_OPENLIBRARY=True,LITMATE_AI_USE_WEB=False,
                       LITMATE_USE_GOOGLE_BOOKS_API=False,LITMATE_AI_USE_WIKIDATA=False)
    def test_sql_catalogue_id_does_not_hide_its_official_work_identifier(self):
        from .ai_narrative_answers import retrieve_sources
        book={'kind':'book','title':'Historia de las islas','author':'Ana Robles','book_id':'sqlkb:internal',
            'source':'Open Library','url':'https://openlibrary.org/works/OL123W','description':'',
            'categories':['History']}
        detail={'key':'/works/OL123W','title':book['title'],'description':
            'Esta obra estudia los intercambios comerciales de las islas. '
            'El libro aborda la vida social de sus habitantes.'}
        req=request_for('Háblame de Historia de las islas del autor Ana Robles')
        with patch('core.ai_quick_answers.quick_knowledge_sources',return_value=[book]), \
                patch('core.literary_search._openlibrary_detail',return_value=detail), \
                patch('core.ai_library_router.sources_for_request',return_value=[]) as fallback, \
                patch('core.ai_persistent_router.persist_sources'):
            found=retrieve_sources('Háblame de Historia de las islas del autor Ana Robles',req,[])
        fallback.assert_not_called()
        self.assertEqual(found[0]['book_id'],'sqlkb:internal')
        self.assertIn('intercambios comerciales',found[0]['synopsis'])

    @override_settings(LITMATE_USE_GOOGLE_BOOKS_API=True,GOOGLE_BOOKS_API_KEY='test-local-key',
        CACHES={'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache','LOCATION':'secure-books-quota'}})
    def test_secure_http_quota_error_is_not_hidden_as_generic_unavailability(self):
        from .books_google import search_volumes,BooksUnavailable
        from .literary_web import PublicFetchError
        with patch('core.books_google.read_json_url',side_effect=PublicFetchError('rate_limited')) as read:
            with self.assertRaises(BooksUnavailable) as error:
                search_volumes('catálogo de prueba',use_cache=False)
        self.assertEqual(error.exception.code,'quota_exceeded')
        self.assertEqual(read.call_count,1)
        with patch('core.books_google.read_json_url') as retry:
            with self.assertRaises(BooksUnavailable):
                search_volumes('otro libro diferente',use_cache=False)
        retry.assert_not_called()
        # La ruta de catálogo inyecta su lector seguro y use_cache=True.
        # Esa inyección tampoco debe desactivar la pausa del proveedor.
        from django.core.cache import cache
        cache.clear()
        from unittest.mock import Mock
        fetch=Mock(side_effect=PublicFetchError('rate_limited'))
        for query in ['otra consulta de catálogo','consulta posterior diferente']:
            with self.assertRaises(BooksUnavailable):
                search_volumes(query,fetch=fetch,use_cache=True)
        self.assertEqual(fetch.call_count,1)

    @override_settings(LITMATE_AI_USE_SEARXNG=True)
    def test_relaxed_search_does_not_spend_both_reads_on_the_same_wrong_page(self):
        from .ai_narrative_answers import _discover_content
        wrong={'title':'Luz de invierno','description':'Una referencia.','source':'SearXNG',
               'url':'https://library.example/wrong','kind':'web'}
        correct={**wrong,'url':'https://library.example/correct'}
        def page(url,*args,**kwargs):
            return {'status':'ok','title':'Luz de invierno','description':'La novela narra el viaje de una exploradora.',
                    'identity_text':'Luz de invierno es una novela de '+('Luis Mar' if url.endswith('wrong') else 'Ana Robles')+'.'}
        with patch('core.literary_search.search_searx',side_effect=[[wrong],[wrong,correct]]), \
                patch('core.literary_search.read_public_web_page',side_effect=page) as read:
            found=_discover_content('Luz de invierno','Ana Robles')
        req=request_for('Háblame de Luz de invierno del autor Ana Robles')
        self.assertEqual([s['url'] for s in bound_sources(req,found)],['https://library.example/correct'])
        self.assertEqual(read.call_count,2)

    @override_settings(LITMATE_AI_USE_WEB=False,LITMATE_AI_USE_WIKIDATA=False,
                       LITMATE_AI_USE_OPENLIBRARY=True,LITMATE_USE_GOOGLE_BOOKS_API=False)
    def test_identity_lookup_does_not_turn_a_book_title_into_a_topic_query(self):
        from .ai_narrative_answers import retrieve_sources
        req=request_for('Háblame de Historia de las letras insulares del autor Ana Robles')
        with patch('core.ai_quick_answers.quick_knowledge_sources',return_value=[]), \
                patch('core.ai_library_router.sources_for_request',return_value=[]), \
                patch('core.literary_search.search_openlibrary',return_value=[]) as lookup, \
                patch('core.ai_persistent_router.persist_sources'):
            retrieve_sources('Háblame de Historia de las letras insulares del autor Ana Robles',req,[])
        self.assertEqual(lookup.call_args.args[0],
            'intitle:"Historia de las letras insulares" inauthor:"Ana Robles"')

    def test_character_request_separates_explicit_author_from_title(self):
        from .ai_character_answers import request_for as character_request,_bound
        req=character_request('Dime los personajes de Luz de invierno del autor Ana Robles')
        self.assertEqual(req['title'],'Luz de invierno')
        self.assertEqual(req['author_hint'],'Ana Robles')
        one={'kind':'book','title':'Luz de invierno','author':'Ana Robles','description':''}
        other={**one,'author':'Luis Mar'}
        self.assertEqual([s['author'] for s in _bound(req,[other,one]) if s['kind']=='book'],['Ana Robles'])

    def test_bare_ordinal_followup_reuses_content_task_and_recommendation_list(self):
        from .literary_ai import canonical_sources
        first=volume_source({'id':'one','volumeInfo':{'title':'Primer ensayo','authors':['Ana Robles']}})
        second=volume_source({'id':'two','volumeInfo':{'title':'Segundo ensayo','authors':['Luis Mar']}})
        history=[{'accepted':True,'question':'Recomiéndame dos ensayos','answer':'Dos opciones.',
                  'books':[first,second],'sources':canonical_sources([first,second])},
                 {'accepted':True,'question':'¿De qué trata el primer libro?','answer':'Una descripción.',
                  'books':[first],'sources':canonical_sources([first])}]
        req=request_for('¿Y el segundo?',history)
        self.assertIsNotNone(req)
        self.assertEqual(req['task'],'summary')
        self.assertEqual(req['title'],'Segundo ensayo')
        focused=[*history,{'accepted':True,'question':'','answer':'','books':[],'sources':[],
                          'context_only':True,'context_work':second}]
        self.assertEqual(request_for('¿Y el segundo?',focused)['title'],'Segundo ensayo')
        pending={'status':'unavailable','original_query':'¿De qué trata el primer libro?'}
        self.assertEqual(request_for('¿Y el segundo?',history[:1],pending)['title'],'Segundo ensayo')
        self.assertIsNone(request_for('¿Y el segundo?',[]))

    def test_missing_information_mentions_sales_links_only_with_a_visible_card(self):
        from .ai_narrative_answers import insufficient_content_answer
        req=request_for('Háblame de Caminos paralelos del autor Ana Robles')
        empty=insufficient_content_answer(req,[])
        self.assertIn('Actualmente no tengo la información de este libro :(',empty.text)
        self.assertNotIn('sitios de venta',empty.text)
        book=volume_source({'id':'missing','volumeInfo':{'title':'Caminos paralelos','authors':['Ana Robles']}})
        result=insufficient_content_answer(req,[book])
        self.assertNotIn('sitios de venta',result.text)
        req['targets']=[book]  # Ficha ya presentada en un turno aceptado.
        result=insufficient_content_answer(req,[book])
        self.assertTrue(result.text.endswith('Actualmente no tengo la información de este libro :( pero si deseas puedes buscarla en los sitios de venta que te proporcioné'))
        self.assertTrue(result.books)

    def test_technical_provider_failure_is_not_disguised_as_missing_information(self):
        from .ai_narrative_answers import insufficient_content_answer
        req=request_for('Háblame de Caminos paralelos del autor Ana Robles')
        req['retrieval_failures']=[{'provider':'SearXNG','status':'timeout'}]
        result=insufficient_content_answer(req,[])
        self.assertNotIn('Actualmente no tengo la información',result.text)
        self.assertIn('temporal',result.text)
        self.assertEqual(result.diagnostics['retrieval_failures'],req['retrieval_failures'])

    def test_recommended_description_survives_ordinal_followup_without_network(self):
        from .ai_narrative_answers import retrieve_sources
        from .literary_ai import canonical_sources
        book=volume_source({'id':'remembered','volumeInfo':{'title':'Caminos paralelos','authors':['Ana Robles'],
            'categories':['History'],'description':'Esta obra estudia la historia cultural de las islas. '
            'El autor analiza sus intercambios comerciales con otras regiones.'}})
        history=[{'accepted':True,'question':'Recomiéndame historia','answer':'Una opción.',
                  'books':[book],'sources':canonical_sources([book])}]
        req=request_for('¿De qué trata el primer libro?',history)
        with patch('core.ai_quick_answers.quick_knowledge_sources',return_value=[]), \
                patch('core.literary_search.search_google') as google, \
                patch('core.literary_search.search_searx') as searx, \
                patch('core.ai_library_router.sources_for_request') as local:
            found=retrieve_sources('¿De qué trata el primer libro?',req,history)
        self.assertIn('intercambios comerciales',found[0]['synopsis'])
        for provider in (google,searx,local):provider.assert_not_called()

    def test_equally_relevant_recommendations_prefer_usable_content_not_length(self):
        from .books_google import rank_book_sources
        common={'kind':'book','author':'Ana Robles','categories':['History'],
                'source':'Google Books API','description_source':'Google Books API','language':'es'}
        thin={**common,'title':'Historia del Perú','synopsis':''}
        useful={**common,'title':'Historia peruana','synopsis':
                'Esta obra estudia las transformaciones sociales de Perú. Aborda la vida política de la república.'}
        publicity={**common,'title':'Historia peruana','author':'Luis Mar','synopsis':'Un libro extraordinario y maravilloso. '*50}
        wrong={**useful,'title':'Historia de Japón','synopsis':'Esta obra estudia la historia de Japón.'}
        found=rank_book_sources([thin,publicity,wrong,useful],'Recomiéndame libros sobre la historia de Perú')
        self.assertEqual(found[0]['author'],'Ana Robles')
        self.assertTrue(found[0]['synopsis'])
        self.assertNotIn(wrong,found)
        self.assertLess(found.index(useful),found.index(publicity))

    def test_a_request_for_another_explainable_book_keeps_the_previous_topic(self):
        from .literary_conversation import resolve_topic_context,remember_topic
        state={}
        first='Recomiéndame libros sobre la historia del Perú'
        remember_topic(state,first,resolve_topic_context(first,state))
        result=resolve_topic_context('Recomiéndame otro libro del que puedas contarme más.',state)
        self.assertTrue(result['followup'])
        self.assertIn('peru',result['query'].lower().replace('ú','u'))

    def test_unrelated_history_cannot_evict_the_richer_requested_record(self):
        thin=volume_source({'id':'thin','volumeInfo':{'title':'Caminos paralelos',
            'authors':['Ana Robles'],'categories':['History']}})
        rich=volume_source({'id':'rich','volumeInfo':{'title':'Caminos paralelos',
            'authors':['Ana Robles'],'categories':['History'],
            'description':'La obra reúne estudios sobre los intercambios culturales entre dos países.'}})
        noise=[{**thin,'title':'Otra obra '+str(i),'author':'Otra persona','book_id':'other'+str(i)}
               for i in range(25)]
        req=request_for('Háblame de Caminos paralelos del autor Ana Robles')
        found=bound_sources(req,[*noise,thin,rich])
        self.assertEqual([s['book_id'] for s in found],['rich'])

    def test_short_editorial_description_with_two_facts_is_synthesized(self):
        from types import SimpleNamespace
        from .ai_narrative_answers import narrative_answer
        from .literary_ai import ChatResult
        source=volume_source({'id':'short','volumeInfo':{'title':'Caminos paralelos',
            'authors':['Ana Robles'],'categories':['History'],'description':
            'Se reúnen las ponencias de un encuentro de historia comparada. '
            'Los artículos estudian los intercambios culturales entre dos países.'}})
        answer=ChatResult('La obra reúne estudios de historia comparada.','answered')
        with patch('core.ai_narrative_answers.retrieve_sources',return_value=[source]), \
                patch('core.ai_narrative_answers.synthesize_answer',return_value=(answer,SimpleNamespace())) as synth:
            result=narrative_answer('Háblame de Caminos paralelos del autor Ana Robles',config=SimpleNamespace())
        synth.assert_called_once()
        self.assertIs(result,answer)

    def test_catalogue_table_preserves_explicit_identity_and_contents(self):
        from .literary_web import _extract_html
        html='''<html><title>Catálogo universitario</title><table>
            <tr><td>Título</td><td>Historia de las letras insulares: Tradiciones orales</td></tr>
            <tr><td>Autor</td><td>Robles, Ana</td></tr>
            <tr><td>Contenido</td><td>Poesía oral -- Mitos de las islas -- Teatro tradicional</td></tr>
            </table></html>'''
        with patch('trafilatura.extract',return_value=''):
            page=_extract_html(html,'https://library.example/record','contenido overview',1800)
        self.assertEqual(page.get('bibliographic_title'),'Historia de las letras insulares: Tradiciones orales')
        self.assertIn('Robles, Ana',page['identity_text'])
        self.assertIn('Mitos de las islas',page['description'])
        req=request_for('Háblame de Historia de las letras insulares: Tradiciones orales del autor Ana Robles')
        source={**page,'title':page.get('bibliographic_title',page['title']),
            'url':'https://library.example/record','kind':'web','source':'SearXNG',
            'author':'Fuente web','read_mode':'pasaje de página pública'}
        self.assertTrue(bound_sources(req,[source]))
        self.assertTrue(_task_content(req,source))

    def test_discovery_accepts_generic_catalogue_heading_only_after_reading_identity(self):
        from .ai_narrative_answers import _discover_content
        hit={'title':'Catálogo universitario','url':'https://library.example/record','kind':'web',
            'source':'SearXNG','description':'Luz de invierno. Ana Robles.'}
        page={'status':'ok','title':'Catálogo universitario','bibliographic_title':'Luz de invierno',
              'description':'Esta novela narra el viaje de una exploradora.',
              'identity_text':'Título: Luz de invierno. Autor: Robles, Ana. Una novela.'}
        with override_settings(LITMATE_AI_USE_SEARXNG=True), \
                patch('core.literary_search.search_searx',return_value=[hit]), \
                patch('core.literary_search.search_duckduckgo',return_value=[]), \
                patch('core.literary_search.read_public_web_page',return_value=page):
            found=_discover_content('Luz de invierno','Ana Robles')
        self.assertTrue(bound_sources(request_for('Háblame de Luz de invierno del autor Ana Robles'),found))

    @override_settings(LITMATE_AI_USE_SEARXNG=True,
                       LITMATE_SEARXNG_ENGINES=('wikipedia','openlibrary','mwmbl'),
                       LITMATE_SEARXNG_WEB_ENGINES=('mwmbl','duckduckgo','qwant'),
                       CACHES={'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache',
                                         'LOCATION':'recommended-web'}})
    def test_web_route_adds_closed_general_engines_and_keeps_failure_provenance(self):
        from .literary_search import search_searx
        from urllib.parse import urlsplit,parse_qs
        response={'results':[{'title':'Historia de las islas','url':'https://biblioteca.pucp.edu.pe/record',
            'content':'Una ficha pertinente.','engines':['mwmbl']}],
            'unresponsive_engines':[['duckduckgo','CAPTCHA'],['qwant','Access denied']]}
        with patch('core.literary_search.read_json_url',return_value=response) as read:
            result=search_searx('historia de las islas',web=True)
        engines=parse_qs(urlsplit(read.call_args.args[0]).query)['engines'][0].split(',')
        self.assertEqual(set(engines),{'mwmbl','duckduckgo','qwant'})
        self.assertEqual(result.status,'partial')
        self.assertEqual(result[0].get('search_engines'),['mwmbl'])
        self.assertIn('duckduckgo',result.providers)
        with patch('core.literary_search.read_json_url',return_value={'results':[]}) as retry:
            search_searx('otra historia de las islas',web=True)
        self.assertEqual(parse_qs(urlsplit(retry.call_args.args[0]).query)['engines'],['mwmbl'])

    def test_published_subtitle_selects_only_the_requested_volume(self):
        first=volume_source({'id':'vol1','volumeInfo':{'title':'Historia de las letras insulares',
              'subtitle':'Tradiciones orales','authors':['Ana Robles']}})
        other=volume_source({'id':'vol2','volumeInfo':{'title':'Historia de las letras insulares',
              'subtitle':'Literatura moderna','authors':['Ana Robles']}})
        req=request_for('Háblame de Historia de las letras insulares: Tradiciones orales del autor Ana Robles')
        found=bound_sources(req,[first,other])
        self.assertEqual([s['book_id'] for s in found],['vol1'])

    def test_provider_responsibility_labels_are_not_part_of_person_names(self):
        source=volume_source({'id':'roles','volumeInfo':{'title':'Documentos de las islas',
            'authors':['Ana - Autor/a Robles','Luis - Compilador/a o Editor/a Mar']}})
        self.assertEqual(source['author'],'Ana Robles, Luis Mar')
        self.assertIn('Compilador/a o Editor/a',source['description'])

    def test_nonfiction_proceedings_and_document_collections_are_content(self):
        for description in ['Se reúnen las ponencias del encuentro dedicado a la historia comparada de dos países.',
                            'Una compilación de documentos que recogen los cambios sociales de la región.']:
            source=volume_source({'id':'proceedings','volumeInfo':{'title':'Caminos paralelos',
                'authors':['Ana Robles'],'categories':['History'],'description':description}})
            self.assertTrue(_task_content({'task':'summary'},source))

    @override_settings(LITMATE_AI_USE_SEARXNG=True)
    def test_page_identity_is_not_replaced_by_the_selected_narrative_excerpt(self):
        from .ai_narrative_answers import _discover_content
        hit={'title':'Luz de invierno','url':'https://publisher.example/libro',
             'kind':'web','source':'SearXNG','description':'Una referencia bibliográfica.'}
        page={'status':'ok','title':'Luz de invierno','description':'Una viajera intenta regresar a su hogar.',
              'identity_text':'Luz de invierno es una novela de Ana Robles.'}
        with patch('core.literary_search.search_searx',return_value=[hit]), \
                patch('core.literary_search.search_duckduckgo',return_value=[]), \
                patch('core.literary_search.read_public_web_page',return_value=page):
            found=_discover_content('Luz de invierno','Ana Robles')
        req=request_for('Háblame de Luz de invierno del autor Ana Robles')
        self.assertTrue(bound_sources(req,found))

    def test_general_country_history_does_not_accept_a_play_or_literature_history(self):
        for book in [
            {'kind':'book','title':'La conquista de las islas','author':'Ana Robles',
             'categories':['Drama','History'],'synopsis':'Una obra teatral ambientada en las islas.'},
            {'kind':'book','title':'Historia de la literatura de las islas','author':'Ana Robles',
             'categories':['History','Literary criticism'],'synopsis':'La literatura peruana y sus tradiciones.'}]:
            self.assertFalse(topic_matches(book,'Recomiéndame libros sobre historia de Perú'))
        self.assertTrue(topic_matches({'kind':'book','title':'Historia de la literatura peruana',
             'categories':['History','Literary criticism']},'Recomiéndame libros sobre historia de la literatura peruana'))
