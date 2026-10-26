"""Memoria de peticiones fallidas sin convertir borradores en conocimiento."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .ai_narrative_answers import _supported_summary, request_for
from .literary_ai import ChatResult, canonical_sources
from .literary_ai_views import HISTORY_KEY, remember


BOOK = {'kind': 'book', 'title': 'Atlas del comercio', 'author': 'Ana Robles',
        'source': 'Open Library', 'url': 'https://openlibrary.org/works/OL99881W'}
OTHER = {**BOOK, 'title': 'Cuaderno lunar', 'author': 'Pablo Vidal',
         'url': 'https://openlibrary.org/works/OL99882W'}
QUERY = 'Dime la trama de Atlas del comercio de Ana Robles'


class Session(dict):
    modified = False


class NarrativeFailureContextTests(SimpleTestCase):
    def history(self):
        return [{'accepted': True, 'question': 'Otra lectura', 'answer': 'Cuaderno lunar.',
                 'books': [OTHER], 'sources': canonical_sources([OTHER])}]

    def test_failed_content_request_survives_as_a_request_without_an_accepted_turn(self):
        state = {'turns': self.history(), 'active_work': OTHER}
        accepted_before = deepcopy(state['turns'])
        request = SimpleNamespace(session=Session(), user=SimpleNamespace(is_authenticated=False))
        failed = ChatResult('Un borrador rechazado que no debe recordarse.', 'unavailable',
                            sources=[BOOK], diagnostics={'narrative_failure': 'audit_not_approved'})
        remember(request, state, QUERY, failed, 1,
                 SimpleNamespace(calls=2, usage={}, provider='local-test'), topic_context={})
        self.assertEqual(state['turns'], accepted_before)
        self.assertEqual(request.session[HISTORY_KEY]['turns'], accepted_before)
        self.assertTrue(request.session.modified)
        pending = state['pending_clarification']
        self.assertEqual(set(pending), {'status', 'original_query'})
        self.assertEqual(pending['status'], 'unavailable')
        self.assertNotIn(failed.text, str(pending))
        resumed = request_for('¿Qué temas aborda este ensayo?', state['turns'], pending)
        self.assertEqual(resumed['title'], BOOK['title'])
        self.assertEqual(resumed['author_hint'], BOOK['author'])
        self.assertEqual(resumed['targets'], [])
        self.assertNotEqual(resumed['title'], OTHER['title'])

    def test_explicit_new_work_does_not_inherit_the_failed_request(self):
        pending = {'status': 'unavailable', 'original_query': QUERY}
        resumed = request_for('Dime la trama de Cuaderno lunar', self.history(), pending)
        self.assertEqual(resumed['title'], OTHER['title'])
        self.assertEqual(resumed['author_hint'], '')
        self.assertEqual(len(resumed['targets']), 1)

    def test_explicit_new_recommendation_does_not_become_a_title_after_failure(self):
        pending = {'status': 'unavailable', 'original_query': QUERY}
        self.assertIsNone(request_for('Recomiéndame libros sobre arte japonés', [], pending))

    def test_neutral_failed_request_cannot_invent_a_work_for_an_essay_followup(self):
        pending = {'status': 'unavailable', 'original_query': 'Hola, ¿cómo estás?'}
        resumed = request_for('¿Qué temas aborda este ensayo?', [], pending)
        self.assertIsNotNone(resumed)
        self.assertEqual(resumed['title'], '')
        self.assertEqual(resumed['targets'], [])

    def test_partial_topic_sentence_is_kept_only_with_a_literal_source(self):
        proof = '3. Rivers 4. Bridges 5. Markets'
        source = canonical_sources([{'kind': 'web', 'title': BOOK['title'],
            'author': 'Fuente web', 'source': 'DuckDuckGo',
            'url': 'https://www.mheducation.com/example-atlas.html',
            'description': 'Table of Contents: ' + proof}])
        supported = 'Entre los temas que aborda están los ríos, los puentes y los mercados.'
        unsupported = 'La obra abarca hasta el siglo XXI.'
        draft = {'status': 'answer', 'basis': 'sources', 'text': supported + ' ' + unsupported,
                 'citations': [1], 'books': [], 'needs_web': False}
        audit = {'decision': 'repair', 'only_books': True, 'issues': [], 'search_queries': [],
                 'coverage': [{'question_id': 1, 'status': 'uncertain'}], 'claims': [
                     {'statement': supported, 'verdict': 'supported', 'source_id': 1, 'evidence': proof},
                     {'statement': unsupported, 'verdict': 'unverified', 'source_id': 0, 'evidence': ''}]}
        plan = {'questions': ['Qué temas aborda']}
        revised = _supported_summary(draft, audit, plan, source, 'Qué temas aborda')
        self.assertIsNotNone(revised)
        self.assertEqual(revised[0]['text'], supported)
        self.assertNotIn('XXI', revised[0]['text'])
        self.assertEqual(revised[1]['claims'][0]['evidence'], proof)
        invalid = deepcopy(audit)
        invalid['claims'][0]['evidence'] = 'Un pasaje inventado que no está en la fuente.'
        self.assertIsNone(_supported_summary(draft, invalid, plan, source, 'Qué temas aborda'))

    def synthesis_with_incomplete_approval(self, *, verdict='inference', valid_proof=True):
        from .ai_narrative_answers import synthesize_answer
        proof = 'The book studies rivers and bridges.'
        source = canonical_sources([{**BOOK, 'categories': ['History']}, {
            'kind': 'web', 'title': BOOK['title'], 'author': 'Fuente web',
            'source': 'DuckDuckGo', 'url': 'https://www.mheducation.com/example-atlas.html',
            'description': proof}])
        first = 'La obra estudia los ríos y los puentes.'
        second = 'También trata de dragones imaginarios.'

        class Client:
            calls = 0
            usage = {}
            stage_timings = []

            def __call__(self, stage, prompt, context, model):
                self.calls += 1
                if stage == 'answer':
                    return {'status': 'answer', 'basis': 'sources', 'text': first + ' ' + second,
                            'citations': [2], 'books': [], 'needs_web': False}
                return {'decision': 'approve', 'only_books': True, 'issues': [], 'search_queries': [],
                    'coverage': [{'question_id': 1, 'status': 'answered'}], 'claims': [
                        {'statement': first, 'verdict': 'supported', 'source_id': 2,
                         'evidence': proof if valid_proof else 'A fabricated proof absent from the source.'},
                        {'statement': second, 'verdict': verdict, 'source_id': 0, 'evidence': ''}]}

        client = Client()
        with patch('core.literary_ai.build_assistant', return_value=(
                SimpleNamespace(answer_model='local-test', guard_model='local-test'), client)):
            result, _ = synthesize_answer(QUERY, request_for(QUERY), source, SimpleNamespace())
        self.assertEqual(client.calls, 2)
        return result, first, second, proof

    def test_incomplete_model_approval_keeps_only_the_supported_sentence(self):
        for verdict in ('inference', 'unverified'):
            with self.subTest(verdict=verdict):
                result, first, second, proof = self.synthesis_with_incomplete_approval(verdict=verdict)
                self.assertEqual(result.status, 'answered')
                self.assertIn(first, result.text)
                self.assertNotIn(second, result.text)
                self.assertTrue(result.diagnostics['partial_evidence'])
                self.assertTrue(result.diagnostics['unsupported_sentences_removed'])
                self.assertEqual(result.diagnostics['audit']['claims'], [{
                    'statement': first, 'verdict': 'supported', 'source_id': 2, 'evidence': proof}])

    def test_partial_salvage_never_accepts_a_fabricated_supported_proof(self):
        result, first, second, _ = self.synthesis_with_incomplete_approval(valid_proof=False)
        self.assertEqual(result.status, 'unavailable')
        self.assertNotIn(first, result.text)
        self.assertNotIn(second, result.text)
        self.assertFalse(result.diagnostics.get('verified_narrative_answer'))

    @override_settings(LITMATE_AI_USE_WEB=True, LITMATE_AI_USE_OPENLIBRARY=True,
                       LITMATE_AI_USE_WIKIDATA=False)
    def test_accepted_english_content_is_reused_without_reopening_search_providers(self):
        from .ai_narrative_answers import retrieve_sources
        page = {'kind': 'web', 'title': BOOK['title'], 'author': 'Fuente web',
                'source': 'DuckDuckGo', 'url': 'https://www.mheducation.com/example-atlas.html',
                'identity_text': 'Atlas del comercio is a nonfiction book by Ana Robles.',
                'description': 'The book examines rivers, bridges and the development of markets.'}
        history = [{'accepted': True, 'question': QUERY, 'answer': 'Una explicación validada.',
                    'books': [BOOK], 'sources': canonical_sources([BOOK, page])}]
        request = request_for('¿Qué temas aborda este ensayo?', history)
        with patch('core.ai_quick_answers.quick_knowledge_sources', return_value=[]), \
                patch('core.literary_search.search_wikipedia') as wiki, \
                patch('core.literary_search.search_openlibrary') as catalogue, \
                patch('core.literary_search.search_searx') as searx, \
                patch('core.literary_search.search_duckduckgo') as duck, \
                patch('core.literary_search.retrieve_web') as web:
            retrieved = retrieve_sources('¿Qué temas aborda este ensayo?', request, history)
        self.assertEqual(request['retrieval_trace'][0]['stage'], 'stored_content')
        self.assertEqual(next(source for source in retrieved if source['kind'] == 'book')['author'], BOOK['author'])
        bound_page = next(source for source in retrieved if source['kind'] == 'web')
        self.assertEqual(bound_page['work_author'], BOOK['author'])
        self.assertEqual(bound_page['description'], page['description'])
        for provider in (wiki, catalogue, searx, duck, web):
            provider.assert_not_called()

    @override_settings(LITMATE_AI_USE_WEB=True, LITMATE_AI_USE_OPENLIBRARY=True,
                       LITMATE_AI_USE_WIKIDATA=False)
    def test_wrong_work_or_catalogue_tags_cannot_trigger_the_stored_content_shortcut(self):
        from .ai_narrative_answers import retrieve_sources
        cases = [
            [OTHER, {'kind': 'web', 'title': OTHER['title'], 'author': 'Fuente web',
                     'source': 'DuckDuckGo', 'url': 'https://www.mheducation.com/other-book.html',
                     'identity_text': 'Cuaderno lunar is a book by Pablo Vidal.',
                     'description': 'The book examines rivers and markets.'}],
            [{**BOOK, 'description': 'Temas del catálogo: History, Trade.',
              'categories': ['History', 'Trade']}],
        ]
        for old_sources in cases:
            with self.subTest(sources=old_sources):
                history = [{'accepted': True, 'question': 'Una lectura anterior',
                            'answer': 'Respuesta validada.', 'books': [old_sources[0]],
                            'sources': canonical_sources(old_sources)}]
                request = request_for(QUERY, history)
                with patch('core.ai_quick_answers.quick_knowledge_sources', return_value=[]), \
                        patch('core.literary_search.search_wikipedia', return_value=[]) as wiki, \
                        patch('core.literary_search.search_openlibrary', return_value=[]), \
                        patch('core.ai_narrative_answers._discover_content', return_value=[]), \
                        patch('core.literary_search.retrieve_web', return_value=[]), \
                        patch('core.literary_search._openlibrary_detail', return_value={}), \
                        patch('core.ai_persistent_router.persist_sources'):
                    retrieved = retrieve_sources(QUERY, request, history)
                wiki.assert_called_once()
                self.assertNotIn('stored_content', [row['stage'] for row in request['retrieval_trace']])
                self.assertFalse(any(source['kind'] == 'web' for source in retrieved))
