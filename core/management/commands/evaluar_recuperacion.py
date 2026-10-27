"""Benchmark RAG aislado y preparación de ranking; nunca migra ni activa modelos."""
import json
import tracemalloc
from contextlib import closing
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.literary_ranking import (FixtureBM25, evaluate, index_retriever, load_dataset,
    split_by_work, train_candidate, training_readiness)


class Command(BaseCommand):
    help = ('Mide Recall@5/10, Precision@k, MRR y nDCG@10 en un dataset con juicios. '
            'Predeterminado: fixtures en SQLite en memoria, sin HTTP ni modelo. '
            '--index evalúa un índice existente; --semantic sólo embeddings locales.')

    def add_arguments(self, parser):
        parser.add_argument('--dataset', type=Path, default=Path(settings.BASE_DIR) /
                            'core' / 'data' / 'retrieval_benchmark.json')
        parser.add_argument('--output', type=Path)
        parser.add_argument('--index', type=Path)
        parser.add_argument('--semantic', action='store_true')
        parser.add_argument('--split', choices=('all', 'train', 'validation', 'test'), default='all')
        parser.add_argument('--precision-k', type=int, default=5)
        parser.add_argument('--train-candidate', action='store_true')

    def handle(self, *args, **options):
        output = options.get('output')
        if output and output.exists():
            raise CommandError('El informe ya existe: usa otra ruta; no se sobrescribió.')
        if not 1 <= options['precision_k'] <= 100:
            raise CommandError('--precision-k debe estar entre 1 y 100.')
        if options['semantic'] and not options.get('index'):
            raise CommandError('--semantic requiere --index; no genera vectores implícitamente.')
        try:
            dataset = load_dataset(options['dataset'])
            partitions = split_by_work(dataset)
            queries = dataset['queries'] if options['split'] == 'all' else partitions[options['split']]
            if not queries:
                raise ValueError('El split seleccionado no tiene consultas')
            report = {'dataset': str(options['dataset']), 'documents': len(dataset['documents']),
                'works': len({d['work_id'] for d in dataset['documents']}),
                'split': options['split'], 'partitions': {name: {
                    'queries': len(rows), 'works': sorted({q['work_id'] for q in rows})}
                    for name, rows in partitions.items()},
                'training_readiness': training_readiness(dataset),
                'generative_calls': 0, 'external_http_calls': 0,
                'factual_answer_accuracy': 'not_measured',
                'entity_extraction_precision': 'not_measured',
                'relation_accuracy': 'not_measured',
                'unsupported_claim_rate': 'not_measured'}
            tracemalloc.start()
            try:
                if options.get('index'):
                    embedder = None
                    if options['semantic']:
                        from core.local_embeddings import configured_embedder
                        embedder = configured_embedder(settings)
                        if embedder is None:
                            raise ValueError('Embeddings locales deshabilitados')
                    retrieve = index_retriever(dataset, options['index'], embedder=embedder)
                    report['evaluation'] = evaluate(dataset, retrieve, queries=queries,
                        k=options['precision_k'], label='production_index_semantic_requested' if embedder else 'production_index_bm25')
                    report['mode'] = 'real_local_index_retrieval_not_end_to_end'
                    report['maximum_returned_by_existing_api'] = 8
                    report['local_embedding_http_possible'] = bool(embedder)
                    report['retrieval_diagnostics'] = retrieve.diagnostics.copy()
                    report['semantic_execution_confirmed'] = bool(embedder
                        and retrieve.diagnostics['embedding_calls'] >= len(queries)
                        and not retrieve.diagnostics['embedding_failures'])
                else:
                    with closing(FixtureBM25(dataset)) as retrieve:
                        report['evaluation'] = evaluate(dataset, retrieve, queries=queries,
                            k=options['precision_k'], label='fixture_sqlite_fts5_bm25')
                    report['mode'] = 'offline_curated_fixture_retrieval_not_end_to_end'
                if options['train_candidate']:
                    report['candidate'] = train_candidate(dataset)
                report['python_peak_traced_bytes'] = tracemalloc.get_traced_memory()[1]
                report['memory_scope'] = 'Python allocations only; excludes SQLite/native/GPU/RSS'
            finally:
                tracemalloc.stop()
            body = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
            if output:
                output.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive creation also protects against a concurrent writer.
                with output.open('x', encoding='utf-8') as stream:
                    stream.write(body + '\n')
                self.stdout.write(str(output))
            else:
                self.stdout.write(body)
        except (OSError, ValueError, TypeError) as exc:
            raise CommandError(str(exc)) from None
