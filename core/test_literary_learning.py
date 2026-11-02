"""Trabajador y selección adaptativa: pruebas offline, nunca datos de producción."""
import io
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from .literary_identity import stable_work_id
from .literary_learning import (_bibliographic_query, _fetch_public_metadata, _covers_requirement,
    provider_order, prioritize_works, run_refresh_batch, schedule_known_works)
from .literary_sources import SearchResults


def work(title='Obra de prueba', author='Autora de prueba'):
    return {'title': title, 'author': author, 'work_id': stable_work_id(title, author),
            'source': 'Open Library', 'kind': 'book', 'url': 'https://openlibrary.org/works/OL123W'}


class AdaptiveProviderTests(SimpleTestCase):
    def test_no_statistics_and_small_sample_keep_policy_order(self):
        self.assertEqual(provider_order([]), ['openlibrary', 'wikidata'])
        self.assertEqual(provider_order([{'provider': 'wikidata', 'verified': 7,
            'failures': 0, 'requirement': 'characters'}], requirement='characters'),
            ['openlibrary', 'wikidata'])

    def test_verified_outcomes_can_prioritize_an_already_eligible_tool(self):
        stats = [{'provider': 'openlibrary', 'verified': 1, 'failures': 9, 'requirement': 'characters'},
                 {'provider': 'wikidata', 'verified': 9, 'failures': 1, 'requirement': 'characters'}]
        self.assertEqual(provider_order(stats, requirement='characters'), ['wikidata', 'openlibrary'])
        self.assertEqual(provider_order(stats, requirement='summary'), ['openlibrary', 'wikidata'])
        self.assertEqual(provider_order(stats, eligible=['openlibrary']), ['openlibrary'])

    def test_hits_are_demand_not_verification_and_unknown_tools_are_excluded(self):
        self.assertEqual(provider_order([{'provider': 'wikidata', 'hits': 10000,
                                         'verified': 0, 'failures': 0}]),
                         ['openlibrary', 'wikidata'])
        self.assertEqual(provider_order([], eligible=['paid-search', 'wikidata', 'wikidata']), ['wikidata'])

    def test_untrusted_or_non_finite_statistics_do_not_change_selection(self):
        rows = [None, {'provider': 'wikidata', 'verified': 'not-a-number'},
                {'provider': 'wikidata', 'verified': 20, 'total_latency': float('nan')},
                {'provider': 'paid-search', 'verified': 100}]
        self.assertEqual(provider_order(rows), ['openlibrary', 'wikidata'])
        with self.assertRaises(ValueError):
            provider_order([], requirement='secret user question')

    def test_demand_prioritizes_only_known_ids_without_adding_knowledge(self):
        first, second = work(), work('Otra obra')
        ordered = prioritize_works([first, second], [
            {'work_id': second['work_id'], 'hits': 6, 'failures': 2},
            {'work_id': 'unknown-user-or-work', 'hits': 1000}], maximum=1)
        self.assertEqual(ordered, [second])
        self.assertEqual(set(ordered[0]), set(second))


