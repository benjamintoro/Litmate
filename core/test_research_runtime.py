"""Regresiones del fallo real de auditoría local y límites de investigación.

No contactan al modelo, buscadores ni bases de producción.
"""
import copy
import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from .ai_budget import request_budget
from .literary_ai import canonical_sources
from .literary_quality import AUDIT_SCHEMA, validate_audit
from .literary_sources import SearchResults, error_status
from .literary_web import PublicFetchError, extract_public_page, read_public_json
from .local_llm import OllamaJSON
from .test_ai_quality import PLAN, audit_for
from .test_literary_ai import BOOK, DRAFT
from .test_local_ai import SHOW, response


class LocalAuditRuntimeRegressionTests(SimpleTestCase):
    def emitted_schema(self, draft, *, questions=None, **flags):
        client = OllamaJSON()
        context = {'message': 'Recomiéndame una novela de guerra',
                   'draft': copy.deepcopy(draft), 'sources': canonical_sources([BOOK]),
                   'plan': {**PLAN, 'questions': questions or PLAN['questions']}, **flags}
        def local_response(url, **kwargs):
            if url.endswith('/api/show'):
                return SHOW
            claims = kwargs['payload']['format']['properties']['claims']
            result = {}
            if claims.get('type') == 'object':
                result['claims'] = {slot: {
                    'verdict': 'unverified', 'proof_id': '',
                } for slot, choices in claims['properties'].items()}
            return response(result)
        with patch('core.local_llm.read_json_url', side_effect=local_response) as fetch:
            client('audit', 'Audita el borrador con sus fuentes.', context, 'test-local-model')
        self.assertTrue(fetch.call_args.kwargs['local'])
        self.last_emitted_context = json.loads(fetch.call_args.kwargs['payload']['messages'][1]['content'])
        return fetch.call_args.kwargs['payload']['format']

    def test_answer_generation_cannot_request_empty_audit_that_validator_would_reject(self):
        # Qwen devolvía [] porque el esquema lo permitía, aunque la posterior
        # validación de una respuesta informativa lo rechazaba sistemáticamente.
        schema = self.emitted_schema(DRAFT)
        self.assertGreaterEqual(schema['properties']['claims']['minItems'], 1)
        with self.assertRaisesRegex(ValueError, 'al menos una afirmación'):
            validate_audit(audit_for(claims=[]), PLAN, DRAFT,
                           canonical_sources([BOOK]), 'Recomiéndame una novela de guerra')

    def test_identification_requires_each_statement_without_enabling_event_rules(self):
        draft = {**DRAFT, 'text': 'Las pistas apuntan a una novela conocida. Su protagonista cuida una rosa.'}
        schema = self.emitted_schema(draft, all_factual_claims_required=True,
                                     specific_factual_question=False)
        claims = schema['properties']['claims']
        self.assertEqual(claims['type'], 'object')
        self.assertEqual(claims['required'], ['c1', 'c2'])
        statements = list(self.last_emitted_context['audit_required_claims'].values())
        self.assertEqual(statements, ['Las pistas apuntan a una novela conocida.',
                                      'Su protagonista cuida una rosa.'])
        ordinary = self.emitted_schema(draft, all_factual_claims_required=False)
        self.assertEqual(ordinary['properties']['claims']['minItems'], 1)

    def test_supported_literal_audit_still_passes_the_existing_validator(self):
        sources = canonical_sources([BOOK])
        draft = {**DRAFT, 'text': BOOK['description'], 'citations': [sources[0]['id']]}
        audit = audit_for(draft)
        audit['claims'][0] = {'statement': BOOK['description'][:250], 'verdict': 'supported',
                              'source_id': sources[0]['id'], 'evidence': BOOK['description'][:250]}
        self.assertEqual(validate_audit(audit, PLAN, draft, sources,
                                       'Recomiéndame una novela de guerra'), audit)

    def test_clarification_audit_does_not_require_invented_factual_claim(self):
        draft = {**DRAFT, 'status': 'clarification', 'text': '¿Recuerdas el autor o algún personaje?',
                 'citations': [], 'books': []}
        schema = self.emitted_schema(draft)
        self.assertEqual(schema['properties']['claims']['minItems'], 0)
        audit = audit_for(draft, claims=[])
        audit['coverage'][0]['status'] = 'uncertain'
        self.assertEqual(validate_audit(audit, PLAN, draft, [], 'Recuerdo una escena'), audit)

    def test_answer_constraints_do_not_mutate_shared_schema_or_leak_into_clarification(self):
        original = copy.deepcopy(AUDIT_SCHEMA)
        self.emitted_schema(DRAFT)
        self.assertEqual(AUDIT_SCHEMA, original)
        schema = self.emitted_schema({**DRAFT, 'status': 'clarification'})
        self.assertEqual(schema['properties']['claims']['minItems'], 0)
        self.assertEqual(AUDIT_SCHEMA, original)

    def test_audit_schema_requires_coverage_of_each_question(self):
        schema = self.emitted_schema(DRAFT, questions=['Identifica la obra', 'Explica sus personajes'])
        coverage = schema['properties']['coverage']
        self.assertEqual((coverage['minItems'], coverage['maxItems']), (2, 2))
        self.assertEqual(coverage['items']['properties']['question_id']['enum'], [1, 2])


class PublicFailureClassificationTests(SimpleTestCase):
    def test_transport_failures_are_not_misreported_as_invalid_model_responses(self):
        expected = {'http_403': 'access_denied', 'http_401': 'unauthorized',
                    'service_unavailable': 'unavailable', 'connection_failed': 'unavailable',
                    'dns_failed': 'unavailable', 'dns_busy': 'unavailable',
                    'timeout': 'timeout', 'rate_limited': 'rate_limited'}
        for code, status in expected.items():
            with self.subTest(code=code):
                self.assertEqual(error_status(PublicFetchError(code)), status)

    def test_empty_failed_search_retains_failure_instead_of_becoming_no_results(self):
        for code in ['http_403', 'service_unavailable', 'timeout', 'rate_limited']:
            with self.subTest(code=code):
                result = SearchResults(status=error_status(PublicFetchError(code)))
                self.assertEqual(result, [])
                self.assertNotIn(result.status, {'empty', 'ok'})
        self.assertEqual(SearchResults().status, 'empty')


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                     'LOCATION': 'research-runtime-bounds'}})
class ExternalResearchDeadlineTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_official_api_timeout_cannot_extend_enclosing_research_deadline(self):
        payload = {'body': json.dumps({'query': {}}).encode(), 'content_type': 'application/json'}
        with patch('core.literary_web.time.monotonic', return_value=100), \
                patch('core.literary_web._secure_fetch', return_value=payload) as fetch:
            with request_budget(103):
                read_public_json('https://es.wikipedia.org/w/api.php', timeout=20)
        self.assertEqual(fetch.call_args.kwargs['deadline'], 103)

    def test_robots_and_content_share_one_budget_instead_of_renewing_it(self):
        html = ('<html><title>Personajes</title><main><p>' +
                'Papelucho y Det protagonizan esta aventura de Marcela Paz. ' * 5 +
                '</p></main></html>').encode()
        responses = [{'body': b'User-agent: *\nAllow: /\n', 'content_type': 'text/plain'},
                     {'body': html, 'content_type': 'text/html'}]
        with patch('core.literary_web.time.monotonic', return_value=100), \
                patch('core.literary_web._secure_fetch', side_effect=responses) as fetch:
            with request_budget(103):
                result = extract_public_page('https://literaturasm.cl/obra', 'Det', timeout=20)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual([call.kwargs['deadline'] for call in fetch.call_args_list], [103, 103])
