"""Regresiones de Books API, privacidad y uso bibliográfico: toda la red es simulada."""
import copy
import io
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, override_settings

from .ai_budget import BudgetExpired
from .books_google import BooksUnavailable, get_volume, public_query, search_volumes, volume_source
from .books_google import book_search_queries, rank_book_sources, source_synopsis
from .ai_catalog_fallback import catalog_fallback, bibliographic_answer
from .literary_ai import LiteraryAssistant, canonical_sources
from .literary_evidence import validate_evidence
from .literary_search import retrieve_books, search_google, enrich_book_sources, relevant_passage, search_wikipedia
from .test_literary_ai import DRAFT, FakeLLM, ROUTE


API_KEY = 'test-only-books-key-never-real'
VOLUME = {
    'id': 'books_test_1',
    'volumeInfo': {
        'title': 'Matar un ruiseñor', 'authors': ['Harper Lee'],
        'description': '<p>Una novela sobre <b>justicia</b> y prejuicios.</p>',
        'publisher': 'Harper Perennial', 'publishedDate': '2006-05-23',
        'pageCount': 336, 'language': 'es', 'categories': ['Ficción'],
        'industryIdentifiers': [{'type': 'ISBN_13', 'identifier': '9780061120084'},
                                {'type': 'ISBN_10', 'identifier': '0061120081'}],
        'canonicalVolumeLink': 'http://books.google.com/books?id=books_test_1',
        'previewLink': 'https://books.google.com/books?id=books_test_1&printsec=frontcover',
    },
    'accessInfo': {'viewability': 'PARTIAL', 'publicDomain': False,
                   'webReaderLink': 'https://play.google.com/books/reader?id=books_test_1'},
}


def fiction_volume(identifier, title, author, synopsis, categories=None):
    item = copy.deepcopy(VOLUME)
    item['id'] = identifier
    item['volumeInfo'].update({'title': title, 'authors': [author], 'description': synopsis,
        'categories': categories or ['Fiction / Science Fiction'],
        'canonicalVolumeLink': 'https://books.google.com/books?id=' + identifier,
        'imageLinks': {'thumbnail': 'http://books.google.com/books/content?id=' + identifier + '&img=1'}})
    return item


SCIENCE_FICTION = [
    fiction_volume('robots', 'Ciudad de robots', 'Ana Robles',
                   'Una novela de ciencia ficción en la que robots e inteligencia artificial conviven con humanos.'),
    fiction_volume('time', 'El viaje imposible', 'Tomás Rivas',
                   'Una novela de ciencia ficción sobre viajes en el tiempo y decisiones que cambian el futuro.'),
    fiction_volume('planet', 'La colonia lejana', 'Sara Vega',
                   'Una novela de ciencia ficción sobre la supervivencia de una colonia en otro planeta.'),
]


SCHOOL_VOLUME = fiction_volume('school', 'Lengua castellana, tercer curso de secundaria', 'Editorial escolar',
    'Actividades y ejercicios de lectura. Una unidad incluye fragmentos de ciencia ficción.', ['Education / Language Arts'])


@override_settings(LITMATE_USE_GOOGLE_BOOKS_API=True, GOOGLE_BOOKS_API_KEY=API_KEY,
                   GOOGLE_BOOKS_LANGUAGE='es', GOOGLE_BOOKS_TIMEOUT=8)
class GoogleBooksClientTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def assert_unavailable(self, code, callback):
        with self.assertRaises(BooksUnavailable) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        self.assertNotIn(API_KEY, str(raised.exception))

    def test_search_uses_books_endpoint_key_language_and_bounded_limit(self):
        fetch = Mock(return_value={'items': [copy.deepcopy(VOLUME)]})
        result = search_volumes('intitle:Matar un ruiseñor inauthor:Harper Lee', 100, fetch=fetch)
        request_url = fetch.call_args.args[0]
        parsed = urlsplit(request_url)
        params = parse_qs(parsed.query)
        self.assertEqual(parsed.scheme, 'https')
        self.assertEqual(parsed.hostname, 'www.googleapis.com')
        self.assertEqual(parsed.path, '/books/v1/volumes')
        self.assertEqual(params['key'], [API_KEY])
        self.assertEqual(params['maxResults'], ['40'])
        self.assertEqual(params['langRestrict'], ['es'])
        self.assertEqual(params['printType'], ['books'])
        self.assertEqual(params['q'], ['intitle:Matar un ruiseñor inauthor:Harper Lee'])
        self.assertEqual(result, [VOLUME])
        self.assertNotIn(API_KEY, repr(result))
        self.assertEqual(fetch.call_args.kwargs['timeout'], 8)

    def test_valid_isbn_is_not_mistaken_for_a_phone(self):
        fetch = Mock(return_value={'items': [VOLUME]})
        search_volumes('ISBN 978-0-06-112008-4', fetch=fetch)
        self.assertEqual(parse_qs(urlsplit(fetch.call_args.args[0]).query)['q'], ['isbn:9780061120084'])

    def test_empty_query_never_calls_network(self):
        fetch = Mock()
        self.assertEqual(search_volumes('', fetch=fetch), [])
        self.assertEqual(search_volumes('fragmento: mi pasaje privado', fetch=fetch), [])
        fetch.assert_not_called()

    @override_settings(LITMATE_USE_GOOGLE_BOOKS_API=False)
    def test_disabled_service_never_calls_network(self):
        fetch = Mock()
        self.assert_unavailable('disabled', lambda: search_volumes('historia Chile', fetch=fetch))
        self.assert_unavailable('disabled', lambda: get_volume('books_test_1', fetch=fetch))
        fetch.assert_not_called()

    def test_missing_and_placeholder_keys_never_call_network(self):
        for key in ['', '  ', 'tu_clave_google_books', 'YOUR_GOOGLE_KEY']:
            with self.subTest(key=key), override_settings(GOOGLE_BOOKS_API_KEY=key):
                fetch = Mock()
                self.assert_unavailable('missing_key', lambda: search_volumes('historia', fetch=fetch))
                self.assert_unavailable('missing_key', lambda: get_volume('books_test_1', fetch=fetch))
                fetch.assert_not_called()

    def test_http_errors_become_safe_actionable_codes(self):
        expected = {400: 'invalid_query', 401: 'invalid_key', 403: 'access_or_quota',
                    404: 'not_found', 429: 'quota_exceeded', 500: 'unavailable'}
        for status, code in expected.items():
            with self.subTest(status=status):
                fetch = Mock(side_effect=HTTPError('https://example.test/?key=' + API_KEY,
                                                   status, API_KEY, {}, None))
                self.assert_unavailable(code, lambda: search_volumes('historia', fetch=fetch))

    def test_network_decode_and_timeout_errors_do_not_expose_secret(self):
        for error in [URLError(API_KEY), TimeoutError(API_KEY), ValueError(API_KEY), OSError(API_KEY)]:
            with self.subTest(error=type(error).__name__):
                self.assert_unavailable('unavailable', lambda: search_volumes('historia',
                                                                         fetch=Mock(side_effect=error)))

    def test_transient_google_503_is_retried_once(self):
        fetch = Mock(side_effect=[HTTPError('https://example.test', 503, 'error temporal', {}, None),
                                  {'items': [VOLUME]}])
        with patch('core.books_google.time.sleep'):
            self.assertEqual(search_volumes('historia', fetch=fetch), [VOLUME])
        self.assertEqual(fetch.call_count, 2)

    def test_quota_error_is_never_retried(self):
        fetch = Mock(side_effect=HTTPError('https://example.test', 429, 'cuota', {}, None))
        self.assert_unavailable('quota_exceeded', lambda: search_volumes('historia', fetch=fetch))
        self.assertEqual(fetch.call_count, 1)

    def test_total_budget_expiration_is_preserved(self):
        with self.assertRaises(BudgetExpired):
            search_volumes('historia', fetch=Mock(side_effect=BudgetExpired('tiempo_total_agotado')))

    def test_malformed_top_level_and_items_are_rejected(self):
        for malformed in [None, [], {'error': {'message': API_KEY}}, {'items': {'title': 'incorrecto'}}]:
            with self.subTest(response=malformed):
                self.assert_unavailable('invalid_response', lambda: search_volumes('historia',
                                                                     fetch=Mock(return_value=malformed)))

    def test_zero_results_are_an_empty_list(self):
        self.assertEqual(search_volumes('obra inexistente', fetch=Mock(return_value={'totalItems': 0})), [])

    def test_malformed_volume_entries_are_skipped(self):
        entries = [None, 'un volumen', {}, {'volumeInfo': []},
                   {'volumeInfo': {'authors': ['Autor sin título']}},
                   {'volumeInfo': {'title': {'texto': 'título inválido'}}},
                   {'volumeInfo': {'title': ['título inválido']}},
                   {'volumeInfo': {'title': '  '}}, VOLUME]
        self.assertEqual(search_volumes('historia', max_results=20,
                                        fetch=Mock(return_value={'items': entries})), [VOLUME])

    def test_search_cache_changes_when_api_key_changes(self):
        fetch = Mock(return_value={'items': [VOLUME]})
        with patch('core.books_google.read_json_url', fetch):
            self.assertEqual(search_volumes('historia'), [VOLUME])
            self.assertEqual(search_volumes('historia'), [VOLUME])
            self.assertEqual(fetch.call_count, 1)
            with override_settings(GOOGLE_BOOKS_API_KEY='another-test-only-key'):
                search_volumes('historia')
            self.assertEqual(fetch.call_count, 2)
        self.assertNotIn(API_KEY, repr(cache._cache))

    def test_cached_search_does_not_bypass_disabling_service(self):
        with patch('core.books_google.read_json_url', return_value={'items': [VOLUME]}) as fetch:
            search_volumes('historia')
            with override_settings(LITMATE_USE_GOOGLE_BOOKS_API=False):
                self.assert_unavailable('disabled', lambda: search_volumes('historia'))
            self.assertEqual(fetch.call_count, 1)

    def test_different_language_does_not_reuse_other_cache(self):
        with patch('core.books_google.read_json_url', return_value={'items': [VOLUME]}) as fetch:
            search_volumes('historia', language='es')
            search_volumes('historia', language='en')
            self.assertEqual(fetch.call_count, 2)

    def test_explicit_fetch_is_not_satisfied_by_cached_test_data(self):
        with patch('core.books_google.read_json_url', return_value={'items': [VOLUME]}):
            search_volumes('historia')
        fetch = Mock(return_value={'items': []})
        self.assertEqual(search_volumes('historia', fetch=fetch), [])
        fetch.assert_called_once()

    def test_get_volume_fetches_detail_without_changing_raw_metadata(self):
        fetch = Mock(return_value=copy.deepcopy(VOLUME))
        self.assertEqual(get_volume('books_test_1', fetch=fetch), VOLUME)
        self.assertEqual(urlsplit(fetch.call_args.args[0]).path, '/books/v1/volumes/books_test_1')
        self.assertEqual(parse_qs(urlsplit(fetch.call_args.args[0]).query)['key'], [API_KEY])

    def test_get_volume_rejects_id_path_injection_before_network(self):
        fetch = Mock()
        for identifier in ['', '../other', 'book?key=secret', 'https://example.test', 'x' * 101, None]:
            with self.subTest(identifier=identifier):
                self.assert_unavailable('invalid_id', lambda: get_volume(identifier, fetch=fetch))
        fetch.assert_not_called()

    def test_get_volume_rejects_a_detail_without_a_title(self):
        for response in [{}, {'volumeInfo': []}, {'volumeInfo': {'description': 'sin título'}},
                         {'volumeInfo': {'title': {'texto': 'título inválido'}}},
                         {'volumeInfo': {'title': ['título inválido']}}, {'volumeInfo': {'title': '  '}}]:
            self.assert_unavailable('invalid_response', lambda: get_volume('books_test_1',
                                                                          fetch=Mock(return_value=response)))

    def test_detail_cache_changes_when_key_changes(self):
        with patch('core.books_google.read_json_url', return_value=VOLUME) as fetch:
            get_volume('books_test_1')
            get_volume('books_test_1')
            self.assertEqual(fetch.call_count, 1)
            with override_settings(GOOGLE_BOOKS_API_KEY='another-test-only-key'):
                get_volume('books_test_1')
            self.assertEqual(fetch.call_count, 2)