class WorkerTests(SimpleTestCase):
    @contextmanager
    def mocked_store(self, *, jobs=None, complete=True):
        record = work()
        pending = jobs if jobs is not None else [{
            'job_id': 'test-job', 'lease_token': 'lease-a', 'work_id': record['work_id'],
            'provider': 'openlibrary', 'requirement': 'metadata', 'attempts': 1}, None]
        mocks = {'claim_job': Mock(side_effect=pending), 'get_work': Mock(return_value=record),
            'remember_evidence': Mock(return_value={'works': 1, 'sources': 1}),
            'retrieve_evidence': Mock(return_value=([record], [record])),
            'finish_job': Mock(return_value=complete), 'fail_job': Mock(return_value=complete),
            'record_use': Mock()}
        with patch.multiple('core.literary_memory', **mocks):
            yield record, mocks

    def test_success_persists_only_matching_public_sources_and_passes_lease(self):
        with self.mocked_store() as (record, mocks):
            wrong = work('Otra obra', 'Otra persona')
            report = run_refresh_batch(database='isolated.sqlite3', max_jobs=1,
                fetch=Mock(return_value=SearchResults([record, wrong])))
            self.assertEqual(report['completed'], 1)
            self.assertEqual(report['llm_calls'], 0)
            self.assertEqual(mocks['remember_evidence'].call_args.args, ([record], [record]))
            mocks['finish_job'].assert_called_once_with('test-job', lease_token='lease-a',
                                                       database='isolated.sqlite3')
            self.assertEqual(mocks['record_use'].call_args.args[2], 'verified')

    def test_api_failure_requeues_with_backoff_without_saving_error_content(self):
        with self.mocked_store() as (_, mocks):
            report = run_refresh_batch(max_jobs=1,
                fetch=Mock(side_effect=OSError('https://private.host token=secret')))
            self.assertEqual(report['deferred'], 1)
            mocks['remember_evidence'].assert_not_called()
            error = mocks['fail_job'].call_args.kwargs
            self.assertEqual(error['error_code'], 'unavailable')
            self.assertGreaterEqual(error['retry_after'], 60)
            self.assertNotIn('secret', json.dumps(report))

    def test_rate_limited_api_does_not_become_empty_or_successful_ingestion(self):
        with self.mocked_store() as (_, mocks):
            report = run_refresh_batch(max_jobs=1,
                fetch=Mock(return_value=SearchResults(status='rate_limited')))
            self.assertEqual(report['jobs'][0]['status'], 'rate_limited')
            mocks['remember_evidence'].assert_not_called()
            mocks['finish_job'].assert_not_called()

    def test_wrong_author_or_different_volume_is_not_attached_to_active_work(self):
        for candidate in [work('Obra de prueba II'), work(author='Autor distinto')]:
            with self.subTest(candidate=candidate), self.mocked_store() as (_, mocks):
                report = run_refresh_batch(max_jobs=1,
                    fetch=Mock(return_value=SearchResults([candidate])))
                self.assertEqual(report['jobs'][0]['status'], 'no_verified_match')
                mocks['remember_evidence'].assert_not_called()

    def test_expired_worker_does_not_record_verified_outcome_or_complete_count(self):
        with self.mocked_store(complete=False) as (record, mocks):
            report = run_refresh_batch(max_jobs=1, fetch=Mock(return_value=SearchResults([record])))
            self.assertEqual(report['completed'], 0)
            self.assertFalse(report['jobs'][0]['lease_current'])
            mocks['record_use'].assert_not_called()

    def test_no_work_in_queue_does_not_fetch_or_create_a_job(self):
        with self.mocked_store(jobs=[None]) as (_, mocks):
            fetch = Mock()
            result = run_refresh_batch(fetch=fetch)
            fetch.assert_not_called()
            self.assertEqual(result['claimed'], 0)
            mocks['remember_evidence'].assert_not_called()

    def test_job_count_total_time_and_pause_are_enforced(self):
        current = [0.]
        def advance(seconds):
            current[0] += seconds
        jobs = [{'id': 'job-' + str(i), 'lease_token': 'lease', 'work_id': work()['work_id'],
                 'provider': 'openlibrary', 'requirement': 'metadata'} for i in range(4)]
        with self.mocked_store(jobs=jobs) as (record, _):
            def fetch(*args):
                advance(2)
                return SearchResults([record])
            report = run_refresh_batch(max_jobs=20, max_seconds=3, job_seconds=2,
                fetch=fetch, clock=lambda: current[0], sleeper=advance)
            self.assertEqual(report['claimed'], 1)
            self.assertEqual(report['seconds'], 3)

    def test_private_or_invalid_bibliographic_metadata_is_never_queried(self):
        for title in ['mail me at private@example.com', 'token=private-secret', 'Text\nwith lines']:
            with self.subTest(title=title), self.assertRaises(ValueError):
                _bibliographic_query(work(title), 'openlibrary')

    def test_only_registered_providers_are_available_and_openlibrary_uses_light_api(self):
        record = work()
        with patch('core.literary_search.search_openlibrary', return_value=[]) as search:
            _fetch_public_metadata(record, 'openlibrary')
        search.assert_called_once_with('title:"Obra de prueba" author:"Autora de prueba"', details=False)
        with self.assertRaises(ValueError):
            _fetch_public_metadata(record, 'paid-service')

    def test_scheduler_skips_fresh_sources_and_queues_only_controlled_work_ids(self):
        fresh, stale = work(), work('Otra obra')
        with patch.multiple('core.literary_memory',
                list_works=Mock(return_value=[fresh, stale]), usage_stats=Mock(return_value=[]),
                retrieve_evidence=Mock(side_effect=[([fresh], [fresh]), ([], [])]),
                enqueue_refresh=Mock(return_value='job')) as mocks:
            # patch.multiple no devuelve mocks ya proporcionados: conservar la
            # referencia permite inspeccionar el contrato sin usar SQL interno.
            from . import literary_memory
            identifiers = schedule_known_works(maximum=1)
            self.assertEqual(identifiers, ['job'])
            literary_memory.enqueue_refresh.assert_called_once_with(stale['work_id'], 'metadata',
                'openlibrary', priority=100, database=None)


