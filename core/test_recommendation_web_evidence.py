"""La sinopsis externa mantiene su fuente y pasa la auditoría real.

Fixtures controladas, sin red, inferencia ni acceso a bases de datos.
"""
import copy
from unittest.mock import Mock

from django.test import SimpleTestCase

from .literary_ai import (LiteraryAssistant, TOPIC_RECOMMENDATION_PROMPT,
                          canonical_sources, recommendation_evidence_sources, validate_draft,
                          validate_recommendation_text)
from .literary_identity import bind_source
from .literary_quality import required_fact_statements, validate_audit
from .test_literary_ai import FakeLLM, ROUTE


SUMMARY = ('En esta novela, John Perry y Jane Sagan aceptan dirigir una nueva '
           'colonia humana llamada Roanoke.')
BOOK = {
    'kind': 'book', 'title': 'The Last Colony', 'author': 'John Scalzi',
    'source': 'Open Library', 'book_id': '/works/OL5734646W',
    'url': 'https://openlibrary.org/works/OL5734646W',
    'description': 'Temas del catálogo: Space warfare, Science fiction, Space colonies.',
    'categories': ['Space warfare', 'Science fiction', 'Space colonies'],
    'read_mode': 'ficha bibliográfica; materias de catálogo, no texto de la obra',
    'research_summary': SUMMARY,
    'synopsis_source_url': 'https://en.wikipedia.org/wiki/The_Last_Colony',
}
WEB = bind_source({
    'kind': 'web', 'title': BOOK['title'], 'author': 'Fuente web',
    'source': 'Wikipedia', 'url': BOOK['synopsis_source_url'],
    'description': SUMMARY,
    'identity_text': 'The Last Colony is a science fiction novel by John Scalzi.',
    'read_mode': 'pasaje de sección de artículo público',
}, BOOK)
REQUEST = 'Recomiéndame un libro con temática espacial'
PLAN = {'questions': [REQUEST], 'search_queries': [], 'needs_contents': False,
        'needs_fresh_sources': False, 'spoilers_requested': False}


class SourceEvidenceLLM(FakeLLM):
    """Selecciona fuentes del contrato; el motor conserva todos sus validadores."""

    def __init__(self, *, needs_web=False, research_once=False):
        super().__init__(route={**ROUTE, 'queries': ['ciencia ficción espacial']})
        self.prompts = []
        self.needs_web = needs_web
        self.research_once = research_once

    def __call__(self, stage, prompt, data, model):
        if stage not in {'answer', 'answer_web', 'repair', 'audit'}:
            return super().__call__(stage, prompt, data, model)
        self.calls += 1
        self.records.append((stage, copy.deepcopy(data), model))
        self.prompts.append((stage, prompt))
        book = next(source for source in data['sources'] if source['kind'] == 'book')
        if stage == 'audit':
            statement = required_fact_statements(data['draft']['text'])[0]
            web = next((source for source in data['sources'] if source['kind'] == 'web'
                        and source['id'] in data['draft']['citations']), None)
            proof = SUMMARY if web else 'Space warfare, Science fiction, Space colonies'
            research = self.research_once
            self.research_once = False
            return {'decision': 'research' if research else 'approve', 'only_books': True,
                    'coverage': [{'question_id': 1, 'status': 'answered'}],
                    'claims': [{'statement': statement, 'verdict': 'supported',
                                'source_id': web['id'] if web else book['id'],
                                'evidence': proof}],
                    'search_queries': ['The Last Colony John Scalzi'] if research else [],
                    'issues': []}
        evidence = data.get('recommendation_evidence_sources', [])
        citations = [book['id']]
        if evidence:
            citations.append(evidence[0]['web_source_id'])
            detail = SUMMARY
        else:
            detail = ''
        return {'status': 'answer', 'basis': 'sources',
                'text': f'1. **{book["title"]} — {book["author"]}**: {detail}',
                'citations': citations, 'needs_web': self.needs_web and stage == 'answer',
                'books': [{'title': book['title'], 'author': book['author'],
                           'source_id': book['id']}]}


