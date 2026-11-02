import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from .literary_ai import ChatResult


@override_settings(LITMATE_AI_QUICK_ANSWERS=False)
class MemoryTraceInstrumentationTests(TestCase):
    def test_trace_file_is_written_when_enabled(self):
        os.environ['LITMATE_TRACE_MEMORY'] = '1'
        fd, path = tempfile.mkstemp(suffix='.jsonl')
        os.close(fd)
        os.environ['LITMATE_TRACE_MEMORY_PATH'] = path
        try:
            with patch('core.literary_ai_views._compute_answer', return_value=(
                    ChatResult('Fuente simulada no disponible.', 'unavailable'),
                    SimpleNamespace(usage={}, provider='fixture', calls=0))), patch(
                    'core.literary_ai_views.rate_allowed', return_value=True):
                response = self.client.post('/chatbot_query/', json.dumps(
                    {'message': 'Dime los personajes de Libro sintético'}), content_type='application/json')
                self.assertEqual(response.status_code, 200)
                b''.join(response.streaming_content)
            with open(path, encoding='utf-8') as handle:
                lines = [json.loads(line) for line in handle if line.strip()]
            self.assertTrue(lines)
            phases = {entry.get('phase') for entry in lines}
            self.assertIn('A_before_load', phases)
            self.assertIn('B_after_load', phases)
        finally:
            os.environ.pop('LITMATE_TRACE_MEMORY', None)
            os.environ.pop('LITMATE_TRACE_MEMORY_PATH', None)
            try:
                os.remove(path)
            except OSError:
                pass

    def test_trace_disabled_by_default(self):
        os.environ.pop('LITMATE_TRACE_MEMORY', None)
        fd, path = tempfile.mkstemp(suffix='.jsonl')
        os.close(fd)
        os.remove(path)
        os.environ['LITMATE_TRACE_MEMORY_PATH'] = path
        try:
            self.client.post('/chatbot_query/', json.dumps({'message': 'Hola'}), content_type='application/json')
            self.assertFalse(os.path.exists(path))
        finally:
            os.environ.pop('LITMATE_TRACE_MEMORY_PATH', None)
