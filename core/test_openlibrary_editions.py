"""Ediciones oficiales: procedencia, separación de campos y presupuesto común.

Las respuestas HTTP son controladas; no constituyen una prueba de cobertura real.
"""
from copy import deepcopy
from unittest.mock import patch
from urllib.error import HTTPError

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from .books_google import source_synopsis
from .literary_search import (_openlibrary_edition_metadata, _openlibrary_detail,
                              _cache_key, search_openlibrary)
from .literary_sources import research_scope, research_snapshot, reserve_page


BOOK = {'title': 'Japanese Art', 'author': 'Ana Robles', 'kind': 'book',
        'book_id': '/works/OL1W', 'source': 'Open Library',
        'url': 'https://openlibrary.org/works/OL1W',
        'description': 'Temas del catálogo: Art, Japan',
        'read_mode': 'ficha bibliográfica; materias de catálogo, no texto de la obra'}
EDITION = {'key': '/books/OL10M', 'title': 'Japanese Art',
           'works': [{'key': '/works/OL1W'}], 'languages': [{'key': '/languages/eng'}]}


class OpenLibraryEditionBindingTests(SimpleTestCase):
    def test_subtitle_is_metadata_and_never_becomes_a_synopsis(self):
        book = deepcopy(BOOK)
        self.assertTrue(_openlibrary_edition_metadata(book, {**EDITION, 'subtitle': 'Painting and sculpture'}))
        self.assertEqual(book['subtitle'], 'Painting and sculpture')
        self.assertEqual(source_synopsis(book), '')
        self.assertNotIn('synopsis', book)
        self.assertNotIn('synopsis_source_url', book)
        self.assertNotIn('description_source', book)
        self.assertEqual(book['title'], BOOK['title'])
        self.assertEqual(book['author'], BOOK['author'])
        self.assertEqual(book['url'], BOOK['url'])

    def test_description_keeps_its_actual_edition_source(self):
        book = deepcopy(BOOK)
        self.assertTrue(_openlibrary_edition_metadata(book, {**EDITION,
            'description': {'value': 'An overview of painting and sculpture.'}}))
        self.assertEqual(book['synopsis'], 'An overview of painting and sculpture.')
        self.assertEqual(book['synopsis_source_url'], 'https://openlibrary.org/books/OL10M')
        self.assertIn('OL10M', book['description_source'])
        self.assertEqual(book['book_id'], '/works/OL1W')

    def test_missing_explicit_work_binding_is_allowed_only_for_nested_search_editions(self):
        edition = {key: value for key, value in EDITION.items() if key != 'works'}
        edition['subtitle'] = 'Painting'
        self.assertFalse(_openlibrary_edition_metadata(deepcopy(BOOK), edition))
        self.assertTrue(_openlibrary_edition_metadata(deepcopy(BOOK), edition, nested_in_work=True))

    def test_explicit_wrong_or_multiple_work_bindings_cannot_be_overridden_by_nesting(self):
        for works in ([{'key': '/works/OL2W'}], [], None,
                      [{'key': '/works/OL1W'}, {'key': '/works/OL2W'}], 'invalid'):
            with self.subTest(works=works):
                book = deepcopy(BOOK)
                edition = {**EDITION, 'works': works, 'subtitle': 'Painting'}
                self.assertFalse(_openlibrary_edition_metadata(book, edition, nested_in_work=True))
                self.assertEqual(book, BOOK)

    def test_a_sequel_is_not_the_same_work_even_with_an_inconsistent_api_link(self):
        book = deepcopy(BOOK)
        self.assertFalse(_openlibrary_edition_metadata(book, {**EDITION,
            'title': 'Japanese Art: The Next Volume', 'subtitle': 'Painting'}))
        self.assertEqual(book, BOOK)

    def test_private_urls_and_invalid_identifiers_are_not_accepted_as_edition_ids(self):
        for identifier in ('http://127.0.0.1/private', '/books/OL10M/../../private',
                           '/works/OL10W', '//attacker.example/books/OL10M'):
            with self.subTest(identifier=identifier):
                self.assertFalse(_openlibrary_edition_metadata(deepcopy(BOOK),
                    {**EDITION, 'key': identifier, 'subtitle': 'Painting'}))

    def test_requested_language_must_be_confirmed_on_the_edition_itself(self):
        self.assertFalse(_openlibrary_edition_metadata(deepcopy(BOOK),
            {**EDITION, 'subtitle': 'Painting'}, requested_language='spa'))
        self.assertTrue(_openlibrary_edition_metadata(deepcopy(BOOK),
            {**EDITION, 'language': ['spa'], 'subtitle': 'Painting'}, requested_language='spa'))
        self.assertTrue(_openlibrary_edition_metadata(deepcopy(BOOK),
            {**EDITION, 'languages': [{'key': '/languages/spa'}], 'subtitle': 'Painting'},
            requested_language='spa'))

    def test_only_checksummed_isbns_of_the_linked_edition_are_accepted(self):
        book = deepcopy(BOOK)
        _openlibrary_edition_metadata(book, {**EDITION, 'subtitle': 'Painting',
            'isbn_13': ['978-0-14-044913-6', '9780000000000'], 'isbn_10': ['0140449132']})
        self.assertEqual(book['isbns'], ['0140449132', '9780140449136'])

    def test_an_existing_synopsis_keeps_its_text_url_and_read_provenance(self):
        book = {**BOOK, 'synopsis': 'Work description.', 'synopsis_source_url': BOOK['url'],
                'description_source': 'Open Library, registro de obra', 'read_mode': 'ficha y descripción bibliográfica'}
        _openlibrary_edition_metadata(book, {**EDITION, 'subtitle': 'Painting',
                                             'description': 'A different edition description.'})
        self.assertEqual(book['synopsis'], 'Work description.')
        self.assertEqual(book['synopsis_source_url'], BOOK['url'])
        self.assertEqual(book['description_source'], 'Open Library, registro de obra')
        self.assertEqual(book['read_mode'], 'ficha y descripción bibliográfica')

    def test_placeholder_description_is_not_promoted(self):
        for description in ('Publisher description.', {'value': 'No description available'}, '', None, []):
            with self.subTest(description=description):
                book = deepcopy(BOOK)
                self.assertFalse(_openlibrary_edition_metadata(book, {**EDITION, 'description': description}))
                self.assertEqual(book, BOOK)


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                     'LOCATION': 'official-edition-tests'}})
class OpenLibraryEditionRetrievalTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def docs(self, *, edition=None, count=1):
        docs = [{'key': '/works/OL' + str(index + 1) + 'W', 'title': 'Japanese Art',
                 'author_name': ['Ana Robles' + str(index)], 'subject': ['Art', 'Japan']}
                for index in range(count)]
        if edition:
            docs[0]['editions'] = {'docs': [edition]}
        return {'docs': docs}

    def test_nested_description_stops_without_unnecessary_detail_requests(self):
        edition = {**EDITION, 'description': 'A description of Japanese painting.'}
        with patch('core.literary_search._openlibrary_fetch', return_value=self.docs(edition=edition)) as fetch:
            result = search_openlibrary('libros sobre arte japonés')
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result[0]['synopsis_source_url'], 'https://openlibrary.org/books/OL10M')

    def test_work_description_has_work_provenance_while_preserving_an_edition_subtitle(self):
        docs = self.docs(edition={**EDITION, 'subtitle': 'Painting and sculpture'})
        with patch('core.literary_search._openlibrary_fetch', side_effect=[docs,
                {'key': '/works/OL1W', 'description': 'A work-level description.'}]) as fetch:
            result = search_openlibrary('libros sobre arte japonés')
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result[0]['synopsis_source_url'], BOOK['url'])
        self.assertEqual(result[0]['description_source'], 'Open Library, registro de obra')
        self.assertEqual(result[0]['subtitle'], 'Painting and sculpture')

    def test_missing_work_description_tries_a_linked_edition_within_two_total_details(self):
        with patch('core.literary_search._openlibrary_fetch', side_effect=[self.docs(count=5),
                {'key': '/works/OL1W'}, {'entries': [{**EDITION,
                    'description': 'A description from a linked edition.'}]}]) as fetch, research_scope():
            result = search_openlibrary('libros sobre arte japonés')
            snapshot = research_snapshot()
        self.assertEqual(fetch.call_count, 3)  # Search + work + editions, never five detail requests.
        self.assertTrue(fetch.call_args.args[0].endswith('/works/OL1W/editions.json?limit=5'))
        self.assertEqual(result[0]['synopsis_source_url'], 'https://openlibrary.org/books/OL10M')
        self.assertEqual(snapshot['page_slots_reserved'], 2)
        self.assertEqual(sum(bool(item.get('synopsis')) for item in result), 1)

    def test_an_existing_subtitle_does_not_hide_a_missing_description(self):
        docs = self.docs(edition={**EDITION, 'subtitle': 'Painting and sculpture'})
        with patch('core.literary_search._openlibrary_fetch', side_effect=[docs,
                {'key': '/works/OL1W', 'description': 'Publisher description.'},
                {'entries': [{**EDITION, 'description': 'A documented description.'}]}]) as fetch:
            result = search_openlibrary('libros sobre arte japonés')
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(result[0]['synopsis'], 'A documented description.')
        self.assertEqual(result[0]['subtitle'], 'Painting and sculpture')

    def test_wrong_work_editions_never_add_a_synopsis_or_rewrite_the_identity(self):
        with patch('core.literary_search._openlibrary_fetch', side_effect=[self.docs(),
                {'key': '/works/OL1W'}, {'entries': [{**EDITION,
                    'works': [{'key': '/works/OL2W'}], 'description': 'Another book.'}]}]):
            result = search_openlibrary('libros sobre arte japonés')
        self.assertNotIn('synopsis', result[0])
        self.assertEqual(result[0]['url'], BOOK['url'])
        self.assertEqual(result[0]['book_id'], '/works/OL1W')

    def test_shared_page_budget_prevents_even_the_first_detail_read(self):
        with research_scope():
            for _ in range(3):
                self.assertTrue(reserve_page())
            with patch('core.literary_search._openlibrary_fetch', return_value=self.docs()) as fetch:
                result = search_openlibrary('libros sobre arte japonés')
        self.assertEqual(len(result), 1)
        self.assertEqual(fetch.call_count, 1)
        self.assertNotIn('synopsis', result[0])

    def test_detail_rate_limit_retains_metadata_and_stops_further_http(self):
        error = HTTPError(BOOK['url'] + '.json', 429, 'rate limit', {'Retry-After': '30'}, None)
        with patch('core.literary_search._openlibrary_fetch', side_effect=[self.docs(count=3), error]) as fetch:
            result = search_openlibrary('libros sobre arte japonés')
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(len(result), 3)
        self.assertFalse(any(item.get('synopsis') for item in result))
        self.assertEqual(cache.get('litmate_ol_cooldown'), 'rate_limited')

    def test_invalid_cached_work_data_is_not_trusted_as_the_requested_work(self):
        cache.set(_cache_key('litmate_ol_work_v1:', '/works/OL1W'),
                  {'key': '/works/OL2W', 'description': 'A different book.'}, 60)
        with patch('core.literary_search._openlibrary_fetch', return_value={
                'key': '/works/OL1W', 'description': 'Correct description.'}) as fetch:
            detail = _openlibrary_detail('/works/OL1W', editions=False, reads={'used': 0})
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(detail['description'], 'Correct description.')

    def test_valid_cached_detail_does_not_spend_an_http_or_page_slot(self):
        cache.set(_cache_key('litmate_ol_work_v1:', '/works/OL1W'),
                  {'key': '/works/OL1W', 'description': 'Correct description.'}, 60)
        reads = {'used': 0}
        with research_scope(), patch('core.literary_search._openlibrary_fetch') as fetch:
            self.assertIsNotNone(_openlibrary_detail('/works/OL1W', editions=False, reads=reads))
            snapshot = research_snapshot()
        fetch.assert_not_called()
        self.assertEqual(reads['used'], 0)
        self.assertEqual(snapshot['page_slots_reserved'], 0)

    def test_detail_service_failures_never_fabricate_a_description(self):
        with patch('core.literary_search._openlibrary_fetch', side_effect=[self.docs(), TimeoutError()]):
            result = search_openlibrary('libros sobre arte japonés')
        self.assertEqual(len(result), 1)
        self.assertEqual(source_synopsis(result[0]), '')

