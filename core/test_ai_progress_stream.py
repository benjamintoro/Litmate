"""Progreso real y finalización segura; fuentes/modelo sustituidos, DB aislada."""
import json
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from contextlib import closing
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.cache import cache
from django.core.signals import request_finished
from django.db import close_old_connections
from django.test import Client, SimpleTestCase, TestCase, override_settings

from .ai_budget import BudgetExpired, check_budget
from .ai_progress import (emit_phase, measure_stage, progress_scope, snapshot_metrics,
                          timed_stage, sanitize_metrics, merge_metrics)
from .ai_stream_jobs import (JobBusy, JobStale, JobUnavailable, claim_finalization,
                             complete_job, create_job, finish_finalization, owner_key)
from .literary_ai import ChatResult
from .literary_ai_views import HISTORY_KEY


def provider():
    return SimpleNamespace(provider='verified-test', calls=0,
                           usage={'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0})


def answer(message, history, topic):
    emit_phase('search')
    return ChatResult('La autoría está comprobada.', 'answered', True,
                      diagnostics={'secret_prompt': 'NO PUBLICAR'}), provider()


class ProgressMetricsTests(SimpleTestCase):
    def test_merge_metrics_preserves_real_origins_stages_and_privacy(self):
        first = {'elapsed_ms': 5, 'stage_totals_ms': {'conversation': 3},
                 'stage_timings': [{'stage': 'conversation', 'started_ms': 1,
                                    'elapsed_ms': 3, 'status': 'ok'}], 'secret': 'not public'}
        second = {'elapsed_ms': 4, 'stage_totals_ms': {'finalization': 2},
                  'stage_timings': [{'stage': 'finalization', 'started_ms': 1,
                                     'elapsed_ms': 2, 'status': 'ok'}],
                  'progress_events': [{'stage': 'review', 'elapsed_ms': .5, 'message': 'private'}]}
        result = merge_metrics(first, second, offset_ms=10)
        self.assertEqual(result['elapsed_ms'], 14)
        self.assertEqual(result['stage_totals_ms'], {'conversation': 3, 'finalization': 2})
        self.assertEqual(result['stage_timings'][1]['started_ms'], 11)
        self.assertEqual(result['first_phase_emitted_ms'], 10.5)
        self.assertNotIn('secret', result)
        self.assertNotIn('message', result['progress_events'][0])

    def test_merge_is_bounded_and_rejects_invalid_offsets(self):
        value = {'stage_timings': [{'stage': 'audit', 'started_ms': i, 'elapsed_ms': 1}
                                  for i in range(128)]}
        self.assertEqual(len(merge_metrics(value, value, offset_ms=128)['stage_timings']), 128)
        for offset in (-1, True, float('inf'), float('nan')):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                merge_metrics({}, {}, offset_ms=offset)

    def test_phases_are_explicit_deduplicated_and_never_contain_reader_data(self):
        callback = Mock()
        with progress_scope(callback):
            self.assertFalse(emit_phase('https://private.example/query'))
            self.assertTrue(emit_phase('search'))
            self.assertFalse(emit_phase('search'))
            with measure_stage('audit'):
                pass
            metrics = snapshot_metrics()
        self.assertEqual(callback.call_count, 2)
        self.assertEqual([item['stage'] for item in metrics['progress_events']], ['search', 'review'])
        self.assertEqual(set(metrics['progress_events'][0]), {'stage', 'message', 'elapsed_ms'})
        self.assertGreaterEqual(metrics['stage_totals_ms']['audit'], 0)
        self.assertIsNotNone(metrics['first_phase_emitted_ms'])
        self.assertEqual(snapshot_metrics(), {})

    def test_public_page_extraction_is_measured_as_its_own_stage(self):
        from .literary_search import read_public_page
        with progress_scope():
            with patch('core.literary_web.extract_public_page',
                       return_value={'status': 'ok', 'description': 'pasaje público'}):
                self.assertEqual(read_public_page(
                    'https://www.cervantesvirtual.com/obra/', 'Nana'), 'pasaje público')
            metrics = snapshot_metrics()
        self.assertIn('extraction', metrics['stage_totals_ms'])
        self.assertTrue(any(row['stage'] == 'extraction' and row['status'] == 'ok'
                            for row in metrics['stage_timings']))

    def test_failed_stage_and_callback_do_not_hide_original_failure(self):
        with progress_scope(Mock(side_effect=ValueError('instrumentation'))):
            with self.assertRaisesRegex(RuntimeError, 'original'):
                with measure_stage('generation'):
                    raise RuntimeError('original')
            self.assertEqual(snapshot_metrics()['stage_timings'][0]['status'], 'failed')

    def test_nested_scope_and_decorator_reuse_the_request_metrics(self):
        @timed_stage('local_search')
        def recover():
            return 7
        with progress_scope() as outer:
            with progress_scope() as inner:
                self.assertIs(outer, inner)
                self.assertEqual(recover(), 7)
            self.assertEqual(len(snapshot_metrics()['stage_timings']), 1)
        self.assertEqual(recover.__name__, 'recover')

    def test_unknown_stage_names_and_unbounded_phase_lists_are_not_recorded(self):
        with progress_scope():
            with measure_stage('private user message'):
                pass
            for _ in range(100):
                emit_phase('search')
                emit_phase('review')
            metrics = snapshot_metrics()
        self.assertEqual(metrics['stage_timings'], [])
        self.assertEqual(len(metrics['progress_events']), 64)

    def test_public_metrics_drop_arbitrary_messages_urls_prompts_and_invalid_numbers(self):
        metrics = sanitize_metrics({'secret_prompt': 'private', 'elapsed_ms': float('nan'),
            'stage_totals_ms': {'audit': 2, 'reader_secret': 9},
            'stage_timings': [{'stage': 'audit', 'elapsed_ms': 2, 'prompt': 'private', 'status': 'ok'},
                              {'stage': 'secret_user_message', 'elapsed_ms': 4}],
            'progress_events': [{'stage': 'review', 'message': 'private', 'elapsed_ms': 5}]})
        self.assertEqual(metrics['stage_totals_ms'], {'audit': 2})
        self.assertEqual(metrics['stage_timings'], [{'stage': 'audit', 'elapsed_ms': 2, 'status': 'ok'}])
        self.assertEqual(metrics['progress_events'], [{'stage': 'review', 'elapsed_ms': 5}])
        self.assertNotIn('private', json.dumps(metrics))
        self.assertNotIn('elapsed_ms', metrics)


class StreamJobTests(SimpleTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='stream-jobs-')
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'stream.sqlite3'
        override = override_settings(LITMATE_AI_STREAM_DB=self.path)
        override.enable()
        self.addCleanup(override.disable)

    def test_private_results_are_owner_bound_and_receipts_are_idempotent(self):
        token = create_job('owner', 'revision', {'message': 'private'})
        self.assertEqual(len(token), 43)
        with self.assertRaises(JobUnavailable):
            claim_finalization(token, 'someone-else')
        self.assertTrue(complete_job(token, 'owner', {'result': 'validated'}))
        first = claim_finalization(token, 'owner')
        self.assertEqual(first['payload']['message'], 'private')
        with self.assertRaises(JobBusy):
            claim_finalization(token, 'owner')
        finish_finalization(token, 'owner', {'body': {'response': 'verified'}})
        repeated = claim_finalization(token, 'owner')
        self.assertEqual(repeated['status'], 'done')
        self.assertEqual(repeated['final']['body']['response'], 'verified')

    def test_new_revision_makes_old_work_stale_even_with_a_stale_signed_cookie(self):
        first = create_job('owner', 'first', {})
        complete_job(first, 'owner', {})
        second = create_job('owner', 'second', {})
        complete_job(second, 'owner', {})
        with self.assertRaises(JobStale):
            claim_finalization(first, 'owner')
        self.assertEqual(claim_finalization(second, 'owner')['revision'], 'second')

    def test_same_quota_principal_is_serialized_across_distinct_sessions(self):
        first = create_job('session-one', 'first', {})
        second = create_job('session-two', 'second', {})
        complete_job(first, 'session-one', {})
        complete_job(second, 'session-two', {})
        claim_finalization(first, 'session-one', quota_owner='same-user')
        with self.assertRaises(JobBusy):
            claim_finalization(second, 'session-two', quota_owner='same-user')
        finish_finalization(first, 'session-one', {})
        self.assertEqual(claim_finalization(second, 'session-two', quota_owner='same-user')['revision'], 'second')

    def test_expiration_removes_private_payload_and_rejects_late_completion(self):
        with patch('core.ai_stream_jobs.time.time', return_value=100):
            token = create_job('owner', 'first', {'message': 'private'})
        with patch('core.ai_stream_jobs.time.time', return_value=221):
            self.assertFalse(complete_job(token, 'owner', {}))
            with self.assertRaises(JobUnavailable):
                claim_finalization(token, 'owner')

    def test_pending_jobs_are_bounded_and_malformed_tokens_do_not_open_database(self):
        create_job('owner', 'first', {})
        create_job('owner', 'second', {})
        with self.assertRaises(JobBusy):
            create_job('owner', 'third', {})
        with patch('core.ai_stream_jobs._connect') as connect:
            with self.assertRaises(JobUnavailable):
                claim_finalization('invalid', 'owner')
            connect.assert_not_called()
        self.assertNotEqual(owner_key('anonymous', 'one'), owner_key('anonymous', 'two'))

    def test_foreign_sqlite_is_rejected_without_modifying_its_bytes_or_rows(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE private_data(secret TEXT)')
            db.execute('INSERT INTO private_data VALUES(\'keep this untouched\')')
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'ajena'):
            create_job('owner', 'revision', {})
        self.assertEqual(self.path.read_bytes(), before)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT secret FROM private_data').fetchall(), [('keep this untouched',)])

    def test_invalid_marker_and_foreign_tables_in_an_owned_database_are_not_adopted(self):
        token = create_job('owner', 'revision', {})
        self.assertNotIn(token.encode('ascii'), self.path.read_bytes())
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE stream_jobs_meta SET value='another-system'")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Marcador'):
            create_job('owner', 'revision', {})
        self.assertEqual(self.path.read_bytes(), before)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE stream_jobs_meta SET value='litmate-private-stream-v1'")
            db.execute('CREATE TABLE private_data(secret TEXT)')
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'ajena'):
            create_job('owner', 'revision', {})
        self.assertEqual(self.path.read_bytes(), before)

    def test_django_and_auxiliary_database_paths_are_rejected_before_connecting(self):
        with patch.object(settings, 'DATABASES', {'default': {'NAME': str(self.path)}}):
            with self.assertRaisesRegex(ValueError, 'base propia'):
                create_job('owner', 'revision', {})
        self.assertFalse(self.path.exists())
        for name in ('LITMATE_AI_RUNTIME_DB', 'LITMATE_RAG_DB', 'LITMATE_KNOWLEDGE_DB',
                     'LITMATE_KNOWLEDGE_RAG_DB', 'LITMATE_AI_ANSWER_CACHE_DB', 'LITMATE_LITERARY_MEMORY_DB'):
            with self.subTest(setting=name), override_settings(**{name: self.path}):
                with self.assertRaisesRegex(ValueError, 'base propia'):
                    create_job('owner', 'revision', {})
                self.assertFalse(self.path.exists())

    def test_new_question_cannot_race_an_active_finalization_for_the_same_session(self):
        token = create_job('owner', 'revision', {})
        complete_job(token, 'owner', {})
        claim_finalization(token, 'owner')
        with self.assertRaises(JobBusy):
            create_job('owner', 'newer', {})


@override_settings(LITMATE_USE_EXISTING_QUOTAS=False, LITMATE_AI_LOCK_BACKEND='cache',
                   LITMATE_AI_QUICK_ANSWERS=False)
class ProgressiveEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        folder = tempfile.TemporaryDirectory(prefix='stream-http-')
        self.addCleanup(folder.cleanup)
        override = override_settings(LITMATE_AI_STREAM_DB=Path(folder.name) / 'stream.sqlite3')
        override.enable()
        self.addCleanup(override.disable)

    def start(self, *, work=answer, client=None, message='¿Quién escribió la obra?', **extra):
        client = client or self.client
        # La vista vuelve antes de ejecutar todas las llamadas del worker. El
        # doble debe sobrevivir hasta consumir/cerrar SSE, no solo client.post.
        worker_patch = patch('core.literary_ai_views._compute_answer', side_effect=work)
        worker_patch.start()
        self.addCleanup(worker_patch.stop)
        with patch('core.literary_ai_views.rate_allowed', return_value=True):
            return client.post('/chatbot_query/', json.dumps({'message': message, 'progress': True, **extra}),
                               content_type='application/json')

    def ready(self, response):
        self.assertEqual(response.status_code, 200)
        raw = b''.join(response.streaming_content).decode('utf-8')
        records = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith('data: {')]
        self.assertTrue(raw.endswith('data: [DONE]\n\n'))
        self.assertNotIn('La autoría está comprobada.', raw)
        return next(item['ready'] for item in records if 'ready' in item)

    def finish(self, token, *, client=None):
        return (client or self.client).post('/chatbot_finalize/', json.dumps({'ready': token}),
                                          content_type='application/json')

    def close_stream(self, response):
        # Igual que closing_iterator_wrapper de Django: el cierre manual no
        # debe cerrar la conexión que contiene la transacción de TestCase.
        request_finished.disconnect(close_old_connections)
        try:
            response.close()
        finally:
            request_finished.connect(close_old_connections)

    def test_first_real_phase_arrives_before_work_finishes_and_history_waits_for_finalization(self):
        started, stop, finished = threading.Event(), threading.Event(), threading.Event()
        def blocked(message, history, topic):
            self.assertNotEqual(threading.current_thread(), threading.main_thread())
            emit_phase('search')
            started.set()
            stop.wait(2)
            finished.set()
            return answer(message, history, topic)
        response = self.start(work=blocked)
        try:
            self.assertTrue(started.wait(1))
            iterator = iter(response.streaming_content)
            first = next(iterator).decode('utf-8')
            self.assertIn('"stage": "search"', first)
            self.assertFalse(finished.is_set())
            self.assertEqual(self.client.session[HISTORY_KEY]['turns'], [])
            stop.set()
            raw = b''.join(iterator).decode('utf-8')
            token = next(json.loads(line[6:])['ready'] for line in raw.splitlines() if '"ready"' in line)
            final = self.finish(token)
            self.assertEqual(final.status_code, 200)
            self.assertEqual(final.json()['response'], 'La autoría está comprobada.')
            self.assertEqual(len(self.client.session[HISTORY_KEY]['turns']), 1)
            self.assertNotIn('secret_prompt', final.json()['diagnostics'])
            metrics = final.json()['diagnostics']['progress_metrics']
            self.assertIn('conversation', metrics['stage_totals_ms'])
            self.assertIn('finalization', metrics['stage_totals_ms'])
            stages = metrics['stage_timings']
            self.assertLess(next(row['started_ms'] for row in stages if row['stage'] == 'conversation'),
                            next(row['started_ms'] for row in stages if row['stage'] == 'finalization'))
        finally:
            stop.set()
            self.close_stream(response)

    def test_token_cannot_be_retrieved_by_another_anonymous_session(self):
        token = self.ready(self.start())
        stolen = self.finish(token, client=Client())
        self.assertEqual(stolen.status_code, 404)
        self.assertNotIn('comprobada', stolen.content.decode())
        self.assertEqual(self.finish(token).status_code, 200)

    def test_completed_worker_notifies_stream_without_a_poll_or_public_control_event(self):
        from queue import Queue
        notified = threading.Event()
        signals = []

        class CompletionQueue(Queue):
            def put_nowait(queue, event):
                super().put_nowait(event)
                if not isinstance(event, dict):
                    signals.append(event)
                    notified.set()

            def get(queue, block=True, timeout=None):
                if notified.is_set() and queue.empty():
                    raise AssertionError('Un Future terminado no debe esperar otro sondeo.')
                return super().get(block, timeout)

        with patch('core.literary_ai_views.Queue', CompletionQueue):
            response = self.start()
            self.assertTrue(notified.wait(2))
            token = self.ready(response)
        self.assertEqual(len(signals), 1)
        self.assertEqual(self.finish(token).status_code, 200)

    def test_worker_failure_notifies_without_publishing_ready_or_internal_details(self):
        def broken(*args):
            raise RuntimeError('private-worker-detail')

        response = self.start(work=broken)
        raw = b''.join(response.streaming_content).decode('utf-8')
        self.assertIn('"error": "unavailable"', raw)
        self.assertTrue(raw.endswith('data: [DONE]\n\n'))
        self.assertNotIn('"ready"', raw)
        self.assertNotIn('private-worker-detail', raw)
        self.assertEqual(self.client.session[HISTORY_KEY]['turns'], [])

    @override_settings(LITMATE_USE_EXISTING_QUOTAS=True)
    def test_duplicate_finalize_charges_once_and_creates_one_authenticated_turn(self):
        from django.contrib.auth import get_user_model
        from .models import MensajeIA
        user = get_user_model().objects.create_user('progress-reader')
        self.client.force_login(user)
        with patch('core.literary_ai_views.cuota_disponible', return_value=(True, {})), \
                patch('core.literary_ai_views.verificar_y_consumir_cuota', return_value=(True, {})) as consume:
            token = self.ready(self.start())
            self.assertEqual(MensajeIA.objects.count(), 0)
            first, second = self.finish(token), self.finish(token)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.status_code, 200)
        self.assertEqual(consume.call_count, 1)
        self.assertEqual(MensajeIA.objects.count(), 2)
        self.assertEqual(len(self.client.session[HISTORY_KEY]['turns']), 1)

    def test_newer_question_prevents_publication_of_an_old_answer(self):
        old = self.ready(self.start())
        new = self.ready(self.start(message='¿Quién escribió el otro libro?'))
        self.assertEqual(self.finish(old).status_code, 409)
        self.assertEqual(self.client.session[HISTORY_KEY]['turns'], [])
        self.assertEqual(self.finish(new).status_code, 200)

    @override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
    def test_signed_cookie_sessions_keep_the_following_turn_and_replay_receipt(self):
        token = self.ready(self.start())
        before_finalize_cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        first = self.finish(token)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(len(self.client.session[HISTORY_KEY]['turns']), 1)
        # Reproducir un ACK HTTP perdido con la cookie previa no repite cuota
        # ni pierde el contexto guardado en el recibo temporal.
        self.client.cookies[settings.SESSION_COOKIE_NAME] = before_finalize_cookie
        self.assertEqual(self.finish(token).status_code, 200)
        self.assertEqual(len(self.client.session[HISTORY_KEY]['turns']), 1)
        received = []
        def following(message, history, topic):
            received.extend(history)
            return answer(message, history, topic)
        next_token = self.ready(self.start(work=following, message='¿Y el anterior?'))
        self.assertEqual(len(received), 1)
        self.assertEqual(self.finish(next_token).status_code, 200)

    @override_settings(LITMATE_USE_EXISTING_QUOTAS=True)
    def test_no_quota_prevents_the_worker_and_final_quota_denial_never_publishes_answer(self):
        worker = Mock(side_effect=answer)
        with patch('core.literary_ai_views.cuota_disponible', return_value=(False, {})):
            denied = self.start(work=worker)
        self.assertEqual(denied.status_code, 429)
        worker.assert_not_called()
        with patch('core.literary_ai_views.cuota_disponible', return_value=(True, {})), \
                patch('core.literary_ai_views.verificar_y_consumir_cuota', return_value=(False, {})) as consume:
            token = self.ready(self.start())
            final = self.finish(token)
            retry = self.finish(token)
        self.assertEqual(final.status_code, 429)
        self.assertEqual(retry.status_code, 429)
        self.assertNotIn('comprobada', final.content.decode())
        self.assertEqual(consume.call_count, 1)
        self.assertEqual(self.client.session[HISTORY_KEY]['turns'], [])

    @override_settings(LITMATE_CHAT_TIMEOUT=.05, LITMATE_USE_EXISTING_QUOTAS=True)
    def test_noncooperative_late_worker_is_not_published_or_charged(self):
        stop, finished = threading.Event(), threading.Event()
        def blocked(message, history, topic):
            try:
                stop.wait(2)
                return answer(message, history, topic)
            finally:
                finished.set()
        try:
            with patch('core.literary_ai_views.cuota_disponible', return_value=(True, {})), \
                    patch('core.literary_ai_views.verificar_y_consumir_cuota') as consume:
                token = self.ready(self.start(work=blocked))
                final = self.finish(token)
                self.assertEqual(final.status_code, 200)
                self.assertEqual(final.json()['status'], 'unavailable')
                self.assertIn('límite de tiempo', final.json()['response'])
                self.assertNotIn('comprobada', final.content.decode())
                consume.assert_not_called()
                self.assertEqual(self.client.session[HISTORY_KEY]['turns'], [])
        finally:
            stop.set()
            self.assertTrue(finished.wait(2))

    def test_close_before_first_chunk_requests_cooperative_cancel(self):
        started, stop, cancelled = threading.Event(), threading.Event(), threading.Event()
        def blocked(message, history, topic):
            started.set()
            stop.wait(2)
            try:
                check_budget()
            except BudgetExpired:
                cancelled.set()
                raise
            return answer(message, history, topic)
        response = self.start(work=blocked)
        try:
            self.assertTrue(started.wait(1))
            self.close_stream(response)
            stop.set()
            self.assertTrue(cancelled.wait(2))
            self.assertEqual(self.client.session[HISTORY_KEY]['turns'], [])
        finally:
            stop.set()

    def test_finalize_requires_post_json_csrf_and_a_valid_token(self):
        self.assertEqual(self.client.get('/chatbot_finalize/').status_code, 405)
        self.assertEqual(self.client.post('/chatbot_finalize/', 'invalid', content_type='text/plain').status_code, 415)
        self.assertEqual(self.client.post('/chatbot_finalize/', '{', content_type='application/json').status_code, 400)
        self.assertEqual(self.finish('invalid').status_code, 404)
        csrf = Client(enforce_csrf_checks=True)
        self.assertEqual(self.finish('x' * 43, client=csrf).status_code, 403)
