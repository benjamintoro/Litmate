"""Ejecutores de calidad: servicios simulados, índices SQLite temporales reales."""
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from django.test import SimpleTestCase

from evaluar_litmate import (compare_reports, conversation_command, read_matrix,
                             report_metrics, run_case, select_cases, summarize_turns)
from evaluar_rag_local import inspect_index, rank_result, run_benchmark
from .local_rag import index_documents


CASE = {'id': 'controlled_conversation', 'mode': 'live', 'messages': [
    {'text': 'Recomienda dos libros de historia', 'expected_intent': 'recommend'},
    {'text': 'Dime más del segundo', 'inherits_work': True},
]}


class ConversationEvaluationToolTests(SimpleTestCase):
    def test_each_case_invokes_one_isolated_process_and_keeps_message_order(self):
        command = conversation_command(CASE, 'qwen3.5:9b-q4_K_M', Path('resultado.json'))
        self.assertIn('--public-catalog', command)
        self.assertIn('--trace', command)
        self.assertIn('--web', command)
        messages = [command[index + 1] for index, value in enumerate(command) if value == '--message']
        self.assertEqual(messages, [message['text'] for message in CASE['messages']])
        self.assertEqual(sum('verificar_investigacion.py' in value for value in command), 1)

    def test_controlled_cases_are_not_executed_or_counted_as_real(self):
        runner = Mock()
        result = run_case({**CASE, 'mode': 'controlled'}, 'local', 'unused', runner=runner)
        runner.assert_not_called()
        self.assertEqual(result['execution_status'], 'not_run_controlled')
        metrics = report_metrics([result])
        self.assertEqual(metrics['controlled_cases_not_run'], 1)
        self.assertEqual(metrics['requested_turns'], 0)

    def test_answered_does_not_mean_correct_or_independently_reviewed(self):
        rows = [{'question': CASE['messages'][0]['text'], 'status': 'answered',
                 'sources_used': [{'url': 'https://example.org/book'}],
                 'diagnostics': {'coverage': [{'question_id': 1, 'status': 'answered'}]}}]
        turns = summarize_turns(CASE, rows)
        self.assertIsNone(turns[0]['correct'])
        self.assertEqual(turns[0]['factual_review'], 'pending_independent_review')
        self.assertEqual(turns[1]['status'], 'missing')
        metrics = report_metrics([{'mode': 'live', 'turns': turns}])
        self.assertEqual(metrics['published_answers'], 1)
        self.assertEqual(metrics['publication_coverage'], .5)
        self.assertIsNone(metrics['factual_error_rate'])
        self.assertIsNone(metrics['correct_answers'])

    def test_simulated_process_logs_exit_and_all_partial_turns_are_preserved(self):
        def runner(command, **kwargs):
            report = Path(command[command.index('--output') + 1])
            report.write_text(json.dumps([{'question': CASE['messages'][0]['text'], 'status': 'unavailable'}]), encoding='utf-8')
            self.assertNotIn('DJANGO_SETTINGS_MODULE', kwargs['env'])
            self.assertFalse(kwargs['check'])
            return subprocess.CompletedProcess(command, 1, 'diagnóstico público', 'servicio no disponible')
        with TemporaryDirectory() as directory:
            result = run_case(CASE, 'local', directory, runner=runner)
            self.assertEqual(result['process_exit_code'], 1)
            self.assertEqual(result['execution_status'], 'incomplete')
            self.assertEqual([turn['status'] for turn in result['turns']], ['unavailable', 'missing'])
            self.assertEqual(Path(result['stdout']).read_text(encoding='utf-8'), 'diagnóstico público')

    def test_timeout_is_not_published_as_a_success(self):
        runner = Mock(side_effect=subprocess.TimeoutExpired(['python'], 30, output=b'partial', stderr=b'timeout'))
        with TemporaryDirectory() as directory:
            result = run_case(CASE, 'local', directory, runner=runner)
            self.assertEqual(result['execution_status'], 'timed_out')
            self.assertIsNone(result['process_exit_code'])
            self.assertTrue(all(turn['status'] == 'missing' for turn in result['turns']))

    def test_existing_report_cannot_be_overwritten(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory) / CASE['id']
            folder.mkdir()
            (folder / 'conversacion.json').write_text('[]', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'ya contiene resultados'):
                run_case(CASE, 'local', directory, runner=Mock())

    def test_comparison_includes_cases_missing_from_either_run(self):
        left = {'matrix_sha256': 'a', 'cases': [{'id': 'old', 'turns': [{'status': 'unavailable'}]},
                                               {'id': 'both', 'turns': [{'status': 'answered'}]}]}
        right = {'matrix_sha256': 'b', 'cases': [{'id': 'new', 'turns': [{'status': 'answered'}]},
                                                {'id': 'both', 'turns': [{'status': 'unavailable'}]}]}
        result = compare_reports(left, right)
        self.assertEqual([case['id'] for case in result['cases']], ['both', 'new', 'old'])
        self.assertFalse(result['same_matrix'])
        self.assertTrue(all(case['factual_correctness_change'] is None for case in result['cases']))

    def test_matrix_validation_rejects_duplicates_and_path_components(self):
        for second in ({**CASE}, {**CASE, 'id': '../unsafe'}):
            with self.subTest(second=second['id']), TemporaryDirectory() as directory:
                path = Path(directory) / 'matrix.json'
                path.write_text(json.dumps({'cases': [CASE, second]}), encoding='utf-8')
                with self.assertRaises(ValueError):
                    read_matrix(path)

    def test_case_selection_keeps_matrix_order_and_rejects_unknown_ids(self):
        matrix = {'cases': [CASE, {**CASE, 'id': 'second'}]}
        self.assertEqual([case['id'] for case in select_cases(matrix, ['second', CASE['id']])],
                         [CASE['id'], 'second'])
        with self.assertRaisesRegex(ValueError, 'desconocidos'):
            select_cases(matrix, ['missing'])


