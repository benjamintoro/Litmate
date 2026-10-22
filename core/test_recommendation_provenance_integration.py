"""Referencias omitidas se reparan antes de una auditoría que no puede aprobarlas."""
import copy
from unittest.mock import Mock

from django.test import SimpleTestCase

from .ai_catalog_fallback import grounded_topic_fallback
from .literary_ai import LiteraryAssistant
from .test_recommendation_web_evidence import BOOK, WEB, REQUEST, SUMMARY, SourceEvidenceLLM


class CitationRepairLLM(SourceEvidenceLLM):
    def __init__(self, *, ignore_repair=False):
        super().__init__()
        self.ignore_repair = ignore_repair

    def __call__(self, stage, prompt, data, model):
        result = super().__call__(stage, prompt, data, model)
        if stage == 'answer' or stage == 'repair' and self.ignore_repair:
            result['citations'] = [book['source_id'] for book in result['books']]
        return result


class RecommendationProvenanceIntegrationTests(SimpleTestCase):
    def build(self, **options):
        llm = CitationRepairLLM(**options)
        bot = LiteraryAssistant(llm, Mock(return_value=copy.deepcopy([BOOK, WEB])),
            quality_checks=True, fast_recommendations=True,
            require_book_sources=True, research_enabled=True)
        return bot, llm

    def test_missing_narrative_citation_gets_specific_repair_before_audit(self):
        bot, llm = self.build()
        result = bot.reply(REQUEST)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        stages = [stage for stage, _, _ in llm.records]
        self.assertEqual(stages.count('audit'), 1)
        self.assertLess(stages.index('repair'), stages.index('audit'))
        repair = next(data for stage, data, _ in llm.records if stage == 'repair')
        correction = ' '.join(repair['corrections'])
        self.assertIn('The Last Colony', correction)
        self.assertIn('fuente web 2', correction)
        self.assertIn('ficha 1', correction)
        self.assertIn(SUMMARY, result.text)
        self.assertTrue(any(source['id'] == 2 and source['kind'] == 'web' for source in result.sources))
        self.assertFalse(result.diagnostics.get('grounded_catalog_fallback'))

    def test_repeated_omission_never_publishes_the_narrative_or_adds_its_reference(self):
        bot, llm = self.build(ignore_repair=True)
        result = bot.reply(REQUEST)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertTrue(result.diagnostics.get('grounded_catalog_fallback'))
        self.assertNotIn(SUMMARY, result.text)
        self.assertNotIn(WEB['url'], result.text)
        self.assertNotIn('audit', [stage for stage, _, _ in llm.records])
        self.assertEqual([source['kind'] for source in result.sources], ['book'])


class ArtistAndAuthorConstraintTests(SimpleTestCase):
    def sources(self):
        return [{'kind': 'book', 'title': title, 'author': 'Autora historiadora',
                 'source': 'Open Library', 'url': 'https://openlibrary.org/works/OL' + str(index) + 'W',
                 'description': 'Temas del catálogo: Japanese art, Art, Japan.',
                 'categories': ['Art', 'Japan'],
                 'read_mode': 'ficha bibliográfica; materias de catálogo, no texto de la obra'}
                for index, title in enumerate(('Estudio de Hokusai', 'Estudio de Hiroshige'), 10001)]

    def test_distinct_artists_do_not_require_different_book_authors(self):
        result = grounded_topic_fallback('Recomiéndame dos libros de arte japonés de distintos artistas',
                                         self.sources())
        self.assertIsNotNone(result)
        self.assertEqual(len(result.books), 2)
        self.assertEqual(len({book['author'] for book in result.books}), 1)
        self.assertNotIn('artistas distintos', result.text.casefold())

    def test_explicit_distinct_authors_still_require_different_authors(self):
        self.assertIsNone(grounded_topic_fallback(
            'Recomiéndame dos libros de arte japonés de distintos autores', self.sources()))
