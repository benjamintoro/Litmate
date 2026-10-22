"""Recuperar un pasaje no basta si la respuesta solo cita la ficha general."""
from unittest.mock import Mock

from django.test import SimpleTestCase

from .literary_ai import LiteraryAssistant
from .test_ai_quality import QualityLLM
from .test_literary_ai import ROUTE
from .test_literary_identity import BOOK


STATEMENT = 'Det intenta volver a su planeta.'
EVENT = {'title': BOOK['title'], 'author': 'Fuente web', 'kind': 'web', 'source': 'Wikipedia',
         'url': 'https://es.wikipedia.org/wiki/Papelucho_y_el_marciano', 'description': STATEMENT,
         'work_binding_verified': True, 'work_title': BOOK['title'], 'work_author': BOOK['author'],
         'literary_facts': [{'subject': 'Det', 'topic': 'events', 'evidence': STATEMENT}]}
GENERAL = {**EVENT, 'source': 'Conocimiento literario local',
           'url': 'https://literaturasm.cl/diario-secreto-de-papelucho-y-el-marciano/',
           'description': 'Papelucho convive con Det, un amigo extraterrestre.', 'literary_facts': []}


def answer(citations):
    return {'status': 'answer', 'text': STATEMENT, 'basis': 'sources',
            'citations': citations, 'needs_web': False,
            'books': [{'title': BOOK['title'], 'author': BOOK['author'], 'source_id': 1}]}


class QuestionSpecificCitationTests(SimpleTestCase):
    def run_case(self, *, repair=True):
        audit = {'decision': 'approve', 'only_books': True,
                 'coverage': [{'question_id': 1, 'status': 'answered'}],
                 'claims': [{'statement': STATEMENT, 'verdict': 'supported', 'source_id': 3,
                             'evidence': STATEMENT}], 'search_queries': [], 'issues': []}
        llm = QualityLLM(route={**ROUTE, 'intent': 'analysis', 'followup': True,
            'queries': [], 'candidates': [{'title': BOOK['title'], 'author': BOOK['author']}]},
            answer=answer([1, 2]), repair=answer([1, 2, 3] if repair else [1, 2]), audits=[audit])
        bot = LiteraryAssistant(llm, Mock(return_value=[BOOK, GENERAL, EVENT]), quality_checks=True,
            require_book_sources=True, research_enabled=True)
        result = bot.reply('¿Qué sucede con Det?', [{'accepted': True, 'books': [BOOK], 'sources': [BOOK]}])
        return result, llm

    def test_citing_only_the_general_record_requires_repair_with_the_actual_event_passage(self):
        result, llm = self.run_case()
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertEqual([stage for stage, data, model in llm.records], ['route', 'answer', 'repair', 'audit'])
        context = next(data for stage, data, model in llm.records if stage == 'answer')
        self.assertEqual(context['question_evidence_source_ids'], [3])
        self.assertIn(EVENT['url'], result.text)
        self.assertIn('Cita el pasaje', result.diagnostics['validation_issues'][0]['issue'])

    def test_repeated_wrong_citations_never_publish_the_unsupported_detail(self):
        result, llm = self.run_case(repair=False)
        self.assertEqual(result.status, 'unavailable')
        self.assertNotIn(STATEMENT, result.text)
        self.assertNotIn('audit', [stage for stage, data, model in llm.records])