class PublicBookQueryTests(SimpleTestCase):
    def test_excerpt_is_removed_before_public_search(self):
        for marker in ['fragmento:', 'pasaje:', 'extracto:', 'texto:', 'fragmento «']:
            with self.subTest(marker=marker):
                self.assertEqual(public_query('Analiza Matar un ruiseñor; ' + marker + ' pasaje privado'),
                                 'Analiza Matar un ruiseñor;')

    def test_qualified_private_excerpt_markers_are_also_removed(self):
        for marker in ['fragmento privado:', 'pasaje del libro:', 'texto de ficción «',
                       'extracto de la página dos:']:
            with self.subTest(marker=marker):
                self.assertEqual(public_query('Analiza 1984; ' + marker + ' frase personal del lector'),
                                 'Analiza 1984;')

    def test_numeric_book_title_is_searchable(self):
        self.assertEqual(public_query('1984'), '1984')

    def test_contact_details_credentials_and_url_are_removed(self):
        query = public_query('libros historia correo@example.test +56 9 1234 5678 '
                             'https://example.test/privado sk-abcdefghijklmnopqrst '
                             'AIzaabcdefghijklmnopqrst Bearer secreto')
        self.assertEqual(query, 'libros historia')

    def test_multiline_passage_and_non_string_are_not_search_queries(self):
        for query in ['línea 1\nlínea 2\nlínea 3\nlínea 4', None, [], {'q': 'libro'}]:
            self.assertEqual(public_query(query), '')

    def test_valid_isbn10_and_isbn13_accept_spacing_and_labels(self):
        examples = {'ISBN-13: 978-0-06-112008-4': 'isbn:9780061120084',
                    'ISBN-10: 0-06-112008-1': 'isbn:0061120081',
                    '9780061120084': 'isbn:9780061120084'}
        for raw, expected in examples.items():
            self.assertEqual(public_query(raw), expected)

    def test_query_is_bounded_and_markup_delimiters_are_removed(self):
        cleaned = public_query('<libros>{historia}`tema`|' + ' ejemplo' * 100)
        self.assertLessEqual(len(cleaned), 240)
        self.assertFalse(any(character in cleaned for character in '<>{}`|'))


class GoogleBibliographicEvidenceTests(SimpleTestCase):
    def test_volume_source_preserves_metadata_without_claiming_full_read(self):
        source = volume_source(copy.deepcopy(VOLUME))
        canonical = canonical_sources([source])[0]
        self.assertEqual(canonical['title'], 'Matar un ruiseñor')
        self.assertEqual(canonical['author'], 'Harper Lee')
        self.assertEqual(canonical['publisher'], 'Harper Perennial')
        self.assertEqual(canonical['year'], '2006')
        self.assertEqual(canonical['published_date'], '2006-05-23')
        self.assertEqual(canonical['page_count'], 336)
        self.assertEqual(canonical['isbns'], ['9780061120084', '0061120081'])
        self.assertEqual(canonical['kind'], 'book')
        self.assertEqual(canonical['source'], 'Google Books API')
        self.assertIn('Sinopsis editorial:', canonical['description'])
        self.assertNotIn('<p>', canonical['description'])
        self.assertIn('ficha y sinopsis', canonical['read_mode'])
        self.assertIn('vista previa externa', canonical['read_mode'])
        self.assertTrue(canonical['url'].startswith('https://books.google.com/'))
        self.assertTrue(canonical['preview_url'].startswith('https://books.google.com/'))
        self.assertFalse(canonical['public_domain'])

    def test_untrusted_preview_and_read_links_are_discarded(self):
        item = copy.deepcopy(VOLUME)
        item['volumeInfo']['previewLink'] = 'javascript:alert(1)'
        item['volumeInfo']['canonicalVolumeLink'] = 'https://evil.example.test'
        item['accessInfo']['webReaderLink'] = 'http://127.0.0.1/private'
        source = volume_source(item)
        self.assertEqual(source['preview_url'], '')
        self.assertEqual(source['read_url'], '')
        self.assertEqual(urlsplit(source['url']).hostname, 'books.google.com')

    def test_google_metadata_survives_duplicate_local_catalog_record(self):
        source = volume_source(VOLUME)
        local = {'title': source['title'], 'author': source['author'],
                 'description': 'Catálogo local', 'source': 'Catálogo LitMate', 'book_id': 'db_1'}
        merged = canonical_sources([local, source])
        self.assertEqual(len(merged), 2)
        google = next(row for row in merged if row['source'] == 'Google Books API')
        catalog = next(row for row in merged if row['source'] == 'Catálogo LitMate')
        self.assertEqual(google['isbns'], ['9780061120084', '0061120081'])
        self.assertEqual(google['page_count'], 336)
        self.assertEqual(google['book_id'], 'books_test_1')
        self.assertEqual(catalog['book_id'], 'db_1')
        self.assertNotIn('isbns', catalog)

    def test_distinct_google_editions_keep_their_own_isbn_dates_and_page_counts(self):
        other = copy.deepcopy(VOLUME)
        other['id'] = 'books_second_edition'
        other['volumeInfo'].update({
            'publisher': 'Editorial de la segunda edición', 'publishedDate': '1995-04-12',
            'pageCount': 281, 'industryIdentifiers': [{'type': 'ISBN_13', 'identifier': '9780306406157'}],
            'canonicalVolumeLink': 'https://books.google.com/books?id=books_second_edition',
            'previewLink': 'https://books.google.com/books?id=books_second_edition&printsec=frontcover',
        })
        sources = canonical_sources([volume_source(VOLUME), volume_source(other)])
        self.assertEqual(len(sources), 2)
        first, second = sources
        self.assertEqual(first['title'], second['title'])
        self.assertEqual(first['author'], second['author'])
        self.assertEqual((first['year'], first['page_count'], first['isbns']),
                         ('2006', 336, ['9780061120084', '0061120081']))
        self.assertEqual((second['year'], second['page_count'], second['isbns']),
                         ('1995', 281, ['9780306406157']))
        self.assertEqual(second['publisher'], 'Editorial de la segunda edición')
        self.assertIn('1995-04-12', second['description'])
        self.assertIn('9780306406157', second['description'])
        self.assertNotIn('9780061120084', second['description'])
        self.assertEqual(parse_qs(urlsplit(second['url']).query)['id'], ['books_second_edition'])
        with self.assertRaises(ValueError):
            validate_evidence({**DRAFT, 'basis': 'sources', 'citations': [1],
                               'text': 'La primera ficha confirma ISBN: 9780306406157 [1].'},
                              sources, 'Dame el ISBN de la primera edición')

    def test_malformed_optional_google_metadata_is_ignored(self):
        item = copy.deepcopy(VOLUME)
        item['accessInfo'] = ['formato inesperado']
        item['volumeInfo']['categories'] = {'tema': 'formato inesperado'}
        item['volumeInfo']['industryIdentifiers'] = {'ISBN_13': '9780061120084'}
        item['volumeInfo']['authors'] = {'autor': 'Harper Lee'}
        item['volumeInfo']['pageCount'] = -100
        source = volume_source(item)
        self.assertEqual(source['categories'], [])
        self.assertEqual(source['isbns'], [])
        self.assertEqual(source['author'], '')
        self.assertIsNone(source['page_count'])
        self.assertEqual(source['preview_url'], VOLUME['volumeInfo']['previewLink'])
        self.assertEqual(source['read_url'], '')
        self.assertIn('ficha y sinopsis bibliográfica', source['read_mode'])

    def test_synopsis_and_cover_are_clean_and_preserved_for_cards(self):
        source = canonical_sources([volume_source(SCIENCE_FICTION[0])])[0]
        self.assertEqual(source_synopsis(source), SCIENCE_FICTION[0]['volumeInfo']['description'])
        self.assertNotIn('ISBN:', source['synopsis'])
        self.assertNotIn('Editorial:', source['synopsis'])
        self.assertEqual(source['image_url'], 'https://books.google.com/books/content?id=robots&img=1')

    def test_external_or_credentialed_cover_url_is_rejected(self):
        for url in ['https://evil.example.test/cover.png', 'https://user:secret@books.google.com/cover',
                    'http://127.0.0.1/cover', 'javascript:alert(1)']:
            item = copy.deepcopy(VOLUME)
            item['volumeInfo']['imageLinks'] = {'thumbnail': url}
            self.assertEqual(volume_source(item)['image_url'], '')

    def test_isbn_claim_requires_matching_cited_edition(self):
        sources = canonical_sources([volume_source(VOLUME)])
        draft = {**DRAFT, 'basis': 'sources', 'text': 'La edición tiene ISBN: 9780061120084 [1].'}
        validate_evidence(draft, sources, '¿Cuál es el ISBN?')
        for text, citations in [('El ISBN: 9780306406157 [1].', [1]),
                                ('El ISBN: 9780061120085 [1].', [1]),
                                ('El ISBN: 9780061120084.', [])]:
            with self.subTest(text=text, citations=citations), self.assertRaises(ValueError):
                validate_evidence({**draft, 'text': text, 'citations': citations}, sources, 'Dame el ISBN')

    def test_isbn10_hyphens_are_allowed_only_when_present_in_evidence(self):
        sources = canonical_sources([volume_source(VOLUME)])
        validate_evidence({**DRAFT, 'basis': 'sources', 'text': 'ISBN-10: 0-06-112008-1 [1].'},
                          sources, 'Dame el ISBN de esa edición')

    def test_google_synopsis_does_not_supply_an_exact_book_page(self):
        draft = {**DRAFT, 'basis': 'sources', 'text': 'El personaje cambia en la página 336 [1].'}
        with self.assertRaises(ValueError):
            validate_evidence(draft, canonical_sources([volume_source(VOLUME)]), 'Analiza la novela')


