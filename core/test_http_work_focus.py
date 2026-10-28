"""Regression of reader intent across actual session/SSE finalization.

Providers are deterministic; these tests make no network/model requests.
"""
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase, override_settings

from .ai_character_answers import request_for
from .literary_ai import ChatResult
from .literary_ai_views import HISTORY_KEY


@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies',
                   LITMATE_AI_QUICK_ANSWERS=False, LITMATE_USE_EXISTING_QUOTAS=False)
class HttpWorkFocusTests(TestCase):
    def setUp(self):
        cache.clear()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        override = override_settings(LITMATE_AI_STREAM_DB=Path(folder.name) / 'jobs.sqlite3')
        override.enable()
        self.addCleanup(override.disable)
        self.resolved = []
        self.worker = patch('core.literary_ai_views._compute_answer', side_effect=self.compute)
        self.worker.start()
        self.addCleanup(self.worker.stop)
        rate = patch('core.literary_ai_views.rate_allowed', return_value=True)
        rate.start()
        self.addCleanup(rate.stop)

    def compute(self, message, history, topic):
        client = SimpleNamespace(provider='fixture', calls=0, usage={})
        if message.startswith(('Háblame de ', 'Habla de ', 'Ahora háblame de ')):
            # Reproduce the observed response: an overview of one work followed
            # by three model-only volume cards. They must not redefine focus.
            return ChatResult('Una aventura literaria.', 'answered', True,
                books=[{'title': 'Los viajes: ' + volume, 'author': 'Autora de prueba',
                        'source_id': 0} for volume in ('Uno', 'Dos', 'Tres')], basis='knowledge'), client
        if message == 'Fallo controlado':
            return ChatResult('Fuente temporalmente no disponible.', 'unavailable'), client
        resolved = request_for(message, history)
        self.resolved.append(resolved)
        return ChatResult('He consultado la obra indicada.', 'answered', True), client

    def turn(self, message, *, progressive=True, client=None):
        client = client or self.client
        response = client.post('/chatbot_query/', json.dumps(
            {'message': message, 'progress': progressive}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        raw = b''.join(response.streaming_content).decode('utf-8')
        if progressive:
            events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith('data: {')]
            token = next(event['ready'] for event in events if 'ready' in event)
            final = client.post('/chatbot_finalize/', json.dumps({'ready': token}),
                                content_type='application/json')
            self.assertEqual(final.status_code, 200)
        return client.session[HISTORY_KEY]

    def test_two_requests_keep_requested_work_not_model_cards(self):
        for progressive in (False, True):
            with self.subTest(progressive=progressive):
                client = Client()
                self.turn('Habla de Los viajes', progressive=progressive, client=client)
                first = client.session[HISTORY_KEY]
                self.assertEqual(first['active_work']['title'], 'Los viajes')
                self.assertFalse(first['active_work'].get('author'))
                self.assertEqual(len(first['turns'][0]['books']), 3)
                self.turn('¿Quién es Aurora?', progressive=progressive, client=client)
                self.assertEqual(self.resolved[-1]['title'], 'Los viajes')
                self.assertFalse(self.resolved[-1]['ambiguous'])

    def test_failure_preserves_focus_and_independent_sessions(self):
        other = Client()
        self.turn('Háblame de Los viajes')
        self.turn('Háblame de El jardín', client=other)
        self.turn('Fallo controlado')
        self.turn('¿Quién es Aurora?')
        self.assertEqual(self.resolved[-1]['title'], 'Los viajes')
        self.turn('¿Quién es Aurora?', client=other)
        self.assertEqual(self.resolved[-1]['title'], 'El jardín')

    def test_switch_and_return_to_first_after_failed_turn(self):
        self.turn('Háblame de Los viajes')
        self.turn('Ahora háblame de El jardín')
        self.turn('Fallo controlado')
        self.turn('Volvamos al primer libro')
        self.turn('¿Quién es Aurora?')
        self.assertEqual(self.resolved[-1]['title'], 'Los viajes')

    def test_first_work_survives_history_window_and_previous_switch(self):
        self.turn('Háblame de Los viajes')
        for _ in range(9):
            self.turn('¿Quién es Aurora?')
        self.turn('Ahora háblame de El jardín')
        self.turn('Volvamos al anterior libro')
        self.turn('¿Quién es Aurora?')
        self.assertEqual(self.resolved[-1]['title'], 'Los viajes')
        self.turn('Ahora háblame de El jardín')
        self.turn('Volvamos al primer libro')
        self.turn('¿Quién es Aurora?')
        self.assertEqual(self.resolved[-1]['title'], 'Los viajes')

    def test_sse_trace_covers_resolver_and_final_persist_with_same_conversation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'trace.jsonl'
            with patch.dict(os.environ, {'LITMATE_TRACE_MEMORY': '1',
                                         'LITMATE_TRACE_MEMORY_PATH': str(path)}):
                self.turn('Háblame de Los viajes')
                self.turn('¿Quién es Aurora?')
            rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len({row['conversation'] for row in rows}), 1)
        for run in {row['run_id'] for row in rows}:
            phases = {row['phase'] for row in rows if row['run_id'] == run}
            self.assertTrue({'A_before_load', 'B_after_load', 'C_before_answer',
                             'D_normalized_history', 'E_resolver',
                             'F_after_answer', 'G_after_persist'} <= phases)
        resolved = [row for row in rows if row['phase'] == 'E_resolver' and row['turn'] == 2][0]
        self.assertEqual(resolved['character_request']['title'], 'Los viajes')


