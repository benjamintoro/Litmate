"""Una sinopsis web conserva su procedencia en el transporte local simulado."""
import copy
import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .literary_ai import recommendation_evidence_sources
from .literary_quality import AUDIT_PROMPT, validate_audit
from .local_llm import OllamaJSON, _external_summary_transport
from .test_local_ai import SHOW, response


SUMMARY = 'Dos exploradoras aceptan dirigir una colonia y descubren un conflicto entre planetas.'
PAGE = SUMMARY + ' La reseña también describe el desenlace de la expedición.'
URL = 'https://es.wikipedia.org/wiki/Rutas_estelares'
STATEMENT = 'Rutas estelares — Alicia Robles: Dos exploradoras aceptan dirigir una colonia.'
PLAN = {'questions': ['Recomienda un libro espacial'], 'search_queries': [],
        'needs_contents': False, 'needs_fresh_sources': False, 'spoilers_requested': False}


def context():
    sources = [
        {'id': 3, 'kind': 'book', 'title': 'Rutas estelares', 'author': 'Alicia Robles',
         'description': 'Temas del catálogo: Science fiction, Space colonies',
         'research_summary': SUMMARY, 'synopsis_source_url': URL},
        {'id': 4, 'kind': 'web', 'title': 'Rutas estelares', 'author': 'Fuente web',
         'description': PAGE, 'url': URL, 'work_title': 'Rutas estelares',
         'work_author': 'Alicia Robles', 'work_binding_verified': True,
         'read_mode': 'pasaje de página pública'},
        {'id': 9, 'kind': 'web', 'title': 'Una fuente discrepante', 'author': 'Fuente web',
         'description': 'Otra fuente contiene una afirmación contradictoria que no debe desaparecer.',
         'url': 'https://biblioteca.example.test/discrepancia'},
    ]
    return {'intent': 'recommend', 'sources': sources, 'message': PLAN['questions'][0],
            'plan': copy.deepcopy(PLAN),
            'recommendation_evidence_sources': recommendation_evidence_sources(sources)}


class ExternalSummaryProjectionTests(SimpleTestCase):
    def test_complete_literal_copy_uses_current_verified_source_without_mutation(self):
        data = context()
        before = copy.deepcopy(data)
        result = _external_summary_transport(data)
        self.assertNotIn('research_summary', result['sources'][0])
        self.assertEqual(result['sources'][0]['research_summary_source_id'], 4)
        self.assertEqual(result['sources'][0]['description'], before['sources'][0]['description'])
        self.assertEqual(result['sources'][0]['title'], before['sources'][0]['title'])
        self.assertEqual(result['sources'][0]['author'], before['sources'][0]['author'])
        self.assertEqual(result['sources'][1:], before['sources'][1:])
        self.assertEqual(data, before)

    def test_partial_paraphrased_or_absent_passage_preserves_original_summary(self):
        for passage in (SUMMARY[:50], SUMMARY.replace('colonia', 'ciudad'), '', None):
            data = context()
            data['sources'][1]['description'] = passage
            with self.subTest(passage=passage):
                result = _external_summary_transport(data)
                self.assertEqual(result, data)
                self.assertEqual(result['sources'][0]['research_summary'], SUMMARY)

    def test_blank_or_nontext_copy_is_never_removed(self):
        for summary in ('', '   ', None, 42):
            data = context()
            data['sources'][0]['research_summary'] = summary
            with self.subTest(summary=summary):
                self.assertEqual(_external_summary_transport(data), data)

    def test_unverified_snippet_injection_wrong_url_or_wrong_work_never_projects(self):
        for changes in ({'work_binding_verified': False}, {'injection_detected': True},
                        {'read_mode': 'fragmento de buscador'},
                        {'url': 'https://es.wikipedia.org/wiki/Otra_obra'},
                        {'work_title': 'Otra novela'}, {'work_author': 'Otra Autora'}):
            data = context()
            data['sources'][1].update(changes)
            with self.subTest(changes=changes):
                self.assertEqual(_external_summary_transport(data), data)

    def test_forged_stale_missing_or_boolean_mapping_cannot_reassign_provenance(self):
        for mapping in ([], None, [{'book_source_id': 3, 'web_source_id': 9}],
                        [{'book_source_id': 3, 'web_source_id': 40}],
                        [{'book_source_id': True, 'web_source_id': 4}],
                        ['malformed']):
            data = context()
            data['recommendation_evidence_sources'] = mapping
            with self.subTest(mapping=mapping):
                self.assertEqual(_external_summary_transport(data), data)

    def test_all_sources_including_contradictory_and_uncited_sources_are_retained(self):
        data = context()
        result = _external_summary_transport(data)
        self.assertEqual([source['id'] for source in result['sources']], [3, 4, 9])
        self.assertEqual(result['sources'][1]['description'], PAGE)
        self.assertEqual(result['sources'][2], data['sources'][2])

    def test_catalogue_matter_is_not_promoted_when_page_is_missing(self):
        data = context()
        data['sources'] = data['sources'][:1]
        self.assertEqual(_external_summary_transport(data), data)


