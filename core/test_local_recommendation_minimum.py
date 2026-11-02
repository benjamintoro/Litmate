"""Un saludo y tarjetas no sustituyen el texto de las recomendaciones."""
import copy
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .literary_ai import ANSWER_SCHEMA
from .local_llm import OllamaJSON
from .test_local_ai import SHOW, response


SOURCES = [{'id': 1, 'kind': 'book', 'title': 'Un título largo', 'author': 'Primera autora'},
           {'id': 2, 'kind': 'book', 'title': 'Otro título', 'author': 'Segundo autor'},
           {'id': 3, 'kind': 'book', 'title': 'Breve', 'author': 'X'}]


class LocalRecommendationMinimumTests(SimpleTestCase):
    def schema(self, stage='answer', **extra):
        data = {'sources': SOURCES, 'require_book_sources': True, 'intent': 'recommend',
                'requested_book_count': 2,
                'recommendation_contract': {'one_short_sentence_per_book': True}, **extra}
        output = {'status': 'clarify', 'books': [], 'text': '¿Qué tema prefieres?'}
        fetch = Mock(side_effect=[SHOW, response(output)])
        with patch('core.local_llm.read_json_url', fetch):
            OllamaJSON()(stage, 'Responde naturalmente.', data, 'local-test')
        return fetch.call_args.kwargs['payload']['format']

    def test_each_answer_stage_requires_at_least_the_n_shortest_identities(self):
        expected = sum(sorted(len(source['title']) + len(source['author']) for source in SOURCES)[:2])
        for stage in ('answer', 'repair', 'answer_web'):
            with self.subTest(stage=stage):
                schema = self.schema(stage)
                self.assertEqual(schema['properties']['text']['minLength'], expected)
                self.assertGreater(expected, len('¡Buen tema!'))
                self.assertNotIn('const', schema['properties']['text'])

    def test_missing_or_disabled_contract_does_not_add_a_text_requirement(self):
        for contract in ({}, {'one_short_sentence_per_book': False}):
            with self.subTest(contract=contract):
                self.assertNotIn('minLength', self.schema(recommendation_contract=contract)['properties']['text'])

    def test_invalid_count_or_insufficient_identities_does_not_add_a_requirement(self):
        for count in (None, 0, True, 6, 4):
            with self.subTest(count=count):
                self.assertNotIn('minLength', self.schema(requested_book_count=count)['properties']['text'])

    def test_shared_schema_and_input_identities_remain_unchanged(self):
        original, identities = copy.deepcopy(ANSWER_SCHEMA), copy.deepcopy(SOURCES)
        self.schema()
        self.assertEqual(ANSWER_SCHEMA, original)
        self.assertEqual(SOURCES, identities)

