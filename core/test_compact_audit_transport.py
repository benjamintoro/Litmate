"""Auditoría compacta: elegir una prueba nunca sustituye su validación literal.

Transporte Ollama simulado, sin red ni base de datos de la aplicación.
"""
import copy
import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .literary_ai import ProviderUnavailable, canonical_sources
from .literary_quality import validate_audit
from .local_llm import OllamaJSON
from .test_local_ai import SHOW, response


SOURCES = canonical_sources([
    {'kind': 'book', 'title': 'Libro del cielo', 'author': 'Autora celeste',
     'description': 'Este libro describe el cielo y las estrellas.'},
    {'kind': 'book', 'title': 'Libro del campo', 'author': 'Autor terrestre',
     'description': 'Este libro describe el campo y sus animales.'},
])
STATEMENTS = ['Libro del cielo describe el cielo y las estrellas.',
              'Libro del campo describe el campo y sus animales.']
PLAN = {'questions': ['Recomienda dos libros'], 'search_queries': [],
        'needs_contents': False, 'needs_fresh_sources': False, 'spoilers_requested': False}


class CompactAuditTransportTests(SimpleTestCase):
    def context(self):
        return {'message': PLAN['questions'][0], 'plan': PLAN, 'sources': SOURCES,
                'all_factual_claims_required': True,
                'draft': {'status': 'answer', 'basis': 'sources', 'text': ' '.join(STATEMENTS),
                          'citations': [1, 2], 'books': [], 'needs_web': False}}

    def generate(self, alter=None, context=None):
        captured = {}
        def local_response(url, **kwargs):
            if url.endswith('/api/show'):
                return SHOW
            payload = kwargs['payload']
            data = json.loads(payload['messages'][1]['content'])
            claims = {}
            for slot, rule in payload['format']['properties']['claims']['properties'].items():
                supported = next((choice['properties'] for choice in rule['anyOf']
                                  if choice['properties']['verdict'].get('const') == 'supported'), None)
                claims[slot] = ({'verdict': 'supported', 'proof_id': supported['proof_id']['enum'][0]}
                                if supported else {'verdict': 'unverified', 'proof_id': ''})
            wire = {'decision': 'approve', 'only_books': True, 'claims': claims,
                    'coverage': [{'question_id': 1, 'status': 'answered'}], 'issues': [], 'search_queries': []}
            if alter:
                alter(wire, data)
            captured.update(payload=payload, input=data, wire=copy.deepcopy(wire))
            return response(wire)
        fetch = Mock(side_effect=local_response)
        with patch('core.local_llm.read_json_url', fetch):
            result = OllamaJSON()('audit', 'Comprueba todos los datos.', context or self.context(), 'local-test')
        return result, captured

    def test_compact_output_hydrates_exact_original_statements_sources_and_proofs(self):
        result, captured = self.generate()
        self.assertEqual(list(captured['input']['audit_required_claims'].values()), STATEMENTS)
        self.assertEqual([claim['statement'] for claim in result['claims']], STATEMENTS)
        self.assertEqual([claim['source_id'] for claim in result['claims']], [1, 2])
        self.assertEqual([claim['evidence'] for claim in result['claims']],
                         [source['description'] for source in SOURCES])
        self.assertTrue(all(set(value) == {'verdict', 'proof_id'}
                            for value in captured['wire']['claims'].values()))
        self.assertEqual(validate_audit(result, PLAN, self.context()['draft'], SOURCES,
                                        PLAN['questions'][0], strict_facts=True), result)
        self.assertLess(len(json.dumps(captured['wire']['claims'])), len(json.dumps(result['claims'])) * .6)

    def test_wrong_book_proof_cannot_be_reused_for_another_slot(self):
        def alter(wire, data):
            wire['claims']['c2']['proof_id'] = wire['claims']['c1']['proof_id']
        with self.assertRaises(ProviderUnavailable):
            self.generate(alter)

    def test_unknown_empty_or_forged_supported_proof_is_rejected(self):
        for proof_id in ('', 'p999', 'http://127.0.0.1/', 'source_id=1'):
            def alter(wire, data):
                wire['claims']['c1']['proof_id'] = proof_id
            with self.subTest(proof_id=proof_id), self.assertRaises(ProviderUnavailable):
                self.generate(alter)

    def test_unverified_verdict_has_no_fabricated_source_or_evidence(self):
        def alter(wire, data):
            wire.update(decision='repair')
            wire['claims']['c2'] = {'verdict': 'unverified', 'proof_id': ''}
        result, _ = self.generate(alter)
        self.assertEqual(result['claims'][1], {'statement': STATEMENTS[1], 'verdict': 'unverified',
                                             'source_id': 0, 'evidence': ''})

    def test_nonsupported_decision_cannot_smuggle_a_literal_proof(self):
        def alter(wire, data):
            wire['claims']['c1']['verdict'] = 'unverified'
        with self.assertRaises(ProviderUnavailable):
            self.generate(alter)

    def test_missing_slot_or_legacy_fields_are_rejected(self):
        def missing(wire, data):
            wire['claims'].pop('c2')
        def injected(wire, data):
            wire['claims']['c1']['evidence'] = 'Contenido inventado.'
        for alter in (missing, injected):
            with self.subTest(alter=alter.__name__), self.assertRaises(ProviderUnavailable):
                self.generate(alter)

    def test_pool_and_statement_maps_are_created_locally_not_taken_from_input(self):
        context = self.context()
        context.update(audit_required_claims={'c1': 'Otra frase.'},
                       audit_evidence_pool={'p1': {'source_id': 999, 'evidence': 'Falso.'}})
        result, captured = self.generate(context=context)
        self.assertEqual(captured['input']['audit_required_claims']['c1'], STATEMENTS[0])
        self.assertNotIn(999, [proof['source_id'] for proof in captured['input']['audit_evidence_pool'].values()])
        self.assertEqual(result['claims'][0]['source_id'], 1)

    def test_same_real_passage_may_verify_two_different_required_facts(self):
        context = self.context()
        statements = ['Libro del cielo describe el cielo.', 'Libro del cielo describe las estrellas.']
        context['draft'].update(text=' '.join(statements), citations=[1])
        context['sources'] = SOURCES[:1]
        result, captured = self.generate(context=context)
        self.assertEqual([claim['statement'] for claim in result['claims']], statements)
        self.assertEqual(result['claims'][0]['evidence'], result['claims'][1]['evidence'])
        self.assertEqual(len(captured['input']['audit_evidence_pool']), 1)

    def test_private_excerpt_source_zero_remains_local_and_literal(self):
        context = self.context()
        passage = 'La biblioteca del faro guardaba los recuerdos de la isla.'
        context.update(message='Analiza este fragmento: ' + passage, sources=[])
        context['draft'].update(text='El fragmento relaciona la biblioteca con los recuerdos.', citations=[])
        result, _ = self.generate(context=context)
        self.assertEqual(result['claims'][0]['source_id'], 0)
        self.assertEqual(result['claims'][0]['evidence'], passage)

