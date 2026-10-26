"""Contrato de evidencias acotadas: proveedores y respuestas siempre simulados."""
from copy import deepcopy
import json
import re
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from .literary_ai import ProviderUnavailable, canonical_sources
from .local_llm import OllamaJSON


PROMOTION = 'A highly accessible and engaging textbook for students and teachers.'
CONTENTS = ('Table of Contents: 1. Ports 2. Ships 3. Rivers '
            '4. Bridges 5. Markets 6. Coasts')
PASSAGE = '3. Rivers 4. Bridges 5. Markets'
STATEMENT = 'Entre los temas que aborda están los ríos, los puentes y los mercados.'


def sources():
    return canonical_sources([
        {'kind': 'book', 'title': 'Atlas del comercio', 'author': 'Ana Robles',
         'source': 'Open Library', 'url': 'https://openlibrary.org/works/OL99881W',
         'description': 'Temas del catálogo: History, Trade.', 'categories': ['History', 'Trade']},
        {'kind': 'web', 'title': 'Atlas del comercio', 'author': 'Fuente web',
         'source': 'DuckDuckGo', 'url': 'https://www.mheducation.com/example-atlas.html',
         'description': PROMOTION + ' ' + CONTENTS,
         'identity_text': 'Atlas del comercio es un libro de Ana Robles.',
         'extraction_method': 'trafilatura+structured_contents',
         'permanent_index_allowed': False},
    ])


def audit_context(*, scoped=True, units=None, cited=(2,)):
    return {'message': 'Explica los temas de Atlas del comercio.', 'sources': sources(),
            'plan': {'questions': ['Qué temas aborda']},
            'draft': {'status': 'answer', 'basis': 'sources', 'text': STATEMENT,
                      'citations': list(cited), 'books': [], 'needs_web': False},
            'all_factual_claims_required': True,
            'narrative_contract': {'content_proofs_only': scoped},
            'task_evidence': [{'source_id': 2, 'evidence': PASSAGE}] if units is None else units}


def compact_response(claim):
    return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({
        'decision': 'approve' if claim['verdict'] == 'supported' else 'repair',
        'only_books': True, 'coverage': [{'question_id': 1, 'status': 'answered'}],
        'claims': {'c1': claim}, 'search_queries': [], 'issues': []})}}


