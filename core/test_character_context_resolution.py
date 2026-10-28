"""Contexto de personajes con evidencia simulada, sin red ni modelo."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .ai_character_answers import request_for
from .literary_identity import normalize_identity


BOOK = {'kind': 'book', 'title': 'Crónicas del roble', 'author': 'Una Autora',
        'source': 'Conocimiento literario local', 'url': 'https://example.org/cronicas'}
FACTS = [
    {'name': 'Rafael de la Vega', 'role': 'Es el protagonista que busca un mapa.'},
    {'name': 'Vera', 'role': 'Es la antagonista que intenta recuperar el mapa.'},
    {'name': 'Clara', 'role': 'Es amiga de Rafael de la Vega.'},
]
PAGE = {'kind': 'web', 'title': BOOK['title'], 'author': 'Fuente web',
        'source': 'Conocimiento literario local', 'url': BOOK['url'], 'license': 'CC0-1.0',
        'work_title': BOOK['title'], 'work_author': BOOK['author'], 'work_binding_verified': True,
        'description': '\n'.join(fact['name'] + ': ' + fact['role'] for fact in FACTS),
        'character_facts': FACTS}


def history(question='¿Quién es Rafael de la Vega?', answer='Rafael busca un mapa.', page=None):
    return [{'accepted': True, 'question': question, 'answer': answer,
             'books': [deepcopy(BOOK)], 'sources': [deepcopy(BOOK), deepcopy(page or PAGE)]}]


class CharacterContextResolutionTests(SimpleTestCase):
    def test_relation_pronoun_uses_last_explicit_character_and_keeps_work(self):
        for question in ('¿Qué relación tiene con Clara?', '¿Y qué relación tiene con Clara?',
                         '¿Cuál es su relación con Clara?'):
            with self.subTest(question=question):
                request = request_for(question, history())
                self.assertIsNotNone(request)
                self.assertEqual(request['task'], 'relationship')
                self.assertEqual([normalize_identity(name) for name in request['names']],
                                 ['rafael de la vega', 'clara'])
                self.assertEqual(request['title'], BOOK['title'])

    def test_singular_antagonist_is_a_narrative_role_not_a_character_name(self):
        for question in ('¿Quién es el antagonista?', '¿Quién es su antagonista?',
                         '¿Quién es el villano?'):
            with self.subTest(question=question):
                request = request_for(question, history())
                self.assertIsNotNone(request)
                self.assertEqual(request['task'], 'characters')
                self.assertEqual(request['focus'], 'antagonist')
                self.assertEqual(request['names'], [])
                self.assertEqual(request['title'], BOOK['title'])

    def test_previous_protagonist_is_resolved_from_a_literal_character_role(self):
        request = request_for('¿Qué relación tiene con Clara?', history(
            '¿Quién es el protagonista?', '**Rafael de la Vega**: Es el protagonista que busca un mapa.'))
        self.assertIsNotNone(request)
        self.assertEqual([normalize_identity(name) for name in request['names']],
                         ['rafael de la vega', 'clara'])

    def test_character_object_relation_uses_the_literal_role_not_the_generated_answer(self):
        question = '¿Qué relación tiene ese antagonista con el mapa?'
        request = request_for(question, history(
            '¿Quién es el antagonista?', '**Vera**: Es la antagonista que intenta recuperar el mapa.'))
        self.assertIsNotNone(request)
        self.assertEqual(request['task'], 'object_relation')
        self.assertFalse(request['ambiguous'])
        self.assertEqual(request['title'], BOOK['title'])
        from .ai_character_answers import object_relation_answer
        result = object_relation_answer(question, request, [deepcopy(PAGE)])
        self.assertIsNotNone(result)
        self.assertIn('recuperar el mapa', result.text)

    def test_generated_answer_alone_cannot_prove_the_referred_antagonist(self):
        page = deepcopy(PAGE)
        page['character_facts'][1]['role'] = 'Es una habitante del puerto.'
        page['description'] = '\n'.join(fact['name'] + ': ' + fact['role'] for fact in page['character_facts'])
        request = request_for('¿Qué relación tiene ese antagonista con el mapa?', history(
            '¿Quién es el antagonista?', '**Vera** es la antagonista.', page))
        self.assertIsNotNone(request, 'No dejar que una referencia literaria se convierta en un concepto general.')
        self.assertTrue(request['ambiguous'])

    def test_two_supported_antagonists_require_clarification_for_that_antagonist(self):
        page = deepcopy(PAGE)
        page['character_facts'].append({'name': 'Iria', 'role': 'Es la antagonista secundaria de la novela.'})
        page['description'] += '\nIria: Es la antagonista secundaria de la novela.'
        request = request_for('¿Qué relación tiene ese antagonista con el mapa?', history(
            '¿Quiénes son los antagonistas?', '**Vera** e **Iria** son antagonistas.', page))
        self.assertIsNotNone(request)
        self.assertTrue(request['ambiguous'])

    def test_a_failed_turn_cannot_donate_a_character_to_the_next_question(self):
        turns = history()
        turns.append({'accepted': False, 'question': '¿Quién es Iria?', 'answer': 'Iria es una reina.',
                      'books': [BOOK], 'sources': []})
        request = request_for('¿Qué relación tiene con Clara?', turns)
        self.assertIsNotNone(request)
        self.assertEqual(normalize_identity(request['names'][0]), 'rafael de la vega')

    def test_unrelated_work_cannot_supply_the_referred_role(self):
        turns = history('¿Quién es el antagonista?', '**Vera** es la antagonista.')
        other = {**BOOK, 'title': 'La costa lejana', 'author': 'Otra Autora'}
        turns.append({'accepted': True, 'question': 'Ahora hablemos de La costa lejana',
                      'answer': 'Hablemos de esa obra.', 'books': [other], 'sources': [other]})
        request = request_for('¿Qué relación tiene ese antagonista con el mapa?', turns)
        self.assertIsNotNone(request)
        self.assertTrue(request['ambiguous'])
        self.assertNotIn('Vera', request['names'])

    @override_settings(LITMATE_AI_USE_WEB=False)
    def test_general_character_facts_cannot_trigger_synthesis_for_an_unbacked_role(self):
        from .ai_character_answers import character_answer
        page = deepcopy(PAGE)
        page['character_facts'] = page['character_facts'][:1]
        page['description'] = 'Rafael de la Vega: Es el protagonista que busca un mapa.'
        with patch('core.ai_quick_answers.quick_knowledge_sources', return_value=[BOOK, page]), \
                patch('core.literary_memory.retrieve_character_entities', return_value=[]), \
                patch('core.ai_narrative_answers.synthesize_answer',
                      side_effect=AssertionError('Otros papeles no respaldan antagonismo.')) as model:
            result = character_answer('¿Quién es el antagonista de Crónicas del roble?', config=SimpleNamespace())
        self.assertEqual(result.status, 'unavailable')
        self.assertEqual(result.diagnostics['model_calls'], 0)
        model.assert_not_called()
