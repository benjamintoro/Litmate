"""Los diagnósticos de latencia usan números de Ollama, nunca texto del lector."""
from unittest.mock import patch

from django.test import SimpleTestCase

from .literary_ai import ProviderUnavailable
from .local_llm import OllamaJSON
from .test_local_ai import SHOW, response


class LocalStageMetricsTests(SimpleTestCase):
    def test_provider_durations_and_token_counts_are_reported_separately(self):
        reply = response({'status': 'answer'}, load_duration=2_500_000_000,
                         prompt_eval_duration=3_750_000_000, eval_duration=1_125_000_000,
                         total_duration=7_375_000_000, prompt_eval_count=1200, eval_count=75,
                         secret='never copy arbitrary response metadata')
        client = OllamaJSON()
        with patch('core.local_llm.read_json_url', side_effect=[SHOW, reply]):
            client('answer', 'JSON', {'message': 'Un mensaje privado'}, 'local-test')
        timing = client.stage_timings[0]
        self.assertEqual(timing['load_ms'], 2500)
        self.assertEqual(timing['prompt_eval_ms'], 3750)
        self.assertEqual(timing['eval_ms'], 1125)
        self.assertEqual(timing['total_ms'], 7375)
        self.assertEqual(timing['prompt_eval_count'], 1200)
        self.assertEqual(timing['eval_count'], 75)
        self.assertNotIn('secret', timing)
        self.assertNotIn('message', timing)

    def test_invalid_metrics_are_ignored_and_not_reused_by_the_next_stage(self):
        client = OllamaJSON()
        first = response({'status': 'answer'}, load_duration=10_000_000)
        second = response({'status': 'answer'}, load_duration=True,
                          prompt_eval_duration='100', eval_duration=-1,
                          total_duration=10**30, prompt_eval_count=False, eval_count=-1)
        with patch('core.local_llm.read_json_url', side_effect=[SHOW, first, second]):
            client('answer', 'JSON', {}, 'local-test')
            client('review', 'JSON', {}, 'local-test')
        self.assertEqual(client.stage_timings[0]['load_ms'], 10)
        for key in ('load_ms', 'prompt_eval_ms', 'eval_ms', 'total_ms', 'prompt_eval_count', 'eval_count'):
            self.assertNotIn(key, client.stage_timings[1])

    def test_incomplete_response_keeps_cost_metrics_without_becoming_success(self):
        client = OllamaJSON()
        incomplete = response(done_reason='length', eval_duration=123_000_000)
        with patch('core.local_llm.read_json_url', side_effect=[SHOW, incomplete]):
            with self.assertRaises(ProviderUnavailable):
                client('answer', 'JSON', {}, 'local-test')
        self.assertEqual(client.stage_timings[0]['status'], 'failed')
        self.assertEqual(client.stage_timings[0]['eval_ms'], 123)