class LearningCommandTests(SimpleTestCase):
    def test_stats_reads_no_network_and_no_initialization(self):
        output = io.StringIO()
        with patch.multiple('core.literary_memory', default_path=Mock(return_value='aux.sqlite3'),
                usage_stats=Mock(return_value=[]), initialize_store=Mock()) as _:
            with patch('core.management.commands.actualizar_conocimiento.run_refresh_batch') as batch:
                call_command('actualizar_conocimiento', stats=True, stdout=output)
                batch.assert_not_called()
            from . import literary_memory
            literary_memory.initialize_store.assert_not_called()
        self.assertFalse(json.loads(output.getvalue())['network'])

    def test_delete_usage_keeps_evidence_and_never_runs_worker(self):
        output = io.StringIO()
        with patch('core.literary_memory.delete_usage', return_value=3), \
                patch('core.management.commands.actualizar_conocimiento.run_refresh_batch') as batch:
            call_command('actualizar_conocimiento', delete_usage=True, stdout=output)
            batch.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['deleted_usage_rows'], 3)

    def test_once_starts_one_bounded_batch(self):
        with patch('core.literary_memory.initialize_store') as initialize, \
                patch('core.management.commands.actualizar_conocimiento.lower_worker_priority'), \
                patch('core.management.commands.actualizar_conocimiento.run_refresh_batch',
                      return_value={'completed': 0}) as batch:
            call_command('actualizar_conocimiento', once=True, max_jobs=1, max_seconds=5,
                         stdout=io.StringIO())
            initialize.assert_called_once()
            batch.assert_called_once()
            self.assertEqual(batch.call_args.kwargs['max_jobs'], 1)

    def test_unbounded_options_are_rejected_before_database_creation(self):
        for kwargs in [{'max_jobs': 1000}, {'max_seconds': 10000}, {'job_seconds': 60},
                       {'interval': 0}, {'pause': 0}]:
            with self.subTest(kwargs=kwargs), patch('core.literary_memory.initialize_store') as initialize:
                with self.assertRaises(CommandError):
                    call_command('actualizar_conocimiento', stdout=io.StringIO(), **kwargs)
                initialize.assert_not_called()