class FocusResolverTests(SimpleTestCase):
    def test_companion_of_protagonist_uses_work_evidence_after_navigation(self):
        from copy import deepcopy
        from .ai_character_answers import answer_from_sources
        from .test_character_context_resolution import BOOK, PAGE, history
        page = deepcopy(PAGE)
        role = 'Acompaña a Rafael de la Vega durante el viaje.'
        page['character_facts'].append({'name': 'Bruno', 'role': role})
        page['description'] += '\nBruno: ' + role
        turns = history(page=page)
        turns.append({'accepted': True, 'question': 'Volvamos al primer libro',
                      'answer': 'Volvamos a Crónicas del roble.', 'books': [], 'sources': [],
                      'context_work': BOOK})
        message = '¿Quién acompaña al protagonista?'
        request = request_for(message, turns)
        self.assertIsNotNone(request)
        self.assertEqual(request['title'], BOOK['title'])
        result = answer_from_sources(message, request, [BOOK, page])
        self.assertIsNotNone(result)
        self.assertIn('Bruno', result.text)
        self.assertNotIn('Clara', result.text)  # Friendship alone does not prove accompaniment.

    def test_explicit_work_overview_is_not_a_character_of_itself(self):
        from .literary_focus import focus_history, prepare_focus
        from .ai_narrative_answers import request_for as narrative_request
        for message in ('Háblame de Los viajes', 'Habla de Los viajes',
                        'Ahora háblame de Los viajes', 'Hablemos de Los viajes'):
            state = {'turns': []}
            prepare_focus(state, message)
            history = focus_history(state)
            self.assertIsNone(request_for(message, history))
            self.assertEqual(narrative_request(message, history)['title'], 'Los viajes')

    def test_verified_identity_and_last_character_survive_followup(self):
        from .literary_focus import focus_history, prepare_focus
        from .test_character_context_resolution import BOOK, history
        from .literary_identity import work_identity
        active = work_identity(BOOK)
        turns = history()
        turns[-1]['context_work'] = dict(active)
        state = {'turns': turns, 'active_work': dict(active)}
        prepare_focus(state, '¿Qué relación tiene con Clara?')
        self.assertEqual(state['active_work'], active)
        resolved = request_for('¿Qué relación tiene con Clara?', focus_history(state))
        self.assertFalse(resolved['ambiguous'])
        self.assertEqual([name.lower() for name in resolved['names']], ['rafael de la vega', 'clara'])

    def test_tell_me_about_known_character_does_not_change_work(self):
        from .literary_focus import prepare_focus
        from .test_character_context_resolution import BOOK, history
        from .literary_identity import work_identity
        state = {'turns': history(), 'active_work': work_identity(BOOK)}
        prepare_focus(state, 'Háblame de Rafael de la Vega')
        self.assertEqual(state['active_work']['title'], BOOK['title'])

    def test_focus_does_not_rewrite_old_cards_or_promote_web_title(self):
        from copy import deepcopy
        from .literary_focus import focus_history, remember_focus
        turns = [{'accepted': True, 'books': [], 'sources': [], 'question': 'Anterior'}]
        before = deepcopy(turns)
        state = {'turns': turns, 'active_work': {'title': 'Los viajes'}}
        prepared = focus_history(state)
        self.assertEqual(turns, before)
        self.assertTrue(prepared[-1]['context_only'])
        other = {'sources': [{'kind': 'web', 'title': 'Página de matemáticas', 'author': 'Fuente web'}]}
        empty = {}
        remember_focus(empty, other)
        self.assertNotIn('active_work', empty)
