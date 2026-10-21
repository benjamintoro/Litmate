"""Recomendaciones temáticas gratuitas: materias verificables, sin títulos semilla."""
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from .books_google import (book_topic_profile, topic_matches, rank_book_sources, source_synopsis)
from .literary_search import search_openlibrary
from .literary_sources import research_scope


class TopicRestrictionTests(SimpleTestCase):
    def test_spanish_history_and_country_become_catalog_subjects(self):
        profile = book_topic_profile('recomiendame libros sobre la historia de corea')
        self.assertTrue(profile['structured'])
        self.assertEqual(profile['query'], 'subject:"history" subject:"korea"')

    def test_spanish_art_request_does_not_become_an_identification(self):
        profile = book_topic_profile('estoy buscando un libro sobre arte japonés')
        self.assertEqual(profile['query'], 'subject:"art" subject:"japan"')

    def test_quoted_and_structured_titles_are_not_translated(self):
        for query in ('"Historia de Corea"', 'intitle:Historia inauthor:Kim', 'isbn:9780140449136'):
            with self.subTest(query=query):
                self.assertFalse(book_topic_profile(query)['structured'])

    def test_unmapped_topic_keeps_meaning_and_removes_request_words(self):
        profile = book_topic_profile('estoy buscando un libro sobre astronomia')
        self.assertFalse(profile['structured'])
        self.assertEqual(profile['query'], 'astronomia')

    def test_all_topic_facets_are_required_not_only_country(self):
        valid = {'title': 'Korean history', 'categories': ['Korea', 'History'], 'kind': 'book'}
        incorrect = {'title': 'Korean recipes', 'categories': ['Korea', 'Cooking'], 'kind': 'book'}
        unrelated = {'title': 'European history', 'categories': ['Europe', 'History'], 'kind': 'book'}
        query = 'recomiendame libros sobre la historia de corea'
        self.assertTrue(topic_matches(valid, query))
        self.assertFalse(topic_matches(incorrect, query))
        self.assertFalse(topic_matches(unrelated, query))
        self.assertEqual(rank_book_sources([incorrect, unrelated, valid], query), [valid])

    def test_art_is_not_language_arts_fiction_or_a_military_manual(self):
        query = 'libros sobre arte japones'
        cases = [
            {'title': 'A Japanese novel', 'categories': ['Japan', 'LANGUAGE ARTS & DISCIPLINES / Linguistics', 'Fiction']},
            {'title': 'Linguistics of Japan', 'categories': ['Japan', 'LANGUAGE ARTS & DISCIPLINES / Linguistics']},
            {'title': 'El arte japonés de la guerra', 'categories': ['Japan', 'Military History', 'Martial Arts']},
            {'title': 'French paintings', 'categories': ['French Art', 'Painting']},
        ]
        for source in cases:
            with self.subTest(title=source['title']):
                self.assertFalse(topic_matches(source, query))
        self.assertTrue(topic_matches({'title': 'Japanese woodblock prints',
                                      'categories': ['Japan', 'Japanese Art', 'Ukiyoe']}, query))

    def test_north_and_south_are_not_interchangeable(self):
        source = {'title': 'A modern history', 'categories': ['History', 'Korea (north)']}
        self.assertFalse(topic_matches(source, 'libros sobre historia de Corea del Sur'))
        self.assertTrue(topic_matches(source, 'libros sobre historia de Corea del Norte'))

    def test_general_history_ranks_before_biography(self):
        history = {'title': 'History of Korea', 'author': 'A scholar', 'categories': ['History', 'Korea']}
        memoir = {'title': 'A life', 'author': 'A writer', 'categories': ['Korea', 'History', 'Biography']}
        self.assertEqual(rank_book_sources([memoir, history], 'historia de corea')[0], history)

    def test_fiction_genre_recommendations_preserve_existing_filters(self):
        profile = book_topic_profile('recomiendame tres novelas de ciencia ficcion y explica sus diferencias')
        self.assertEqual(profile['query'], 'subject:"science fiction"')
        source = {'title': 'Una aventura espacial', 'categories': ['Fiction', 'Science Fiction']}
        self.assertTrue(topic_matches(source, 'recomiendame novelas de ciencia ficcion'))

    def test_historical_novels_keep_fiction_constraint(self):
        profile = book_topic_profile('recomiendame novelas historicas de corea')
        self.assertEqual(profile['query'], 'subject:"history" subject:"fiction" subject:"korea"')

    def test_spanish_language_does_not_imply_spain_as_a_subject(self):
        self.assertEqual(book_topic_profile('libros sobre arte en español')['query'], 'subject:"art"')

    def test_catalog_subjects_are_not_a_synopsis(self):
        self.assertEqual(source_synopsis({'description': 'Temas del catálogo: Japanese Art, History'}), '')
        self.assertEqual(source_synopsis({'description': 'Temas del catálogo: Art',
                                         'synopsis': 'A documented overview of Japanese painting.'}),
                         'A documented overview of Japanese painting.')


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                     'LOCATION': 'free-topic-catalog'}})
class OpenLibraryTopicTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        # Mock only the local rate gate; all URL/schema/provenance handling is
        # real and HTTP is mocked separately in every test.
        gate = patch('core.literary_search._openlibrary_fetch',
                     side_effect=lambda url, **kw: __import__('core.literary_search', fromlist=['read_json_url']).read_json_url(url, **kw))
        gate.start()
        self.addCleanup(gate.stop)

    def docs(self, count=1):
        return {'docs': [{'key': '/works/OL' + str(i + 1) + 'W', 'title': 'Japanese Art ' + str(i),
                          'author_name': ['A verified author'], 'subject': ['Japanese Art', 'Japan', 'Painting'],
                          'cover_i': 123, 'first_publish_year': 2000}
                         for i in range(count)]}

    def test_real_bibliographic_ids_and_structured_query_and_descriptions(self):
        calls = []
        def fetch(url, **kwargs):
            calls.append(url)
            if '/search.json?' in url:
                return self.docs()
            return {'key': '/works/OL1W', 'description': {'value': 'A description supplied by the bibliographic record.'}}
        with patch('core.literary_search.read_json_url', side_effect=fetch):
            sources = search_openlibrary('estoy buscando un libro sobre arte japones')
        self.assertEqual(parse_qs(urlsplit(calls[0]).query)['q'], ['subject:"art" subject:"japan"'])
        self.assertEqual(sources[0]['url'], 'https://openlibrary.org/works/OL1W')
        self.assertEqual(sources[0]['author'], 'A verified author')
        self.assertEqual(sources[0]['synopsis'], 'A description supplied by the bibliographic record.')
        self.assertEqual(len(calls), 2)

    def test_search_has_cache_and_does_not_repeat_record_reads(self):
        with patch('core.literary_search.read_json_url', side_effect=[self.docs(),
                    {'key': '/works/OL1W', 'description': 'A real description.'}]) as fetch:
            first = search_openlibrary('libros sobre arte japones')
            second = search_openlibrary('recomiendame libros sobre arte japones')
        self.assertEqual(first, second)
        self.assertEqual(fetch.call_count, 2)

    def test_three_page_budget_is_shared_with_other_tools(self):
        def fetch(url, **kwargs):
            if '/search.json?' in url:
                return self.docs(5)
            work = urlsplit(url).path.removesuffix('.json')
            return {'key': work, 'description': 'Verified catalog description.'}
        from .literary_sources import reserve_page
        with research_scope(2, 15, 3):
            self.assertTrue(reserve_page())
            with patch('core.literary_search.read_json_url', side_effect=fetch) as request:
                sources = search_openlibrary('libros sobre arte japones')
            self.assertEqual(request.call_count, 3)  # One search, two remaining record reads.
            self.assertEqual(sum(bool(source.get('synopsis')) for source in sources), 2)

    def test_two_record_read_limit_leaves_a_page_for_further_research(self):
        def fetch(url, **kwargs):
            if '/search.json?' in url:
                return self.docs(5)
            return {'key': urlsplit(url).path.removesuffix('.json')}
        from .literary_sources import reserve_page
        with research_scope(2, 15, 3):
            with patch('core.literary_search.read_json_url', side_effect=fetch) as request:
                self.assertEqual(len(search_openlibrary('libros sobre arte japones')), 5)
            self.assertEqual(request.call_count, 3)
            self.assertTrue(reserve_page())

    def test_record_missing_description_does_not_invent_one(self):
        with patch('core.literary_search.read_json_url', side_effect=[self.docs(), {'key': '/works/OL1W'}]):
            source = search_openlibrary('libros sobre arte japones')[0]
        self.assertNotIn('synopsis', source)
        self.assertEqual(source_synopsis(source), '')

    def test_each_facet_survives_canonical_five_category_limit(self):
        docs = {'docs': [{'key': '/works/OL1W', 'title': 'A documented overview',
                'author_name': ['A historian'],
                'subject': ['History', 'Modern history', 'Social history', 'Economic history',
                            'Ancient history', 'Political history', 'Korea']} ]}
        from .literary_ai import canonical_sources
        with patch('core.literary_search.read_json_url', side_effect=[docs, {'key': '/works/OL1W'}]):
            sources = canonical_sources(search_openlibrary('libros sobre historia de corea'))
        self.assertIn('Korea', sources[0]['categories'])
        self.assertTrue(topic_matches(sources[0], 'libros sobre historia de corea'))

    def test_invalid_or_private_record_ids_are_never_requested(self):
        docs = {'docs': [{'key': 'http://127.0.0.1/private', 'title': 'Japanese Art',
                          'author_name': ['An author'], 'subject': ['Japanese Art']}]}
        with patch('core.literary_search.read_json_url', return_value=docs) as fetch:
            self.assertEqual(search_openlibrary('libros sobre arte japones'), [])
        self.assertEqual(fetch.call_count, 1)

    def test_unrelated_search_results_are_discarded_without_enrichment(self):
        docs = {'docs': [{'key': '/works/OL1W', 'title': 'El Código Da Vinci',
                          'author_name': ['Dan Brown'], 'subject': ['Fiction', 'Art', 'France']}]}
        with patch('core.literary_search.read_json_url', return_value=docs) as fetch:
            self.assertEqual(search_openlibrary('libros sobre arte japones'), [])
        self.assertEqual(fetch.call_count, 1)

    def test_api_failure_and_rate_limit_are_not_announced_as_no_books(self):
        error = HTTPError('https://openlibrary.org/search.json', 429, 'rate limit', {}, None)
        with patch('core.literary_search.read_json_url', side_effect=error) as fetch:
            result = search_openlibrary('libros sobre historia de corea')
            repeated = search_openlibrary('libros sobre arte japones')
        self.assertEqual(result.status, 'rate_limited')
        self.assertEqual(repeated.status, 'cooldown')
        self.assertEqual(fetch.call_count, 1)

    def test_empty_results_are_cached_and_invalid_schema_is_distinct(self):
        with patch('core.literary_search.read_json_url', return_value={'docs': []}) as fetch:
            self.assertEqual(search_openlibrary('libros sobre arte japones').status, 'empty')
            self.assertEqual(search_openlibrary('libros sobre arte japones').status, 'empty')
        self.assertEqual(fetch.call_count, 1)
        cache.clear()
        with patch('core.literary_search.read_json_url', return_value={'unexpected': []}):
            self.assertEqual(search_openlibrary('libros sobre arte japones').status, 'invalid_response')

    def test_exhausted_shared_external_time_does_not_call_the_api(self):
        from .literary_sources import account_research
        with research_scope(2, 15, 3):
            account_research(15)
            with patch('core.literary_search.read_json_url') as fetch:
                self.assertEqual(search_openlibrary('libros sobre arte japones').status, 'budget_exhausted')
            fetch.assert_not_called()


