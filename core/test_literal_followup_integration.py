"""Omitir clasificación literal no omite investigación ni auditoría factual."""
import tempfile
from pathlib import Path
from unittest.mock import Mock

from django.test import SimpleTestCase, override_settings

from .literary_ai import LiteraryAssistant
from .literary_knowledge import prepare_seed_knowledge, search_knowledge
from .test_literary_ai import ROUTE
from .test_research_integration import EvidenceFixtureLLM


class LiteralFollowupIntegrationTests(SimpleTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / 'knowledge.sqlite3'
        prepare_seed_knowledge(self.database)
        self.sources = search_knowledge('Papelucho y el marciano', database=self.database)
        self.statement = ('La convivencia de Papelucho con Det provoca problemas y enfados '
                          'y ofrece la posibilidad de viajar a otros mundos.')
        self.model = EvidenceFixtureLLM({**ROUTE, 'intent': 'analysis'}, self.statement,
            title=self.sources[0]['title'], proofs={self.statement: self.statement})
        self.bot = LiteraryAssistant(self.model, Mock(return_value=self.sources),
            quality_checks=True, require_book_sources=True, research_enabled=True,
            web_search=Mock(return_value=[]))
        self.history = [{'accepted': True, 'books': [self.sources[0]], 'sources': self.sources}]

    def test_documented_followup_keeps_the_real_factual_audit_and_sources(self):
        with override_settings(LITMATE_KNOWLEDGE_DB=self.database):
            result = self.bot.reply('¿Y qué sucede con Det?', self.history)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        stages = [stage for stage, _, _ in self.model.records]
        self.assertNotIn('route', stages)
        self.assertNotIn('plan', stages)
        self.assertIn('answer', stages)
        self.assertIn('audit', stages)
        self.assertTrue(result.diagnostics['literal_followup_route'])
        self.assertEqual(result.books[0]['title'], self.sources[0]['title'])
        self.assertTrue(any(self.statement in source['description'] for source in result.sources))

    def test_no_shortcut_when_character_only_exists_in_previous_model_answer(self):
        history = [{**self.history[0], 'answer': 'Conversamos sobre Det.',
                    'sources': [self.sources[0]]}]
        with override_settings(LITMATE_KNOWLEDGE_DB=self.database):
            self.bot.reply('¿Y qué sucede con Det?', history)
        self.assertIn('route', [stage for stage, _, _ in self.model.records])

    def test_unsupported_fact_is_still_rejected_after_literal_classification(self):
        original = self.model
        def incorrect_model(stage, prompt, data, model):
            if stage == 'audit':
                # El auditor simulado intenta omitir la frase inventada.
                data = {**data, 'draft': {**data['draft'], 'text': self.statement}}
            result = original(stage, prompt, data, model)
            if stage in {'answer', 'repair', 'answer_web'}:
                result['text'] += ' Det gana una batalla en Saturno.'
            return result
        self.bot.llm = incorrect_model
        with override_settings(LITMATE_KNOWLEDGE_DB=self.database):
            result = self.bot.reply('¿Y qué sucede con Det?', self.history)
        self.assertEqual(result.status, 'unavailable', result.diagnostics)
        self.assertNotIn('Saturno', result.text)
        self.assertTrue(result.diagnostics['literal_followup_route'])
        self.assertIn('audit', [stage for stage, _, _ in original.records])
