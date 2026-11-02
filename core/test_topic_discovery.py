"""Descubrimiento temático: no cerrar la búsqueda con una sola ficha."""
import threading
import time
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from .literary_search import retrieve_discovery_books


def _book(title, author, source):
    return {'kind': 'book', 'title': title, 'author': author,
            'categories': ['French Revolution', 'France', 'History'],
            'description': 'Una historia documentada de la Revolución francesa.',
            'url': 'https://openlibrary.org/works/' + title.replace(' ', '') + 'W',
            'source': source}


QUERY = 'libros sobre la revolucion francesa'


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                       'LOCATION': 'topic-discovery'}},
                   LITMATE_AI_USE_OPENLIBRARY=True,
                   LITMATE_USE_GOOGLE_BOOKS_API=False)
class TopicDiscoveryTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_one_local_option_does_not_hide_the_other_sources(self):
        local = [_book('Uno', 'Autora local', 'Catálogo LitMate')]
        external = [_book('Dos', 'Autor externo', 'Open Library'),
                    _book('Tres', 'Otra autora', 'Open Library')]
        with patch('core.literary_knowledge.search_knowledge', return_value=[]), \
                patch('core.literary_search.search_catalog', return_value=local), \
                patch('core.literary_search.search_openlibrary', return_value=external):
            found = retrieve_discovery_books(
                QUERY, accept=lambda sources: len(sources) >= 3)
        self.assertGreaterEqual(len(found), 3)
        self.assertIn('Open Library', found.providers)
        self.assertIn('Catálogo LitMate', found.providers)

    def test_three_verified_local_options_can_return_without_waiting_for_a_slow_api(self):
        local = [_book('Uno', 'Autora local', 'Catálogo LitMate'),
                 _book('Dos', 'Autor local', 'Catálogo LitMate'),
                 _book('Tres', 'Otra autora', 'Catálogo LitMate')]
        release = threading.Event()

        def slow_external():
            release.wait(5)
            return []

        try:
            with patch('core.literary_knowledge.search_knowledge', return_value=[]), \
                    patch('core.literary_search.search_catalog', return_value=local), \
                    patch('core.literary_search.search_openlibrary', side_effect=slow_external):
                start = time.monotonic()
                found = retrieve_discovery_books(
                    QUERY, accept=lambda sources: len(sources) >= 3)
                elapsed = time.monotonic() - start
        finally:
            release.set()
        self.assertGreaterEqual(len(found), 3)
        self.assertLess(elapsed, 1.5)
        self.assertIn('Catálogo LitMate', found.providers)
