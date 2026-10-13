"""Contrato de tarjetas verificadas y presentación SSE, con datos simulados."""
import copy
import json
from urllib.parse import urlsplit, parse_qs

from django.test import SimpleTestCase

from .ai_presentation import build_book_cards
from .literary_ai import ChatResult, LiteraryAssistant, canonical_sources
from .literary_ai_views import stream_result


SOURCE = {'id': 1, 'title': '1984', 'author': 'George Orwell', 'kind': 'book', 'book_id': 'volume_1984',
          'source': 'Google Books API', 'synopsis': 'Una sociedad vigilada enfrenta a un hombre con el poder.',
          'description': 'Sinopsis editorial: Una sociedad vigilada enfrenta a un hombre con el poder.',
          'image_url': 'https://books.google.com/books/content?id=volume_1984&img=1',
          'url': 'https://books.google.com/books?id=volume_1984',
          'preview_url': 'https://books.google.com/books?id=volume_1984&printsec=frontcover'}
SECOND = {**SOURCE, 'id': 2, 'title': 'El Hobbit', 'author': 'J. R. R. Tolkien', 'book_id': 'volume_hobbit',
          'synopsis': 'Un hobbit sale de su hogar y participa en una aventura inesperada.',
          'url': 'https://books.google.com/books?id=volume_hobbit',
          'preview_url': 'https://books.google.com/books?id=volume_hobbit&printsec=frontcover',
          'image_url': 'https://books.google.com/books/content?id=volume_hobbit&img=1'}


def result(sources=None, books=None, text='**Dos lecturas** para elegir según lo que te apetece.'):
    sources = copy.deepcopy([SOURCE] if sources is None else sources)
    books = copy.deepcopy([{'title': SOURCE['title'], 'author': SOURCE['author'], 'source_id': 1}]
                          if books is None else books)
    return ChatResult(text, 'answered', True, sources, books, 'sources', 'recommend')