class ScopedNarrativeEvidenceTests(SimpleTestCase):
    def transport(self, context, *, reply=None):
        captured = []
        client = OllamaJSON()

        def fetch(url, **kwargs):
            payload = deepcopy(kwargs['payload'])
            captured.append(payload)
            data = json.loads(payload['messages'][1]['content'])
            pool = data.get('audit_evidence_pool', {})
            claim = ({'verdict': 'supported', 'proof_id': next(iter(pool))} if pool else
                     {'verdict': 'unverified', 'proof_id': ''})
            return compact_response(claim if reply is None else reply)

        with patch.object(client, 'inspect_model', return_value={'capabilities': ['completion']}), \
                patch('core.local_llm.read_json_url', side_effect=fetch):
            result = client('audit', 'Comprueba la evidencia.', context, 'local-test')
        return result, captured[0]

    def test_scoped_audit_has_only_the_literal_content_passage_not_marketing(self):
        result, payload = self.transport(audit_context())
        context = json.loads(payload['messages'][1]['content'])
        self.assertEqual(list(context['audit_evidence_pool'].values()),
                         [{'source_id': 2, 'evidence': PASSAGE}])
        self.assertEqual(result['claims'][0]['evidence'], PASSAGE)
        original = next(source for source in context['sources'] if source['id'] == 2)
        self.assertIn(PROMOTION, original['description'])
        self.assertIn(CONTENTS, original['description'])
        choices = payload['format']['properties']['claims']['properties']['c1']['anyOf']
        self.assertEqual(len(choices), 2)
        self.assertEqual(choices[0]['properties']['proof_id']['enum'], ['p1'])

    def test_fabricated_wrong_origin_and_oversized_units_cannot_be_supported(self):
        for unit in (
            {'source_id': 2, 'evidence': '3. Invented wars 4. Invented dates'},
            {'source_id': 99, 'evidence': PASSAGE},
            {'source_id': 1, 'evidence': PASSAGE},
            {'source_id': 2, 'evidence': 'x' * 301},
        ):
            with self.subTest(unit=unit):
                result, payload = self.transport(audit_context(units=[unit]))
                context = json.loads(payload['messages'][1]['content'])
                self.assertEqual(context['audit_evidence_pool'], {})
                choices = payload['format']['properties']['claims']['properties']['c1']['anyOf']
                self.assertTrue(all(choice['properties']['verdict'].get('const') != 'supported'
                                    for choice in choices))
                self.assertEqual(result['claims'][0]['verdict'], 'unverified')

    def test_model_cannot_select_a_proof_id_excluded_by_the_content_scope(self):
        with self.assertRaises(ProviderUnavailable):
            self.transport(audit_context(), reply={'verdict': 'supported', 'proof_id': 'p999'})

    def test_normal_audit_preserves_its_original_proof_candidates(self):
        _, payload = self.transport(audit_context(scoped=False, units=[]))
        context = json.loads(payload['messages'][1]['content'])
        proofs = list(context['audit_evidence_pool'].values())
        self.assertTrue(any(PROMOTION in proof['evidence'] for proof in proofs))
        self.assertTrue(all(proof['source_id'] == 2 for proof in proofs))
        self.assertTrue(any('Bridges' in proof['evidence'] for proof in proofs))

    def test_index_generation_is_scoped_but_audit_retains_original_sources(self):
        from .ai_narrative_answers import request_for, synthesize_answer
        captured = {}

        class Client:
            calls = 0
            usage = {}
            stage_timings = []

            def __call__(self, stage, prompt, context, model):
                self.calls += 1
                captured[stage] = deepcopy(context)
                if stage == 'answer':
                    return {'status': 'answer', 'basis': 'sources', 'text': STATEMENT,
                            'citations': [2], 'books': [], 'needs_web': False}
                proof = context['task_evidence'][0]
                return {'decision': 'approve', 'only_books': True,
                        'coverage': [{'question_id': 1, 'status': 'answered'}],
                        'issues': [], 'search_queries': [], 'claims': [{
                            'statement': STATEMENT, 'verdict': 'supported', **proof}]}

        original = sources()
        client = Client()
        with patch('core.literary_ai.build_assistant', return_value=(
                SimpleNamespace(answer_model='local-test', guard_model='local-test'), client)):
            result, _ = synthesize_answer('Dime la trama de Atlas del comercio',
                request_for('Dime la trama de Atlas del comercio'), original, SimpleNamespace())
        self.assertEqual(result.status, 'answered')
        self.assertEqual(client.calls, 2)
        generation, audit = captured['answer'], captured['audit']
        self.assertTrue(generation['narrative_contract']['content_proofs_only'])
        self.assertEqual(generation['task_evidence'], [{'source_id': 2, 'evidence': PASSAGE}])
        self.assertEqual(len(re.findall(r'\d+\.\s', PASSAGE)), 3)
        self.assertTrue(all(source.get('description', '') in {'', PASSAGE}
                            for source in generation['sources']))
        self.assertNotIn(PROMOTION, json.dumps(generation))
        self.assertEqual(generation['selected_books'], [])
        self.assertEqual(audit['sources'], original)
        self.assertTrue(all(unit['evidence'] in original[unit['source_id'] - 1]['description']
                            for unit in audit['task_evidence']))

    def test_catalogue_subjects_cannot_bypass_the_scoped_content_evidence(self):
        _, payload = self.transport(audit_context(cited=(1, 2)))
        context = json.loads(payload['messages'][1]['content'])
        self.assertEqual(list(context['audit_evidence_pool'].values()),
                         [{'source_id': 2, 'evidence': PASSAGE}])