class RecommendationWebEvidenceTests(SimpleTestCase):
    def build(self, sources):
        llm = SourceEvidenceLLM()
        bot = LiteraryAssistant(llm, Mock(return_value=copy.deepcopy(sources)),
            quality_checks=True, fast_recommendations=True,
            require_book_sources=True, research_enabled=True)
        return bot, llm

    def answer_context(self, llm):
        return next(data for stage, data, _ in llm.records if stage == 'answer')

    def test_verified_external_synopsis_is_cited_as_separate_literal_source(self):
        bot, llm = self.build([BOOK, WEB])
        result = bot.reply(REQUEST)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        context = self.answer_context(llm)
        self.assertEqual(context['recommendation_evidence_sources'],
                         [{'book_source_id': 1, 'web_source_id': 2}])
        self.assertTrue(context['recommendation_contract']['canonical_source_title_author'])
        self.assertEqual([source['kind'] for source in result.sources], ['book', 'web'])
        self.assertEqual(result.sources[0]['description'], BOOK['description'])
        self.assertEqual(result.sources[1]['description'], SUMMARY)
        self.assertEqual(result.diagnostics['repairs'], 0)
        self.assertFalse(result.diagnostics.get('grounded_catalog_fallback'))
        self.assertIn('recommendation_evidence_sources', llm.prompts[0][1])
        audit_data = next(data for stage, data, _ in llm.records if stage == 'audit')
        audit = llm('audit', '', audit_data, '')
        validate_audit(audit, PLAN, audit_data['draft'], result.sources,
                       REQUEST, strict_facts=True)

    def test_unbound_source_does_not_receive_a_new_binding(self):
        bot, llm = self.build([BOOK, {**WEB, 'work_binding_verified': False}])
        bot.reply(REQUEST)
        self.assertEqual(self.answer_context(llm)['recommendation_evidence_sources'], [])

    def test_different_work_is_not_synopsis_evidence_even_with_same_author(self):
        other = {**WEB, 'title': 'Old Man\'s War', 'work_title': 'Old Man\'s War',
                 'work_id': 'another-work', 'identity_text': 'Old Man\'s War by John Scalzi.'}
        bot, llm = self.build([BOOK, other])
        bot.reply(REQUEST)
        self.assertEqual(self.answer_context(llm)['recommendation_evidence_sources'], [])

    def test_snippet_injected_or_unmatched_page_never_enters_map(self):
        for changed in ({'read_mode': 'fragmento del buscador'},
                        {'injection_detected': True},
                        {'url': 'https://en.wikipedia.org/wiki/Old_Man%27s_War'},
                        {'description': 'Breve pista.'}):
            with self.subTest(changed=changed):
                bot, llm = self.build([BOOK, {**WEB, **changed}])
                bot.reply(REQUEST)
                self.assertEqual(self.answer_context(llm)['recommendation_evidence_sources'], [])

    def test_metadata_only_source_does_not_require_web_citations(self):
        book = {key: value for key, value in BOOK.items()
                if key not in {'research_summary', 'synopsis_source_url'}}
        bot, llm = self.build([book])
        result = bot.reply(REQUEST)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertEqual(self.answer_context(llm)['recommendation_evidence_sources'], [])
        self.assertEqual([source['kind'] for source in result.sources], ['book'])

    def test_research_summary_copy_cannot_prove_narrative_in_catalogue_alone(self):
        sources = canonical_sources([BOOK])
        draft = {'status': 'answer', 'basis': 'sources', 'text': SUMMARY,
                 'citations': [1], 'needs_web': False, 'books': []}
        audit = {'decision': 'approve', 'only_books': True,
                 'coverage': [{'question_id': 1, 'status': 'answered'}],
                 'claims': [{'statement': SUMMARY, 'verdict': 'supported',
                             'source_id': 1, 'evidence': SUMMARY}],
                 'search_queries': [], 'issues': []}
        with self.assertRaisesRegex(ValueError, 'prueba literal'):
            validate_audit(audit, PLAN, draft, sources, REQUEST, strict_facts=True)

    def test_confirmed_alias_alone_does_not_replace_canonical_card_title(self):
        sources = canonical_sources([{**BOOK, 'confirmed_aliases': [{
            'title': 'La última colonia', 'source_url': BOOK['url'],
            'evidence': 'Edición bibliográfica confirmada de The Last Colony.'}]}])
        draft = {'status': 'answer', 'basis': 'sources',
                 'text': '1. **La última colonia — John Scalzi**: Una opción de ciencia ficción.',
                 'citations': [1], 'needs_web': False,
                 'books': [{'title': BOOK['title'], 'author': BOOK['author'], 'source_id': 1}]}
        validate_draft(draft, sources)
        with self.assertRaisesRegex(ValueError, 'título de cada obra'):
            validate_recommendation_text(draft, sources)
        draft['text'] = ('1. **The Last Colony — John Scalzi** (La última colonia): '
                         'Una opción de ciencia ficción.')
        validate_recommendation_text(draft, sources)
        self.assertIn('canónico EXACTO', TOPIC_RECOMMENDATION_PROMPT)

    def test_pure_map_uses_current_ids_after_renumbering_without_mutating_sources(self):
        before = canonical_sources([BOOK, WEB])
        saved = copy.deepcopy(before)
        self.assertEqual(recommendation_evidence_sources(before),
                         [{'book_source_id': 1, 'web_source_id': 2}])
        after = canonical_sources([WEB, BOOK])
        self.assertEqual(recommendation_evidence_sources(after),
                         [{'book_source_id': 2, 'web_source_id': 1}])
        self.assertEqual(before, saved)

    def test_pure_map_drops_removed_page_instead_of_reusing_old_id(self):
        sources = canonical_sources([BOOK, WEB])
        self.assertTrue(recommendation_evidence_sources(sources))
        self.assertEqual(recommendation_evidence_sources(canonical_sources([BOOK])), [])
        self.assertEqual(recommendation_evidence_sources(canonical_sources([WEB])), [])

    def test_needs_web_rebuilds_mapping_before_answer_web_with_new_ids(self):
        self.assert_mapping_refreshed(needs_web=True)

    def test_audit_research_rebuilds_mapping_before_answer_web_with_new_ids(self):
        self.assert_mapping_refreshed(research_once=True)

    def assert_mapping_refreshed(self, **options):
        llm = SourceEvidenceLLM(**options)
        bot = LiteraryAssistant(llm, Mock(return_value=copy.deepcopy([BOOK, WEB])),
            web_search=Mock(), quality_checks=True, fast_recommendations=True,
            require_book_sources=True, research_enabled=True)
        bot._enrich_web = Mock(return_value=canonical_sources([WEB, BOOK]))
        result = bot.reply(REQUEST)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        bot._enrich_web.assert_called_once()
        initial = self.answer_context(llm)
        updated = next(data for stage, data, _ in llm.records if stage == 'answer_web')
        self.assertEqual(initial['recommendation_evidence_sources'],
                         [{'book_source_id': 1, 'web_source_id': 2}])
        self.assertEqual(updated['recommendation_evidence_sources'],
                         [{'book_source_id': 2, 'web_source_id': 1}])
        self.assertEqual(next(source['title'] for source in updated['sources']
                              if source['id'] == 2), BOOK['title'])
        self.assertEqual(next(source['kind'] for source in updated['sources']
                              if source['id'] == 1), 'web')