class BookCardTests(SimpleTestCase):
    def test_card_has_only_received_metadata_and_explicit_store_search_links(self):
        card = build_book_cards(result())[0]
        self.assertEqual(set(card), {'id', 'title', 'author', 'synopsis', 'image_url', 'links'})
        self.assertEqual(card['id'], 'volume_1984')
        self.assertEqual(card['title'], SOURCE['title'])
        self.assertEqual(card['synopsis'], SOURCE['synopsis'])
        self.assertEqual(card['image_url'], SOURCE['image_url'])
        links = {link['label']: link['url'] for link in card['links']}
        self.assertEqual(links['Google Books'], SOURCE['url'])
        self.assertEqual(urlsplit(links['Amazon']).hostname, 'www.amazon.com')
        self.assertIn('George Orwell', parse_qs(urlsplit(links['Amazon']).query)['k'][0])
        self.assertEqual(urlsplit(links['Buscalibre']).hostname, 'www.buscalibre.cl')
        self.assertNotIn('precio', card)

    def test_card_order_follows_recommendations_instead_of_search_rank(self):
        books = [{'title': SECOND['title'], 'author': SECOND['author'], 'source_id': 2},
                 {'title': SOURCE['title'], 'author': SOURCE['author'], 'source_id': 1}]
        cards = build_book_cards(result([SOURCE, SECOND], books))
        self.assertEqual([card['title'] for card in cards], [SECOND['title'], SOURCE['title']])

    def test_unverified_or_mismatched_model_identity_never_creates_a_card(self):
        for book in ({'title': SOURCE['title'], 'author': SOURCE['author'], 'source_id': 0},
                     {'title': SOURCE['title'], 'author': 'Autor inventado', 'source_id': 1},
                     {'title': 'Libro inventado', 'author': SOURCE['author'], 'source_id': 1}):
            with self.subTest(book=book):
                self.assertEqual(build_book_cards(result(books=[book])), [])

    def test_article_and_unavailable_response_do_not_create_book_cards(self):
        self.assertEqual(build_book_cards(result([{**SOURCE, 'kind': 'web'}])), [])
        unavailable = result()
        unavailable.status = 'unavailable'
        self.assertEqual(build_book_cards(unavailable), [])

    def test_editions_of_same_book_do_not_appear_as_different_recommendations(self):
        other = {**SOURCE, 'id': 2, 'book_id': 'other_edition', 'synopsis': 'Otra sinopsis editorial.'}
        books = [{'title': SOURCE['title'], 'author': SOURCE['author'], 'source_id': 2},
                 {'title': SOURCE['title'], 'author': SOURCE['author'], 'source_id': 1}]
        cards = build_book_cards(result([SOURCE, other], books))
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['id'], 'other_edition')
        self.assertEqual(cards[0]['synopsis'], other['synopsis'])

    def test_unsafe_source_links_and_covers_cannot_enter_card_payload(self):
        for url in ('javascript:alert(1)', 'data:text/html,<script>alert(1)</script>',
                    'https://books.google.com.evil.test/book', 'https://user:password@books.google.com/book'):
            with self.subTest(url=url):
                source = {**SOURCE, 'url': url, 'preview_url': url, 'image_url': url}
                card = build_book_cards(result([source]))[0]
                self.assertEqual(card['image_url'], '')
                self.assertNotIn('Google Books', [link['label'] for link in card['links']])
                self.assertTrue(all(urlsplit(link['url']).scheme == 'https' for link in card['links']))

    def test_missing_cover_and_synopsis_remain_missing_instead_of_being_invented(self):
        source = {key: value for key, value in SOURCE.items() if key not in {'image_url', 'synopsis'}}
        card = build_book_cards(result([source]))[0]
        self.assertEqual(card['image_url'], '')
        self.assertEqual(card['synopsis'], '')

    def test_canonical_sources_preserve_synopsis_and_image_for_card_rendering(self):
        source = canonical_sources([SOURCE])[0]
        self.assertEqual(source['synopsis'], SOURCE['synopsis'])
        self.assertEqual(source['image_url'], SOURCE['image_url'])


class PresentationStreamTests(SimpleTestCase):
    def events(self, response):
        text = b''.join(response.streaming_content).decode('utf-8')
        self.assertTrue(text.endswith('data: [DONE]\n\n'))
        return [json.loads(line[6:]) for line in text.splitlines() if line.startswith('data: {')]

    def test_metadata_event_is_compatible_with_text_only_clients(self):
        expected = result(text='**Una historia** con vigilancia, identidad y resistencia.\nUna opción para conversar.')
        events = self.events(stream_result(expected))
        self.assertEqual(''.join(event['token'] for event in events), expected.text)
        metadata = [event for event in events if 'books' in event]
        self.assertEqual(len(metadata), 1)
        self.assertEqual(metadata[0]['token'], '')
        self.assertEqual(metadata[0]['books'][0]['title'], SOURCE['title'])

    def test_non_book_social_response_emits_text_without_fake_cards(self):
        social = ChatResult('¡Hola! ¿Cómo estás hoy?', 'social')
        events = self.events(stream_result(social))
        self.assertFalse(any('books' in event for event in events))
        self.assertEqual(''.join(event['token'] for event in events), social.text)

    def test_book_recommendation_preserves_markdown_without_reference_dump(self):
        draft = {'status': 'answer', 'basis': 'mixed', 'text': '**1984** ofrece una trama de vigilancia y resistencia [1].',
                 'citations': [1], 'needs_web': False, 'books': result().books}
        published = LiteraryAssistant._publish(draft, [SOURCE], 'recommend', {})
        self.assertIn('**1984**', published.text)
        self.assertNotIn('Referencias bibliográficas', published.text)
        self.assertNotIn('conocimiento del modelo', published.text)
        self.assertEqual(published.sources[0]['title'], SOURCE['title'])
        self.assertTrue(build_book_cards(published))
