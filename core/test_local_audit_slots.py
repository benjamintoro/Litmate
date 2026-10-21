"""Contrato local realista: cada frase estricta tiene un campo obligatorio único.

HTTP y modelo simulados; no se consulta Ollama, Internet ni bases de producción.
"""
import copy
import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .literary_ai import ProviderUnavailable, canonical_sources
from .literary_quality import AUDIT_SCHEMA, validate_audit
from .local_llm import OllamaJSON
from .test_local_ai import SHOW, response


FACTS = [
    'La biblioteca de la isla conserva recuerdos.',
    'El atlas de la montaña describe caminos.',
    'El diario del faro reúne testimonios.',
]
SOURCES = canonical_sources([{
    'kind': 'book', 'title': 'Tres catálogos de prueba', 'author': 'Autora ficticia de prueba',
    'description': ' '.join(FACTS), 'source': 'Fixture controlado',
}])
PLAN = {'questions': ['Recomienda tres catálogos'], 'search_queries': [],
        'needs_contents': False, 'needs_fresh_sources': False, 'spoilers_requested': False}


def audit_claim(statement):
    return {'statement': statement, 'verdict': 'supported', 'source_id': 1,
            'evidence': statement}


def wire_audit():
    return {'decision': 'approve', 'only_books': True,
            'coverage': [{'question_id': 1, 'status': 'answered'}],
            'claims': {'c' + str(i): audit_claim(fact) for i, fact in enumerate(FACTS, 1)},
            'search_queries': [], 'issues': []}


