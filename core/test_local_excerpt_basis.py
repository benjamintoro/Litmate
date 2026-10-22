"""Una sinopsis no habilita basis=excerpt; un fragmento recibido sí lo hace."""
import copy
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .literary_ai import ANSWER_SCHEMA
from .local_llm import OllamaJSON
from .test_local_ai import SHOW, response


class LocalExcerptBasisTests(SimpleTestCase):
    def basis_values(self, stage, data):
        fetch = Mock(side_effect=[SHOW, response({'basis': 'sources'})])
        with patch('core.local_llm.read_json_url', fetch):
            result = OllamaJSON()(stage, 'Responde con evidencia.', data, 'local-test')
        self.assertEqual(result, {'basis': 'sources'})
        return fetch.call_args.kwargs['payload']['format']['properties']['basis']['enum']

    def test_absent_user_and_local_excerpts_excludes_that_basis_in_each_answer_stage(self):
        data = {'has_user_excerpt': False, 'sources': [
            {'kind': 'book', 'title': 'Una obra', 'description': 'Sinopsis editorial.'},
            {'kind': 'web', 'description': 'Resumen de una página pública.'}]}
        for stage in ('answer', 'repair', 'answer_web'):
            with self.subTest(stage=stage):
                values = self.basis_values(stage, data)
                self.assertNotIn('excerpt', values)
                self.assertEqual(set(values), {'sources', 'knowledge', 'mixed'})

    def test_explicit_user_excerpt_preserves_the_excerpt_basis(self):
        for stage in ('answer', 'repair', 'answer_web'):
            with self.subTest(stage=stage):
                self.assertIn('excerpt', self.basis_values(stage, {'has_user_excerpt': True, 'sources': []}))

    def test_actual_retrieved_excerpt_preserves_that_basis_without_user_excerpt(self):
        for stage in ('answer', 'repair', 'answer_web'):
            with self.subTest(stage=stage):
                self.assertIn('excerpt', self.basis_values(stage, {
                    'has_user_excerpt': False, 'sources': [{'kind': 'excerpt', 'description': 'Pasaje real recuperado.'}]}))

    def test_missing_or_nonboolean_excerpt_flag_does_not_trigger_the_restriction(self):
        for data in ({}, {'has_user_excerpt': None}, {'has_user_excerpt': 0}):
            with self.subTest(data=data):
                self.assertIn('excerpt', self.basis_values('answer', data))

    def test_schema_and_caller_data_remain_unchanged(self):
        original = copy.deepcopy(ANSWER_SCHEMA)
        data = {'has_user_excerpt': False, 'sources': []}
        before = copy.deepcopy(data)
        self.basis_values('answer', data)
        self.assertEqual(ANSWER_SCHEMA, original)
        self.assertEqual(data, before)

