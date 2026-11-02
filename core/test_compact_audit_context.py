"""El ahorro de contexto elimina copias, manteniendo todas las pruebas literales."""
import copy
import json

from django.test import SimpleTestCase

from .local_llm import OllamaJSON, _compact_audit_descriptions
from .literary_quality import AUDIT_PROMPT


class CompactAuditContextTests(SimpleTestCase):
    def test_fully_covered_description_uses_ordered_proofs_of_its_own_source(self):
        text = 'Una descripción original que debe conservarse literalmente en el pool.'
        source = {'id': 1, 'description': text, 'synopsis': text, 'title': 'La obra'}
        pool = {'p1': {'source_id': 1, 'evidence': text[:45]},
                'p2': {'source_id': 1, 'evidence': text[35:]}}
        data = {'sources': [source], 'audit_evidence_pool': pool}
        before = copy.deepcopy(data)
        result = _compact_audit_descriptions(data, pool)
        self.assertNotIn('description', result['sources'][0])
        self.assertNotIn('synopsis', result['sources'][0])
        self.assertEqual(result['sources'][0]['description_proof_ids'], ['p1', 'p2'])
        self.assertEqual(result['audit_evidence_pool'], pool)
        self.assertEqual(data, before)

    def test_incomplete_evidence_or_wrong_source_never_removes_original_description(self):
        text = 'La descripción contiene una parte conocida y otra parte adicional.'
        source = {'id': 1, 'description': text}
        for pool in ({'p1': {'source_id': 2, 'evidence': text}},
                     {'p1': {'source_id': 1, 'evidence': text[:20]}}, {}):
            with self.subTest(pool=pool):
                result = _compact_audit_descriptions({'sources': [source]}, pool)
                self.assertEqual(result['sources'][0]['description'], text)

    def test_contradictory_or_uncited_source_without_pool_stays_available(self):
        source = {'id': 2, 'description': 'Una fuente contradice el dato de la primera.'}
        pool = {'p1': {'source_id': 1, 'evidence': 'El dato de la primera fuente.'}}
        self.assertEqual(_compact_audit_descriptions({'sources': [source]}, pool)['sources'], [source])

    def test_8k_transport_can_fit_complete_evidence_without_duplicating_descriptions(self):
        # Fuentes controladas grandes: todas las evidencias permanecen idénticas.
        text = 'Las estrellas y el cielo aparecen en esta descripción autorizada. ' * 25
        sources = [{'id': index, 'kind': 'web', 'title': 'Ficha ' + str(index),
                    'description': text} for index in range(1, 4)]
        pool = {}
        for source in sources:
            for start in range(0, len(text), 250):
                pool['p' + str(len(pool) + 1)] = {'source_id': source['id'], 'evidence': text[start:start + 300]}
        data = {'sources': sources, 'audit_evidence_pool': pool,
                'draft': {'text': 'Una afirmación que se debe auditar completa.'}}
        compact = _compact_audit_descriptions(data, pool)
        self.assertEqual(compact['audit_evidence_pool'], pool)
        self.assertEqual(compact['draft'], data['draft'])
        self.assertLess(len(json.dumps(compact)), len(json.dumps(data)))
        result = json.loads(OllamaJSON(context=8192)._fit_context(AUDIT_PROMPT, compact, 2048))
        self.assertEqual(result['audit_evidence_pool'], pool)
        self.assertTrue(all(source.get('description_proof_ids') for source in result['sources']))

