from django.test import SimpleTestCase
from .literary_constraints import (requested_language, language_matches, explicit_author,
                                   publication_range, recommendation_constraints, constraints_match)
from .literary_ai import LiteraryAssistant
from .test_literary_ai import FakeLLM, ROUTE
from .test_recommendation_grounding import IDEALS


class ExplicitRecommendationLanguageTests(SimpleTestCase):
    def test_explicit_author_is_a_full_name_not_a_topic_or_a_quoted_title(self):
        for message, expected in [('Novelas de Isabel Allende', 'Isabel Allende'),
                                  ('libros escritos por marcela paz sobre la infancia', 'marcela paz'),
                                  ('libros sobre historia de Corea', ''),
                                  ('Un libro llamado «Novelas de Isabel Allende»', '')]:
            self.assertEqual(explicit_author(message), expected)

    def test_publication_period_is_distinct_from_the_historical_subject(self):
        self.assertEqual(publication_range('Novelas publicadas entre 1940 y 1960'), (1940, 1960))
        self.assertEqual(publication_range('libros escritos antes de 1950'), (1, 1949))
        self.assertEqual(publication_range('Novelas del siglo XIX'), (1801, 1900))
        self.assertIsNone(publication_range('Libros sobre la historia de Corea en el siglo XIX'))
        self.assertEqual(publication_range('obras publicadas en 1955'), (1955, 1955))

    def test_author_and_original_publication_constraints_need_record_evidence(self):
        constraints = recommendation_constraints('Novelas de Isabel Allende publicadas entre 1980 y 1990')
        source = {'kind': 'book', 'source': 'Open Library', 'author': 'Isabel Allende', 'year': '1982'}
        self.assertTrue(constraints_match(source, constraints))
        for changes in ({'author': 'Otro Autor'}, {'year': '2020'}, {'year': ''},
                        {'source': 'Google Books API'}):
            self.assertFalse(constraints_match({**source, **changes}, constraints))

    def test_language_is_explicit_not_a_title_or_nationality(self):
        for message, expected in [('Tres libros de arte japonés en español', 'es'),
                                  ('Libros de autores ingleses', ''),
                                  ('Un libro titulado «En inglés»', ''),
                                  ('Recomiéndame una novela en francés', 'fr')]:
            self.assertEqual(requested_language(message), expected)

    def test_unknown_language_metadata_cannot_satisfy_a_language_request(self):
        for value in ('', None, 'en', 'japonés'):
            self.assertFalse(language_matches({'kind': 'book', 'language': value}, 'es'))
        for value in ('es', 'spa', 'Español', 'castellano'):
            self.assertTrue(language_matches({'kind': 'book', 'language': value}, 'es'))

    def test_supporting_pages_need_not_be_in_the_edition_language(self):
        self.assertTrue(language_matches({'kind': 'web', 'language': 'en'}, 'es'))

    def test_an_actual_catalogue_result_in_another_language_is_not_recommended(self):
        llm = FakeLLM(route={**ROUTE, 'queries': ['arte japonés en español']})
        result = LiteraryAssistant(llm, lambda query: [{**IDEALS, 'language': 'en'}],
            require_book_sources=True).reply('Recomiéndame un libro de arte japonés en español')
        self.assertEqual(result.status, 'clarification', result.diagnostics)
        self.assertEqual(result.books, [])
        self.assertNotIn('answer', [record[0] for record in llm.records])
