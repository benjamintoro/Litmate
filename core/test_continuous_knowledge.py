"""Cola continua: sólo almacenes temporales y proveedores controlados."""
import json
import sqlite3
from contextlib import closing
from contextlib import nullcontext, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from django.test import SimpleTestCase, override_settings
from . import literary_memory as memory
from .literary_identity import stable_work_id
from .test_narrative_answers import BOOK, PAGE


class ContinuousKnowledgeTests(SimpleTestCase):
    def test_backup_comparison_allows_only_derived_worker_checkpoint_progress(self):
        from scripts.knowledge.continuous_worker import checkpoint_rows_for_comparison
        from .bibliographic_repository import digest
        columns = ['id','last_rowid','counters','updated_at','lease_token']
        original = [[digest('continuous-enrichment-v1'),5,{},'earlier',''],
                    ['unrelated',3,{},'unchanged','']]
        actual = [[original[0][0],9,{'works_selected':2,'completed':1,'sources_stored':1},'later',''],original[1]]
        self.assertEqual(checkpoint_rows_for_comparison(original,actual,columns),original)
        actual[0][-1] = 'unexpected lease change'
        self.assertNotEqual(checkpoint_rows_for_comparison(original,actual,columns),original)
        actual[0][1] = 4
        with self.assertRaises(ValueError):
            checkpoint_rows_for_comparison(original,actual,columns)

    def test_main_character_gap_is_not_completed_by_unclassified_roles(self):
        from .literary_learning import _covers_requirement
        from .literary_ai import canonical_sources
        page = {**PAGE, 'description':'Ana: una viajera de la estación. Bruno: capitán de la nave.',
            'character_facts':[{'name':'Ana','role':'una viajera de la estación'},
                               {'name':'Bruno','role':'capitán de la nave'}]}
        self.assertFalse(_covers_requirement(BOOK,[BOOK],canonical_sources([page]),'main_characters'))
        page['description'] = 'Ana: protagonista que viaja a la estación.'
        page['character_facts'] = [{'name':'Ana','role':'protagonista que viaja a la estación'}]
        self.assertTrue(_covers_requirement(BOOK,[BOOK],canonical_sources([page]),'main_characters'))

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / 'memory.sqlite3'
        override = override_settings(LITMATE_LITERARY_MEMORY_DB=self.database,
            LITMATE_AI_RUNTIME_DB=self.database.parent/'runtime.sqlite3',
            LITMATE_LITERARY_MEMORY_RAG_DB=self.database.parent/'memory_rag.sqlite3')
        override.enable()
        self.addCleanup(override.disable)
        memory.initialize_store(self.database)
        memory.remember_evidence([BOOK], [BOOK], database=self.database)
        self.work_id = stable_work_id(BOOK['title'], BOOK['author'])

    def rows(self):
        with memory._connection(self.database) as db:
            return [dict(row) for row in db.execute('SELECT * FROM memory_jobs ORDER BY job_id')]

    def test_duplicate_gap_is_one_durable_task_and_only_whitelisted_metadata(self):
        from .continuous_knowledge import queue_gap
        first = queue_gap(self.work_id, 'characters', 'insufficient_evidence', database=self.database)
        second = queue_gap(self.work_id, 'characters', 'audit_rejected', database=self.database)
        self.assertEqual(first, second)
        self.assertEqual(len(self.rows()), 1)
        payload = json.loads(self.rows()[0]['payload'])
        self.assertEqual(payload['last_gap_reason'], 'audit_rejected')
        self.assertEqual(payload['gap_count'], 2)
        self.assertNotIn('message', payload)
        with self.assertRaises(ValueError):
            queue_gap(self.work_id, 'characters', 'private user correction', database=self.database)

    def test_unknown_identity_does_not_create_public_knowledge(self):
        from .continuous_knowledge import queue_gap
        self.assertIsNone(queue_gap('litmate:' + 'a'*24, 'summary', 'insufficient_evidence', database=self.database))
        self.assertEqual(self.rows(), [])

    def test_verified_quarantine_revokes_retrieval_without_erasing_source_or_assertions(self):
        with memory._connection(self.database) as db:
            sid = db.execute('SELECT source_id FROM memory_sources LIMIT 1').fetchone()[0]
            assertions = db.execute('SELECT COUNT(*) FROM memory_assertions').fetchone()[0]
        revision = memory.revision(self.database)
        self.assertTrue(memory.quarantine_source(sid, 'evaluation_fixture', database=self.database))
        self.assertIsNone(memory.get_current_source(sid, database=self.database))
        self.assertNotEqual(revision, memory.revision(self.database))
        with memory._connection(self.database) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM memory_assertions').fetchone()[0], assertions)
            self.assertTrue(db.execute('SELECT 1 FROM memory_sources WHERE source_id=?', (sid,)).fetchone())
        self.assertFalse(memory.quarantine_source(sid, 'evaluation_fixture', database=self.database))
        updated = {**BOOK, 'categories': ['Fiction']}
        memory.remember_evidence([updated], [updated], database=self.database)
        self.assertIsNotNone(memory.get_current_source(sid, database=self.database))

    def test_disambiguation_page_is_not_admitted_even_if_it_lists_the_right_author(self):
        from .literary_identity import bind_source
        ambiguous = {**PAGE, 'identity_text': 'Cuaderno lunar puede referirse a varias obras. '
                     'Cuaderno lunar, novela de Ana Robles. Cuaderno lunar, película de Otra Persona.',
                     'description': 'Cuaderno lunar puede referirse a varias obras. Ana Robles escribió una novela.'}
        self.assertEqual(memory.remember_evidence([BOOK], [bind_source(ambiguous, BOOK)],
                                                database=self.database)['sources'], 0)

    def test_legacy_disambiguation_snapshot_is_quarantined_without_deletion(self):
        from .literary_identity import bind_source
        memory.remember_evidence([BOOK], [bind_source(PAGE, BOOK)], database=self.database)
        with memory._connection(self.database, write=True) as db:
            row = db.execute("SELECT source_id,record FROM memory_sources WHERE provider='wikipedia'").fetchone()
            raw = json.loads(row['record'])
            raw['identity_text'] = 'Cuaderno lunar puede referirse a varias obras de autores distintos.'
            db.execute('UPDATE memory_sources SET record=? WHERE source_id=?', (json.dumps(raw), row['source_id']))
        self.assertIsNone(memory.get_current_source(row['source_id'], database=self.database))
        with memory._connection(self.database) as db:
            self.assertTrue(db.execute('SELECT 1 FROM memory_sources WHERE source_id=?', (row['source_id'],)).fetchone())

    def test_intro_only_summary_does_not_prevent_a_worker_from_fetching_actual_plot(self):
        from .literary_identity import bind_source
        from .literary_learning import run_refresh_batch
        from .literary_enrichment import enrich_source
        intro = {**PAGE, 'description': 'Narra la historia de una joven que viaja a la luna para encontrar a su hermano.'}
        memory.remember_evidence([BOOK], [bind_source(intro, BOOK)], database=self.database)
        memory.enqueue_refresh(self.work_id, 'summary', 'wikipedia', database=self.database)
        fetch = Mock(return_value=[bind_source(enrich_source(PAGE, BOOK, 'summary'), BOOK)])
        report = run_refresh_batch(database=self.database, max_jobs=1, reuse_fresh=True, narrative_pages=1, fetch=fetch)
        fetch.assert_called_once()
        self.assertEqual(report['completed'], 1)
        self.assertEqual(report['reused'], 0)

    def test_corrupt_task_is_quarantined_without_blocking_the_next_valid_task(self):
        invalid = memory.enqueue_refresh(self.work_id, 'summary', 'wikipedia', priority=100, database=self.database)
        valid = memory.enqueue_refresh(self.work_id, 'characters', 'wikipedia', database=self.database)
        with memory._connection(self.database, write=True) as db:
            db.execute('UPDATE memory_jobs SET payload=? WHERE job_id=?', ('{broken', invalid))
        job = memory.claim_job('worker', database=self.database)
        self.assertEqual(job['id'], valid)
        self.assertEqual(next(row for row in self.rows() if row['job_id'] == invalid)['status'], 'invalid')

    def test_two_workers_and_expired_lease_recovery_keep_token_ownership(self):
        with patch('core.literary_memory.time.time', return_value=100):
            memory.enqueue_refresh(self.work_id, 'characters', 'wikipedia', database=self.database)
            first = memory.claim_job('one', lease_seconds=30, database=self.database)
            self.assertIsNone(memory.claim_job('two', database=self.database))
        with patch('core.literary_memory.time.time', return_value=131):
            second = memory.claim_job('two', database=self.database)
            self.assertFalse(memory.finish_job(first['id'], lease_token=first['lease_token'], database=self.database))
            self.assertTrue(memory.finish_job(second['id'], lease_token=second['lease_token'], database=self.database))

    def test_worker_reuses_fresh_verified_content_without_network(self):
        from .literary_learning import run_refresh_batch
        from .literary_enrichment import enrich_source
        from .literary_identity import bind_source
        memory.remember_evidence([BOOK], [bind_source(enrich_source(PAGE, BOOK, 'summary'), BOOK)], database=self.database)
        memory.enqueue_refresh(self.work_id, 'summary', 'wikipedia', database=self.database)
        fetch = Mock(side_effect=AssertionError('network must not run'))
        result = run_refresh_batch(database=self.database, max_jobs=1, reuse_fresh=True, fetch=fetch)
        self.assertEqual(result['completed'], 1)
        self.assertEqual(result['reused'], 1)
        fetch.assert_not_called()

    def test_stop_guard_does_not_consume_pending_job(self):
        from .literary_learning import run_refresh_batch
        memory.enqueue_refresh(self.work_id, 'characters', 'wikipedia', database=self.database)
        result = run_refresh_batch(database=self.database, stop=lambda: True)
        self.assertEqual(result['claimed'], 0)
        self.assertEqual(self.rows()[0]['attempts'], 0)

    def test_fair_scan_reaches_less_used_works_across_restarts(self):
        from .continuous_knowledge import schedule_incremental
        for index in range(4):
            book = {**BOOK, 'title': 'Obra ' + str(index), 'url': 'https://openlibrary.org/works/OL' + str(index+200) + 'W'}
            memory.remember_evidence([book], [book], database=self.database)
        memory.record_use(self.work_id, 'characters', 'failed', database=self.database)
        seen = set()
        for unused in range(5):
            plan = schedule_incremental(database=self.database, maximum=2, requirements=('characters',))
            seen.update(plan['work_ids'])
        self.assertEqual(len(seen), 5)

    def test_missing_license_and_network_failure_do_not_complete_jobs(self):
        from .literary_learning import run_refresh_batch
        memory.enqueue_refresh(self.work_id, 'characters', 'wikipedia', database=self.database)
        bad = {**PAGE, 'license': 'unknown'}
        result = run_refresh_batch(database=self.database, max_jobs=1, fetch=lambda *args: [bad])
        self.assertEqual(result['completed'], 0)
        self.assertEqual(self.rows()[0]['status'], 'pending')

    def test_completed_job_has_verification_time_and_daily_cooldown(self):
        from .continuous_knowledge import queue_gap
        identifier = queue_gap(self.work_id, 'summary', 'insufficient_evidence', database=self.database)
        job = memory.claim_job('one', database=self.database)
        self.assertTrue(memory.finish_job(identifier, lease_token=job['lease_token'], database=self.database))
        completed = json.loads(self.rows()[0]['payload'])
        self.assertGreater(completed['last_completed_at'], 0)
        self.assertEqual(completed['last_verification'], 'source_identity_license_and_coverage')
        queue_gap(self.work_id, 'summary', 'audit_rejected', database=self.database)
        self.assertIsNone(memory.claim_job('two', database=self.database))

    def test_actual_chat_observation_records_category_without_private_question(self):
        from .continuous_knowledge import observe_answer
        from .literary_ai import ChatResult
        report = observe_answer('Dime los personajes de Cuaderno lunar', ChatResult('No tengo evidencia.', 'unavailable'),
                                database=self.database)
        self.assertEqual(report['queued'], 1)
        self.assertEqual(self.rows()[0]['requirement'], 'characters')
        self.assertNotIn('Dime', self.rows()[0]['payload'])
        self.assertEqual(observe_answer('Mi correo es lector@example.com',
            ChatResult('Hola', 'answered'), database=self.database), {'queued': 0})

    def test_stop_file_prevents_scheduling_and_network(self):
        from .continuous_knowledge import run_continuous_batch
        stop = self.database.parent / 'stop'
        stop.touch()
        result = run_continuous_batch(database=self.database, stop_file=stop)
        self.assertEqual(result['stopped'], 'stop_file')
        self.assertEqual(self.rows(), [])

    def test_global_worker_lease_prevents_second_run(self):
        from .continuous_knowledge import run_continuous_batch
        with patch('core.ai_concurrency.acquire', return_value=False):
            result = run_continuous_batch(database=self.database, min_free_gb=1)
        self.assertEqual(result['stopped'], 'another_worker')
        self.assertEqual(self.rows(), [])

    def test_pending_reader_correction_never_becomes_an_assertion(self):
        from .continuous_knowledge import observe_answer
        from .literary_ai import ChatResult
        from .test_narrative_answers import history
        report = observe_answer('Te equivocaste: la protagonista se llama Nombre Inventado',
            ChatResult('Lo revisaré.', 'unavailable'), history(), database=self.database)
        self.assertEqual(report['queued'], 1)
        self.assertEqual(json.loads(self.rows()[0]['payload'])['last_gap_reason'], 'reader_correction_pending')
        with memory._connection(self.database) as db:
            self.assertFalse(db.execute("SELECT 1 FROM memory_assertions WHERE record LIKE '%Inventado%'").fetchone())

    def test_known_focus_can_queue_adaptations_without_publishing_reader_text(self):
        from .continuous_knowledge import observe_answer
        from .literary_ai import ChatResult
        from .test_narrative_answers import history
        result = observe_answer('¿Y las adaptaciones de ese libro?', ChatResult('Falta evidencia.', 'unavailable'),
                                history(), database=self.database)
        self.assertEqual(result.get('requirement'), 'adaptations')
        self.assertEqual(result['queued'], 1)

    def test_context_section_is_stored_with_its_scope_and_never_used_as_plot(self):
        from .literary_identity import bind_source
        from .literary_enrichment import enrich_source
        from .literary_learning import _covers_requirement
        from .ai_narrative_answers import _task_content
        source = {**PAGE, 'description': '== Contexto histórico == La novela fue escrita durante un '
                  'periodo de cambios sociales y publicada por primera vez en una revista de la ciudad.'}
        source = bind_source(enrich_source(source, BOOK, 'historical_context'), BOOK)
        self.assertEqual(memory.remember_evidence([BOOK], [source], database=self.database)['sources'], 1)
        books, sources = memory.retrieve_evidence(BOOK['title'], books=[BOOK], database=self.database)
        self.assertTrue(_covers_requirement(BOOK, books, sources, 'historical_context'))
        self.assertFalse(any(_task_content({'task':'summary'}, source) for source in sources))

    def test_attempt_cap_preserves_failure_for_review(self):
        from .literary_learning import run_refresh_batch
        memory.enqueue_refresh(self.work_id, 'summary', 'wikipedia', database=self.database)
        report = run_refresh_batch(database=self.database, max_jobs=1, max_attempts=1,
                                   fetch=lambda *args: [])
        self.assertEqual(report['completed'], 0)
        self.assertEqual(self.rows()[0]['status'], 'review')

    def test_one_incremental_run_persists_facts_and_rehydrates_new_index(self):
        from .continuous_knowledge import run_continuous_batch
        from .literary_enrichment import enrich_source
        from .literary_identity import bind_source
        from .literary_memory_rag import search_memory_semantic
        admitted = bind_source(enrich_source(PAGE, BOOK, 'summary'), BOOK)
        with patch('core.literary_learning._fetch_public_metadata', return_value=[admitted]):
            result = run_continuous_batch(database=self.database, work_ids=[self.work_id],
                max_jobs=1, max_seconds=20, min_free_gb=1,requirements=('summary',))
        self.assertEqual(result['batch']['completed'], 1)
        self.assertTrue(result['index']['index_updated'])
        unused, sources = search_memory_semantic('estación lunar hermano', books=[BOOK],
            database=self.database, index=self.database.parent/'memory_rag.sqlite3')
        self.assertTrue(any('hermano' in source['description'] for source in sources))
        self.assertTrue(all(source['memory_verified'] for source in sources))

    def test_mysql_failure_keeps_admitted_memory_and_pending_queue(self):
        from django.db import DatabaseError
        from .continuous_knowledge import run_continuous_batch
        before = self.database.read_bytes()
        with patch('core.literary_learning.run_refresh_batch', return_value={'completed': 0}), \
                patch('django.db.connection.vendor', 'mysql'), \
                patch.dict('django.db.connection.settings_dict', {'HOST':'127.0.0.1'}), \
                patch('django.db.transaction.atomic', return_value=nullcontext()), \
                patch('core.continuous_knowledge.project_references', side_effect=DatabaseError('private DSN')):
            result = run_continuous_batch(database=self.database, work_ids=[self.work_id],
                min_free_gb=1, reindex=False, project_mysql=True)
        self.assertEqual(result['mysql_projection_error'], 'database_unavailable')
        self.assertTrue(memory.get_work(self.work_id, database=self.database))
        self.assertEqual(len(self.rows()), 2)
        self.assertNotIn('DSN', json.dumps(result))

    def test_priority_job_outside_rotating_scan_is_included_in_mysql_references(self):
        from .continuous_knowledge import run_continuous_batch
        other = {**BOOK, 'title':'Otra obra', 'url':'https://openlibrary.org/works/OL222W'}
        memory.remember_evidence([other], [other], database=self.database)
        outside = stable_work_id(other['title'], other['author'])
        batch = {'completed':1, 'jobs':[{'work_id':outside, 'lease_current':True}]}
        with patch('core.literary_learning.run_refresh_batch', return_value=batch), \
                patch('django.db.connection.vendor', 'mysql'), \
                patch.dict('django.db.connection.settings_dict', {'HOST':'127.0.0.1'}), \
                patch('django.db.transaction.atomic', return_value=nullcontext()), \
                patch('core.continuous_knowledge.project_references', return_value=1) as project, \
                patch('core.knowledge_models.KBProjection.objects.update_or_create'):
            result = run_continuous_batch(database=self.database, maximum=1,
                min_free_gb=1, reindex=False, project_mysql=True)
        self.assertEqual(project.call_args.args[0][0], outside)
        self.assertIn(outside, result['projected_work_ids'])

    def test_bounded_index_selection_does_not_scan_every_assertion_for_every_source(self):
        # Bound SQLite VM work for a 601-document synthetic catalogue. This
        # reproduces the quadratic selection observed in the real pilot.
        with memory._connection(self.database, write=True) as db:
            source = db.execute('SELECT * FROM memory_sources LIMIT 1').fetchone()
            assertion = db.execute('SELECT * FROM memory_assertions LIMIT 1').fetchone()
            for index in range(600):
                sid = str(index).zfill(64)
                values = list(source); values[0] = sid
                db.execute('INSERT INTO memory_sources VALUES (?,?,?,?,?,?,?,?,?,?)', values)
                values = list(assertion); values[0] = sid; values[2] = sid
                db.execute('INSERT INTO memory_assertions VALUES (?,?,?,?,?,?,?,?)', values)
        original = memory._connection
        @contextmanager
        def metered(*args, **kwargs):
            with original(*args, **kwargs) as db:
                ticks = [0]
                def budget():
                    ticks[0] += 1
                    return int(ticks[0] > 200)  # 200,000 VM steps, independent of CPU speed.
                db.set_progress_handler(budget, 1000)
                yield db
        with patch('core.literary_memory._connection', metered):
            result = memory.export_index_sources(database=self.database, limit=1)
        self.assertEqual(len(result), 1)