@override_settings(LITMATE_USE_GOOGLE_BOOKS_API=True, GOOGLE_BOOKS_API_KEY=API_KEY,
                   GOOGLE_BOOKS_LANGUAGE='es', LITMATE_AI_USE_OPENLIBRARY=False,
                   LITMATE_RAG_SEMANTIC=False, LITMATE_RAG_DB='missing-google-books-test.sqlite3')
class GoogleBooksPipelineTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_missing_synopsis_fetches_volume_detail(self):
        partial = copy.deepcopy(VOLUME)
        partial['volumeInfo'].pop('description')
        with patch('core.literary_search.read_json_url', side_effect=[{'items': [partial]}, VOLUME]) as fetch:
            sources = search_google('Matar un ruiseñor')
        self.assertEqual(fetch.call_count, 2)
        self.assertIn('Sinopsis editorial:', sources[0]['description'])

    def test_detail_failure_preserves_bibliographic_search_hit(self):
        partial = copy.deepcopy(VOLUME)
        partial['volumeInfo'].pop('description')
        with patch('core.literary_search.read_json_url',
                   side_effect=[{'items': [partial]}, URLError('fallo simulado')]):
            sources = search_google('Matar un ruiseñor')
        self.assertEqual(sources[0]['title'], VOLUME['volumeInfo']['title'])
        self.assertEqual(sources[0]['isbns'], ['9780061120084', '0061120081'])

    def test_api_errors_are_logged_without_the_key(self):
        with patch('core.literary_search.read_json_url',
                   side_effect=HTTPError('https://example.test/?key=' + API_KEY, 403, API_KEY, {}, None)), \
                self.assertLogs('litmate', level='WARNING') as logs:
            self.assertEqual(search_google('historia'), [])
        self.assertIn('access_or_quota', ' '.join(logs.output))
        self.assertNotIn(API_KEY, ' '.join(logs.output))

    def test_google_facts_reach_answer_and_public_sources_when_catalog_is_empty(self):
        route = {**ROUTE, 'queries': ['Matar un ruiseñor'], 'candidates': []}
        answer = {**DRAFT, 'basis': 'sources',
                  'text': 'Matar un ruiseñor, de Harper Lee, trata sobre justicia y prejuicios [1]. '
                          'Esta edición tiene ISBN: 9780061120084 [1].',
                  'books': [{'title': 'Matar un ruiseñor', 'author': 'Harper Lee', 'source_id': 1}]}
        llm = FakeLLM(route=route, answer=answer)
        with patch('core.literary_search.read_json_url', return_value={'items': [VOLUME]}) as fetch, \
                patch('core.literary_search.search_catalog', return_value=[]), \
                patch('core.literary_search.retrieve_fragments', return_value=[]), \
                patch('core.local_embeddings.configured_embedder', return_value=None):
            result = LiteraryAssistant(llm, retrieve_books, require_book_sources=True).reply(
                'Recomienda una novela sobre justicia')
        self.assertEqual(result.status, 'answered')
        self.assertEqual(fetch.call_count, 1)
        source = next(record[1]['sources'] for record in llm.records if record[0] == 'answer')[0]
        self.assertEqual(source['source'], 'Google Books API')
        self.assertEqual(source['page_count'], 336)
        self.assertEqual(source['isbns'], ['9780061120084', '0061120081'])
        self.assertEqual(result.sources[0]['preview_url'], VOLUME['volumeInfo']['previewLink'])
        self.assertEqual(result.sources[0]['source'], 'Google Books API')
        self.assertIn('ficha y sinopsis', result.sources[0]['read_mode'])
        self.assertNotIn(API_KEY, repr(result))

    def test_production_google_adapter_uses_shared_cache(self):
        with patch('core.literary_search.read_json_url', return_value={'items': [VOLUME]}) as fetch:
            first = search_google('Matar un ruiseñor')
            second = search_google('Matar un ruiseñor')
        self.assertEqual(first, second)
        self.assertEqual(fetch.call_count, 1)

    def test_science_fiction_request_uses_subject_queries_and_rejects_schoolbooks(self):
        with patch('core.literary_search.read_json_url',
                   return_value={'items': [SCHOOL_VOLUME, *SCIENCE_FICTION]}) as fetch:
            sources = search_google('Recomiéndame tres novelas de ciencia ficción y explica sus diferencias')
        queries = [parse_qs(urlsplit(call.args[0]).query)['q'][0] for call in fetch.call_args_list]
        self.assertEqual(set(queries), {'subject:fiction novela "ciencia ficción"', 'ciencia ficción novela'})
        self.assertEqual([source['title'] for source in sources],
                         [item['volumeInfo']['title'] for item in SCIENCE_FICTION])
        self.assertTrue(all(source['synopsis'] for source in sources))

    def test_genre_ranking_ignores_irrelevant_fiction_and_study_guides(self):
        romance = fiction_volume('romance', 'Un amor de verano', 'Autora D',
                                 'Una historia de amor durante unas vacaciones.', ['Fiction / Romance'])
        guide = fiction_volume('guide', 'Guía de estudio de ciencia ficción', 'Autor E',
                               'Una guía de lectura de novelas de ciencia ficción.', ['Fiction / Science Fiction'])
        ranked = rank_book_sources([volume_source(SCHOOL_VOLUME), volume_source(romance),
                                    volume_source(guide), volume_source(SCIENCE_FICTION[0])],
                                   'novelas ciencia ficción')
        self.assertEqual([source['title'] for source in ranked], ['Ciudad de robots'])

    def test_novel_request_excludes_short_story_anthologies(self):
        anthology = fiction_volume('stories', 'Cuentos del futuro', 'Autora D',
                                   'Cuentos de ciencia ficción y viajes espaciales.')
        ranked = rank_book_sources([volume_source(anthology), volume_source(SCIENCE_FICTION[0])],
                                   'novelas de ciencia ficción')
        self.assertEqual([source['title'] for source in ranked], ['Ciudad de robots'])

    def test_juvenile_novel_is_not_excluded_as_a_schoolbook(self):
        young_novel = fiction_volume('young', 'Viaje a Marte', 'Ana Robles',
                                    'Una novela de ciencia ficción sobre supervivencia en Marte.', ['Juvenile Fiction'])
        self.assertEqual(len(rank_book_sources([volume_source(young_novel)], 'novelas ciencia ficción')), 1)

    def test_misclassified_essay_and_anthology_are_not_novels(self):
        essay = fiction_volume('essay', 'Viajes por el cine', 'Ana Robles',
                               'Un ensayo sobre películas de ciencia ficción y viajes en el tiempo.', ['Fiction'])
        anthology = fiction_volume('collection', 'Otros futuros', 'Sara Vega',
                                   'Una antología de ciencia ficción con once cuentos.', ['Fiction'])
        self.assertEqual(rank_book_sources([volume_source(essay), volume_source(anthology)],
                                          'novelas ciencia ficción'), [])

    def test_science_fiction_tag_does_not_override_education_classification(self):
        school = fiction_volume('mixed_tags', 'Ideas del futuro', 'Ana Robles',
                                'Lecturas y ejercicios sobre ciencia ficción.', ['Education', 'Science Fiction'])
        self.assertEqual(rank_book_sources([volume_source(school)], 'novelas ciencia ficción'), [])

    def test_spanish_edition_of_same_work_is_preferred_over_richer_english_metadata(self):
        english = copy.deepcopy(SCIENCE_FICTION[0])
        english['volumeInfo']['language'] = 'en'
        spanish = copy.deepcopy(SCIENCE_FICTION[0])
        spanish['id'] = 'robots_es'
        spanish['volumeInfo']['categories'] = ['Fiction']
        sources = rank_book_sources([volume_source(english), volume_source(spanish)],
                                    'novelas ciencia ficción', distinct_works=True)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['language'], 'es')

    def test_explicit_study_request_can_still_find_nonfiction(self):
        queries = book_search_queries('ensayos y teoría de la ciencia ficción')
        self.assertEqual(queries, ['ensayos y teoría de la ciencia ficción'])
        ranked = rank_book_sources([volume_source(SCHOOL_VOLUME)], 'estudios de ciencia ficción')
        self.assertEqual(len(ranked), 1)

    def test_exact_title_and_isbn_queries_do_not_become_genre_queries(self):
        self.assertEqual(book_search_queries('intitle:"La ciencia ficción" inauthor:Autora'),
                         ['intitle:"La ciencia ficción" inauthor:Autora'])
        self.assertEqual(book_search_queries('ISBN 9780061120084'), ['isbn:9780061120084'])

    def test_recommendation_without_book_sources_never_calls_answer_model(self):
        llm = FakeLLM(route={**ROUTE, 'queries': ['historia chilena']})
        result = LiteraryAssistant(llm, lambda query: [], require_book_sources=True).reply(
            'Recomienda un título de historia chilena')
        self.assertEqual(result.status, 'clarification')
        self.assertTrue(result.diagnostics['book_sources_missing'])
        self.assertNotIn('answer', [record[0] for record in llm.records])
        self.assertIn('con confianza', result.text)

    def test_retrieval_cache_is_invalidated_when_google_configuration_changes(self):
        with patch('core.literary_search.search_google', return_value=[volume_source(VOLUME)]) as google, \
                patch('core.literary_search.search_catalog', return_value=[]), \
                patch('core.literary_search.retrieve_fragments', return_value=[]), \
                patch('core.local_embeddings.configured_embedder', return_value=None):
            retrieve_books('Matar un ruiseñor')
            retrieve_books('Matar un ruiseñor')
            self.assertEqual(google.call_count, 1)
            with override_settings(GOOGLE_BOOKS_API_KEY='changed-test-key'):
                retrieve_books('Matar un ruiseñor')
            self.assertEqual(google.call_count, 2)


