"""Fuentes progresivas: procedencia real y fallos controlados, sin red ni DB."""
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from .literary_identity import same_work
from .literary_search import (enrich_book_sources, search_wikipedia, search_searx,
                              retrieve_web, _openlibrary_fetch, _search_wikipedia,
                              discovery_url, trusted_url, _retrieve_web, search_openlibrary)
from .literary_sources import research_scope, research_snapshot, record_research_event


BOOK = {'title': 'Cuaderno de la luna', 'author': 'Ana Robles', 'kind': 'book',
        'source': 'Open Library', 'url': 'https://openlibrary.org/works/OL1W',
        'description': 'Temas del catálogo: Fiction, Space travel'}
PAGE = {'title': 'Cuaderno de la luna (novela)', 'author': 'Fuente web', 'kind': 'web',
        'source': 'Wikipedia', 'url': 'https://es.wikipedia.org/wiki/Cuaderno_de_la_luna',
        'description': 'Cuaderno de la luna, de Ana Robles, narra el viaje de una astrónoma a una estación abandonada.',
        'read_mode': 'extracto de introducción'}


class SupplementarySourceProvenanceTests(SimpleTestCase):
    def enrich(self, page):
        with patch('core.literary_search.retrieve_web', return_value=[page]):
            return enrich_book_sources([BOOK])

    def test_actual_public_extract_retains_its_verified_book_identity(self):
        book, evidence = self.enrich(PAGE)
        self.assertIn('estación abandonada', book['research_summary'])
        self.assertNotIn('synopsis', book)
        self.assertTrue(evidence['work_binding_verified'])
        self.assertTrue(same_work(evidence, book))
        self.assertEqual(book['synopsis_source_url'], evidence['url'])

    def test_snippet_is_discovery_data_and_cannot_become_a_read_synopsis(self):
        result = self.enrich({**PAGE, 'read_mode': 'fragmento del buscador'})
        self.assertEqual(result, [BOOK])

    def test_missing_read_provenance_is_not_promoted(self):
        result = self.enrich({key: value for key, value in PAGE.items() if key != 'read_mode'})
        self.assertEqual(result, [BOOK])

    def test_catalogue_topics_are_not_a_plot(self):
        result = self.enrich({**PAGE, 'description': 'Temas del catálogo: Cuaderno de la luna, Ana Robles, Astronomy, Fiction, Science, Space'})
        self.assertEqual(result, [BOOK])

    def test_injection_flag_prevents_promotion_even_on_an_authorized_domain(self):
        result = self.enrich({**PAGE, 'injection_detected': True})
        self.assertEqual(result, [BOOK])

    def test_a_shared_surname_does_not_prove_authorship(self):
        result = self.enrich({**PAGE, 'description': PAGE['description'].replace('Ana Robles', 'Carlos Robles')})
        self.assertEqual(result, [BOOK])

    def test_a_page_about_another_book_cannot_be_bound_by_a_secondary_mention(self):
        result = self.enrich({**PAGE, 'title': 'La segunda luna (novela)'})
        self.assertEqual(result, [BOOK])

    def test_saga_prefix_does_not_identify_a_different_volume(self):
        result = self.enrich({**PAGE, 'title': 'Cuaderno de la luna y la estación perdida'})
        self.assertEqual(result, [BOOK])

    def test_publisher_decoration_does_not_change_verified_identity(self):
        result = self.enrich({**PAGE, 'title': 'Cuaderno de la luna | Editorial oficial',
                              'url': 'https://www.penguinlibros.com/es/cuaderno'})
        self.assertEqual(len(result), 2)
        self.assertTrue(result[1]['work_binding_verified'])
        self.assertIn('Editorial oficial', result[1]['title'])


