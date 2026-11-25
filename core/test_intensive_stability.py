"""Regresiones de defectos observados en las conversaciones intensivas."""
import copy
import json
from django.test import SimpleTestCase
from .ai_quick_answers import catalogue_lookup_answer
from .literary_genres import matches_categories

SOURCE={'kind':'book','source':'Catálogo LitMate','book_id':'db_123',
        'title':'Manual de redes','author':'Ana Escritora','url':'','description':'Ficha bibliográfica.'}

class IntensiveDialogueTests(SimpleTestCase):
    def test_explicit_new_preference_replaces_the_old_subject(self):
        from .literary_conversation import remember_topic,resolve_topic_context
        state={}
        original='Recomiéndame libros sobre la historia del Perú'
        remember_topic(state,original,resolve_topic_context(original,state))
        context=resolve_topic_context('No quiero historia, prefiero ciencia ficción sobre extraterrestres',state)
        self.assertTrue(context['preference_replacement'])
        self.assertNotIn('Perú',context['query'])
        self.assertIn('extraterrestres',context['query'])

    def test_metadata_only_kafka_identity_does_not_hide_reviewed_recall_evidence(self):
        from unittest.mock import patch
        from .ai_identification_details import identification_answer
        from .ai_quick_answers import quick_knowledge_sources
        identity={'title':'La metamorfosis','author':'Franz Kafka','source':'Wikipedia',
                  'kind':'book','description':'','url':'https://es.wikipedia.org/wiki/La_metamorfosis'}
        with patch('core.literary_knowledge.search_knowledge',return_value=[identity]), \
             patch('core.bibliographic_repository.lookup_sources',return_value=[]), \
             patch('core.ai_library_router.library_catalogue',return_value=[]), \
             patch('core.literary_memory.retrieve_evidence',return_value=[]):
            answer=identification_answer('Recuerdo un hombre que despierta convertido en un insecto',
                                         search=quick_knowledge_sources)
        self.assertIsNotNone(answer)
        self.assertIn('Franz Kafka',answer.text)
        self.assertIn('podrías',answer.text)

    def test_recall_still_works_when_current_index_lacks_the_identity(self):
        from .ai_identification_details import identification_recall_answer
        answer=identification_recall_answer('Recuerdo un hombre que despierta convertido en un insecto',
                                           search=lambda *args,**kwargs:[])
        self.assertIn('Franz Kafka',answer.text)

    def test_catalogue_metadata_is_not_a_plot_summary(self):
        from .books_google import source_synopsis
        metadata='Información catalográfica; sin sinopsis ni texto completo. Fuente: https://example.org/obra'
        self.assertEqual(source_synopsis({'description':metadata,'synopsis':metadata}),'')

    def test_dante_summary_without_spoilers_uses_the_reviewed_work(self):
        from .ai_quick_answers import quick_answer
        result=quick_answer('Resume el argumento del Infierno de Dante sin spoilers')
        self.assertIsNotNone(result)
        self.assertEqual(result.books[0]['author'],'Dante Alighieri')
        self.assertIn('Virgilio',result.text)

    def test_sentence_splitter_keeps_an_authors_initials_together(self):
        from .literary_quality import factual_statements
        answer='La novela fue escrita por H. G. Wells. Fue su mejor novela.'
        self.assertEqual(factual_statements(answer,strip_markers=False)[0],
                         'La novela fue escrita por H. G. Wells.')

    def history(self):
        return [{'accepted':True,'question':'Recomiéndame un manual de redes','answer':'Manual de redes',
                 'books':[SOURCE],'sources':[SOURCE],'intent':'recommend'}]

    def test_author_pronoun_uses_the_selected_book(self):
        result=catalogue_lookup_answer('¿Quién es su autor?',self.history(),lambda query:[SOURCE])
        self.assertEqual(result.status,'answered');self.assertIn('Ana Escritora',result.text)

    def test_author_pronoun_without_history_requires_a_title(self):
        result=catalogue_lookup_answer('¿Quién es su autor?',[],lambda query:self.fail('No inventar una obra'))
        self.assertEqual(result.status,'clarification');self.assertFalse(result.books)

    def test_latest_single_recommendation_wins_over_an_older_active_book(self):
        old={**SOURCE,'title':'Python Web Programming','author':'Steve Holden'}
        history=[{'accepted':True,'question':'¿Quién escribió Python Web Programming?',
                  'answer':'Steve Holden','books':[old],'sources':[old],'intent':'author'},
                 {**self.history()[0],'context_work':old},
                 {'accepted':True,'context_only':True,'context_work':old,'books':[],'sources':[]}]
        result=catalogue_lookup_answer('¿Quién es su autor?',history,lambda query:[old,SOURCE])
        self.assertIn('Ana Escritora',result.text);self.assertNotIn('Holden',result.text)

    def test_relevant_technical_category_survives_normalization(self):
        from .genre_recommendations import genre_answer
        source={**SOURCE,'title':'A database handbook','categories':[
            *['Generic category '+str(i) for i in range(8)],'SQL (Computer program language)']}
        result=genre_answer('Recomiéndame un libro de SQL',[],{},candidates=[source])
        self.assertIsNotNone(result)
        self.assertTrue(matches_categories(result.sources[0],['sql_programming']))

    def test_empty_url_uses_a_real_catalogue_label(self):
        result=catalogue_lookup_answer('¿Quién escribió Manual de redes?',[],lambda query:[SOURCE])
        self.assertTrue(result.text.endswith('Fuente: Catálogo LitMate'))

    def test_question_prefix_does_not_trigger_another_model_round(self):
        source={**SOURCE,'title':'Infierno','author':'Dante Alighieri'}
        result=catalogue_lookup_answer('¿Y quién escribió Infierno de Dante?',[],lambda query:[source])
        self.assertEqual(result.status,'answered');self.assertIn('Dante',result.text)

    def test_proposed_wrong_author_is_not_copied_as_fact(self):
        source={**SOURCE,'title':'Frankenstein','author':'Mary Shelley'}
        result=catalogue_lookup_answer('¿Frankenstein fue escrito por Stephen King?',[],lambda query:[source])
        self.assertIn('Mary Shelley',result.text);self.assertNotIn('Stephen King',result.text)

    def test_jscript_net_is_not_recommended_as_browser_javascript(self):
        source={**SOURCE,'title':'JScript.NET programming','categories':['JavaScript (Computer program language)']}
        self.assertFalse(matches_categories(source,['javascript_programming']))
        self.assertTrue(matches_categories(source,['programming']))

    def test_topic_navigation_does_not_reject_a_literary_catalogue_subject(self):
        from .literary_ai_views import _compute_answer_impl
        result,client=_compute_answer_impl('No, volvamos a Packet Tracer',[],{})
        self.assertEqual(result.status,'clarification');self.assertIn('packet tracer',result.text)
        self.assertEqual(client.calls,0)