class StrictAuditSlotTests(SimpleTestCase):
    def context(self, **extra):
        return {'message': PLAN['questions'][0], 'plan': PLAN, 'sources': SOURCES,
                'all_factual_claims_required': True,
                'draft': {'status': 'answer', 'basis': 'sources', 'text': ' '.join(FACTS),
                          'citations': [1], 'books': [], 'needs_web': False}, **extra}

    def run_audit(self, result, **extra):
        client = OllamaJSON()
        def local_response(url, **kwargs):
            if url.endswith('/api/show'):
                return SHOW
            payload = kwargs['payload']
            data = json.loads(payload['messages'][1]['content'])
            wire = copy.deepcopy(result)
            if payload['format']['properties']['claims']['type'] == 'object' and isinstance(wire.get('claims'), dict):
                for slot, claim in list(wire['claims'].items()):
                    if not isinstance(claim, dict) or 'statement' not in claim:
                        continue
                    if claim['statement'] != data['audit_required_claims'].get(slot):
                        continue  # Simula un proveedor que viola el contrato.
                    proof_id = next((key for key, proof in data['audit_evidence_pool'].items()
                        if proof['source_id'] == claim['source_id'] and claim['evidence'] in proof['evidence']), '')
                    wire['claims'][slot] = {'verdict': claim['verdict'],
                                           'proof_id': proof_id if claim['verdict'] == 'supported' else ''}
            return response(wire)
        fetch = Mock(side_effect=local_response)
        with patch('core.local_llm.read_json_url', fetch):
            parsed = client('audit', 'Audita sin inventar pruebas.', self.context(**extra), 'local-test')
        return parsed, fetch.call_args.kwargs['payload']

    def test_every_fact_has_a_required_distinct_slot_with_a_fixed_input_statement(self):
        parsed, payload = self.run_audit(wire_audit())
        claims = payload['format']['properties']['claims']
        self.assertEqual(claims['type'], 'object')
        self.assertEqual(claims['required'], ['c1', 'c2', 'c3'])
        self.assertEqual(set(claims['properties']), {'c1', 'c2', 'c3'})
        self.assertFalse(claims['additionalProperties'])
        data = json.loads(payload['messages'][1]['content'])
        self.assertEqual(data['audit_required_claims'], dict(zip(claims['required'], FACTS)))
        for slot in claims['required']:
            for alternative in claims['properties'][slot]['anyOf']:
                self.assertEqual(set(alternative['properties']), {'verdict', 'proof_id'})
        self.assertIn('claims debe ser un OBJETO', payload['messages'][0]['content'])
        self.assertEqual([claim['statement'] for claim in parsed['claims']], FACTS)
        self.assertTrue(all(claim['verdict'] == 'supported' and claim['source_id'] == 1
                            and claim['statement'] in claim['evidence'] for claim in parsed['claims']))

    def test_decoded_list_still_passes_the_unchanged_strict_validator(self):
        parsed, _ = self.run_audit(wire_audit())
        context = self.context()
        self.assertEqual(validate_audit(parsed, PLAN, context['draft'], SOURCES,
                                        context['message'], strict_facts=True), parsed)

    def test_transport_cannot_duplicate_first_claim_instead_of_checking_the_second(self):
        result = wire_audit()
        result['claims']['c2'] = copy.deepcopy(result['claims']['c1'])
        with self.assertRaisesRegex(ProviderUnavailable, 'ollama_sin_respuesta_valida'):
            self.run_audit(result)

    def test_missing_extra_swapped_or_array_claims_are_rejected_before_publication(self):
        missing = wire_audit()
        missing['claims'].pop('c3')
        extra = wire_audit()
        extra['claims']['c4'] = audit_claim(FACTS[0])
        swapped = wire_audit()
        swapped['claims']['c1'], swapped['claims']['c2'] = swapped['claims']['c2'], swapped['claims']['c1']
        array = wire_audit()
        array['claims'] = list(array['claims'].values())
        for result in (missing, extra, swapped, array):
            with self.subTest(claims=result['claims']), self.assertRaises(ProviderUnavailable):
                self.run_audit(result)

    def test_wire_dictionary_order_does_not_change_the_draft_order(self):
        result = wire_audit()
        result['claims'] = dict(reversed(list(result['claims'].items())))
        parsed, _ = self.run_audit(result)
        self.assertEqual([claim['statement'] for claim in parsed['claims']], FACTS)

    def test_specific_factual_question_also_uses_required_slots(self):
        _, payload = self.run_audit(wire_audit(), all_factual_claims_required=False,
                                    specific_factual_question=True)
        self.assertEqual(payload['format']['properties']['claims']['required'], ['c1', 'c2', 'c3'])

    def test_repair_audit_checks_each_fact_even_if_decision_is_not_approve(self):
        result = wire_audit()
        result['decision'] = 'repair'
        result['claims']['c2'].update(verdict='unverified', source_id=0, evidence='')
        parsed, _ = self.run_audit(result)
        self.assertEqual(len(parsed['claims']), 3)
        self.assertEqual(parsed['claims'][1]['verdict'], 'unverified')

    def test_nonstrict_audit_keeps_the_existing_array_transport(self):
        result = wire_audit()
        result['claims'] = list(result['claims'].values())
        parsed, payload = self.run_audit(result, all_factual_claims_required=False)
        self.assertEqual(payload['format']['properties']['claims']['type'], 'array')
        self.assertEqual(parsed, result)

    def test_strict_generation_does_not_mutate_the_shared_schema(self):
        original = copy.deepcopy(AUDIT_SCHEMA)
        self.run_audit(wire_audit())
        self.assertEqual(AUDIT_SCHEMA, original)

    def test_auxiliary_arrays_have_the_same_bounds_as_the_existing_validator(self):
        _, payload = self.run_audit(wire_audit())
        for field, maximum, length in (('search_queries', 2, 240), ('issues', 4, 500)):
            with self.subTest(field=field):
                schema = payload['format']['properties'][field]
                self.assertEqual(schema['maxItems'], maximum)
                self.assertEqual(schema['items'], {'type': 'string', 'minLength': 1, 'maxLength': length})

    def test_slots_still_bind_supported_evidence_to_the_source_that_contains_it(self):
        _, payload = self.run_audit(wire_audit())
        pool = json.loads(payload['messages'][1]['content'])['audit_evidence_pool']
        for slot in payload['format']['properties']['claims']['properties'].values():
            supported = [choice['properties'] for choice in slot['anyOf']
                         if choice['properties']['verdict'].get('const') == 'supported']
            self.assertTrue(supported)
            for choice in supported:
                for proof_id in choice['proof_id']['enum']:
                    proof = pool[proof_id]
                    self.assertEqual(proof['source_id'], 1)
                    self.assertTrue(any(proof['evidence'] in SOURCES[0][field]
                                        for field in ('description', 'title', 'author')))

    def supported_choices(self, statement, sources):
        result = wire_audit()
        result['claims'] = {'c1': {'statement': statement, 'verdict': 'unverified',
                                   'source_id': 0, 'evidence': ''}}
        context = self.context()
        context['draft'].update(text=statement, citations=[source['id'] for source in sources])
        _, payload = self.run_audit(result, draft=context['draft'], sources=sources)
        choices = payload['format']['properties']['claims']['properties']['c1']['anyOf']
        pool = json.loads(payload['messages'][1]['content'])['audit_evidence_pool']
        proofs = [pool[proof_id] for choice in choices
                  if choice['properties']['verdict'].get('const') == 'supported'
                  for proof_id in choice['properties']['proof_id']['enum']]
        return [{'source_id': {'const': identifier}, 'evidence': {'enum': [
            proof['evidence'] for proof in proofs if proof['source_id'] == identifier]}}
            for identifier in dict.fromkeys(proof['source_id'] for proof in proofs)]

    def test_description_claim_cannot_select_title_or_author_as_its_proof(self):
        source = SOURCES[0]
        statement = source['title'] + ' describe los recuerdos de una isla.'
        choices = self.supported_choices(statement, SOURCES)
        self.assertTrue(choices)
        for choice in choices:
            self.assertNotIn(source['title'], choice['evidence']['enum'])
            self.assertNotIn(source['author'], choice['evidence']['enum'])
            self.assertIn(source['description'], choice['evidence']['enum'])

    def test_simple_identity_can_still_select_bibliographic_title_or_author(self):
        source = SOURCES[0]
        statement = source['title'] + ' es un libro de ' + source['author'] + '.'
        choices = self.supported_choices(statement, SOURCES)
        self.assertTrue(any(source['title'] in choice['evidence']['enum'] for choice in choices))

    def test_claim_about_one_book_cannot_select_the_other_books_description(self):
        sources = canonical_sources([
            {'kind': 'book', 'title': 'Libro de la isla', 'author': 'Autora primera',
             'description': 'Este libro describe recuerdos de una isla.'},
            {'kind': 'book', 'title': 'Atlas de la montaña', 'author': 'Autor segundo',
             'description': 'Este atlas describe caminos de una montaña.'},
        ])
        choices = self.supported_choices('Libro de la isla describe recuerdos de una isla.', sources)
        self.assertEqual({choice['source_id']['const'] for choice in choices}, {1})

    def test_unsupported_catalogue_style_has_no_supported_alternative(self):
        sources = canonical_sources([{'kind': 'book', 'title': 'A history of Korea',
            'author': 'Kyung Moon Hwang', 'description': 'Temas del catálogo: History, Korea, civilization.',
            'categories': ['History', 'Korea', 'civilization'],
            'read_mode': 'ficha bibliográfica; materias de catálogo, no texto de la obra'}])
        choices = self.supported_choices('A history of Korea presenta una narrativa episódica.', sources)
        self.assertEqual(choices, [])

    def test_supported_catalogue_subject_keeps_its_descriptive_proof(self):
        sources = canonical_sources([{'kind': 'book', 'title': 'A history of Korea',
            'author': 'Kyung Moon Hwang', 'description': 'Temas del catálogo: History, Korea, civilization.',
            'categories': ['History', 'Korea', 'civilization']}])
        choices = self.supported_choices('A history of Korea está catalogado como historia de Corea.', sources)
        self.assertTrue(choices)
        self.assertTrue(all(sources[0]['description'] in choice['evidence']['enum'] for choice in choices))

