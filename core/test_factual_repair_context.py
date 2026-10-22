"""Una auditoría inválida conserva sus advertencias sin publicarlas como hechos."""
from unittest.mock import Mock

from django.test import SimpleTestCase

from .literary_ai import LiteraryAssistant, canonical_sources
from .literary_quality import required_fact_statements
from .test_ai_quality import QualityLLM
from .test_grounded_topic_fallback import KOREA


BAD = 'A history of Korea — Kyung Moon Hwang. Abarca desde sus orígenes hasta la actualidad.'
GOOD = 'A history of Korea — Kyung Moon Hwang. Una opción sobre historia de Corea.'


def draft(text):
    return {'status': 'answer', 'text': text, 'basis': 'sources', 'citations': [1],
            'needs_web': False, 'books': [{'title': KOREA['title'], 'author': KOREA['author'], 'source_id': 1}]}


def audit(text, *, rejected=False):
    claims = [{'statement': statement, 'verdict': 'supported', 'source_id': 1,
               'evidence': KOREA['description']} for statement in required_fact_statements(text)]
    if rejected:
        claims[-1].update(verdict='inference', source_id=0, evidence='')
    return {'decision': 'approve', 'only_books': True,
            'coverage': [{'question_id': 1, 'status': 'answered'}],
            'claims': claims, 'search_queries': [], 'issues': []}


class FactualRepairContextTests(SimpleTestCase):
    def make(self, *, repeated=False):
        llm = QualityLLM(answer=draft(BAD), repair=draft(BAD if repeated else GOOD),
                         audits=[audit(BAD, rejected=True), audit(BAD if repeated else GOOD, rejected=repeated)])
        bot = LiteraryAssistant(llm, Mock(return_value=[KOREA]), quality_checks=True,
                               require_book_sources=True, fast_recommendations=True, research_enabled=True)
        return bot, llm

    def test_rejected_phrase_reaches_repair_as_a_warning_and_new_text_is_audited(self):
        bot, llm = self.make()
        result = bot.reply('Recomiéndame un libro sobre historia de Corea', topic_context={
            'subject': 'historia de Corea', 'intent': 'recommend',
            'query': 'Recomiéndame un libro sobre historia de Corea'})
        repair = next(data for stage, data, model in llm.records if stage == 'repair')
        self.assertEqual(repair['rejected_claims'], [{'statement': required_fact_statements(BAD)[-1],
                         'verdict': 'inference', 'action': 'remove_or_qualify'}])
        self.assertNotIn('previous_draft', repair)
        self.assertEqual(repair['sources'], canonical_sources([KOREA]))
        self.assertEqual(result.status, 'answered')
        self.assertIn('Una opción', result.text)
        self.assertNotIn('actualidad', result.text)
        self.assertEqual(sum(stage == 'audit' for stage, data, model in llm.records), 2)
        self.assertNotIn('rejected_claims', result.diagnostics)

    def test_repeating_the_rejected_phrase_cannot_bypass_existing_validators(self):
        bot, llm = self.make(repeated=True)
        result = bot.reply('Recomiéndame un libro sobre historia de Corea', topic_context={
            'subject': 'historia de Corea', 'intent': 'recommend',
            'query': 'Recomiéndame un libro sobre historia de Corea'})
        self.assertNotIn('actualidad', result.text)
        self.assertTrue(result.diagnostics.get('grounded_catalog_fallback'))
        self.assertTrue(result.diagnostics['validation_issues'])

    def test_false_supported_label_does_not_hide_the_phrase_with_invalid_catalogue_support(self):
        bad_audit = audit(BAD)
        llm = QualityLLM(answer=draft(BAD), repair=draft(GOOD), audits=[bad_audit, audit(GOOD)])
        bot = LiteraryAssistant(llm, Mock(return_value=[KOREA]), quality_checks=True,
            require_book_sources=True, fast_recommendations=True, research_enabled=True)
        result = bot.reply('Recomiéndame un libro sobre historia de Corea', topic_context={
            'subject': 'historia de Corea', 'intent': 'recommend',
            'query': 'Recomiéndame un libro sobre historia de Corea'})
        repair = next(data for stage, data, model in llm.records if stage == 'repair')
        self.assertEqual(repair['rejected_claims'], [{'statement': required_fact_statements(BAD)[-1],
            'verdict': 'invalid_support', 'action': 'verify_or_remove'}])
        self.assertEqual(result.status, 'answered')
        self.assertNotIn('actualidad', result.text)

    def test_a_rejected_greeting_uses_validated_records_without_a_second_generation(self):
        llm = QualityLLM(answer=draft('¡Buen tema!'))
        bot = LiteraryAssistant(llm, Mock(return_value=[KOREA]), quality_checks=True,
            require_book_sources=True, fast_recommendations=True, research_enabled=True)
        result = bot.reply('Recomiéndame un libro sobre historia de Corea', topic_context={
            'subject': 'historia de Corea', 'intent': 'recommend',
            'query': 'Recomiéndame un libro sobre historia de Corea'})
        self.assertEqual(result.status, 'answered')
        self.assertIn(KOREA['title'], result.text)
        self.assertTrue(result.diagnostics['early_grounded_fallback'])
        self.assertTrue(result.diagnostics['validation_issues'])
        self.assertEqual(result.diagnostics['catalog_fallback_audit']['decision'], 'approve')
        self.assertEqual([stage for stage, data, model in llm.records], ['answer'])
        self.assertTrue(result.diagnostics['simple_literary_route'])
