"""Diccionario local de materias: cobertura, integridad y frases más largas."""
import json
from pathlib import Path
from unittest.mock import Mock

from django.test import SimpleTestCase

from . import topic_reference
from .ai_catalog_fallback import _topic_article, _topic_label
from .ai_quick_answers import quick_answer
from .books_google import book_topic_profile


class TopicReferenceDataTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.data = json.loads((Path(__file__).parent / 'data' / 'topic_reference.json')
                              .read_text(encoding='utf-8'))

    def test_reference_base_is_large_enough_to_be_useful_locally(self):
        self.assertGreaterEqual(len(self.data['facets']), 200)
        self.assertGreaterEqual(len(self.data['topics']), 250)
        self.assertGreaterEqual(sum(len(topic['aliases']) for topic in self.data['topics']), 900)

    def test_every_topic_points_to_real_facets_and_has_aliases(self):
        facets = self.data['facets']
        identifiers = [topic['id'] for topic in self.data['topics']]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        for topic in self.data['topics']:
            with self.subTest(topic=topic['id']):
                self.assertTrue(topic['aliases'])
                self.assertEqual(len(topic['aliases']), len(set(topic['aliases'])))
                self.assertTrue(topic['subjects'] or topic['places'])
                for key in (*topic['subjects'], *topic['places']):
                    self.assertIn(key, facets)
                    self.assertTrue(facets[key]['terms'])

    def test_longest_phrase_suppresses_generic_war_and_peace(self):
        subjects = topic_reference.resolve('libros sobre la segunda guerra mundial')['subjects']
        self.assertEqual([row[0] for row in subjects], ['world war ii'])
        subjects = topic_reference.resolve('libros sobre la guerra fria')['subjects']
        self.assertEqual([row[0] for row in subjects], ['cold war'])
        subjects = topic_reference.resolve('libros sobre la guerra')['subjects']
        self.assertEqual([row[0] for row in subjects], ['war'])

    def test_accents_punctuation_and_case_are_irrelevant(self):
        subjects = topic_reference.resolve('REVOLUCIÓN, FRANCESA')['subjects']
        self.assertEqual([row[0] for row in subjects], ['french revolution'])
        self.assertIn('revolucion francesa', subjects[0][2])

    def test_country_qualifiers_do_not_fall_back_to_the_generic_country(self):
        profile = book_topic_profile('historia de corea del sur')
        self.assertEqual(profile['query'], 'subject:"history" subject:"korea (south)"')
        profile = book_topic_profile('historia de corea del norte')
        self.assertEqual(profile['query'], 'subject:"history" subject:"korea (north)"')
        profile = book_topic_profile('historia de corea')
        self.assertEqual(profile['query'], 'subject:"history" subject:"korea"')

    def test_new_topics_become_verifiable_catalog_subjects(self):
        profile = book_topic_profile('libros sobre la revolucion francesa')
        self.assertTrue(profile['structured'])
        self.assertIn('subject:"french revolution"', profile['query'])
        profile = book_topic_profile('libros sobre la revolucion industrial')
        self.assertEqual(profile['query'], 'subject:"industrial revolution"')
        profile = book_topic_profile('libros sobre la guerra fria')
        self.assertEqual(profile['query'], 'subject:"cold war"')

    def test_new_topic_can_use_verified_discovery_without_the_model(self):
        def book(index):
            return {'kind': 'book', 'title': f'Historia de la Revolución {index}',
                    'author': f'Autor {index}',
                    'url': f'https://openlibrary.org/works/OL{index}W',
                    'source': 'Open Library',
                    'categories': ['French Revolution', 'France', 'History'],
                    'description': 'Una historia documentada de la Revolución francesa y su impacto político.'}
        search = Mock(return_value=[book(1), book(2), book(3)])
        result = quick_answer('libros sobre la revolucion francesa', search=search)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'answered')
        self.assertEqual(len(result.books), 3)
        search.assert_called_once_with('libros sobre la revolucion francesa')

    def test_guerra_y_paz_remains_a_title_not_a_war_and_peace_subject(self):
        profile = book_topic_profile('libros sobre Guerra y Paz')
        self.assertFalse(profile['structured'])
        self.assertEqual(profile['query'], 'guerra y paz')

    def test_dictionary_labels_and_articles_are_ready_for_spanish_text(self):
        self.assertEqual(_topic_label('cold war'), 'Guerra Fría')
        self.assertEqual(_topic_label('french revolution'), 'Revolución Francesa')
        self.assertEqual(_topic_article('cold war'), 'la ')
        self.assertEqual(_topic_article('theater'), 'el ')
        self.assertEqual(_topic_article('history'), 'la ')

    def test_known_facets_and_aliases_are_exposed_without_mutable_data(self):
        self.assertIn('cold war', topic_reference.known_facets())
        self.assertIn('french_revolution', topic_reference.known_topics())
        self.assertGreater(topic_reference.alias_count(), 900)
        self.assertEqual(topic_reference.catalog_subject('world war ii'), 'world war, 1939-1945')
