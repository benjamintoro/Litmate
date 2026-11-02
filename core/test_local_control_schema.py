"""Los límites del transporte coinciden con los validadores de control existentes."""
import copy
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .literary_ai import ROUTE_SCHEMA, REVIEW_SCHEMA, validate_route, validate_review
from .literary_quality import PLAN_SCHEMA, validate_plan
from .local_llm import OllamaJSON
from .test_local_ai import SHOW, response


ROUTE = {'decision': 'allow', 'intent': 'identify', 'queries': ['Una consulta'],
         'candidates': [{'title': 'Una obra', 'author': 'Su autor'}],
         'followup': False, 'clarification': ''}
PLAN = {'questions': ['¿Qué obra es?'], 'search_queries': [], 'needs_contents': False,
        'needs_fresh_sources': False, 'spoilers_requested': False}


class LocalControlSchemaTests(SimpleTestCase):
    def schema(self, stage, result):
        fetch = Mock(side_effect=[SHOW, response(result)])
        with patch('core.local_llm.read_json_url', fetch):
            parsed = OllamaJSON()(stage, 'Solo JSON.', {'message': 'Una consulta literaria'}, 'local-test')
        self.assertEqual(parsed, result)
        return fetch.call_args.kwargs['payload']['format']['properties']

    def test_route_and_rescue_limit_queries_candidates_fields_and_clarification(self):
        for stage in ('route', 'route_rescue'):
            with self.subTest(stage=stage):
                schema = self.schema(stage, ROUTE)
                self.assertEqual(schema['queries'], {'type': 'array', 'maxItems': 2,
                    'items': {'type': 'string', 'minLength': 1, 'maxLength': 240}})
                self.assertEqual(schema['candidates']['maxItems'], 3)
                for name in ('title', 'author'):
                    self.assertEqual(schema['candidates']['items']['properties'][name],
                                     {'type': 'string', 'minLength': 1, 'maxLength': 220})
                self.assertEqual(schema['clarification']['maxLength'], 500)
                self.assertNotIn('minLength', schema['clarification'])

    def test_actual_six_query_regression_remains_rejected_by_the_validator(self):
        with self.assertRaisesRegex(ValueError, 'Consultas inválidas'):
            validate_route({**ROUTE, 'queries': ['pista ' + str(index) for index in range(6)]})

    def test_valid_route_boundaries_and_empty_optional_fields_still_pass(self):
        route = {**ROUTE, 'queries': ['a' * 240, 'b' * 240], 'clarification': 'c' * 500,
                 'candidates': [{'title': 't' * 220, 'author': 'a' * 220} for _ in range(3)]}
        self.assertEqual(validate_route(route), route)
        self.schema('route', route)
        self.schema('route', {**ROUTE, 'queries': [], 'candidates': [], 'clarification': ''})

    def test_plan_enforces_one_to_five_bounded_questions_and_two_bounded_searches(self):
        schema = self.schema('plan', PLAN)
        self.assertEqual(schema['questions'], {'type': 'array', 'minItems': 1, 'maxItems': 5,
            'items': {'type': 'string', 'minLength': 1, 'maxLength': 400}})
        self.assertEqual(schema['search_queries'], {'type': 'array', 'maxItems': 2,
            'items': {'type': 'string', 'minLength': 1, 'maxLength': 240}})
        self.assertEqual(validate_plan(PLAN), PLAN)

    def test_plan_cannot_remove_existing_semantic_validation_of_whitespace(self):
        for fields in ({'questions': []}, {'questions': [' ']}, {'search_queries': ['']}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                validate_plan({**PLAN, **fields})

    def test_review_keeps_its_existing_contract_including_empty_issue_strings(self):
        review = {'decision': 'approve', 'only_books': True, 'issues': ['', 'i' * 500]}
        self.assertEqual(validate_review(review), review)
        schema = self.schema('review', review)
        self.assertEqual(schema['issues'], {'type': 'array', 'maxItems': 4,
                                           'items': {'type': 'string', 'maxLength': 500}})

    def test_shared_schema_dictionaries_remain_unchanged(self):
        original = [copy.deepcopy(schema) for schema in (ROUTE_SCHEMA, PLAN_SCHEMA, REVIEW_SCHEMA)]
        self.schema('route', ROUTE)
        self.schema('plan', PLAN)
        self.schema('review', {'decision': 'approve', 'only_books': True, 'issues': []})
        self.assertEqual([ROUTE_SCHEMA, PLAN_SCHEMA, REVIEW_SCHEMA], original)

