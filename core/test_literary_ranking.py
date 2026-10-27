"""Relevance evaluation is isolated: no production DB, source download or LLM."""
import io
import json
import math
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from .literary_ranking import (FEATURES, FixtureBM25, evaluate, features, fingerprint,
    index_retriever, load_dataset, ranking_metrics, reciprocal_rank_fusion, split_by_work,
    train_candidate, training_readiness, validate_dataset)


class RankingEvaluationTests(SimpleTestCase):
    def dataset(self, works=8):
        documents, queries = [], []
        for i in range(works):
            for j in range(2):
                documents.append({'id': f'd{i}-{j}', 'work_id': f'w{i}',
                    'title': f'Título {i}', 'author': f'Autora {i}',
                    'text': f'Pasaje de evidencia sobre personaje {i}, relación {j} y un viaje.',
                    'source_url': f'https://example.org/work/{i}', 'license': 'CC0-1.0'})
            queries.append({'id': f'q{i}', 'work_id': f'w{i}', 'text': f'Título {i} personaje',
                'label_status': 'curated_test', 'qrels': {f'd{i}-0': 2, f'd{i}-1': 0}})
        return {'version': 1, 'documents': documents, 'queries': queries}

    def test_metrics_use_correct_denominators_and_graded_dcg(self):
        metrics = ranking_metrics(['wrong', 'partial', 'best'], {'best': 2, 'partial': 1}, k=5)
        self.assertEqual(metrics['recall@5'], 1.)
        self.assertEqual(metrics['recall@10'], 1.)
        self.assertEqual(metrics['precision@5'], .4)
        self.assertEqual(metrics['mrr'], .5)
        expected = (1 / math.log2(3) + 3 / math.log2(4)) / (3 + 1 / math.log2(3))
        self.assertAlmostEqual(metrics['ndcg@10'], expected)

    def test_duplicate_document_does_not_inflate_hits(self):
        metrics = ranking_metrics(['a', 'a', 'a'], {'a': 2}, k=5)
        self.assertEqual(metrics['precision@5'], .2)
        self.assertEqual(metrics['ndcg@10'], 1.)

    def test_missing_documents_count_as_misses(self):
        metrics = ranking_metrics([], {'a': 2}, k=5)
        self.assertEqual(metrics['recall@10'], 0.)
        self.assertEqual(metrics['mrr'], 0.)
        self.assertEqual(metrics['ndcg@10'], 0.)

    def test_k_and_dataset_boundaries_are_validated(self):
        for k in (0, 101, True, 1.5):
            with self.subTest(k=k), self.assertRaises(ValueError):
                ranking_metrics([], {}, k=k)
        for mutate in (
            lambda d: d['documents'].append(d['documents'][0]),
            lambda d: d['queries'][0]['qrels'].update({'unknown': 2}),
            lambda d: d['queries'][0]['qrels'].update({'d0-0': True}),
            lambda d: d['queries'][0].update(label_status='self_generated'),
            lambda d: d['documents'][0].update(source_url='http://127.0.0.1/'),
            lambda d: d['queries'][0]['qrels'].update({'d1-0': 2}),
        ):
            data = self.dataset()
            mutate(data)
            with self.assertRaises(ValueError):
                validate_dataset(data)

    def test_work_splits_keep_every_paraphrase_and_edition_group_together(self):
        data = self.dataset(13)
        for query in list(data['queries']):
            data['queries'].append({**query, 'id': query['id'] + '-paraphrase', 'text': 'Otra pregunta'})
        partitions = split_by_work(data)
        seen = set()
        for partition in partitions.values():
            works = {query['work_id'] for query in partition}
            self.assertFalse(seen & works)
            seen |= works
            for work in works:
                self.assertEqual(sum(q['work_id'] == work for q in partition), 2)
        self.assertEqual(len(seen), 13)
        self.assertEqual(partitions, split_by_work(data))

    def test_split_is_independent_of_document_order_or_labels(self):
        data = self.dataset()
        first = {name: {q['work_id'] for q in qs} for name, qs in split_by_work(data).items()}
        data['documents'].reverse()
        data['queries'].reverse()
        for query in data['queries']:
            query['qrels'] = {i: min(1, grade) for i, grade in query['qrels'].items()}
        self.assertEqual(first, {name: {q['work_id'] for q in qs}
                                 for name, qs in split_by_work(data).items()})

    def test_rrf_deduplicates_inside_each_ranker(self):
        self.assertEqual(reciprocal_rank_fusion([['a', 'a', 'b'], ['b', 'c']]), ['b', 'a', 'c'])
        with self.assertRaises(ValueError):
            reciprocal_rank_fusion([['a']], constant=float('nan'))

    def test_features_never_include_ids_or_labels(self):
        data = self.dataset()
        query, document = data['queries'][0], data['documents'][0]
        before = features(query, document, lexical_position=2)
        self.assertEqual(len(before), len(FEATURES))
        query = {**query, 'work_id': 'secret-work', 'qrels': {'arbitrary': 2}}
        document = {**document, 'id': 'different', 'work_id': 'different'}
        self.assertEqual(before, features(query, document, lexical_position=2))

    def test_small_fixture_never_pretends_to_train_or_activate(self):
        report = train_candidate(self.dataset())
        self.assertFalse(report['trained'])
        self.assertFalse(report['readiness']['ready'])
        self.assertFalse(report['readiness']['model_activated'])
        self.assertNotIn('weights', report)

    def test_declared_human_labels_require_explicit_evidence_review(self):
        data = self.dataset(40)
        for query in data['queries']:
            query['label_status'] = 'human_reviewed'
        self.assertEqual(training_readiness(data)['counts']['train_pairs'], 0)

    def test_explicit_unjudged_results_are_not_training_negatives(self):
        data = self.dataset(40)
        for query in data['queries']:
            query.update(label_status='human_reviewed', label_evidence_verified=True)
            query['qrels'] = {identifier: grade for identifier, grade in query['qrels'].items() if grade > 0}
        self.assertIn('train_needs_positive_and_negative_labels', training_readiness(data)['reasons'])

    def test_readiness_rejects_manual_work_leakage(self):
        data = self.dataset()
        report = training_readiness(data, {'train': data['queries'],
                                         'validation': data['queries'], 'test': data['queries']})
        self.assertIn('work_leakage', report['reasons'])

    def test_heldout_negative_does_not_enter_training_counts(self):
        data = self.dataset(40)
        partitions = split_by_work(data)
        heldout = partitions['test'][0]['work_id']
        for query in data['queries']:
            query.update(label_status='human_reviewed', label_evidence_verified=True)
            if query['work_id'] != heldout:
                query['qrels'][next(d['id'] for d in data['documents'] if d['work_id'] == heldout)] = 0
        readiness = training_readiness(data)
        self.assertEqual(readiness['counts']['train_pairs'], 2 * len(partitions['train']))

    def test_training_is_real_only_after_gates_and_does_not_activate(self):
        data = self.dataset(40)
        expanded = []
        for query in data['queries']:
            for index in range(6):
                expanded.append({**query, 'id': query['id'] + f'-{index}',
                    'text': query['text'] + f' variante {index}',
                    'label_status': 'human_reviewed', 'label_evidence_verified': True})
        data['queries'] = expanded
        # Synthetic labels exercise the optimizer only; never used by the application.
        report = train_candidate(data, epochs=4)
        self.assertTrue(report['trained'])
        self.assertEqual(len(report['weights']), len(FEATURES))
        self.assertTrue(any(abs(weight) > 0 for weight in report['weights']))
        self.assertFalse(report['model_activated'])
        self.assertEqual(report['dataset_sha256'], fingerprint(data))
        self.assertIn('test', report['evaluation'])

    def test_duplicate_paraphrases_do_not_bypass_sample_gate(self):
        data = self.dataset(40)
        data['queries'] = [{**query, 'id': query['id'] + f'-{i}',
            'label_status': 'human_reviewed', 'label_evidence_verified': True}
            for query in data['queries'] for i in range(20)]
        self.assertFalse(training_readiness(data)['ready'])
        self.assertLess(training_readiness(data)['counts']['train_pairs'], 200)

    def test_bm25_retrieval_does_not_read_qrels(self):
        data = self.dataset()
        with closing(FixtureBM25(data)) as retrieve:
            query = data['queries'][0]
            original = retrieve(query)
            self.assertEqual(original, retrieve({**query, 'qrels': {'d7-0': 2}}))

    def test_report_is_retrieval_only_and_unknown_ids_fail(self):
        data = self.dataset()
        with self.assertRaises(ValueError):
            evaluate(data, lambda query: ['invented'])
        with closing(FixtureBM25(data)) as retrieve:
            result = evaluate(data, retrieve)
        self.assertEqual(result['scope'], 'retrieval_only_not_chat_or_factual_accuracy')
        self.assertEqual(result['queries'], len(data['queries']))

    def test_real_index_adapter_requires_passage_not_title_only(self):
        data = self.dataset()
        with tempfile.TemporaryDirectory() as temporary:
            index = Path(temporary) / 'index.sqlite3'
            index.touch()
            document = data['documents'][0]
            with patch('core.local_rag.retrieve_fragments', return_value=[{
                    'title': document['title'], 'author': document['author'],
                    'description': 'Texto diferente sin evidencia.'}]):
                ranking = index_retriever(data, index)(data['queries'][0])
                self.assertEqual(len(ranking), 1)
                self.assertTrue(ranking[0].startswith('unjudged:'))
            with patch('core.local_rag.retrieve_fragments', return_value=[{
                    'title': document['title'], 'author': document['author'],
                    'description': document['text']}]):
                self.assertEqual(index_retriever(data, index)(data['queries'][0]), [document['id']])

    def test_fixture_has_provenance_and_no_training_labels(self):
        dataset = load_dataset(Path(settings.BASE_DIR) / 'core/data/retrieval_benchmark.json')
        self.assertGreaterEqual(len(dataset['documents']), 30)
        self.assertEqual(len(dataset['queries']), 48)
        self.assertTrue(all(q['label_status'] == 'curated_test' for q in dataset['queries']))
        self.assertFalse(training_readiness(dataset)['ready'])

    def test_command_is_offline_and_refuses_report_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'report.json'
            stdout = io.StringIO()
            call_command('evaluar_recuperacion', output=path, train_candidate=True, stdout=stdout)
            report = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(report['external_http_calls'], 0)
            self.assertFalse(report['candidate']['trained'])
            self.assertEqual(report['factual_answer_accuracy'], 'not_measured')
            with self.assertRaises(CommandError):
                call_command('evaluar_recuperacion', output=path, stdout=stdout)

    def test_semantic_requires_explicit_existing_index(self):
        with self.assertRaises(CommandError):
            call_command('evaluar_recuperacion', semantic=True, stdout=io.StringIO())

    def test_training_cpu_and_pair_budgets_are_bounded(self):
        for options in ({'max_seconds': float('nan')}, {'max_seconds': 301}, {'max_pairs': 100000}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                train_candidate(self.dataset(), **options)

    def test_semantic_adapter_counts_failure_even_when_production_falls_back(self):
        from unittest.mock import Mock
        data = self.dataset()
        with tempfile.TemporaryDirectory() as temporary:
            index = Path(temporary) / 'index.sqlite3'
            index.touch()
            embedder = Mock()
            embedder.embed.side_effect = TimeoutError('offline')
            def fallback(*args, **kwargs):
                try:
                    kwargs['embedder'].embed(['query'], query=True)
                except TimeoutError:
                    pass
                return []
            with patch('core.local_rag.retrieve_fragments', side_effect=fallback):
                retrieve = index_retriever(data, index, embedder=embedder)
                self.assertEqual(retrieve(data['queries'][0]), [])
                self.assertEqual(retrieve.diagnostics['embedding_calls'], 1)
                self.assertEqual(retrieve.diagnostics['embedding_failures'], 1)

    def test_unjudged_chunks_preserve_rank_in_real_index_metrics(self):
        data = self.dataset()
        document = data['documents'][0]
        fragments = [{'title': 'Otro libro', 'author': 'Otro autor', 'description': f'Irrelevante {i}',
                      'book_id': f'unknown-{i}'} for i in range(7)]
        fragments.append({'title': document['title'], 'author': document['author'],
                          'description': document['text'], 'book_id': 'known-eighth'})
        with tempfile.TemporaryDirectory() as temporary:
            index = Path(temporary) / 'index.sqlite3'
            index.touch()
            with patch('core.local_rag.retrieve_fragments', return_value=fragments):
                retrieve = index_retriever(data, index)
                result = evaluate(data, retrieve, queries=[data['queries'][0]])
        self.assertEqual(result['metrics']['mrr'], 1 / 8)
        self.assertEqual(result['metrics']['recall@5'], 0)
        self.assertEqual(result['metrics']['recall@10'], 1)
        self.assertEqual(result['metrics']['judged_fraction@10'], 1 / 8)

    def test_original_hash_prevents_edition_confusion_and_cross_split_leakage(self):
        data = self.dataset()
        document = data['documents'][0]
        document['original_sha256'] = 'a' * 64
        data['documents'][2]['original_sha256'] = 'a' * 64
        with self.assertRaisesMessage(ValueError, 'distintas obras'):
            validate_dataset(data)
        data['documents'][2].pop('original_sha256')
        with tempfile.TemporaryDirectory() as temporary:
            index = Path(temporary) / 'index.sqlite3'
            index.touch()
            source = {'title': document['title'], 'author': document['author'],
                      'description': document['text'], 'original_sha256': 'b' * 64}
            with patch('core.local_rag.retrieve_fragments', return_value=[source]):
                self.assertNotIn(document['id'], index_retriever(data, index)(data['queries'][0]))
            source['original_sha256'] = 'a' * 64
            with patch('core.local_rag.retrieve_fragments', return_value=[source]):
                self.assertIn(document['id'], index_retriever(data, index)(data['queries'][0]))

    def test_real_paragraph_matching_normalizes_only_layout_whitespace(self):
        data = self.dataset()
        document = data['documents'][0]
        with tempfile.TemporaryDirectory() as temporary:
            index = Path(temporary) / 'index.sqlite3'
            index.touch()
            with patch('core.local_rag.retrieve_fragments', return_value=[{
                    'title': document['title'], 'author': document['author'],
                    'description': document['text'].replace(' ', '\n')} ]):
                self.assertIn(document['id'], index_retriever(data, index)(data['queries'][0]))

    def test_real_original_dataset_contains_agent_labels_not_training_labels(self):
        dataset = load_dataset(Path(settings.BASE_DIR) / 'core/data/library_retrieval_benchmark.json')
        self.assertEqual(len(dataset['documents']), 15)
        self.assertEqual(len(dataset['queries']), 30)
        self.assertEqual({q['label_status'] for q in dataset['queries']}, {'agent_reviewed'})
        self.assertEqual(training_readiness(dataset)['counts']['train_pairs'], 0)
        for work in {d['work_id'] for d in dataset['documents']}:
            self.assertLessEqual(sum(len(d['text']) for d in dataset['documents']
                                     if d['work_id'] == work), 1200)
        dataset['documents'][0]['text'] += ' modified'
        with self.assertRaisesMessage(ValueError, 'SHA256'):
            validate_dataset(dataset)