class OpenLibraryRateControlTests(SimpleTestCase):
    def test_all_gets_reserve_the_same_one_second_slot(self):
        from .literary_search import _openlibrary_fetch
        with patch('core.literary_search.cache.add', return_value=True) as add, \
                patch('core.literary_search.read_json_url', return_value={'key': '/works/OL1W'}) as fetch:
            self.assertEqual(_openlibrary_fetch('https://openlibrary.org/works/OL1W.json', timeout=4),
                             {'key': '/works/OL1W'})
        add.assert_called_once_with('litmate_ol_http_slot', True, timeout=1)
        self.assertEqual(fetch.call_count, 1)

    def test_rate_gate_wait_is_bounded(self):
        from .literary_search import _openlibrary_fetch
        with patch('core.literary_search.cache.add', return_value=False), \
                patch('core.literary_search.time.monotonic', side_effect=[0, 2]), \
                patch('core.literary_search.budget_timeout', side_effect=lambda n: n), \
                patch('core.literary_search.read_json_url') as fetch:
            with self.assertRaises(TimeoutError):
                _openlibrary_fetch('https://openlibrary.org/search.json?q=history', timeout=6)
        fetch.assert_not_called()

    def test_rate_gate_failure_does_not_allow_uncontrolled_requests(self):
        from .literary_search import _openlibrary_fetch
        with patch('core.literary_search.cache.add', side_effect=RuntimeError), \
                patch('core.literary_search.read_json_url') as fetch:
            with self.assertRaises(TimeoutError):
                _openlibrary_fetch('https://openlibrary.org/works/OL1W.json', timeout=4)
        fetch.assert_not_called()


class CuratedArtDomainTests(SimpleTestCase):
    def test_official_museum_and_publisher_are_allowed_in_both_readers(self):
        from .literary_search import trusted_url
        from .literary_web import PUBLIC_DOMAINS, _validated_url
        for host in ('www.metmuseum.org', 'www.tuttlepublishing.com'):
            with self.subTest(host=host):
                url = 'https://' + host + '/books/example'
                self.assertEqual(trusted_url(url), url)
                self.assertEqual(_validated_url(url, PUBLIC_DOMAINS)[1], host)

    def test_lookalikes_credentials_and_private_urls_remain_blocked(self):
        from .literary_search import trusted_url
        from .literary_web import PUBLIC_DOMAINS, PublicFetchError, _validated_url
        urls = ('https://metmuseum.org.attacker.example/book',
                'https://fake-tuttlepublishing.com/book', 'https://127.0.0.1/book',
                'https://192.168.1.1/book', 'https://[::1]/book',
                'https://www.metmuseum.org@127.0.0.1/book')
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(trusted_url(url), '')
                with self.assertRaises(PublicFetchError):
                    _validated_url(url, PUBLIC_DOMAINS)

