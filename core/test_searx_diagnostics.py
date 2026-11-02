"""El diagnostico no confunde salud HTTP, infoboxes ni fallos con busquedas utiles."""
from unittest import TestCase
from unittest.mock import patch

from diagnosticar_buscador import summarize_payload, probe_json, probe_docker


class SearchDiagnosticTests(TestCase):
    def test_infobox_alone_is_not_a_result(self):
        result = summarize_payload({'results': [], 'unresponsive_engines': [],
                                    'infoboxes': [{'id': 'https://es.wikipedia.org/wiki/Nana'}]})
        self.assertEqual(result['status'], 'empty')
        self.assertEqual(result['infoboxes_count'], 1)

    def test_working_results_and_failed_engine_are_partial(self):
        result = summarize_payload({'results': [{'title': 'Una obra', 'url': 'https://example.org',
                                                'content': 'Dato'}],
                                    'unresponsive_engines': [['openlibrary', 'unexpected crash']]})
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['results_count'], 1)
        self.assertNotIn('content', result['results'][0])

    def test_empty_failed_engines_are_unavailable(self):
        self.assertEqual(summarize_payload({'results': [], 'unresponsive_engines': [
            ['openlibrary', 'timeout']]})['status'], 'unavailable')

    def test_malformed_api_is_not_success(self):
        for payload in (None, [], {'results': {}}, {'results': [], 'unresponsive_engines': 'error'}):
            self.assertEqual(summarize_payload(payload)['status'], 'invalid_response')

    def test_connection_failure_records_only_exception_class(self):
        with patch('diagnosticar_buscador.build_opener') as opener:
            opener.return_value.open.side_effect = OSError('secret=do-not-print')
            result = probe_json('Un libro')
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('secret', str(result))

    def test_docker_uses_selected_inspection_fields(self):
        with patch('diagnosticar_buscador._docker', return_value={}) as execute:
            probe_docker()
        commands = [call.args for call in execute.call_args_list]
        self.assertEqual(commands[1][2], '{{json .State}}')
        self.assertEqual(commands[2][2], '{{json .NetworkSettings.Ports}}')
        self.assertNotIn('Config.Env', str(commands))
