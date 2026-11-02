"""Presupuesto de salida menor sin cambiar la conversación ni omitir revisión."""
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .literary_ai import ANSWER_PROMPT
from .local_llm import OllamaJSON
from .test_local_ai import SHOW, response


class ConversationOutputBudgetTests(SimpleTestCase):
    def test_small_context_keeps_the_full_personality_prompt_and_message(self):
        message = 'Me gusta conversar sobre las historias que leo.'
        fetch = Mock(side_effect=[SHOW, response({'status': 'answer'})])
        with patch('core.local_llm.read_json_url', fetch):
            OllamaJSON(context=8192, answer_tokens=3072)('answer', ANSWER_PROMPT,
                {'intent': 'conversation', 'message': message, 'sources': []}, 'local-test')
        payload = fetch.call_args.kwargs['payload']
        self.assertEqual(payload['options']['num_predict'], 1024)
        self.assertEqual(payload['messages'][0]['content'], ANSWER_PROMPT)
        self.assertIn(message, payload['messages'][1]['content'])
        self.assertEqual(payload['options']['num_ctx'], 8192)

    def test_other_answer_intents_keep_the_configured_output_limit(self):
        fetch = Mock(side_effect=[SHOW, response({'status': 'answer'})])
        with patch('core.local_llm.read_json_url', fetch):
            OllamaJSON(context=16384, answer_tokens=3072)('answer', 'Analiza el pasaje recibido.',
                {'intent': 'analysis', 'sources': []}, 'local-test')
        self.assertEqual(fetch.call_args.kwargs['payload']['options']['num_predict'], 3072)
