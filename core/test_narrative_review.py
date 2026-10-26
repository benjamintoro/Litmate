"""Regresiones de identidad y evidencia detectadas al revisar sinopsis.

Las fichas y las respuestas de modelo son simuladas. Ninguna de estas pruebas
consulta Internet, carga Ollama ni modifica la base de datos del proyecto.
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .literary_ai import canonical_sources


BOOK = {
    'id': 1, 'kind': 'book', 'title': 'Historia del puerto', 'author': 'Ana Robles',
    'source': 'Open Library', 'url': 'https://openlibrary.org/works/OL99871W',
    'description': '', 'subjects': ['History', 'Ports'],
}


@override_settings(LITMATE_AI_USE_WIKIDATA=False)
class NarrativeReviewRegressionTests(SimpleTestCase):
    def test_essay_reference_uses_the_active_work_instead_of_a_literal_placeholder(self):
        from .ai_narrative_answers import request_for
        history = [{'accepted': True, 'question': 'Una lectura de historia',
                    'answer': 'Puedes leer Historia del puerto.', 'books': [BOOK], 'sources': []}]
        request = request_for('¿Qué temas aborda este ensayo?', history)
        self.assertIsNotNone(request)
        self.assertEqual(request['task'], 'summary')
        self.assertEqual(request['title'], BOOK['title'])
        self.assertEqual(len(request['targets']), 1)

    def test_previously_mentioned_book_is_a_context_reference(self):
        from .ai_narrative_answers import request_for
        history = [{'accepted': True, 'question': 'Una lectura de historia',
                    'answer': 'Puedes leer Historia del puerto.', 'books': [BOOK], 'sources': []}]
        request = request_for('¿De qué trata el libro que mencionaste anteriormente?', history)
        self.assertIsNotNone(request)
        self.assertEqual(request['title'], BOOK['title'])
        self.assertEqual(len(request['targets']), 1)

    def test_catalogue_subjects_do_not_become_an_unaudited_nonfiction_synopsis(self):
        from .ai_narrative_answers import narrative_answer
        with patch('core.ai_narrative_answers.retrieve_sources', return_value=[BOOK]):
            result = narrative_answer('Dime la trama de Historia del puerto', [])
        self.assertIsNotNone(result)
        self.assertNotEqual(result.status, 'answered')
        self.assertFalse(result.diagnostics.get('verified_narrative_answer'))
        self.assertNotIn('no cuenta con una trama de ficción', result.text)

    def test_explicit_author_does_not_inherit_a_homonym_from_history(self):
        from .ai_narrative_answers import request_for
        history = [{'accepted': True, 'question': 'Háblame de Historia del puerto',
                    'answer': 'Una obra de Ana Robles.', 'books': [BOOK], 'sources': []}]
        request = request_for('Dime la trama de Historia del puerto de Pablo Vidal', history)
        self.assertEqual(request['title'], BOOK['title'])
        self.assertEqual(request['author_hint'], 'Pablo Vidal')
        self.assertEqual(request['targets'], [])

    @override_settings(LITMATE_AI_USE_WEB=False, LITMATE_AI_USE_OPENLIBRARY=True)
    def test_explicit_author_still_searches_the_catalogue_without_a_previous_identity(self):
        from .ai_narrative_answers import request_for, retrieve_sources
        message = 'Dime la trama de Historia del puerto de Ana Robles'
        with patch('core.ai_quick_answers.quick_knowledge_sources', return_value=[]), \
                patch('core.literary_search.search_openlibrary', return_value=[BOOK]) as catalogue, \
                patch('core.literary_search._openlibrary_detail', return_value={}), \
                patch('core.ai_persistent_router.persist_sources'):
            sources = retrieve_sources(message, request_for(message), [])
        self.assertTrue(catalogue.called)
        self.assertTrue(any(source['title'] == BOOK['title'] and
                            source['author'] == BOOK['author'] for source in sources))

    @override_settings(LITMATE_AI_USE_WEB=False, LITMATE_AI_USE_OPENLIBRARY=False)
    def test_known_homonyms_request_clarification_instead_of_discarding_both(self):
        from .ai_narrative_answers import narrative_answer
        alternatives = [BOOK, {**BOOK, 'author': 'Pablo Vidal',
                               'url': 'https://openlibrary.org/works/OL99872W'}]
        with patch('core.ai_quick_answers.quick_knowledge_sources', return_value=alternatives), \
                patch('core.ai_persistent_router.persist_sources'):
            result = narrative_answer('Dime la trama de Historia del puerto', [])
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'clarification')
        self.assertIn('Ana Robles', result.text)
        self.assertIn('Pablo Vidal', result.text)

    def test_synthesis_exposes_actual_model_calls_and_usage_to_the_view(self):
        from .ai_narrative_answers import narrative_answer
        proof = ('This book explores the history of a port and its relationship '
                 'with the surrounding city.')
        sources = canonical_sources([{**BOOK, 'description': proof, 'synopsis': proof}])
        text = 'La obra explora la historia de un puerto y su relación con la ciudad que lo rodea.'

        class Client:
            calls = 0
            usage = {'prompt_tokens': 12, 'completion_tokens': 14, 'total_tokens': 26}
            stage_timings = []

            def __call__(self, stage, prompt, context, model):
                self.calls += 1
                if stage == 'answer':
                    return {'status': 'answer', 'basis': 'sources', 'text': text,
                            'citations': [1], 'books': [], 'needs_web': False}
                return {'decision': 'approve', 'only_books': True, 'claims': [{
                    'statement': text, 'verdict': 'supported', 'source_id': 1,
                    'evidence': proof}], 'coverage': [{'question_id': 1, 'status': 'answered'}],
                    'issues': [], 'search_queries': []}

        client = Client()
        assistant = SimpleNamespace(answer_model='local-test', guard_model='local-test')
        with patch('core.ai_narrative_answers.retrieve_sources', return_value=sources), \
                patch('core.literary_ai.build_assistant', return_value=(assistant, client)):
            result = narrative_answer('Dime la trama de Historia del puerto', [], config=SimpleNamespace())
        self.assertEqual(result.status, 'answered')
        self.assertEqual(client.calls, 2)
        self.assertEqual(result.diagnostics.get('model_calls'), client.calls)
        self.assertEqual(result.diagnostics.get('usage'), client.usage)
