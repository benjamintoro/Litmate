"""Regresiones de continuidad y ampliación, sin red ni bases compartidas."""
from copy import deepcopy
from unittest.mock import patch
from django.test import SimpleTestCase,override_settings
from .test_narrative_answers import BOOK,PAGE
from .ai_narrative_answers import request_for,comparison_answer


class CompletionTests(SimpleTestCase):
    def test_unequal_comparison_does_not_generate_a_new_plot_for_the_only_foreign_source(self):
        from types import SimpleNamespace
        second,other,turns=self.fixtures()
        other={**other,'description':'The story follows Bruno as he travels to a remote forest.'}
        turns[0]['sources']=[BOOK,second,other]
        with patch('core.ai_narrative_answers.retrieve_sources',return_value=[]), \
                patch('core.ai_narrative_answers.synthesize_answer',side_effect=AssertionError('No nueva trama')):
            result=comparison_answer('¿Qué diferencias hay entre los dos primeros?',turns,config=SimpleNamespace())
        self.assertNotEqual(result.status,'answered')
        self.assertEqual(result.diagnostics['model_calls'],0)

    def test_integrity_requires_exact_archived_fact_and_its_original_passage(self):
        import json
        from scripts.knowledge.verify_openlibrary_batch import assertion_preserved_in_snapshot
        fact={'evidence':'Ana viaja a una estación lunar.','topic':'plot'}
        assertion={'work_id':'work-a','record':json.dumps(fact)}
        source={'work_id':'work-a','literary_facts':[fact],'description':fact['evidence']}
        self.assertTrue(assertion_preserved_in_snapshot(assertion,source))
        for change in ({'work_id':'other'},{'literary_facts':[]},{'description':'Un pasaje distinto.'}):
            self.assertFalse(assertion_preserved_in_snapshot(assertion,{**source,**change}))

    def test_missing_second_or_third_is_not_replaced_with_the_only_recommendation(self):
        from .test_narrative_answers import history
        for message in ('Dime de qué trata el segundo','Explícame el tercer libro'):
            with self.subTest(message=message):
                request=request_for(message,history())
                self.assertTrue(request['ambiguous'])
                self.assertEqual(request['targets'],[])
        result=comparison_answer('¿Qué diferencias hay entre los dos primeros?',history())
        self.assertEqual(result.status,'clarification')
        second,other,turns=self.fixtures()
        turns.append({'accepted':True,'intent':'recommend','question':'Recomiéndame otro libro',
                      'answer':'Otra opción.','books':[BOOK],'sources':[BOOK,PAGE]})
        self.assertTrue(request_for('Explícame el segundo libro',turns)['ambiguous'])
        self.assertEqual(comparison_answer('¿Qué diferencias hay entre los dos primeros?',turns).status,'clarification')

    def test_bibliographic_heading_is_not_a_character_of_the_previous_work(self):
        from .ai_character_answers import request_for as character_request
        from .test_narrative_answers import history
        request=character_request('Háblame de Historia de las letras australes: lenguas y crónicas',history())
        self.assertIsNone(request)
        narrative=request_for('Háblame de Historia de las letras australes: lenguas y crónicas',history())
        self.assertIsNotNone(narrative)
        self.assertEqual(narrative['title'],'Historia de las letras australes: lenguas y crónicas')

    def test_plot_extraction_rejects_an_initial_fragment_after_an_abbreviation(self):
        from .ai_narrative_answers import _sentences
        fragment='musicales, es el orgullo de su familia.'
        source={**PAGE,'description':'== Argumento == Ana organiza un viaje a la luna. '+fragment}
        self.assertNotIn(fragment,_sentences(source))

    @override_settings(LITMATE_AI_USE_OPENLIBRARY=False,LITMATE_AI_USE_WEB=False)
    def test_resolved_identity_gets_task_scoped_memory_before_external_research(self):
        from .ai_narrative_answers import retrieve_sources
        message='Dime la trama de Cuaderno lunar'
        request=request_for(message)
        with patch('core.ai_quick_answers.quick_knowledge_sources',return_value=[BOOK]), \
                patch('core.literary_memory.retrieve_evidence',return_value=([BOOK],[PAGE])) as memory, \
                patch('core.literary_search.search_wikipedia',side_effect=AssertionError('No red')):
            sources=retrieve_sources(message,request,[])
        memory.assert_called_once()
        self.assertEqual(memory.call_args.kwargs['requirement'],'summary')
        self.assertEqual(memory.call_args.kwargs['books'][0]['title'],BOOK['title'])
        self.assertTrue(any('estación lunar' in s['description'] for s in sources))

    def test_synthesis_rejects_a_model_and_auditor_that_swap_the_capture_target(self):
        from types import SimpleNamespace
        from .ai_narrative_answers import synthesize_answer
        from .literary_ai import canonical_sources
        proof='The story follows a journey. The guards captured and imprisoned Arturo.'
        statement='Los guardias lograron capturar a Beatriz.'
        class Client:
            calls=0
            usage={}
            stage_timings=[]
            def __call__(self,stage,prompt,context,model):
                self.calls+=1
                if stage=='answer':
                    return {'status':'answer','basis':'sources','text':statement,'citations':[2],
                            'books':[],'needs_web':False}
                return {'decision':'approve','only_books':True,'coverage':[{'question_id':1,'status':'answered'}],
                        'claims':[{'statement':statement,'verdict':'supported','source_id':2,'evidence':proof}],
                        'issues':[],'search_queries':[]}
        client=Client()
        with patch('core.literary_ai.build_assistant',return_value=(
                SimpleNamespace(answer_model='local-test',guard_model='local-test'),client)):
            result,_=synthesize_answer('Dime la trama de Cuaderno lunar',
                request_for('Dime la trama de Cuaderno lunar'),
                canonical_sources([BOOK,{**PAGE,'description':proof}]),SimpleNamespace())
        self.assertEqual(client.calls,2)
        self.assertNotEqual(result.status,'answered')
        self.assertNotIn(statement,result.text)

    def test_author_initials_are_not_mistaken_for_multiple_questions(self):
        request=request_for('Dime la trama de Cuaderno lunar de A. B. Robles')
        self.assertIsNotNone(request)
        self.assertEqual(request['title'],'Cuaderno lunar')
        self.assertEqual(request['author_hint'],'A. B. Robles')
        self.assertIsNone(request_for('Dime la trama de Cuaderno lunar. Recomienda otra obra'))

    def test_plot_sampling_keeps_the_premise_before_skipping_to_later_paragraphs(self):
        from .literary_search import _plot_selection
        premise='Ana construye un vehículo para visitar el futuro. Allí descubre dos comunidades enfrentadas.'
        body='== Argumento ==\n'+premise+'\nBruno organiza una expedición para encontrar su hogar.\nClara busca refugio en una ciudad abandonada.'
        self.assertIn(premise,_plot_selection(body,1500)['passage'])

    def test_singular_alternative_has_one_card_even_in_metadata_only_fallback(self):
        from .literary_ai import requested_book_count
        self.assertEqual(requested_book_count('Recomiéndame otro libro que puedas explicarme'),1)
        self.assertEqual(requested_book_count('Recomiéndame otro sobre el mismo tema'),1)
        self.assertEqual(requested_book_count('Dame otros dos libros'),2)

    def test_read_book_followup_excludes_previously_recommended_cards(self):
        from .ai_quick_answers import verified_book_list_answer
        from .literary_ai import canonical_sources
        books=[{**BOOK,'title':title,'description':'Temas del catálogo: History, Peru.',
                 'categories':['History','Peru'],'book_id':f'/works/OL{index}W',
                 'url':f'https://openlibrary.org/works/OL{index}W'}
               for index,title in enumerate(('Historia andina','Crónicas peruanas','Sociedad del Perú'),100)]
        turns=[{'accepted':True,'question':'Recomiéndame libros sobre la historia del Perú',
                'answer':'Opciones verificadas.','books':books[:2],'sources':canonical_sources(books[:2])}]
        context={'query':'Recomiéndame libros sobre la historia del Perú','followup':True}
        result=verified_book_list_answer('Ya leí ese',books,history=turns,topic_context=context)
        self.assertIsNotNone(result)
        self.assertEqual([b['title'] for b in result.books],['Sociedad del Perú'])

    def test_literal_evidence_cannot_approve_a_capture_of_a_different_person(self):
        from .test_subject_attribution_audit import validate_statement
        proof='The guards captured and imprisoned Arturo. He paid a ransom.'
        with self.assertRaisesRegex(ValueError,'captura'):
            validate_statement('Los guardias lograron capturar a Beatriz.',proof)
        self.assertEqual(validate_statement('Los guardias capturaron a Arturo.',proof)['decision'],'approve')

    def test_local_dump_precedes_remote_detail_even_during_provider_cooldown(self):
        from .literary_search import _openlibrary_detail
        detail={'key':'/works/OL123W','title':'Cuaderno lunar','description':'Un viaje verificado.'}
        with patch('core.literary_acquisition.local_openlibrary_detail',return_value=detail), \
                patch('core.literary_search._openlibrary_fetch',side_effect=AssertionError('No red')):
            reads={'used':0}
            self.assertEqual(_openlibrary_detail(detail['key'],editions=False,reads=reads),detail)
            self.assertEqual(reads['used'],0)

    def test_factual_audit_cannot_swap_the_person_captured_in_a_translation(self):
        from .literary_quality import unsupported_event_target
        evidence='The guards prevailed. They captured and imprisoned Arturo. He paid a ransom.'
        self.assertTrue(unsupported_event_target('Los habitantes lograron capturar a Beatriz.',evidence))
        self.assertFalse(unsupported_event_target('Los guardias capturaron a Arturo.',evidence))
        self.assertFalse(unsupported_event_target('Los guardias capturaron a Arturo.',
                                                  'The guards captured Arturo Robles.'))
        self.assertTrue(unsupported_event_target('Los guardias capturaron a Arturo Ríos.',
                                                 'The guards captured Arturo Robles.'))
        self.assertFalse(unsupported_event_target('Los guardias viajaron al norte.',evidence))
        self.assertFalse(unsupported_event_target('Los guardias capturaron a Beatriz.',
                          evidence+' They later captured Beatriz.'))

    def test_plot_extraction_does_not_prepend_editorial_or_author_biography(self):
        from .ai_narrative_answers import _sentences
        source={**PAGE,'narrative_context':
            'El autor describe su estilo literario durante la redacción. '
            'El escritor desarrolló el resto de la novela dos años después.',
            'description':'== Argumento == Ana viaja a una estación lunar para encontrar a su hermano. '
            'La entretenida obra muestra el contexto histórico de la época.'}
        sentences=_sentences(source)
        self.assertEqual(sentences,['Ana viaja a una estación lunar para encontrar a su hermano.'])

    def test_requests_for_an_explainable_alternative_preserve_the_topic(self):
        from .literary_conversation import resolve_topic_context,remember_topic
        state={};message='Recomiéndame libros sobre la historia del Perú'
        remember_topic(state,message,resolve_topic_context(message,state))
        for followup in ['Recomiéndame otro libro que puedas explicarme','Recomiéndame otro sobre el mismo tema']:
            context=resolve_topic_context(followup,state)
            self.assertTrue(context['followup'])
            self.assertEqual(context['subject'],state['topic']['subject'])

    def test_explicit_translated_title_is_reusable_but_an_unstated_sequel_is_not(self):
        from .literary_identity import published_title_alias,same_work
        page=deepcopy(PAGE)
        page.update(title='Cuaderno de invierno',identity_text=
            'Cuaderno de invierno (en inglés, Winter Notebook o Winter Notebook of the Islands) es una novela de Ana Robles.')
        page['attribution']['title']=page['title']
        self.assertTrue(published_title_alias(page,'Winter Notebook'))
        self.assertTrue(same_work(page,{**BOOK,'title':'Winter Notebook'}))
        self.assertFalse(published_title_alias(page,'Winter Notebook II'))
        self.assertFalse(published_title_alias(page,'Winter'))
        self.assertFalse(published_title_alias({**page,'license':''},'Winter Notebook'))

    def test_wrong_spanish_work_does_not_consume_the_only_narrative_page(self):
        from .literary_search import _search_wikipedia
        from .literary_sources import research_scope,research_snapshot
        page={'pageid':1,'title':'Horizontes (pintura)','fullurl':'https://es.wikipedia.org/wiki/Horizontes',
              'extract':'Horizontes es una pintura de Carlos Pintor.','revisions':[{'revid':1}]}
        with research_scope(pages=1),patch('core.literary_search._wikipedia_fetch',side_effect=[
                {'query':{'pages':{'1':page}}},{'query':{'pages':{}}}]):
            result=_search_wikipedia('"Horizontes" Ana Robles argumento',language='es')
            self.assertEqual(research_snapshot()['page_slots_reserved'],0)
        self.assertEqual(result,[])

    def test_wikipedia_author_qualifier_still_requires_full_authorship(self):
        from .literary_identity import same_work
        book={**BOOK,'title':'Horizontes','author':'Ana Robles'}
        source={**PAGE,'title':'Horizontes (Robles)',
                'identity_text':'Horizontes es una novela de Ana Robles.'}
        self.assertTrue(same_work(source,book))
        self.assertFalse(same_work({**source,'identity_text':'Horizontes es una novela de Luis Robles.'},book))
        self.assertFalse(same_work({**source,'title':'Horizontes (película)'},book))

    def test_catalogue_parenthetical_expansion_matches_only_the_stated_initials(self):
        from .literary_identity import same_author_name,same_work
        author='A. B. (Ana Beatriz) Robles'
        self.assertTrue(same_author_name(author,'Ana Beatriz Robles'))
        self.assertTrue(same_author_name(author,'A. B. Robles'))
        self.assertFalse(same_author_name(author,'Alicia Beatriz Robles'))
        self.assertFalse(same_author_name('A. B. (Alicia Marta) Robles','A. B. Robles'))
        self.assertFalse(same_author_name('A. B. Robles','Ana Beatriz Robles'))
        self.assertTrue(same_author_name('A. Beatriz (Ana Beatriz) Robles','Ana Beatriz Robles'))
        book={**BOOK,'author':author}
        page={**PAGE,'identity_text':'Cuaderno lunar es una novela escrita por Ana Beatriz Robles.'}
        self.assertTrue(same_work(page,book))

    def test_exact_wikipedia_fallback_does_not_reintroduce_disambiguation(self):
        from .literary_search import _search_wikipedia
        page={'pageid':1,'title':'Un título ambiguo','fullurl':'https://es.wikipedia.org/wiki/Ambiguo',
              'extract':'Un título ambiguo puede referirse a diferentes obras.',
              'pageprops':{'disambiguation':''},'revisions':[{'revid':1}]}
        with patch('core.literary_search._wikipedia_fetch',side_effect=[
                {'query':{'pages':{}}},{'query':{'pages':{'1':page}}}]):
            result=_search_wikipedia('"Un título ambiguo" Ana Robles argumento',language='es')
        self.assertEqual(result,[])

    def fixtures(self):
        second={**BOOK,'title':'Bosques de otoño','url':'https://openlibrary.org/works/OL456W'}
        other={**deepcopy(PAGE),'title':second['title'],
               'identity_text':'Bosques de otoño es una novela de Ana Robles.',
               'url':'https://es.wikipedia.org/wiki/Bosques_de_otoño',
               'description':'== Argumento == Bruno viaja a un bosque para investigar una señal. '
                             'La historia sigue su búsqueda de un pueblo abandonado.'}
        other['attribution'].update(title=other['title'],url=other['url'])
        return second,other,[{'accepted':True,'intent':'recommend','question':'Recomiéndame dos novelas',
            'answer':'Dos opciones.','books':[BOOK,second],'sources':[BOOK,PAGE,second,other]}]

    def test_explain_the_third_is_a_content_request(self):
        second,other,turns=self.fixtures()
        third={**BOOK,'title':'Tercer cuaderno'}
        turns[0]['books'].append(third)
        req=request_for('Explícame el tercer libro',turns)
        self.assertIsNotNone(req)
        self.assertEqual(req['title'],'Tercer cuaderno')

    def test_two_ordinal_comparison_uses_both_existing_passages_without_network(self):
        second,other,turns=self.fixtures()
        with patch('core.ai_narrative_answers.retrieve_sources') as retrieve:
            result=comparison_answer('¿Qué diferencias hay entre los dos primeros?',turns)
        self.assertIsNotNone(result)
        self.assertEqual(result.status,'answered')
        self.assertIn('estación lunar',result.text)
        self.assertIn('pueblo abandonado',result.text)
        self.assertEqual(len(result.books),2)
        self.assertEqual(result.diagnostics['model_calls'],0)
        retrieve.assert_not_called()

    def test_novel_index_is_not_a_substitute_for_comparison_evidence(self):
        second,other,turns=self.fixtures()
        turns[0]['sources']=[BOOK,PAGE,second]
        with patch('core.ai_narrative_answers.retrieve_sources',return_value=[]):
            result=comparison_answer('¿Qué diferencias hay entre los dos primeros?',turns)
        self.assertIsNotNone(result)
        self.assertTrue(result.diagnostics['comparison_partial'])
        self.assertIn('estación lunar',result.text)
        self.assertNotIn('pueblo abandonado',result.text)

    def test_partial_comparison_declares_uncertainty_even_if_missing_title_contains_numbers(self):
        second,other,turns=self.fixtures()
        second={**second,'title':'Cuaderno para el 1. (al 5.) año de educación secundaria'}
        turns[0]['books']=[BOOK,second]
        turns[0]['sources']=[BOOK,PAGE,second]
        with patch('core.ai_narrative_answers.retrieve_sources',return_value=[]):
            result=comparison_answer('¿Qué diferencias hay entre los dos primeros?',turns)
        self.assertIsNotNone(result)
        self.assertEqual(result.status,'answered')
        self.assertTrue(result.diagnostics['comparison_partial'])
        self.assertIn('No dispongo de información',result.text)

    def test_downloader_rejects_corrupted_file_before_publishing_it(self):
        import hashlib
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from scripts.knowledge.download_openlibrary import verify_file
        with TemporaryDirectory() as directory:
            path=Path(directory)/'dump.gz';path.write_bytes(b'fixture')
            self.assertEqual(verify_file(path,7,hashlib.sha1(b'fixture').hexdigest()),
                             hashlib.sha256(b'fixture').hexdigest())
            with self.assertRaisesRegex(ValueError,'checksum'):
                verify_file(path,7,'0'*40)
            with self.assertRaisesRegex(ValueError,'size'):
                verify_file(path,9,'0'*40)