class ExternalSummaryLLMTransportTests(SimpleTestCase):
    def generate(self, stage, data, wire):
        before = copy.deepcopy(data)
        fetch = Mock(side_effect=[SHOW, response(wire)])
        with patch('core.local_llm.read_json_url', fetch):
            result = OllamaJSON()(stage, 'Instrucción original.', data, 'local-test')
        self.assertEqual(data, before)
        payload = fetch.call_args.kwargs['payload']
        return result, json.loads(payload['messages'][1]['content']), payload

    def test_answer_repair_and_web_answer_keep_model_citations_exactly_as_selected(self):
        wire = {'status': 'answer', 'text': STATEMENT, 'basis': 'sources',
                'citations': [3], 'needs_web': False, 'books': []}
        for stage in ('answer', 'repair', 'answer_web'):
            with self.subTest(stage=stage):
                result, sent, payload = self.generate(stage, context(), wire)
                self.assertEqual(result, wire)
                self.assertEqual(result['citations'], [3])  # No cita web añadida.
                self.assertNotIn('research_summary', sent['sources'][0])
                self.assertEqual(sent['sources'][0]['research_summary_source_id'], 4)
                self.assertEqual(sent['sources'][1]['description'], PAGE)
                self.assertEqual([s['id'] for s in sent['sources']], [3, 4, 9])
                self.assertIn('si no los usas', payload['messages'][0]['content'])
                # La página sigue disponible, pero el esquema nunca obliga a citarla.
                self.assertEqual(payload['format']['properties']['citations']['items']['enum'], [3, 4, 9])
                self.assertNotIn('minItems', payload['format']['properties']['citations'])

    def test_audit_retains_projection_and_complete_evidence_in_compact_proof_pool(self):
        data = context()
        data['all_factual_claims_required'] = True
        data['draft'] = {'status': 'answer', 'text': STATEMENT, 'basis': 'sources',
                         'citations': [3, 4], 'needs_web': False, 'books': []}
        captured = {}

        def local_response(url, **kwargs):
            if url.endswith('/api/show'):
                return SHOW
            payload = kwargs['payload']
            sent = json.loads(payload['messages'][1]['content'])
            claims = {}
            for slot, rule in payload['format']['properties']['claims']['properties'].items():
                allowed = [proof_id for choice in rule['anyOf']
                           if choice['properties']['verdict'].get('const') == 'supported'
                           for proof_id in choice['properties']['proof_id']['enum']
                           if sent['audit_evidence_pool'][proof_id]['source_id'] == 4]
                self.assertTrue(allowed, 'La prueba web real debe estar disponible para su afirmación.')
                claims[slot] = {'verdict': 'supported', 'proof_id': allowed[0]}
            captured.update(sent)
            return response({'decision': 'approve', 'only_books': True, 'coverage': [
                {'question_id': 1, 'status': 'answered'}], 'claims': claims, 'issues': [], 'search_queries': []})

        before = copy.deepcopy(data)
        with patch('core.local_llm.read_json_url', side_effect=local_response):
            result = OllamaJSON()('audit', AUDIT_PROMPT, data, 'local-test')
        self.assertEqual(data, before)
        self.assertNotIn('research_summary', captured['sources'][0])
        self.assertEqual(captured['sources'][0]['research_summary_source_id'], 4)
        self.assertEqual(captured['sources'][2]['description'], before['sources'][2]['description'])
        self.assertEqual(result['claims'][0]['source_id'], 4)
        self.assertIn(SUMMARY, result['claims'][0]['evidence'])
        self.assertEqual(validate_audit(result, PLAN, data['draft'], data['sources'],
                                        data['message'], strict_facts=True), result)
        # La referencia ausente no se rellena ni se permite al publicar la auditoría.
        uncited = {**data['draft'], 'citations': [3]}
        with self.assertRaises(ValueError):
            validate_audit(result, PLAN, uncited, data['sources'], data['message'], strict_facts=True)

    def test_noncompact_audit_preserves_full_page_and_uncited_disagreement(self):
        wire = {'decision': 'repair', 'only_books': True, 'coverage': [],
                'claims': [], 'issues': [], 'search_queries': []}
        result, sent, _ = self.generate('audit', context(), wire)
        self.assertEqual(result, wire)
        self.assertNotIn('research_summary', sent['sources'][0])
        self.assertEqual(sent['sources'][1]['description'], PAGE)
        self.assertEqual(sent['sources'][2]['description'], context()['sources'][2]['description'])

    def test_missing_web_citation_still_has_no_allowed_narrative_proof(self):
        data = context()
        data['all_factual_claims_required'] = True
        data['draft'] = {'status': 'answer', 'text': STATEMENT, 'basis': 'sources',
                         'citations': [3], 'needs_web': False, 'books': []}
        captured = {}

        def local_response(url, **kwargs):
            if url.endswith('/api/show'):
                return SHOW
            payload = kwargs['payload']
            captured.update(json.loads(payload['messages'][1]['content']))
            claims = {}
            for slot, rule in payload['format']['properties']['claims']['properties'].items():
                self.assertFalse(any(choice['properties']['verdict'].get('const') == 'supported'
                                     for choice in rule['anyOf']))
                claims[slot] = {'verdict': 'unverified', 'proof_id': ''}
            return response({'decision': 'repair', 'only_books': True, 'coverage': [
                {'question_id': 1, 'status': 'answered'}], 'claims': claims,
                'issues': ['Falta citar el pasaje narrativo recibido.'], 'search_queries': []})

        with patch('core.local_llm.read_json_url', side_effect=local_response):
            result = OllamaJSON()('audit', AUDIT_PROMPT, data, 'local-test')
        self.assertTrue(all(proof['source_id'] != 4
                            for proof in captured['audit_evidence_pool'].values()))
        self.assertEqual(captured['draft']['citations'], [3])
        self.assertEqual(result['claims'][0]['verdict'], 'unverified')
        self.assertNotIn('research_summary', captured['sources'][0])
        self.assertEqual(captured['sources'][1]['description'], PAGE)
        self.assertEqual(validate_audit(result, PLAN, data['draft'], data['sources'],
                                        data['message'], strict_facts=True), result)
        self.assertEqual(result['decision'], 'repair')

    def test_control_stage_does_not_rewrite_source_transport(self):
        wire = {'decision': 'allow', 'intent': 'recommend', 'queries': [],
                'candidates': [], 'followup': False, 'clarification': ''}
        _, sent, payload = self.generate('route', context(), wire)
        self.assertEqual(sent['sources'][0]['research_summary'], SUMMARY)
        self.assertNotIn('PROCEDENCIA DE SINOPSIS', payload['messages'][0]['content'])

    def test_spoiler_guard_evaluates_draft_literal_without_disabling_existing_protection(self):
        self.assertIn('No revelar finales si no se solicitaron.', AUDIT_PROMPT)
        self.assertIn('afirmación literal del borrador', AUDIT_PROMPT)
        self.assertIn('No atribuyas al borrador esos pasajes que no contiene.', AUDIT_PROMPT)