class NaturalCatalogFallbackTests(SimpleTestCase):
    def test_three_novels_have_distinct_titles_plots_and_supported_differences(self):
        search = Mock(return_value=[volume_source(SCHOOL_VOLUME),
                                    *[volume_source(item) for item in SCIENCE_FICTION]])
        result = catalog_fallback('Recomiéndame tres novelas de ciencia ficción y explica sus diferencias', [], search)
        self.assertEqual(len(result.books), 3)
        self.assertNotIn(SCHOOL_VOLUME['volumeInfo']['title'], result.text)
        self.assertEqual(result.intent, 'recommend')
        for item in SCIENCE_FICTION:
            self.assertIn(item['volumeInfo']['title'], result.text)
            self.assertIn(item['volumeInfo']['authors'][0], result.text)
        self.assertEqual(result.text.count('Trama:'), 3)
        self.assertIn('Qué las diferencia', result.text)
        self.assertIn('robots e inteligencia artificial', result.text)
        self.assertIn('viajes en el tiempo', result.text)
        self.assertIn('supervivencia', result.text)
        self.assertIn('podemos seguir por una de estas historias', result.text)
        self.assertNotIn('[1]', result.text)
        self.assertNotIn('ISBN:', result.text)
        self.assertNotIn('Publicación:', result.text)
        self.assertNotIn('Editorial:', result.text)
        self.assertTrue(all(source['synopsis'] for source in result.sources))

    def test_fallback_respects_one_requested_book(self):
        result = catalog_fallback('Recomiéndame una novela de ciencia ficción', [],
                                  Mock(return_value=[volume_source(item) for item in SCIENCE_FICTION]))
        self.assertEqual(len(result.books), 1)

    def test_duplicate_editions_do_not_count_as_different_recommendations(self):
        second = copy.deepcopy(SCIENCE_FICTION[0])
        second['id'] = 'robots_second_edition'
        result = catalog_fallback('Recomiéndame tres novelas de ciencia ficción', [],
                                  Mock(return_value=[volume_source(SCIENCE_FICTION[0]), volume_source(second),
                                                     volume_source(SCIENCE_FICTION[1])]))
        self.assertEqual(len(result.books), 2)
        self.assertIn('dos opciones', result.text)

    def test_missing_synopses_do_not_produce_fake_plots_or_comparisons(self):
        sources = []
        for item in SCIENCE_FICTION[:2]:
            item = copy.deepcopy(item)
            item['volumeInfo'].pop('description')
            sources.append(volume_source(item))
        result = catalog_fallback('Recomiéndame dos novelas de ciencia ficción y explica sus diferencias', [],
                                  Mock(return_value=sources))
        self.assertIn('No encontré una descripción fiable de su trama', result.text)
        self.assertIn('Las sinopsis necesitan más detalle', result.text)
        self.assertNotIn('robots e inteligencia artificial', result.text)

    def test_synopsis_fallback_extracts_old_sources_without_dumping_metadata(self):
        source = volume_source(SCIENCE_FICTION[0])
        source.pop('synopsis')
        result = catalog_fallback('Recomiéndame una novela de ciencia ficción', [], Mock(return_value=[source]))
        self.assertIn('robots e inteligencia artificial', result.text)
        self.assertNotIn('ISBN:', result.text)
        self.assertNotIn('Editorial:', result.text)

    def test_connection_failure_is_explained_without_claiming_quality_failure_is_a_disconnect(self):
        search = Mock(return_value=[volume_source(SCIENCE_FICTION[0])])
        unavailable = catalog_fallback('Recomiéndame una novela de ciencia ficción', [], search,
                                        failure_reason='ollama_no_iniciado')
        quality = catalog_fallback('Recomiéndame una novela de ciencia ficción', [], search,
                                    failure_reason='quality_check_failed')
        self.assertIn('No pude conectar con el chat', unavailable.text)
        self.assertNotIn('No pude conectar', quality.text)


