"""Espacio narrativo: materia verificable, sin títulos ni autores semilla."""
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from .books_google import book_search_profile, book_topic_profile, rank_book_sources, topic_matches
from .literary_conversation import remember_topic, resolve_topic_context
from .literary_search import search_openlibrary
from .literary_sources import research_scope


REQUEST = 'Si busco recomendaciones de otros libros con temática espacial'
SPACE_BOOK = {'kind': 'book', 'title': 'La nave de las islas', 'author': 'Autora de prueba',
              'categories': ['Fiction', 'Science fiction', 'Interplanetary voyages', 'Space colonies']}


class SpaceTopicRestrictionTests(SimpleTestCase):
    def test_the_actual_request_maps_to_space_and_fiction_not_the_entire_sentence(self):
        profile = book_topic_profile(REQUEST)
        self.assertTrue(profile['structured'])
        self.assertEqual({facet[0] for facet in profile['subjects']}, {'space', 'science fiction'})
        self.assertEqual(profile['query'], 'subject:"space" subject:"science fiction"')
        self.assertTrue(book_search_profile(REQUEST)['fiction'])

    def test_related_narrative_phrasings_preserve_the_space_constraint(self):
        for query in ['Recomiéndame aventuras espaciales', 'Libros de space opera',
                      'Recomiéndame novelas de viajes interplanetarios',
                      'Libros con ambientación espacial']:
            with self.subTest(query=query):
                self.assertTrue(book_search_profile(query)['fiction'])
                self.assertIn('space', {row[0] for row in book_topic_profile(query)['subjects']})
                self.assertTrue(topic_matches(SPACE_BOOK, query))

    def test_generic_science_fiction_is_not_sufficient_evidence_of_space_setting(self):
        dystopia = {'title': 'La ciudad vigilada', 'categories': ['Dystopian fiction', 'Science fiction'],
                    'synopsis': 'Una ciudad terrestre donde se vigila a sus habitantes.'}
        self.assertFalse(topic_matches(dystopia, REQUEST))
        self.assertTrue(topic_matches(dystopia, 'Recomiéndame ciencia ficción'))

    def test_a_real_catalogue_record_needs_both_facets(self):
        astronomy = {'title': 'Exploración espacial', 'categories': ['Astronomy', 'Space exploration', 'Nonfiction']}
        sociology = {'title': 'Sociología espacial', 'categories': ['Social sciences', 'Space']}
        manual = {'title': 'Manual de ciencia ficción espacial',
                  'categories': ['Science fiction', 'Space', 'Literary criticism', 'Nonfiction']}
        for source in (astronomy, sociology, manual):
            with self.subTest(title=source['title']):
                self.assertFalse(topic_matches(source, REQUEST))
        self.assertTrue(topic_matches(SPACE_BOOK, REQUEST))
        self.assertEqual(rank_book_sources([astronomy, sociology, manual, SPACE_BOOK], REQUEST), [SPACE_BOOK])

    def test_explicit_scientific_requests_do_not_become_fiction(self):
        for query in ['Busco libros de divulgación con temática espacial',
                      'Busco libros científicos con temática espacial',
                      'Recomiéndame manuales sobre exploración espacial',
                      'Busco un libro sobre astronomía']:
            with self.subTest(query=query):
                self.assertFalse(book_search_profile(query)['fiction'])
                self.assertNotIn('science fiction', {row[0] for row in book_topic_profile(query)['subjects']})

    def test_the_word_space_alone_is_a_subject_but_not_a_fiction_preference(self):
        self.assertFalse(book_search_profile('Busco libros sobre el espacio')['fiction'])
        profile = book_topic_profile('Busco libros sobre el espacio')
        self.assertTrue(profile['structured'])
        self.assertEqual(profile['query'], 'subject:"space"')

    def test_quoted_titles_are_not_replaced_with_subject_searches(self):
        for query in ('Busco el libro «Temática espacial»', 'intitle:Temática espacial',
                      'ISBN:9780140449136'):
            self.assertFalse(book_topic_profile(query)['structured'])

    def test_an_explicit_exclusion_cannot_be_reactivated_by_the_space_alias(self):
        for exclusion in ('sin ciencia ficción', 'no ciencia ficción',
                          'no quiero ciencia ficción', 'que no sean de ciencia ficción',
                          'excepto ciencia ficción', 'excluye ciencia ficción',
                          'sin novelas de ciencia ficción', 'not science fiction',
                          'excluding science fiction', 'sin sci-fi', 'sin space opera'):
            query = 'Recomiéndame libros con temática espacial ' + exclusion
            with self.subTest(exclusion=exclusion):
                reading = book_search_profile(query)
                self.assertIn('science_fiction', reading['excluded_genres'])
                self.assertIsNone(reading['genre'])
                self.assertFalse(reading['fiction'])
                self.assertEqual(book_topic_profile(query)['query'],
                                 'subject:"space" -subject:"science fiction"')
                self.assertFalse(topic_matches(SPACE_BOOK, query))

    def test_a_scientific_space_request_keeps_its_subject_and_excludes_narrative(self):
        query = 'Busco libros de divulgación con temática espacial sin ciencia ficción'
        science = {'kind': 'book', 'title': 'Exploración del cosmos',
                   'categories': ['Space exploration', 'Astronomy', 'Nonfiction']}
        self.assertTrue(book_search_profile(query)['studies'])
        self.assertTrue(topic_matches(science, query))
        self.assertFalse(topic_matches(SPACE_BOOK, query))
        self.assertEqual(rank_book_sources([SPACE_BOOK, science], query), [science])

    def test_an_allowed_different_genre_is_preserved_alongside_the_exclusion(self):
        query = 'Recomiéndame libros de fantasía con temática espacial sin ciencia ficción'
        fantasy = {'kind': 'book', 'title': 'Dragones entre planetas',
                   'categories': ['Fantasy', 'Fiction', 'Space travel']}
        self.assertEqual(book_search_profile(query)['genre'][0], 'fantasy')
        self.assertTrue(topic_matches(fantasy, query))
        self.assertFalse(topic_matches(SPACE_BOOK, query))

    def test_a_quoted_title_is_not_mistaken_for_a_genre_exclusion(self):
        for query in ('Busco «Sin ciencia ficción»', 'intitle:Sin ciencia ficción'):
            with self.subTest(query=query):
                self.assertEqual(book_search_profile(query)['excluded_genres'], ())