class IntensiveContextTests(SimpleTestCase):
    def test_long_previous_answer_can_fit_without_losing_the_book_or_current_message(self):
        from .local_llm import OllamaJSON
        data={'message':'Pregunta actual intacta','accepted_history':[
            {'question':'Pregunta anterior','answer':'Texto previo. '*1000,'books':[SOURCE]}],
            'sources':[]}
        before=copy.deepcopy(data)
        fitted=json.loads(OllamaJSON(context=8192)._fit_context('P'*12000,data,2048))
        self.assertEqual(data,before)
        self.assertEqual(fitted['message'],data['message'])
        self.assertEqual(fitted['accepted_history'][0]['books'],[SOURCE])
        self.assertLess(len(fitted['accepted_history'][0]['answer']),len(data['accepted_history'][0]['answer']))

    def test_required_draft_and_original_excerpt_are_never_truncated_to_force_success(self):
        from .local_llm import OllamaJSON
        from .literary_ai import ProviderUnavailable
        data={'message':'Actual','draft':{'text':'D'*40000},'sources':[{'kind':'excerpt','description':'Cita literal'}]}
        before=copy.deepcopy(data)
        with self.assertRaises(ProviderUnavailable):OllamaJSON(context=8192)._fit_context('JSON',data,2048)
        self.assertEqual(data,before)
