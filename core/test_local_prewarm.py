"""Precarga explícita con HTTP simulado; sin GPU, red ni base de datos."""
import io
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from .management.commands.precalentar_ia import Command


MODEL = 'qwen3.5:9b-q4_K_M'
INFO = {'details': {'format': 'gguf'}, 'model_info': {'general.architecture': 'qwen35'},
        'capabilities': ['completion', 'thinking']}
LOADED = {'model': MODEL, 'response': '', 'done': True, 'done_reason': 'load',
          'load_duration': 81_038_000_000}
PATH = 'core.management.commands.precalentar_ia.'


@override_settings(LITMATE_OLLAMA_URL='http://localhost:11434',
                   LITMATE_LOCAL_MODEL=MODEL, LITMATE_LOCAL_CONTEXT=12288)
class LocalPrewarmTests(SimpleTestCase):
    def invoke(self, *, show=INFO, response=LOADED, **options):
        out = io.StringIO()
        with patch('core.local_llm.read_json_url', return_value=show) as inspect, \
                patch(PATH + 'read_json_url', return_value=response) as generate:
            call_command('precalentar_ia', stdout=out, **options)
        return out.getvalue(), inspect, generate

    def test_explicit_preload_uses_current_model_context_and_empty_prompt_without_checks_or_db(self):
        self.assertEqual(Command.requires_system_checks, [])
        self.assertIs(Command.requires_migrations_checks, False)
        with patch.object(Command, 'check') as checks, \
                patch.object(Command, 'check_migrations') as migrations:
            output, inspect, generate = self.invoke()
        checks.assert_not_called()
        migrations.assert_not_called()
        self.assertEqual(inspect.call_args.args[0], 'http://127.0.0.1:11434/api/show')
        self.assertEqual(inspect.call_args.kwargs['payload'], {'model': MODEL})
        self.assertTrue(inspect.call_args.kwargs['local'])
        generate.assert_called_once()
        self.assertEqual(generate.call_args.args[0], 'http://127.0.0.1:11434/api/generate')
        self.assertEqual(generate.call_args.kwargs['payload'], {
            'model': MODEL, 'prompt': '', 'stream': False, 'keep_alive': '30m',
            'options': {'num_ctx': 12288}})
        self.assertTrue(generate.call_args.kwargs['local'])
        self.assertGreater(generate.call_args.kwargs['timeout'], 0)
        self.assertLessEqual(generate.call_args.kwargs['timeout'], 300)
        self.assertIn('load_ms: 81038.000', output)
        self.assertIn('duración:', output)
        self.assertIn('sin generar texto', output)

    def test_bounded_options_accept_endpoints_and_context_matches_runtime_clamp(self):
        for keep_alive, timeout, context in [('5m', 30, 4096), ('120m', 600, 65536)]:
            with self.subTest(keep_alive=keep_alive), override_settings(LITMATE_LOCAL_CONTEXT=context):
                _, _, generate = self.invoke(keep_alive=keep_alive, timeout=timeout)
                payload = generate.call_args.kwargs['payload']
                self.assertEqual(payload['keep_alive'], keep_alive)
                self.assertEqual(payload['options']['num_ctx'], max(8192, min(context, 32768)))
                self.assertLessEqual(generate.call_args.kwargs['timeout'], timeout)

    def test_invalid_limits_fail_before_any_http(self):
        options = ([{'keep_alive': value} for value in
                    ['0', '-1', '4m', '121m', '1h', '30m\n', '05m', '', None]]
                   + [{'timeout': value} for value in [29, 601, True, '300']])
        for option in options:
            with self.subTest(option=option), patch('core.local_llm.read_json_url') as inspect, \
                    patch(PATH + 'read_json_url') as generate:
                with self.assertRaises(CommandError):
                    call_command('precalentar_ia', stdout=io.StringIO(), **option)
                inspect.assert_not_called()
                generate.assert_not_called()

    def test_external_credentials_and_private_non_loopback_origins_never_receive_requests(self):
        for origin in ['https://ollama.com:443', 'http://192.168.1.2:11434',
                       'http://user:SECRET@127.0.0.1:11434', 'http://127.0.0.1:11434/path',
                       'http://127.0.0.1:11434/?token=SECRET']:
            with self.subTest(origin=origin), override_settings(LITMATE_OLLAMA_URL=origin), \
                    patch('core.local_llm.read_json_url') as inspect, \
                    patch(PATH + 'read_json_url') as generate:
                with self.assertRaises(CommandError) as error:
                    call_command('precalentar_ia', stdout=io.StringIO())
                self.assertNotIn('SECRET', str(error.exception))
                inspect.assert_not_called()
                generate.assert_not_called()

    def test_cloud_or_remote_model_metadata_is_rejected_before_preload(self):
        metadata = [{**INFO, 'remote_host': 'https://paid.example/SECRET'},
                    {**INFO, 'details': {'format': 'gguf', 'remote_model': MODEL}},
                    {**INFO, 'capabilities': ['completion', 'cloud']},
                    {**INFO, 'details': {'format': 'unknown'}},
                    {**INFO, 'capabilities': ['embedding']}]
        for info in metadata:
            with self.subTest(info=info), patch('core.local_llm.read_json_url', return_value=info), \
                    patch(PATH + 'read_json_url') as generate:
                with self.assertRaises(CommandError) as error:
                    call_command('precalentar_ia', stdout=io.StringIO())
                self.assertNotIn('SECRET', str(error.exception))
                generate.assert_not_called()
        with override_settings(LITMATE_LOCAL_MODEL='qwen3:cloud'), \
                patch('core.local_llm.read_json_url') as inspect, \
                patch(PATH + 'read_json_url') as generate:
            with self.assertRaises(CommandError):
                call_command('precalentar_ia', stdout=io.StringIO())
            inspect.assert_not_called()
            generate.assert_not_called()

    def test_missing_or_unavailable_model_never_pulls_and_hides_server_details(self):
        errors = [HTTPError('http://localhost:11434/SECRET', 404, 'SECRET', {}, None),
                  URLError('Authorization: Bearer SECRET'), TimeoutError('SECRET')]
        for failure in errors:
            with self.subTest(failure=type(failure).__name__), \
                    patch('core.local_llm.read_json_url', side_effect=failure) as inspect, \
                    patch(PATH + 'read_json_url') as generate:
                with self.assertRaises(CommandError) as error:
                    call_command('precalentar_ia', stdout=io.StringIO())
                self.assertNotIn('SECRET', str(error.exception))
                self.assertEqual(inspect.call_args.args[0], 'http://127.0.0.1:11434/api/show')
                generate.assert_not_called()

    def test_preload_failure_has_no_raw_exception_or_unverified_success_output(self):
        for failure in [TimeoutError('SECRET'), ValueError('SECRET'), RuntimeError('SECRET')]:
            output = io.StringIO()
            with self.subTest(failure=type(failure).__name__), \
                    patch('core.local_llm.read_json_url', return_value=INFO), \
                    patch(PATH + 'read_json_url', side_effect=failure):
                with self.assertRaises(CommandError) as error:
                    call_command('precalentar_ia', stdout=output)
            self.assertNotIn('SECRET', str(error.exception))
            self.assertEqual(output.getvalue(), '')

    def test_malformed_or_generated_output_is_rejected_and_optional_metrics_are_safe(self):
        for response in [None, [], {}, {**LOADED, 'done': False},
                         {**LOADED, 'response': 'SECRET'}, {**LOADED, 'error': 'SECRET'},
                         {**LOADED, 'eval_count': 1}, {**LOADED, 'prompt_eval_count': True},
                         {**LOADED, 'thinking': 'SECRET'}, {**LOADED, 'done_reason': 'unload'}]:
            with self.subTest(response=response), self.assertRaises(CommandError) as error:
                self.invoke(response=response)
            self.assertNotIn('SECRET', str(error.exception))
        for metric in [None, -1, True, 'SECRET', 10 ** 1000]:
            with self.subTest(metric=metric):
                output, _, _ = self.invoke(response={**LOADED, 'load_duration': metric})
                self.assertNotIn('load_ms:', output)
                self.assertNotIn('SECRET', output)