@override_settings(LITMATE_AI_USE_WEB=True)
class MissingSynopsisResearchTests(SimpleTestCase):
    def missing_source(self, item=SCIENCE_FICTION[0]):
        item = copy.deepcopy(item)
        item['volumeInfo'].pop('description')
        return volume_source(item)

    def evidence(self, title='Ciudad de robots', author='Ana Robles'):
        return {'title': title + ' (novela)', 'author': 'Fuente web', 'kind': 'web',
                'source': 'Wikipedia', 'url': 'https://es.wikipedia.org/wiki/Ciudad_de_robots',
                'description': title + ', de ' + author + ', cuenta una convivencia entre humanos y robots.',
                'read_mode': 'extracto de introducción'}

    def test_missing_synopsis_triggers_public_search_and_keeps_attribution_separate(self):
        source = self.missing_source()
        with patch('core.literary_search.retrieve_web', return_value=[self.evidence()]) as research:
            enriched = enrich_book_sources([source], 'Recomiéndame una novela de ciencia ficción')
        research.assert_called_once_with('Ciudad de robots Ana Robles')
        book, web = enriched
        self.assertEqual(book['synopsis'], '')
        self.assertIn('humanos y robots', book['research_summary'])
        self.assertEqual(book['description_source'], 'Wikipedia')
        self.assertEqual(book['synopsis_source_url'], web['url'])
        self.assertNotIn('Sinopsis editorial:', book['research_summary'])

    def test_wrong_title_author_or_untrusted_page_cannot_fill_a_plot(self):
        for web in [self.evidence(title='Otra obra'), self.evidence(author='Un escritor distinto'),
                    {**self.evidence(), 'url': 'https://untrusted.example.test/book'}]:
            with self.subTest(web=web), patch('core.literary_search.retrieve_web', return_value=[web]):
                enriched = enrich_book_sources([self.missing_source()])
            self.assertEqual(len(enriched), 1)
            self.assertNotIn('research_summary', enriched[0])

    def test_existing_synopses_and_reader_private_passages_never_trigger_research(self):
        with patch('core.literary_search.retrieve_web') as research:
            enrich_book_sources([volume_source(SCIENCE_FICTION[0])])
            enrich_book_sources([self.missing_source()], 'Analiza este fragmento privado: una frase personal.')
        research.assert_not_called()

    def test_research_is_bounded_to_two_missing_books(self):
        with patch('core.literary_search.retrieve_web', return_value=[]) as research:
            enriched = enrich_book_sources([self.missing_source(item) for item in SCIENCE_FICTION])
        self.assertEqual(research.call_count, 2)
        self.assertEqual(len(enriched), 3)

    def test_fallback_researches_before_saying_plot_is_unavailable(self):
        with patch('core.literary_search.retrieve_web', return_value=[self.evidence()]) as research:
            result = catalog_fallback('Recomiéndame una novela de ciencia ficción', [],
                                      Mock(return_value=[self.missing_source()]))
        research.assert_called_once()
        self.assertEqual(len(result.sources), 2)
        self.assertIn('humanos y robots', result.text)
        self.assertNotIn('No encontré una descripción fiable de su trama', result.text)
        self.assertEqual(result.sources[0]['description_source'], 'Wikipedia')
        self.assertEqual(result.sources[1]['kind'], 'web')

    def test_fallback_prefers_available_synopsis_without_unnecessary_web_calls(self):
        with patch('core.literary_search.retrieve_web') as research:
            result = catalog_fallback('Recomiéndame una novela de ciencia ficción', [], Mock(return_value=[
                self.missing_source(), volume_source(SCIENCE_FICTION[1])]))
        research.assert_not_called()
        self.assertEqual(result.books[0]['title'], 'El viaje imposible')

    def test_many_catalog_records_do_not_crowd_out_supporting_web_evidence(self):
        sources = [self.missing_source()] + [
            {**volume_source(SCIENCE_FICTION[1]), 'book_id': 'different_' + str(index)} for index in range(7)]
        with patch('core.literary_search.retrieve_web', return_value=[self.evidence()]):
            enriched = canonical_sources(enrich_book_sources(sources), 8)
        self.assertLessEqual(len(enriched), 8)
        self.assertTrue(any(source['kind'] == 'web' for source in enriched))
        self.assertEqual(enriched[0]['description_source'], 'Wikipedia')

    def test_failed_extra_search_is_explained_and_does_not_invent_a_plot(self):
        with patch('core.literary_search.retrieve_web', return_value=[]) as research:
            result = catalog_fallback('Recomiéndame una novela de ciencia ficción', [],
                                      Mock(return_value=[self.missing_source()]))
        research.assert_called_once()
        self.assertIn('Busqué también información sobre esta obra', result.text)
        self.assertNotIn('conviven con humanos', result.text)