class ProgressiveWikipediaTests(SimpleTestCase):
    def response(self, language='en'):
        return {'query': {'pages': {'123': {'pageid': 123, 'title': 'A documented book',
            'extract': 'A documented book is a book by Ana Robles about an observatory and its researchers.',
            'fullurl': 'https://' + language + '.wikipedia.org/wiki/A_documented_book'}}}}

    def test_empty_spanish_search_tries_the_official_english_api(self):
        with patch('core.literary_search.read_json_url', side_effect=[{'query': {}}, self.response()]) as fetch:
            result = search_wikipedia('A documented book Ana Robles')
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result[0]['url'], 'https://en.wikipedia.org/wiki/A_documented_book')
        self.assertTrue(fetch.call_args_list[0].args[0].startswith('https://es.wikipedia.org/w/api.php?'))
        self.assertTrue(fetch.call_args_list[1].args[0].startswith('https://en.wikipedia.org/w/api.php?'))

    def test_adequate_spanish_extract_stops_without_an_unnecessary_language_request(self):
        with patch('core.literary_search.read_json_url', return_value=self.response('es')) as fetch:
            result = search_wikipedia('A documented book Ana Robles')
        self.assertEqual(result.status, 'ok')
        self.assertEqual(fetch.call_count, 1)

    def test_tangential_spanish_article_does_not_prevent_searching_for_the_actual_title(self):
        tangential = self.response('es')
        tangential['query']['pages']['123']['title'] = 'Ceremonia tradicional'
        with patch('core.literary_search.read_json_url', side_effect=[tangential, self.response()]) as fetch:
            result = search_wikipedia('A documented book Ana Robles')
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result[0]['title'], 'A documented book')
        self.assertTrue(result[0]['url'].startswith('https://en.wikipedia.org/'))

    def test_rate_limits_are_not_reported_as_no_books(self):
        error = HTTPError('https://es.wikipedia.org/w/api.php', 429, 'Rate limit', {}, None)
        with patch('core.literary_search.read_json_url', side_effect=error) as fetch:
            result = search_wikipedia('A documented book Ana Robles')
        self.assertEqual(result.status, 'unavailable')
        self.assertEqual(set(result.providers.values()), {'rate_limited'})
        self.assertLessEqual(fetch.call_count, 2)

    def test_failure_then_english_result_preserves_partial_status(self):
        with patch('core.literary_search.read_json_url', side_effect=[TimeoutError(), self.response()]):
            result = search_wikipedia('A documented book Ana Robles')
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.providers['Wikipedia (es)'], 'timeout')

    def test_api_error_object_is_not_a_valid_empty_search(self):
        with patch('core.literary_search.read_json_url', return_value={'error': {'code': 'ratelimited'}}):
            result = search_wikipedia('A documented book Ana Robles')
        self.assertEqual(result.status, 'unavailable')
        self.assertEqual(set(result.providers.values()), {'invalid_response'})

    def test_language_cannot_change_the_request_destination(self):
        with patch('core.literary_search.read_json_url') as fetch, self.assertRaises(ValueError):
            _search_wikipedia('A documented book', language='localhost:80')
        fetch.assert_not_called()


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                     'LOCATION': 'progressive-events'}},
                   LITMATE_AI_USE_SEARXNG=True, LITMATE_SEARXNG_URL='http://127.0.0.1:8080')
class ResearchOperationTraceTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_invalid_searx_schema_is_a_service_error(self):
        for response in ({'results': {}}, {'results': [], 'unresponsive_engines': 'invalid'}):
            with self.subTest(response=response), patch('core.literary_search.read_json_url', return_value=response):
                self.assertEqual(search_searx('A documented book').status, 'invalid_response')

    def test_http_failure_and_page_reservation_are_distinct_from_successful_extraction(self):
        from .literary_sources import reserve_page
        with research_scope(2, 15, 3):
            reserve_page()
            with patch('core.literary_search.read_json_url', side_effect=TimeoutError()):
                result = search_searx('A documented book')
            snapshot = research_snapshot()
        self.assertEqual(result.status, 'timeout')
        self.assertEqual(snapshot['http_requests_started'], 1)
        self.assertEqual(snapshot['page_slots_reserved'], 1)
        self.assertEqual(snapshot['pages_extracted'], 0)
        self.assertEqual(snapshot['events'][-1]['status'], 'timeout')

    def test_trace_has_only_closed_identifiers_and_no_reader_data(self):
        with research_scope():
            record_research_event('http_request', 'Wikipedia', 'started')
            record_research_event('http_request', 'https://private.example/secret', 'started')
            record_research_event('http_request', 'Wikipedia', 'user@example.org password=secret')
            snapshot = research_snapshot()
        self.assertEqual(len(snapshot['events']), 2)
        self.assertEqual(snapshot['events'][1]['status'], 'unavailable')
        self.assertNotIn('secret', str(snapshot))
        self.assertNotIn('user@', str(snapshot))
        self.assertEqual(research_snapshot(), {})

    def test_cached_web_result_is_not_counted_as_a_new_http_request(self):
        from .literary_search import _web_cache_key
        cache.set(_web_cache_key('A documented book'), [PAGE], 60)
        with research_scope(), patch('core.literary_search._retrieve_web') as retrieve:
            result = retrieve_web('A documented book')
            snapshot = research_snapshot()
        retrieve.assert_not_called()
        self.assertEqual(result, [PAGE])
        self.assertEqual(snapshot['http_requests_started'], 0)
        self.assertEqual(snapshot['events'][0]['stage'], 'cache_hit')

    def test_open_library_http_counter_records_only_an_actual_reserved_call(self):
        with research_scope(), patch('core.literary_search.cache.add', return_value=True), \
                patch('core.literary_search.read_json_url', return_value={'key': '/works/OL1W'}):
            _openlibrary_fetch('https://openlibrary.org/works/OL1W.json', timeout=4)
            snapshot = research_snapshot()
        self.assertEqual(snapshot['http_requests_started'], 1)
        self.assertEqual(snapshot['events'][-1]['status'], 'ok')

    def test_retail_discovery_keeps_a_provider_link_without_authorizing_extraction(self):
        url = 'https://www.buscalibre.cl/libro-un-ejemplo/123/p/123'
        self.assertEqual(discovery_url(url), url)
        self.assertEqual(trusted_url(url), '')
        response = {'results': [{'title': BOOK['title'], 'url': url, 'content': PAGE['description']}]}
        with patch('core.literary_search.read_json_url', return_value=response):
            found = search_searx('Cuaderno de la luna Ana Robles')
        self.assertEqual(found[0]['url'], url)
        self.assertEqual(found[0]['read_mode'], 'fragmento del buscador')
        with research_scope(), patch('core.literary_search.search_searx', return_value=found), \
                patch('core.literary_search.search_wikipedia', return_value=[]), \
                patch('core.literary_search.search_duckduckgo', return_value=[]), \
                patch('core.literary_search.read_public_page') as read:
            results = _retrieve_web('Cuaderno de la luna Ana Robles')
            snapshot = research_snapshot()
        read.assert_not_called()
        self.assertEqual(results[0]['read_mode'], 'fragmento del buscador')
        self.assertEqual(snapshot['page_slots_reserved'], 0)
        self.assertEqual(snapshot['pages_extracted'], 0)

    def test_discovery_does_not_allow_private_addresses_or_lookalike_domains(self):
        for url in ('https://buscalibre.cl.evil.example/book', 'https://not-amazon.com/book',
                    'https://127.0.0.1/book', 'https://192.168.0.1/book',
                    'https://www.amazon.com@127.0.0.1/book', 'https://amazon.com:8443/book'):
            with self.subTest(url=url):
                self.assertEqual(discovery_url(url), '')


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                     'LOCATION': 'progressive-author-language'}})
class OpenLibraryAuthorLanguageTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def docs(self, languages=('spa', 'eng')):
        return {'docs': [{'key': '/works/OL1W', 'title': 'Una obra registrada',
                         'author_name': ['Marcela Paz'], 'subject': ['Fiction'],
                         'language': list(languages)}]}

    def test_google_author_operator_is_translated_to_the_official_open_library_field(self):
        with patch('core.literary_search._openlibrary_fetch', return_value=self.docs()) as fetch:
            result = search_openlibrary('inauthor:"Marcela Paz"')
        query = parse_qs(urlsplit(fetch.call_args.args[0]).query)['q'][0]
        self.assertEqual(query, 'author:"Marcela Paz"')
        self.assertEqual(result[0]['author'], 'Marcela Paz')

    def test_spanish_is_a_catalogue_constraint_rather_than_a_subject(self):
        with patch('core.literary_search._openlibrary_fetch', return_value=self.docs()) as fetch:
            result = search_openlibrary('inauthor:"Marcela Paz" en español')
        query = parse_qs(urlsplit(fetch.call_args.args[0]).query)['q'][0]
        self.assertEqual(query, 'author:"Marcela Paz" language:spa')
        self.assertEqual(result[0]['language'], 'es')

    def test_missing_or_different_language_metadata_does_not_confirm_a_spanish_edition(self):
        for languages in ((), ('eng',)):
            cache.clear()
            with self.subTest(languages=languages), patch('core.literary_search._openlibrary_fetch', return_value=self.docs(languages)):
                result = search_openlibrary('inauthor:"Marcela Paz" en español')
            self.assertEqual(result, [])

    def test_a_title_named_en_espanol_does_not_become_a_language_restriction(self):
        with patch('core.literary_search._openlibrary_fetch', return_value=self.docs(('eng',))) as fetch:
            result = search_openlibrary('intitle:"En español"')
        query = parse_qs(urlsplit(fetch.call_args.args[0]).query)['q'][0]
        self.assertEqual(query, 'title:"En español"')
        self.assertEqual(len(result), 1)

    def test_requested_language_does_not_remove_words_inside_the_book_title(self):
        with patch('core.literary_search._openlibrary_fetch', return_value=self.docs()) as fetch:
            search_openlibrary('intitle:"Un libro en español" en español')
        query = parse_qs(urlsplit(fetch.call_args.args[0]).query)['q'][0]
        self.assertEqual(query, 'title:"Un libro en español" language:spa')

    def test_operator_like_words_in_a_literal_title_are_preserved(self):
        with patch('core.literary_search._openlibrary_fetch', return_value=self.docs()) as fetch:
            search_openlibrary('intitle:"El misterio inauthor: detective"')
        query = parse_qs(urlsplit(fetch.call_args.args[0]).query)['q'][0]
        self.assertEqual(query, 'title:"El misterio inauthor: detective"')

    def test_language_changes_do_not_reuse_a_different_cached_search(self):
        with patch('core.literary_search._openlibrary_fetch', return_value=self.docs()) as fetch:
            search_openlibrary('inauthor:"Marcela Paz"')
            cache.delete('litmate_local_ol_slot')
            search_openlibrary('inauthor:"Marcela Paz" en español')
        self.assertEqual(fetch.call_count, 2)
