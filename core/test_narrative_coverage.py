"""Narrative coverage: public-source structures, synthetic works, isolated stores."""
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import SimpleTestCase, override_settings
from .test_narrative_answers import BOOK, PAGE, history
from .literary_web import character_content
from .ai_character_answers import answer_from_sources, request_for


class NarrativeCoverageTests(SimpleTestCase):
    def test_period_question_uses_published_scope_instead_of_an_unrelated_editorial_sentence(self):
        from .ai_narrative_answers import direct_answer,request_for as narrative_request
        from .books_google import volume_source
        source=volume_source({'id':'abc','volumeInfo':{'title':BOOK['title'],'authors':[BOOK['author']],
             'subtitle':'desde la colonización hasta la independencia (1600-1900)',
             'categories':['History'],'description':
             'Este libro describe la vida de las comunidades costeras y sus vínculos con otros países.'}})
        request=narrative_request('¿Qué períodos históricos aborda?',history())
        self.assertEqual(request.get('summary_focus'),'periods')
        result=direct_answer('¿Qué períodos históricos aborda?',request,[source])
        self.assertIsNotNone(result)
        self.assertIn('1600-1900',result.text)
        self.assertNotIn('vínculos con otros países',result.text)
        self.assertNotIn('no tengo una descripción',result.text)

    def test_failed_editorial_synthesis_keeps_the_audited_short_fallback(self):
        from types import SimpleNamespace
        from .ai_narrative_answers import narrative_answer
        from .literary_ai import ChatResult
        from .books_google import volume_source
        source=volume_source({'id':'abc','volumeInfo':{'title':BOOK['title'],'authors':[BOOK['author']],
             'categories':['History'],'description':
             'Este libro describe la vida cotidiana de las comunidades costeras. '+
             'El autor analiza las transformaciones políticas de las islas durante la época colonial. '*8}})
        failed=ChatResult('No se pudo completar la síntesis.','unavailable',diagnostics={'narrative_failure':'ProviderUnavailable'})
        with patch('core.ai_narrative_answers.retrieve_sources',return_value=[source]), \
                patch('core.ai_narrative_answers.synthesize_answer',return_value=(failed,SimpleNamespace(calls=1,usage={}))):
            result=narrative_answer('Dime la trama de Cuaderno lunar',config=SimpleNamespace())
        self.assertEqual(result.status,'answered')
        self.assertTrue(result.diagnostics['editorial_excerpt'])
        self.assertEqual(result.diagnostics['synthesis_fallback_reason'],'ProviderUnavailable')

    def test_nonfiction_scope_description_is_content_even_without_a_story_action_verb(self):
        from .ai_narrative_answers import _task_content
        from .books_google import volume_source
        source=volume_source({'id':'abc','volumeInfo':{'title':'Historia de las islas','authors':['Ana Robles'],
            'categories':['History'],'description':
            'Esta obra es una historia de las islas destinada a lectores de otras disciplinas. '
            'El autor se detiene en las transiciones políticas de la región.'}})
        self.assertTrue(_task_content({'task':'summary'},source))

    @override_settings(LITMATE_USE_GOOGLE_BOOKS_API=True)
    def test_empty_exact_catalogue_lookup_broadens_once_and_rechecks_title_and_author(self):
        from .ai_narrative_answers import _google_work_sources,request_for as narrative_request,bound_sources
        from .books_google import volume_source
        request=narrative_request('Dime la trama de Cuaderno lunar')
        correct={'id':'correct','volumeInfo':{'title':BOOK['title'],'authors':[BOOK['author']],
                  'description':'El libro describe la vida de una exploradora en una estación lunar.'}}
        other={'id':'wrong','volumeInfo':{'title':'Otra historia','authors':[BOOK['author']],
                'description':'El libro describe una historia diferente de la misma autora.'}}
        with patch('core.literary_search.search_google',return_value=[]), \
                patch('core.books_google.search_volumes',return_value=[other,correct]) as broad:
            sources=_google_work_sources(request,BOOK['author'])
        broad.assert_called_once_with(BOOK['author'],max_results=8)
        bound=bound_sources(request,sources)
        self.assertEqual([s['book_id'] for s in bound if s['kind']=='book'],['correct'])

    def test_google_quota_failure_does_not_trigger_another_query(self):
        from .ai_narrative_answers import _google_work_sources,request_for as narrative_request
        from .literary_sources import SearchResults
        with patch('core.literary_search.search_google',return_value=SearchResults(status='quota_exceeded')), \
                patch('core.books_google.search_volumes') as broad:
            self.assertEqual(_google_work_sources(narrative_request('Dime la trama de Cuaderno lunar'),BOOK['author']),[])
        broad.assert_not_called()

    @override_settings(LITMATE_USE_GOOGLE_BOOKS_API=True,LITMATE_AI_USE_WEB=False,
                       LITMATE_AI_USE_WIKIDATA=False)
    def test_existing_google_provider_is_used_for_missing_recommended_book_content(self):
        from .ai_narrative_answers import retrieve_sources,request_for as narrative_request
        from .books_google import volume_source
        rich=volume_source({'id':'abc','volumeInfo':{'title':BOOK['title'],'authors':[BOOK['author']],
            'description':'Este libro describe la vida cotidiana de las islas durante la época colonial.'}})
        with patch('core.ai_quick_answers.quick_knowledge_sources',return_value=[BOOK]), \
                patch('core.ai_library_router.sources_for_request',return_value=[]), \
                patch('core.literary_search._openlibrary_detail',return_value=None), \
                patch('core.literary_search.search_google',return_value=[rich]) as google, \
                patch('core.ai_persistent_router.persist_sources'):
            found=retrieve_sources('Dime la trama de Cuaderno lunar',narrative_request('Dime la trama de Cuaderno lunar'),[])
        google.assert_called_once()
        self.assertTrue(any(s.get('synopsis') and s.get('description_source') for s in found))

    def test_openlibrary_enrichment_survives_canonical_deduplication_of_the_same_work(self):
        from .literary_ai import canonical_sources
        thin={**BOOK,'book_id':'/works/OL123W','synopsis':''}
        rich={**thin,'subtitle':'desde la colonización hasta la independencia (1600-1900)',
              'description':'Subtítulo verificado de una edición: desde la colonización hasta la independencia (1600-1900)',
              'synopsis_source_url':'https://openlibrary.org/books/OL456M'}
        result=canonical_sources([thin,rich])
        self.assertEqual(len(result),1)
        self.assertEqual(result[0].get('subtitle'),rich['subtitle'])
        other={**rich,'book_id':'/works/OL999W','url':'https://openlibrary.org/works/OL999W'}
        self.assertNotIn('subtitle',canonical_sources([thin,other])[0])

    def test_verified_nonfiction_subtitle_answers_scope_without_model(self):
        from .ai_narrative_answers import metadata_content_answer, request_for as narrative_request
        subtitle='desde la colonización de las islas hasta la independencia (1600-1900)'
        book={**BOOK,'categories':['History'],'source':'Open Library','book_id':'/works/OL123W',
              'url':'https://openlibrary.org/works/OL123W','subtitle':subtitle,
              'description':'Subtítulo verificado de una edición: '+subtitle,
              'synopsis_source_url':'https://openlibrary.org/books/OL456M'}
        req=narrative_request('Dime la trama de Cuaderno lunar')
        result=metadata_content_answer('Dime la trama de Cuaderno lunar',req,[book])
        self.assertIsNotNone(result)
        self.assertIn('1600-1900',result.text)
        self.assertTrue(result.diagnostics['partial_evidence'])
        self.assertEqual(result.diagnostics['model_calls'],0)
        self.assertIsNone(metadata_content_answer('Dime la trama de Cuaderno lunar',req,
            [{**book,'categories':['Fantasy'],'subtitle':'La última aventura'}]))

    def test_contextual_comparison_keeps_active_work_and_original_second_recommendation(self):
        from .ai_narrative_answers import comparison_answer
        first={**BOOK,'source':'Open Library','categories':['History'],
               'description':'Subtítulo verificado de una edición: historia de las islas (1600-1900)',
               'subtitle':'historia de las islas (1600-1900)'}
        second={**first,'title':'Los años difíciles','author':'Daniel Mar',
                'url':'https://openlibrary.org/works/OL789W','book_id':'/works/OL789W',
                'description':'Subtítulo verificado de una edición: la república durante la crisis (1930-1940)',
                'subtitle':'la república durante la crisis (1930-1940)'}
        turns=[{'accepted':True,'question':'Recomiéndame libros de historia','answer':'Opciones','intent':'recommend',
                'books':[first,second],'sources':[first,second]},
               {'accepted':True,'question':'Dime la trama del primero','answer':'Contenido','books':[first],'sources':[first]}]
        with patch('core.ai_narrative_answers.retrieve_sources',side_effect=lambda m,r,h:
                   [s for s in [first,second] if s['title']==r['title']]):
            result=comparison_answer('¿En qué se diferencia del segundo libro que recomendaste?',turns)
        self.assertIsNotNone(result)
        self.assertIn('1600-1900',result.text)
        self.assertIn('1930-1940',result.text)
        self.assertEqual(result.diagnostics['model_calls'],0)
        self.assertEqual(len(result.books),2)

    def test_scope_fallback_does_not_replace_a_supported_comparison_of_novels(self):
        from .ai_narrative_answers import comparison_answer
        second={**BOOK,'title':'Las islas azules','author':'Daniel Mar','url':'https://openlibrary.org/works/OL789W'}
        turns=[{'accepted':True,'question':'Recomiéndame dos novelas','answer':'Opciones','intent':'recommend',
                'books':[BOOK,second],'sources':[BOOK,second]},
               {'accepted':True,'question':'Dime la trama del primero','answer':'Contenido','books':[BOOK],'sources':[BOOK,PAGE]}]
        with patch('core.ai_narrative_answers.retrieve_sources',side_effect=lambda m,r,h:
                   [BOOK,PAGE] if r['title']==BOOK['title'] else [second,{**PAGE,'title':second['title'],
                      'identity_text':'Las islas azules es una novela de Daniel Mar.',
                      'url':'https://es.wikipedia.org/wiki/Las_islas_azules'}]):
            self.assertIsNone(comparison_answer('¿En qué se diferencia del segundo libro que recomendaste?',turns))

    def test_summary_request_with_author_particles_is_a_book_not_a_generic_topic(self):
        from .ai_narrative_answers import request_for as narrative_request
        q='Dime de qué trata Historia de las islas de Ana de Robles'
        request=narrative_request(q)
        self.assertIsNotNone(request)
        self.assertEqual(request['title'],'Historia de las islas')
        self.assertEqual(request['author_hint'],'Ana de Robles')
        self.assertIsNone(narrative_request('De qué trata la historia de las islas'))

    def test_descriptive_recommendation_is_not_hidden_by_an_empty_local_catalogue_record(self):
        from .ai_narrative_answers import bound_sources,request_for as narrative_request
        rich={**BOOK,'source':'Google Books API','description':'Este libro describe la vida cotidiana de las islas durante la época colonial.',
              'synopsis':'Este libro describe la vida cotidiana de las islas durante la época colonial.',
              'description_source':'Google Books, descripción editorial','book_id':'abc',
              'url':'https://books.google.com/books?id=abc'}
        request=narrative_request('Dime la trama de Cuaderno lunar')
        bound=bound_sources(request,[{**BOOK,'description':''},rich])
        self.assertTrue(any(s.get('synopsis') for s in bound))

    def test_editorial_excerpt_can_answer_without_model_and_without_copying_a_long_blurb(self):
        from .ai_narrative_answers import direct_answer,request_for as narrative_request
        text='Este libro describe la vida cotidiana de las islas durante la época colonial.'
        source={**BOOK,'source':'Google Books API','description':text,'synopsis':text,
                'description_source':'Google Books, descripción editorial','url':'https://books.google.com/books?id=abc'}
        result=direct_answer('Dime la trama de Cuaderno lunar',narrative_request('Dime la trama de Cuaderno lunar'),[source])
        self.assertIsNotNone(result)
        self.assertEqual(result.diagnostics['model_calls'],0)
        self.assertIn('época colonial',result.text)
        self.assertTrue(result.diagnostics['editorial_excerpt'])

    def test_author_in_a_role_is_not_mistaken_for_another_novel_title(self):
        from .ai_character_answers import _classification
        page={**PAGE,'work_title':BOOK['title'],'work_author':BOOK['author'],'work_binding_verified':True}
        fact={'name':'Elena','role':'es la protagonista de la novela homónima de la escritora Ana Robles.'}
        self.assertEqual(_classification(fact,page),'main')
        fact['role']='es la protagonista de la novela Otra historia de la escritora Ana Robles.'
        self.assertEqual(_classification(fact,page),'')

    def test_heading_classification_uses_the_recovered_proof_if_provider_omits_it(self):
        page={**PAGE,'description':'=== Personajes principales ===\nBruno: Antagonista de la expedición lunar.',
              'character_facts':[{'name':'Bruno','role':'Antagonista de la expedición lunar.',
                   'classification':'principal','classification_evidence':'Personajes principales'}]}
        q='Dime los personajes principales de Cuaderno lunar'
        result=answer_from_sources(q,request_for(q,history()),[BOOK,page])
        self.assertIsNotNone(result)
        self.assertIn('Bruno',result.text)

    def test_worker_roster_goal_uses_literal_roles_not_membership_only(self):
        from .literary_learning import _covers_requirement
        page={**PAGE,'description':'Elena: protagonista del viaje. Bruno: el barquero de la estación. Dora: la capitana del barco.',
              'character_facts':[{'name':'Elena','role':'protagonista del viaje.'},
                {'name':'Bruno','role':'el barquero de la estación.'},{'name':'Dora','role':'la capitana del barco.'}]}
        self.assertTrue(_covers_requirement(BOOK,[BOOK],[page],'character_roster'))
        role='Personaje registrado para esta obra en Wikidata'
        page['character_facts']=[{'name':name,'role':role} for name in ('Elena','Bruno','Dora')]
        page['description']='\n'.join(f['name']+': '+role for f in page['character_facts'])
        self.assertFalse(_covers_requirement(BOOK,[BOOK],[page],'character_roster'))

    def test_linked_names_after_explicit_nominal_roles_are_not_lost(self):
        html=('<h2>Argumento</h2><p>Bruno visita a su hermano menor <a href="/wiki/Ciro">Ciro</a>. '
              'Una sirvienta de la familia —<a href="/wiki/Dora_Mar">Dora Mar</a>— lo ayuda en la casa.</p>')
        content=character_content(html,title=BOOK['title'],context='Cuaderno lunar es una novela de Ana Robles.')
        names={fact['name'] for fact in content['character_facts']}
        self.assertTrue({'Ciro','Dora Mar'}<=names)
        self.assertNotIn('Bruno',names)

    def test_explicit_nominal_roles_identify_names_even_without_hyperlinks(self):
        from .literary_web import narrative_character_facts
        facts=narrative_character_facts('Bruno visita a su hermano menor Ciro. '
            'Una sirvienta de la familia —Dora Mar— lo ayuda en la casa.')
        self.assertEqual({f['name'] for f in facts},{'Ciro','Dora Mar'})
        self.assertEqual(narrative_character_facts('Bruno recuerda a Ciro y Dora Mar.'),[])

    def test_targeted_worker_does_not_claim_an_unrelated_older_requirement(self):
        from . import literary_memory as memory
        from .literary_identity import stable_work_id
        with TemporaryDirectory() as temporary:
            database=Path(temporary)/'memory.sqlite3'
            memory.remember_evidence([BOOK],[BOOK],database=database)
            wid=stable_work_id(BOOK['title'],BOOK['author'])
            memory.enqueue_refresh(wid,'characters','wikipedia',database=database,priority=99)
            wanted=memory.enqueue_refresh(wid,'plot_development','wikipedia',database=database,priority=60)
            job=memory.claim_job('worker',database=database,requirements=('plot_development',))
            self.assertEqual(job['job_id'],wanted)

    def test_missing_roles_have_priority_over_already_known_relations(self):
        from .continuous_knowledge import gap_priority
        self.assertGreater(gap_priority(BOOK,[BOOK],[],'characters'),
                           gap_priority(BOOK,[BOOK],[PAGE],'relationships'))

    def test_protagonist_profile_does_not_need_the_extra_word_character(self):
        from .ai_character_answers import bind_character_profile
        text='Elena es la protagonista de la novela Cuaderno lunar, de Ana Robles.'
        profile={**PAGE,'title':'Elena','description':text,'identity_text':text}
        self.assertIsNotNone(bind_character_profile(profile,BOOK))

    def test_bounded_plot_selection_reaches_development_without_taking_the_ending(self):
        from .literary_search import relevant_passage
        paragraphs = ['Elena llega a una estación lunar para buscar a su hermano. '+
                      'Elena prepara su equipaje y recorre los pasillos de la estación. '*25,
                      'Bruno descubre que la estación pierde su reserva de agua.\n',
                      'Elena organiza una expedición para investigar las antiguas galerías.\n',
                      'Dora se une al grupo para construir una nueva ruta de abastecimiento.\n',
                      '=== El fin ===\nFinalmente Elena muere y Bruno abandona para siempre la estación.']
        text='== Argumento ==\n'+'\n\n'.join(paragraphs)
        passage=relevant_passage(text,'"Cuaderno lunar" argumento',maximum=900)
        self.assertLessEqual(len(passage),900)
        self.assertTrue('reserva de agua' in passage or 'nueva ruta' in passage)
        self.assertNotIn('Finalmente',passage)
        self.assertNotIn('muere',passage)

    def test_main_antagonist_is_main_but_an_unranked_antagonist_is_not(self):
        html = ('<h2>Personajes</h2><ul><li><b>Elena</b>: Protagonista de la expedición lunar.</li>'
                '<li><b>Bruno</b>: Antagonista principal que gobierna la estación.</li>'
                '<li><b>Dora</b>: Antagonista que vigila una puerta.</li></ul>')
        content = character_content(html,title=BOOK['title'])
        page = {**PAGE,'description':content['passage'],'character_facts':content['character_facts']}
        q='Dime los personajes principales de Cuaderno lunar'
        result=answer_from_sources(q,request_for(q,history()),[BOOK,page])
        self.assertIn('**Bruno**',result.text)
        self.assertNotIn('**Dora**',result.text)

    @override_settings(LITMATE_AI_USE_WEB=True,LITMATE_AI_USE_WIKIDATA=False)
    def test_one_cached_main_character_does_not_hide_a_second_published_main(self):
        from .ai_character_answers import character_answer
        first = {**PAGE,'description':'Elena: protagonista que explora una estación lunar.',
                 'character_facts':[{'name':'Elena','role':'protagonista que explora una estación lunar.'}]}
        second = {**PAGE,'description':'Bruno: protagonista que guía la nave.',
                  'character_facts':[{'name':'Bruno','role':'protagonista que guía la nave.'}],
                  'url':PAGE['url']+'_personajes'}
        with patch('core.ai_quick_answers.quick_knowledge_sources',return_value=[BOOK,first]), \
                patch('core.literary_memory.retrieve_character_entities',return_value=[]), \
                patch('core.ai_character_answers._character_profiles',side_effect=lambda r,k:([],r)), \
                patch('core.ai_library_router.character_answer_from_library',return_value=None) as library, \
                patch('core.literary_search.search_wikipedia',return_value=[second]) as search, \
                patch('core.ai_persistent_router.persist_sources'):
            result = character_answer('Dime los personajes principales de Cuaderno lunar')
        self.assertEqual(result.diagnostics['character_count'],2)
        search.assert_called_once()
        library.assert_not_called()

    def test_character_description_column_is_explicit_and_not_a_cast(self):
        html = ('<h2>Personajes</h2><table><tr><th>Personaje</th><th>Descripción personaje</th></tr>'
                '<tr><td>Elena</td><td>Personaje principal femenino de la novela. Es amiga de Bruno.</td></tr>'
                '<tr><td>Bruno</td><td>Protagonista que explora una ciudad abandonada.</td></tr></table>')
        content = character_content(html,context='Cuaderno lunar personajes principales',title=BOOK['title'])
        self.assertEqual(len(content['character_facts']),2)
        page = {**PAGE,'description':content['passage'],'character_facts':content['character_facts']}
        question = 'Dime los personajes principales de Cuaderno lunar'
        answer = answer_from_sources(question,request_for(question,history()),[BOOK,page])
        self.assertIsNotNone(answer)
        self.assertEqual(answer.diagnostics['character_count'],2)
        self.assertEqual(character_content(html.replace('Descripción personaje','Actor'),title=BOOK['title'])['character_facts'],[])

    def test_inverted_protagonist_definition_and_other_roles_are_retained(self):
        html = ('<h2>Personajes</h2><p>La protagonista por antonomasia es Elena, una viajera que busca su camino.</p>'
                '<ul><li><b>Bruno</b>: Es el barquero que la acompaña durante el viaje.</li></ul>')
        content = character_content(html,title=BOOK['title'],context='Cuaderno lunar personajes')
        self.assertEqual({f['name'] for f in content['character_facts']},{'Elena','Bruno'})
        page = {**PAGE,'description':content['passage'],'character_facts':content['character_facts']}
        question = 'Dime los personajes principales de Cuaderno lunar'
        result = answer_from_sources(question,request_for(question,history()),[BOOK,page])
        self.assertIsNotNone(result)
        self.assertIn('Elena',result.text)
        self.assertNotIn('**Bruno**',result.text)
        self.assertIn('Lista parcial.',result.text)
        self.assertTrue(all(c['verdict']=='supported' for c in result.diagnostics['audit']['claims']))

    def test_verified_aliases_do_not_duplicate_an_entity_across_fragments(self):
        first = {**PAGE,'description':'Elena Cruz (Lena): protagonista que explora una estación lunar.',
                 'character_facts':[{'name':'Elena Cruz','aliases':['Lena'],
                    'role':'protagonista que explora una estación lunar.',
                    'evidence':'Elena Cruz (Lena): protagonista que explora una estación lunar.'}]}
        second = {**PAGE,'url':PAGE['url']+'_otra_seccion',
                  'description':'Lena: protagonista que busca a su hermana. Bruno: protagonista que guía la nave.',
                  'character_facts':[{'name':'Lena','role':'protagonista que busca a su hermana.'},
                                     {'name':'Bruno','role':'protagonista que guía la nave.'}]}
        q = 'Dime los personajes principales de Cuaderno lunar'
        result = answer_from_sources(q,request_for(q,history()),[BOOK,first,second])
        self.assertIsNotNone(result)
        self.assertEqual(result.diagnostics['character_count'],2)
        self.assertIn('Elena Cruz',result.text)
        self.assertIn('Bruno',result.text)