class SpaceTopicMemoryTests(SimpleTestCase):
    def test_a_new_theme_is_not_interpreted_as_more_details_of_the_previous_book(self):
        book = {'title': 'Papelucho y el marciano', 'author': 'Marcela Paz', 'kind': 'book'}
        state = {'turns': [{'accepted': True, 'books': [book], 'sources': [book]}], 'active_work': book}
        context = resolve_topic_context(REQUEST, state, now=1000)
        self.assertEqual(context['subject'], 'temática espacial')
        self.assertTrue(context['reset_work_context'])
        self.assertEqual(context['intent'], 'recommend')
        self.assertNotIn('Papelucho', context['query'])
        self.assertTrue(book_search_profile(context['query'])['fiction'])
        remember_topic(state, REQUEST, context, now=1000)
        self.assertNotIn('active_work', state)
        self.assertEqual(len(state['turns']), 1)

    def test_the_next_elliptical_request_keeps_the_confirmed_topic_request(self):
        state = {'turns': []}
        remember_topic(state, REQUEST, now=1000)
        context = resolve_topic_context('Recomiéndame otros dos', state, now=1001)
        self.assertEqual(context['subject'], 'temática espacial')
        self.assertTrue(context['followup'])
        self.assertTrue(topic_matches(SPACE_BOOK, context['query']))
        self.assertEqual(book_topic_profile(context['query'])['query'],
                         'subject:"space" subject:"science fiction"')

    def test_themed_words_do_not_allow_private_material_into_topic_memory(self):
        state = {'turns': []}
        remember_topic(state, REQUEST + ' mi contraseña es secreto123', now=1000)
        self.assertNotIn('topic', state)


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                     'LOCATION': 'space-topic-catalogue'}})
class OpenLibrarySpaceTopicTests(SimpleTestCase):
    def test_search_uses_both_subjects_and_preserves_real_metadata_provenance(self):
        cache.clear()
        requests = []
        def fetch(url, **kwargs):
            requests.append(url)
            if '/search.json?' in url:
                return {'docs': [
                    {'key': '/works/OL1001W', 'title': 'La nave de las islas',
                     'author_name': ['Autora de prueba'], 'subject': SPACE_BOOK['categories']},
                    {'key': '/works/OL1002W', 'title': 'Sociología espacial',
                     'author_name': ['Autor de otro ámbito'], 'subject': ['Space', 'Social sciences']},
                    {'key': '/works/OL1003W', 'title': 'Guía de astronomía',
                     'author_name': ['Autora científica'], 'subject': ['Space', 'Astronomy', 'Nonfiction']},
                ]}
            return {'key': '/works/OL1001W'}
        with patch('core.literary_search._openlibrary_fetch', side_effect=fetch), research_scope(2, 15, 3):
            sources = search_openlibrary(REQUEST)
        query = parse_qs(urlsplit(requests[0]).query)['q'][0]
        self.assertEqual(query, 'subject:"space" subject:"science fiction"')
        self.assertEqual([source['title'] for source in sources], [SPACE_BOOK['title']])
        self.assertEqual(sources[0]['author'], SPACE_BOOK['author'])
        self.assertEqual(sources[0]['url'], 'https://openlibrary.org/works/OL1001W')
        self.assertEqual(sources[0]['source'], 'Open Library')

    def test_negative_genre_is_sent_to_the_catalogue_and_checked_again_locally(self):
        cache.clear()
        requests = []
        def fetch(url, **kwargs):
            requests.append(url)
            if '/search.json?' in url:
                return {'docs': [
                    {'key': '/works/OL1001W', 'title': 'La nave de las islas',
                     'author_name': ['Autora narrativa'], 'subject': SPACE_BOOK['categories']},
                    {'key': '/works/OL1002W', 'title': 'Exploración del cosmos',
                     'author_name': ['Autora científica'],
                     'subject': ['Space exploration', 'Astronomy', 'Nonfiction']},
                ]}
            return {'key': '/works/OL1002W'}
        query = 'Busco libros de divulgación con temática espacial sin ciencia ficción'
        with patch('core.literary_search._openlibrary_fetch', side_effect=fetch), research_scope(2, 15, 3):
            sources = search_openlibrary(query)
        actual_query = parse_qs(urlsplit(requests[0]).query)['q'][0]
        self.assertEqual(actual_query, 'subject:"space" -subject:"science fiction"')
        self.assertEqual([source['title'] for source in sources], ['Exploración del cosmos'])
        self.assertEqual(sources[0]['url'], 'https://openlibrary.org/works/OL1002W')