class FixtureEmbedder:
    def identity(self):
        return 'fixture-embedding:latest', 'a' * 64

    def embed(self, texts, *, query=False):
        return [[1., 0.] if any(word in text.lower() for word in ('cielo', 'viajero')) else [0., 1.]
                for text in texts]


class LocalRAGEvaluationToolTests(SimpleTestCase):
    def prepare_index(self, directory, *, authorized=True):
        folder = Path(directory) / 'cards'
        folder.mkdir()
        metadata = {}
        for title, author, body in [('Cielo', 'Autora', 'Un niño visita mundos pequeños y lejanos.'),
                                     ('Campo', 'Autor', 'Los animales gobiernan una granja y concentran poder.')]:
            filename = title + '__' + author + '.txt'
            (folder / filename).write_text(body, encoding='utf-8')
            if authorized:
                metadata[filename] = {'kind': 'book', 'license': 'CC0-1.0 fixture original de prueba',
                    'indexing_authorized': True, 'url': 'https://example.org/' + title,
                    'work_title': title, 'work_author': author}
        database = Path(directory) / 'rag.sqlite3'
        index_documents(folder, database, embedder=FixtureEmbedder(), metadata=metadata)
        return database

    def test_benchmark_measures_real_fts_and_controlled_semantics_without_modifying_index(self):
        queries = [{'id': 'paraphrase', 'query': 'viajero estelar', 'expected_title': 'Cielo', 'type': 'paraphrase'}]
        with TemporaryDirectory() as directory:
            database = self.prepare_index(directory)
            report = run_benchmark(database, embedder=FixtureEmbedder(), queries=queries)
        self.assertTrue(report['index_unchanged'])
        self.assertEqual(report['queries'][0]['fts']['expected_rank'], None)
        self.assertEqual(report['queries'][0]['hybrid']['expected_rank'], 1)
        self.assertEqual(report['embedding_successes'], 1)
        self.assertEqual(report['metrics']['hybrid']['hits_at_1'], 1)

    def test_mismatched_model_is_not_counted_as_hybrid_success(self):
        wrong = Mock()
        wrong.identity.return_value = ('other-model', 'b' * 64)
        with TemporaryDirectory() as directory:
            database = self.prepare_index(directory)
            report = run_benchmark(database, embedder=wrong,
                queries=[{'id': 'one', 'query': 'Cielo', 'expected_title': 'Cielo'}])
        wrong.embed.assert_not_called()
        self.assertEqual(report['queries'][0]['hybrid']['status'], 'embedding_model_does_not_match_existing_index')
        self.assertEqual(report['metrics']['hybrid']['measured_positive_queries'], 0)

    def test_embedding_failure_is_reported_as_fts_degradation(self):
        failing = Mock()
        failing.identity.return_value = FixtureEmbedder().identity()
        failing.embed.side_effect = TimeoutError('controlled local model failure')
        with TemporaryDirectory() as directory:
            database = self.prepare_index(directory)
            report = run_benchmark(database, embedder=failing,
                queries=[{'id': 'one', 'query': 'Cielo', 'expected_title': 'Cielo'}])
        self.assertEqual(report['queries'][0]['hybrid']['status'], 'degraded_to_fts')
        self.assertEqual(report['embedding_errors'], ['TimeoutError'])
        self.assertEqual(report['metrics']['hybrid']['measured_positive_queries'], 0)

    def test_novel_excerpt_index_without_explicit_factual_license_is_rejected(self):
        with TemporaryDirectory() as directory:
            database = self.prepare_index(directory, authorized=False)
            with self.assertRaisesRegex(ValueError, 'autorización y licencia'):
                inspect_index(database)

    def test_fts_only_never_claims_to_have_used_a_semantic_model(self):
        with TemporaryDirectory() as directory:
            database = self.prepare_index(directory)
            report = run_benchmark(database,
                queries=[{'id': 'one', 'query': 'Cielo', 'expected_title': 'Cielo'}])
        self.assertEqual(report['embedding_attempts'], 0)
        self.assertEqual(report['queries'][0]['hybrid']['status'], 'not_run_fts_only')
        self.assertEqual(report['metrics']['hybrid']['measured_positive_queries'], 0)

    def test_duplicate_sources_for_one_book_do_not_shift_its_rank(self):
        result = rank_result([{'title': 'Cielo'}, {'title': 'Cielo'}, {'title': 'Campo'}], 'Campo')
        self.assertEqual(result['ranked_titles'], ['Cielo', 'Campo'])
        self.assertEqual(result['expected_rank'], 2)