class MissingBibliographicMetadataTests(SimpleTestCase):
    def test_missing_field_fetches_the_exact_volume_before_returning_an_answer(self):
        source = volume_source(VOLUME)
        source['page_count'] = None
        with patch('core.ai_catalog_fallback.get_volume', return_value=VOLUME) as fetch:
            result = bibliographic_answer('¿Cuántas páginas tiene «Matar un ruiseñor»?', [],
                                          Mock(return_value=[source]))
        fetch.assert_called_once_with('books_test_1', use_cache=True)
        self.assertIn('336 páginas', result.text)
        self.assertEqual(result.sources[0]['book_id'], 'books_test_1')

    def test_missing_detail_still_routes_to_model_and_web_instead_of_stopping_at_unknown(self):
        source = volume_source(VOLUME)
        source['page_count'] = None
        with patch('core.ai_catalog_fallback.get_volume', side_effect=BooksUnavailable('unavailable')):
            self.assertIsNone(bibliographic_answer('¿Cuántas páginas tiene «Matar un ruiseñor»?', [],
                                                  Mock(return_value=[source])))

    def test_other_edition_cannot_fill_requested_page_count(self):
        source = volume_source(VOLUME)
        source['page_count'] = None
        other = copy.deepcopy(VOLUME)
        other['id'] = 'other_edition'
        other['volumeInfo']['pageCount'] = 999
        with patch('core.ai_catalog_fallback.get_volume', return_value=other):
            self.assertIsNone(bibliographic_answer('¿Cuántas páginas tiene «Matar un ruiseñor»?', [],
                                                  Mock(return_value=[source])))


class DirectedWikipediaRetrievalTests(SimpleTestCase):
    INTRODUCTION = 'Horizonte, de Elena Torres, es una novela que fue publicada en 2001. '
    CHARACTERS = ('== Personajes ==\nNora: protagonista que investiga la desaparición de su hermano.\n'
                  'Esteban: hermano de Nora y personaje cuya ausencia da comienzo a la historia.\n'
                  'Teresa: madre de ambos y guardiana de los recuerdos familiares.\n')

    def test_character_section_wins_over_many_title_mentions_in_introduction(self):
        article = self.INTRODUCTION * 50 + '\n' + self.CHARACTERS + '\n== Publicación ==\nOtros datos editoriales.'
        passage = relevant_passage(article, 'Horizonte Elena Torres personajes principales descripción')
        self.assertIn('Nora:', passage)
        self.assertIn('Esteban:', passage)
        self.assertIn('Teresa:', passage)
        self.assertNotIn('publicada en 2001', passage)
        self.assertNotIn('Otros datos editoriales', passage)
        self.assertLessEqual(len(passage), 1800)

    def test_character_descriptions_skip_long_prefaces_and_keep_subsections(self):
        article = ('== Personajes ==\n\nLa historia del grupo y su ciudad ocupa un largo prefacio. ' * 35
                   + '\n\n=== Familia ===\n' + 'La historia familiar precede a las fichas. ' * 25
                   + '\n\nNora, protagonista e investigadora.\n'
                     'Esteban, hermano de Nora y personaje desaparecido.\n'
                     'Teresa, madre de Nora y Esteban.\n\n== Ediciones ==\nDatos de ediciones.')
        passage = relevant_passage(article, '"Horizonte" Elena Torres personajes principales')
        self.assertIn('Nora, protagonista', passage)
        self.assertIn('Esteban, hermano de Nora', passage)
        self.assertIn('Teresa, madre', passage)
        self.assertNotIn('largo prefacio', passage)
        self.assertNotIn('Datos de ediciones', passage)

    def test_wikipedia_details_fetch_full_article_without_exintro_or_exchars(self):
        intro = {'query': {'pages': {'42': {'pageid': 42, 'title': 'Horizonte (novela)',
                  'extract': self.INTRODUCTION, 'fullurl': 'https://es.wikipedia.org/wiki/Horizonte'}}}}
        full = {'query': {'pages': {'42': {**intro['query']['pages']['42'],
                 'extract': self.INTRODUCTION * 50 + '\n' + self.CHARACTERS}}}}
        with patch('core.literary_search.read_json_url', side_effect=[intro, full]) as fetch:
            sources = search_wikipedia('"Horizonte" Elena Torres personajes principales descripción')
        self.assertEqual(fetch.call_count, 2)
        search_params = parse_qs(urlsplit(fetch.call_args_list[0].args[0]).query)
        detail_params = parse_qs(urlsplit(fetch.call_args_list[1].args[0]).query)
        self.assertNotIn('personajes', search_params['gsrsearch'][0])
        self.assertEqual(search_params['gsrnamespace'], ['0|104'])
        self.assertEqual(detail_params['pageids'], ['42'])
        self.assertNotIn('exintro', detail_params)
        self.assertNotIn('exchars', detail_params)
        self.assertEqual(detail_params['exsectionformat'], ['wiki'])
        self.assertIn('Nora:', sources[0]['description'])
        self.assertIn('sección', sources[0]['read_mode'])

    def test_failed_full_article_keeps_honest_intro_label(self):
        intro = {'query': {'pages': {'42': {'pageid': 42, 'title': 'Horizonte (novela)',
                  'extract': self.INTRODUCTION, 'fullurl': 'https://es.wikipedia.org/wiki/Horizonte'}}}}
        with patch('core.literary_search.read_json_url', side_effect=[intro, URLError('fuente temporalmente caída')]):
            sources = search_wikipedia('Horizonte Elena Torres personajes')
        self.assertEqual(sources[0]['description'], self.INTRODUCTION)
        self.assertEqual(sources[0]['read_mode'], 'extracto de introducción')

    def test_general_query_does_not_fetch_an_entire_article(self):
        intro = {'query': {'pages': {'42': {'pageid': 42, 'title': 'Horizonte (novela)',
                  'extract': self.INTRODUCTION, 'fullurl': 'https://es.wikipedia.org/wiki/Horizonte'}}}}
        with patch('core.literary_search.read_json_url', return_value=intro) as fetch:
            sources = search_wikipedia('Horizonte Elena Torres')
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(sources[0]['read_mode'], 'extracto de introducción')


