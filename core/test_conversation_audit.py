"""El auditor se prueba con capturas sintéticas; no ejecuta red ni modelos."""
import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from .conversation_audit import (DIMENSIONS, atomic_json, evaluate_turn, load_bank,
    pick_message, select_cases, summarize, validate_bank)


def row(answer='Frodo es un hobbit.', **changes):
    value = {'answer': answer, 'question': '¿Quién es Frodo?', 'case': 'case', 'turn': 1,
             'http_status': 200, 'completed_sse': True, 'status': 'answered', 'seconds': 2,
             'model_calls': 0, 'source_urls': []}
    value.update(changes)
    return value


class ConversationAuditTests(SimpleTestCase):
    def test_default_bank_is_finite_and_covers_all_four_levels(self):
        bank = load_bank(Path(__file__).parent / 'data/conversation_audit_cases.json')
        cases = select_cases(bank)
        self.assertEqual(len(cases), 3)
        self.assertEqual(sum(len(case['messages']) for case in cases), 23)
        self.assertEqual({case['level'] for case in bank['cases']}, {1, 2, 3, 4})

    def test_bank_revision_two_restores_unicode_without_garbled_question_words(self):
        bank = load_bank(Path(__file__).parent / 'data/conversation_audit_cases.json')
        self.assertEqual(bank['revision'], 2)
        for case in bank['cases']:
            for item in case['messages']:
                self.assertNotRegex(item['text'], r'\w\?\w|^\?')
        memory = next(case for case in bank['cases'] if case['id'] == 'memoria_contexto')
        self.assertEqual(memory['messages'][1]['text'], '¿Quién es Frodo?')
        self.assertIn('debía', memory['messages'][7]['text'])

    def test_refusal_enum_is_accepted_only_for_the_action_that_should_be_refused(self):
        bank = load_bank(Path(__file__).parent / 'data/conversation_audit_cases.json')
        adversarial = next(case for case in bank['cases'] if case['id'] == 'alucinaciones_cambios')
        rejected = row('Me especializo en literatura; puedes preguntarme por un libro.', status='rejected')
        legitimate = evaluate_turn(rejected, adversarial['messages'][0])
        forbidden_action = evaluate_turn(rejected, adversarial['messages'][3])
        self.assertIn('unexpected_status', [finding['code'] for finding in legitimate['findings']])
        self.assertNotIn('unexpected_status', [finding['code'] for finding in forbidden_action['findings']])
        self.assertIsNone(forbidden_action['scores']['factualidad']['score'])
        self.assertFalse(forbidden_action['factual_certification'])

    def test_papelucho_reference_names_the_observed_book_publisher_not_the_film(self):
        bank = load_bank(Path(__file__).parent / 'data/conversation_audit_cases.json')
        precision = next(case for case in bank['cases'] if case['id'] == 'conocimiento_precision')
        for item in precision['messages'][:2]:
            self.assertEqual(item['oracle']['references'],
                ['https://literaturasm.cl/diario-secreto-de-papelucho-y-el-marciano/'])

    def test_seeded_variants_are_reproducible_and_not_an_llm_generation(self):
        item = {'text': '¿Quién es Frodo?', 'variants': ['Háblame de Frodo.', 'Describe a Frodo.']}
        a = pick_message({'id': 'case'}, 2, item, [], seed=42)
        self.assertEqual(a, pick_message({'id': 'case'}, 2, item, [], seed=42))
        self.assertIn(a, [item['text'], *item['variants']])

    def test_dynamic_followup_depends_on_the_actual_previous_status(self):
        item = {'text': '¿Y sus personajes?', 'if_previous': {
            'status': 'clarification', 'text': 'Me refiero a la obra de Jane Austen.'}}
        self.assertEqual(pick_message({'id': 'case'}, 2, item,
            [{'status': 'clarification'}], seed=42), item['if_previous']['text'])
        self.assertEqual(pick_message({'id': 'case'}, 2, item,
            [{'status': 'answered'}], seed=42), item['text'])

    def test_success_http_and_expected_name_do_not_certify_factual_accuracy(self):
        result = evaluate_turn(row(), {'oracle': {'required_all': [['Frodo']],
            'references': ['https://es.wikipedia.org/wiki/Frodo_Bols%C3%B3n']}})
        self.assertIsNone(result['scores']['factualidad']['score'])
        self.assertFalse(result['factual_certification'])
        self.assertEqual(set(result['scores']), set(DIMENSIONS))
        self.assertEqual(result['scores']['relevancia']['score'], 4)

    def test_negated_false_premise_is_not_marked_as_an_assertion(self):
        item = {'oracle': {'forbidden_assertions': [r'gandalf aparece en harry potter'],
            'expects_uncertainty_or_correction': True}}
        for answer in ('Gandalf no aparece en Harry Potter.',
                       'No es correcto: Gandalf aparece en Harry Potter es una premisa falsa.'):
            result = evaluate_turn(row(answer), item)
            self.assertNotIn('explicit_false_assertion', [finding['code'] for finding in result['findings']])

    def test_explicit_false_claim_has_critical_evidence_and_not_a_style_penalty(self):
        answer = 'Gandalf aparece en Harry Potter como profesor.'
        result = evaluate_turn(row(answer), {'oracle': {
            'forbidden_assertions': [r'gandalf aparece en harry potter']}})
        incident = next(finding for finding in result['findings'] if finding['code'] == 'explicit_false_assertion')
        self.assertEqual(incident['severity'], 'critical')
        self.assertEqual(incident['evidence'][0]['statement'], answer)
        self.assertEqual(result['scores']['factualidad']['score'], 0)

    def test_a_question_repeating_a_false_premise_is_not_an_affirmation(self):
        result = evaluate_turn(row('¿Gandalf aparece en Harry Potter? Necesito comprobarlo.'),
            {'oracle': {'forbidden_assertions': [r'gandalf aparece en harry potter']}})
        self.assertFalse(any(finding['code'] == 'explicit_false_assertion' for finding in result['findings']))

    def test_correct_list_style_is_not_rejected_as_mechanical(self):
        answer = '**Frodo**: es un hobbit.\n\n**Sam**: acompaña a Frodo.'
        result = evaluate_turn(row(answer), {'oracle': {'required_all': [['Frodo'], ['Sam']]}})
        self.assertIsNone(result['scores']['naturalidad']['score'])
        self.assertFalse(result['findings'])

    def test_search_wrapper_is_recorded_instead_of_counted_as_a_good_answer(self):
        result = evaluate_turn(row('Encontré estas referencias relacionadas con tu consulta: Frodo.'), {})
        self.assertIn('references_instead_of_answer', [finding['code'] for finding in result['findings']])

    def test_literal_quote_check_does_not_assert_semantic_entailment(self):
        source = {'id': 1, 'title': 'Una obra', 'description': 'Frodo es un hobbit.'}
        claim = {'source_id': 1, 'statement': 'Frodo es un hobbit.',
                 'verdict': 'supported', 'evidence': source['description']}
        trace = {'sources': [source], 'diagnostics': {'audit': {'claims': [claim]}}}
        original = copy.deepcopy(trace)
        result = evaluate_turn(row(), {}, trace=trace)
        self.assertEqual(trace, original)
        self.assertTrue(result['literal_evidence_checks'][0]['literal_in_source'])
        self.assertEqual(result['scores']['fuentes']['score'], 3)
        self.assertIsNone(result['scores']['factualidad']['score'])

    def test_nonliteral_supported_evidence_is_a_critical_observable_failure(self):
        trace = {'sources': [{'id': 1, 'description': 'Frodo es un hobbit.'}],
                 'diagnostics': {'audit': {'claims': [{'source_id': 1, 'statement': 'Una afirmación.',
                     'verdict': 'supported', 'evidence': 'Esta frase no existe en la fuente.'}]}}}
        result = evaluate_turn(row(), {}, trace=trace)
        self.assertIn('audit_evidence_not_literal', [finding['code'] for finding in result['findings']])

    def test_missing_trace_is_unknown_instead_of_a_false_source_failure(self):
        value = row()
        value['diagnostics'] = {'audit': {'claims': [{'source_id': 1, 'statement': 'Frodo.',
             'verdict': 'supported', 'evidence': 'Prueba de la fuente.'}]}}
        result = evaluate_turn(value, {})
        self.assertNotIn('audit_evidence_not_literal', [finding['code'] for finding in result['findings']])

    def test_capture_integrity_uses_the_original_answer_without_modifications(self):
        answer = '  Una respuesta\ncon saltos.  '
        result = evaluate_turn(row(answer), {})
        self.assertEqual(result['original_answer_sha256'], hashlib.sha256(answer.encode()).hexdigest())

    def test_transport_failure_and_latency_are_measured_separately(self):
        result = evaluate_turn(row('', completed_sse=False, http_status=500, seconds=40), {})
        self.assertIn('incomplete_transport', [finding['code'] for finding in result['findings']])
        self.assertIn('latency_over_30s', [finding['code'] for finding in result['findings']])
        self.assertEqual(result['scores']['latencia']['score'], 2)

    def test_empty_batch_has_no_fake_percentiles_or_accuracy(self):
        report = summarize([])
        self.assertIsNone(report['p95_seconds'])
        self.assertIsNone(report['factual_accuracy'])
        self.assertEqual(report['turns'], 0)

    def test_nearest_rank_p95_and_resource_counts(self):
        rows = [row(seconds=value, model_calls=1) for value in (1, 2, 4, 50)]
        report = summarize(rows)
        self.assertEqual(report['p95_seconds'], 50)
        self.assertEqual(report['p50_seconds'], 3)
        self.assertEqual(report['model_calls'], 4)

    def test_completed_conversations_are_not_silently_run_again(self):
        bank = load_bank(Path(__file__).parent / 'data/conversation_audit_cases.json')
        cases = select_cases(bank, completed=['memoria_contexto'])
        self.assertEqual([case['id'] for case in cases], ['conocimiento_precision', 'alucinaciones_cambios'])

    def test_invalid_bank_cannot_hide_duplicate_ids_or_unbounded_dialogues(self):
        bank = {'version': 1, 'cases': [{'id': 'same', 'mode': 'live', 'level': 1,
                                       'messages': [{'text': 'Una pregunta'}]}]}
        bank['cases'] *= 2
        with self.assertRaises(ValueError):
            validate_bank(bank)

    def test_atomic_report_preserves_existing_report_when_serialization_fails(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'report.json'
            atomic_json(path, {'valid': True})
            with self.assertRaises(ValueError):
                atomic_json(path, {'bad': float('nan')})
            self.assertEqual(json.loads(path.read_text()), {'valid': True})

    def test_plan_only_uses_no_http_model_or_production_settings(self):
        import auditar_conversaciones
        with TemporaryDirectory() as folder, patch('evaluar_chat_http.main',
            side_effect=AssertionError('Plan sin servicios')):
            code = auditar_conversaciones.main(['--output-dir', str(Path(folder) / 'plan'), '--plan-only'])
            self.assertEqual(code, 0)
            state = json.loads((Path(folder) / 'plan/estado.json').read_text(encoding='utf-8'))
            self.assertEqual(state['turns_executed'], 0)
            self.assertEqual(state['last_plan']['planned_turns'], 23)

    def test_resume_rejects_a_changed_seed_instead_of_comparing_unrelated_runs(self):
        import auditar_conversaciones
        with TemporaryDirectory() as folder:
            directory = Path(folder) / 'plan'
            auditar_conversaciones.main(['--output-dir', str(directory), '--plan-only'])
            with self.assertRaises(SystemExit):
                auditar_conversaciones.main(['--output-dir', str(directory), '--plan-only', '--resume', '--seed', '12'])