class PersistentWorkerIntegrationTests(SimpleTestCase):
    """SQLite real temporal; sólo las respuestas HTTP son simuladas."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / 'memory.sqlite3'
        from .literary_memory import initialize_store, remember_evidence
        initialize_store(database=self.database)
        self.record = work()
        counts = remember_evidence([self.record], [self.record], database=self.database)
        self.assertEqual(counts['sources'], 1)

    def tearDown(self):
        self.temporary.cleanup()

    def test_once_refresh_is_durable_and_fresh_metadata_prevents_repeated_download(self):
        from .literary_memory import enqueue_refresh, usage_stats, retrieve_evidence, claim_job
        enqueue_refresh(self.record['work_id'], 'metadata', 'openlibrary', database=self.database)
        fetch = Mock(return_value=SearchResults([self.record]))
        report = run_refresh_batch(database=self.database, max_jobs=1, fetch=fetch)
        self.assertEqual(report['completed'], 1)
        self.assertEqual(report['stored'], 1)
        self.assertIsNone(claim_job('second-worker', database=self.database))
        self.assertEqual(usage_stats(database=self.database)[0]['verified'], 1)
        known, sources = retrieve_evidence(self.record['title'], database=self.database)
        self.assertTrue(known and sources)
        # Todas las llamadas abren/cerran sus conexiones: este segundo lote
        # conserva el resultado sin depender de un caché de proceso.
        self.assertEqual(schedule_known_works(database=self.database), [])
        second = run_refresh_batch(database=self.database, max_jobs=1, fetch=fetch)
        self.assertEqual(second['claimed'], 0)
        fetch.assert_called_once()

    def test_failure_backoff_and_restart_preserve_queue_and_previously_known_sources(self):
        from .literary_memory import enqueue_refresh, usage_stats, retrieve_evidence, claim_job
        enqueue_refresh(self.record['work_id'], 'metadata', 'openlibrary', database=self.database)
        report = run_refresh_batch(database=self.database, max_jobs=1,
            fetch=Mock(side_effect=OSError('password=private information')))
        self.assertEqual(report['deferred'], 1)
        self.assertIsNone(claim_job('new-process', database=self.database))
        self.assertEqual(usage_stats(database=self.database)[0]['failures'], 1)
        self.assertTrue(retrieve_evidence(self.record['title'], database=self.database)[1])
        import time
        now = time.time()
        with patch('core.literary_memory.time.time', return_value=now + 1000):
            job = claim_job('resumed-process', database=self.database)
        self.assertIsNotNone(job)
        self.assertEqual(job['attempts'], 2)
        self.assertNotIn('private information', json.dumps(job))

    def test_catalogue_metadata_does_not_satisfy_character_job(self):
        from .literary_memory import enqueue_refresh, usage_stats
        enqueue_refresh(self.record['work_id'], 'characters', 'openlibrary', database=self.database)
        report = run_refresh_batch(database=self.database, max_jobs=1,
            fetch=Mock(return_value=SearchResults([self.record])))
        self.assertEqual(report['completed'], 0)
        self.assertEqual(report['jobs'][0]['status'], 'no_evidence')
        self.assertEqual(usage_stats(database=self.database)[0]['verified'], 0)

    def test_registered_wikidata_character_evidence_survives_into_a_new_batch(self):
        from .literary_memory import enqueue_refresh, retrieve_evidence, get_work, delete_usage, usage_stats
        enqueue_refresh(self.record['work_id'], 'characters', 'wikidata', database=self.database)
        book = {**self.record, 'source': 'Wikidata', 'license': 'CC0',
                'url': 'https://www.wikidata.org/wiki/Q1234'}
        page = {**book, 'kind': 'web', 'author': 'Fuente web',
            'work_title': self.record['title'], 'work_author': self.record['author'],
            'work_binding_verified': True,
            'description': 'Elena: Narradora del viaje.\nTomás: Hermano de Elena.',
            'character_facts': [{'name': 'Elena', 'role': 'Narradora del viaje.'},
                                {'name': 'Tomás', 'role': 'Hermano de Elena.'}]}
        report = run_refresh_batch(database=self.database, max_jobs=1,
            fetch=Mock(return_value=SearchResults([book, page])))
        self.assertEqual(report['completed'], 1)
        books, sources = retrieve_evidence(self.record['title'], requirement='characters',
            books=[self.record], database=self.database)
        self.assertTrue(_covers_requirement(self.record, books, sources, 'characters'))
        self.assertEqual(schedule_known_works(database=self.database, requirement='characters',
                                             provider='wikidata'), [])
        self.assertEqual(delete_usage(database=self.database), 1)
        self.assertEqual(usage_stats(database=self.database), [])
        self.assertIsNotNone(get_work(self.record['work_id'], database=self.database))
        self.assertTrue(retrieve_evidence(self.record['title'], database=self.database)[1])