class GoogleBooksDiagnosticTests(SimpleTestCase):
    @override_settings(LITMATE_USE_GOOGLE_BOOKS_API=True, GOOGLE_BOOKS_API_KEY=API_KEY)
    def test_offline_diagnostic_reports_configuration_without_network_or_key(self):
        out = io.StringIO()
        with patch('core.books_google.read_json_url') as books, \
                patch('core.management.commands.diagnosticar_ia.read_json_url') as other, \
                patch('core.local_llm.read_json_url') as ollama:
            call_command('diagnosticar_ia', stdout=out)
        for network in [books, other, ollama]:
            network.assert_not_called()
        self.assertIn('clave configurada', out.getvalue())
        self.assertIn('--books-live', out.getvalue())
        self.assertNotIn(API_KEY, out.getvalue())

    @override_settings(LITMATE_USE_GOOGLE_BOOKS_API=True, GOOGLE_BOOKS_API_KEY='')
    def test_offline_missing_key_has_no_network(self):
        out = io.StringIO()
        with patch('core.books_google.read_json_url') as fetch:
            call_command('diagnosticar_ia', stdout=out)
        fetch.assert_not_called()
        self.assertIn('missing_key', out.getvalue())

    @override_settings(LITMATE_USE_GOOGLE_BOOKS_API=True, GOOGLE_BOOKS_API_KEY=API_KEY)
    def test_books_live_only_checks_books_and_does_not_require_ollama(self):
        out = io.StringIO()
        with patch('core.management.commands.diagnosticar_ia.search_volumes', return_value=[VOLUME]) as books, \
                patch('core.management.commands.diagnosticar_ia.build_assistant') as build, \
                patch('core.management.commands.diagnosticar_ia.read_json_url') as other:
            call_command('diagnosticar_ia', books_live=True, message='ISBN 9780061120084', stdout=out)
        books.assert_called_once_with('isbn:9780061120084', max_results=3)
        build.assert_not_called()
        other.assert_not_called()
        self.assertIn('conexión correcta', out.getvalue())
        self.assertNotIn(API_KEY, out.getvalue())

    @override_settings(LITMATE_USE_GOOGLE_BOOKS_API=False, GOOGLE_BOOKS_API_KEY='')
    def test_books_live_missing_configuration_explains_required_action(self):
        out = io.StringIO()
        with patch('core.books_google.read_json_url') as fetch:
            with self.assertRaisesMessage(CommandError, 'LITMATE_USE_GOOGLE_BOOKS_API=True'):
                call_command('diagnosticar_ia', books_live=True, message='historia', stdout=out)
        fetch.assert_not_called()

    @override_settings(LITMATE_USE_GOOGLE_BOOKS_API=True, GOOGLE_BOOKS_API_KEY=API_KEY)
    def test_books_live_quota_failure_is_safe_and_actionable(self):
        with patch('core.management.commands.diagnosticar_ia.search_volumes',
                   side_effect=BooksUnavailable('quota_exceeded')):
            with self.assertRaises(CommandError) as error:
                call_command('diagnosticar_ia', books_live=True, stdout=io.StringIO())
        self.assertIn('cuotas', str(error.exception))
        self.assertNotIn(API_KEY, str(error.exception))

    def test_books_live_private_excerpt_does_not_query_google(self):
        with patch('core.management.commands.diagnosticar_ia.search_volumes') as fetch:
            with self.assertRaisesMessage(CommandError, 'invalid_query'):
                call_command('diagnosticar_ia', books_live=True, message='fragmento: pasaje privado',
                             stdout=io.StringIO())
        fetch.assert_not_called()

    @override_settings(LITMATE_USE_GOOGLE_BOOKS_API=True, GOOGLE_BOOKS_API_KEY=API_KEY)
    def test_unexpected_network_exception_never_prints_url_with_key(self):
        with patch('core.management.commands.diagnosticar_ia.search_volumes',
                   side_effect=RuntimeError('https://example.test?key=' + API_KEY)):
            with self.assertRaises(CommandError) as error:
                call_command('diagnosticar_ia', books_live=True, stdout=io.StringIO())
        self.assertIn('unavailable', str(error.exception))
        self.assertNotIn(API_KEY, str(error.exception))
