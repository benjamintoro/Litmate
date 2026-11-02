"""Recomendaciones son fichas, no artículos: proveedores de prueba, sin red."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase, override_settings

from .ai_presentation import build_book_cards
from .ai_quick_answers import _simple_topic_request, quick_answer
from .literary_ai import ChatResult, LiteraryAssistant
from .literary_focus import prepare_focus, remember_focus
from .literary_ai_views import _compute_answer_impl, stream_result


QUESTION = 'Hola, recomiéndame libros sobre la historia de Colombia'
# Datos controlados de un catálogo simulado; no se incorporan a producción.
BOOK = {'kind': 'book', 'source': 'Open Library', 'title': 'Colombia, una nación a pesar de sí misma',
        'author': 'David Bushnell', 'url': 'https://openlibrary.org/works/OL123W',
        'description': 'Temas del catálogo: Colombia; History.', 'categories': ['Colombia', 'History'],
        'image_url': 'https://covers.openlibrary.org/b/id/123-M.jpg'}
ARTICLE = {'kind': 'web', 'source': 'SearXNG', 'title': '7 libros para entender la historia de Colombia',
           'author': 'Fuente web', 'url': 'https://example.org/lista',
           'description': 'Siete libros sobre Colombia y su historia.', 'read_mode': 'fragmento del buscador'}


class OverlappingTopicSpansTests(SimpleTestCase):
    def test_open_library_cards_offer_an_explicit_google_books_search(self):
        from urllib.parse import urlsplit, parse_qs
        with patch('core.ai_quick_answers._bundled', return_value=[]):
            result = quick_answer(QUESTION, search=lambda query: [deepcopy(BOOK)])
        links = {link['label']: link['url'] for link in build_book_cards(result)[0]['links']}
        self.assertIn('Google Books', links)
        query = parse_qs(urlsplit(links['Google Books']).query)
        self.assertEqual(query['q'], [BOOK['title'] + ' ' + BOOK['author']])
        self.assertNotIn('id', query)
    def test_natural_novel_requests_keep_their_documented_genre(self):
        from .books_google import book_topic_profile
        profile = book_topic_profile('Quiero cinco novelas de terror')
        self.assertTrue(profile['structured'])
        self.assertIn('horror', [row[0] for row in profile['subjects']])
        self.assertFalse(_simple_topic_request('Quiero cinco novelas de terror psicológico',
                                              'Quiero cinco novelas de terror psicológico'))
    def test_all_original_topic_spans_are_consumed_together(self):
        for query in (QUESTION, 'Recomiéndame libros sobre historia de Argentina'):
            with self.subTest(query=query):
                self.assertTrue(_simple_topic_request(query, query))

    def test_unknown_restrictions_still_require_the_full_pipeline(self):
        for query in ('Recomiéndame libros sobre submarinos de la Segunda Guerra Mundial',
                      'Recomiéndame libros sobre historia de Venezuela',
                      QUESTION + ' publicados en 2025', QUESTION + ' y explica sus diferencias'):
            with self.subTest(query=query):
                self.assertFalse(_simple_topic_request(query, query))

    def test_catalogue_books_are_verified_and_emit_cards_in_sse(self):
        with patch('core.ai_quick_answers._bundled', return_value=[]):
            result = quick_answer(QUESTION, search=lambda query: [ARTICLE, deepcopy(BOOK)])
        self.assertIsNotNone(result)
        self.assertEqual(result.intent, 'recommend')
        cards = build_book_cards(result)
        self.assertEqual([card['title'] for card in cards], [BOOK['title']])
        self.assertNotIn(ARTICLE['title'], result.text)
        raw = b''.join(stream_result(result).streaming_content).decode('utf-8')
        events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith('data: {')]
        self.assertEqual(next(row['books'] for row in events if row.get('books')), cards)


@override_settings(LITMATE_AI_QUICK_ANSWERS=True, LITMATE_AI_USE_WEB=True,
                   LITMATE_AI_BIBLIOGRAPHIC_FAST_PATH=False)
class RecommendationRoutingCardsTests(SimpleTestCase):
    def test_article_only_recommendation_is_not_reusable_from_answer_cache(self):
        from .ai_answer_cache import _validate
        from .ai_quick_answers import reference_answer
        reference = reference_answer(QUESTION, [ARTICLE])
        self.assertIsNotNone(reference)  # Legacy helper alone still formats sources.
        self.assertFalse(_validate(QUESTION, reference))
    def test_normal_generation_cannot_publish_an_article_only_recommendation(self):
        from .test_web_search import WebOnlyAssistantTests
        for invented in (False, True):
            with self.subTest(invented=invented):
                assistant, _ = WebOnlyAssistantTests().build(invented=invented)
                with patch('core.literary_knowledge.search_knowledge', return_value=[]):
                    result = assistant.reply('recomiendame libros sobre la revolucion francesa')
                self.assertNotEqual(result.status, 'answered')
                self.assertEqual(build_book_cards(result), [])
    @override_settings(LITMATE_AI_CATALOG_FALLBACK=False)
    def test_non_simple_model_failure_does_not_publish_background_search_articles(self):
        from .literary_ai_views import _model_answer
        assistant = SimpleNamespace(reply=lambda *args, **kwargs: ChatResult('Sin libros verificados.', 'unavailable'))
        provider = SimpleNamespace(usage={}, calls=1, provider='fixture')
        with patch('core.literary_search.retrieve_web', return_value=[ARTICLE]), \
             patch('core.literary_ai_views.build_assistant', return_value=(assistant, provider)), \
             patch('core.ai_quick_answers.reference_answer', return_value=ChatResult(
                 'Artículos publicados como recomendaciones.', 'answered')) as references:
            result, _ = _model_answer('Quiero cinco novelas de terror psicológico', [], {},
                                     'Quiero cinco novelas de terror psicológico')
        references.assert_not_called()
        self.assertEqual(result.status, 'unavailable')
    def call(self, message, found):
        with patch('core.ai_character_answers.character_answer', return_value=None), \
             patch('core.ai_persistent_router.indexed_answer', return_value=None), \
             patch('core.ai_narrative_answers.narrative_answer', return_value=None), \
             patch('core.ai_persistent_router.research_answer', return_value=None), \
             patch('core.ai_quick_answers.isbn_lookup_answer', return_value=None), \
             patch('core.ai_quick_answers._bundled', return_value=[]), \
             patch('core.literary_search.retrieve_discovery_books', return_value=found) as discovery, \
             patch('core.ai_quick_answers.web_reference_answer', return_value=ChatResult(
                 'Encontré estas referencias relacionadas con tu consulta', 'answered', sources=[ARTICLE])) as web, \
             patch('core.literary_ai_views._model_answer', return_value=(
                 ChatResult('No pude confirmar libros con esos filtros.', 'unavailable'),
                 SimpleNamespace(calls=0, usage={}, provider='fixture-model'))) as model:
            result, client = _compute_answer_impl(message, [], {})
        return result, discovery, web, model

    def test_reported_query_reaches_catalogue_before_web_articles(self):
        result, discovery, web, model = self.call(QUESTION, [deepcopy(BOOK)])
        self.assertEqual(result.intent, 'recommend')
        self.assertEqual(len(build_book_cards(result)), 1)
        discovery.assert_called_once()
        web.assert_not_called()
        model.assert_not_called()

    def test_an_unknown_qualifier_does_not_publish_article_lists(self):
        result, _, web, model = self.call('Quiero cinco novelas de terror psicológico', [])
        self.assertNotIn('referencias relacionadas', result.text)
        web.assert_not_called()
        model.assert_called_once()

    def test_failed_model_does_not_turn_recommendations_into_article_lists(self):
        assistant = LiteraryAssistant(lambda *args: None, lambda query: [])
        result = assistant._web_reference_fallback([ARTICLE], 'recommend', {}, message=QUESTION)
        self.assertIsNone(result)


class RecommendationFocusCardsTests(SimpleTestCase):
    def test_recommendations_preserve_active_and_previous_work(self):
        for count in (1, 2):
            with self.subTest(count=count):
                active = {'title': 'Frankenstein', 'author': 'Mary Shelley'}
                previous = {'title': 'Rayuela', 'author': 'Julio Cortázar'}
                state = {'turns': [], 'active_work': dict(active), 'previous_work': dict(previous)}
                prepare_focus(state, QUESTION)
                cards = [deepcopy(BOOK)]
                if count == 2:
                    cards.append({**BOOK, 'title': 'Otra historia documentada', 'author': 'Autora de prueba'})
                turn = {'question': QUESTION, 'intent': 'recommend', 'books': cards, 'sources': cards}
                remember_focus(state, turn)
                self.assertEqual(state['active_work'], active)
                self.assertEqual(state['previous_work'], previous)
                self.assertEqual(turn['books'], cards)

    def test_recommendation_without_prior_focus_does_not_pick_first_book(self):
        state = {'turns': []}
        prepare_focus(state, QUESTION)
        remember_focus(state, {'question': QUESTION, 'intent': 'recommend', 'books': [BOOK], 'sources': [BOOK]})
        self.assertNotIn('active_work', state)

    def test_explicit_selection_uses_recommended_cards_without_losing_active_work(self):
        from .literary_identity import resolve_followup_context
        active = {'title': 'Frankenstein', 'author': 'Mary Shelley'}
        second = {**BOOK, 'title': 'Otra historia documentada', 'author': 'Autora de prueba'}
        state = {'turns': [], 'active_work': active}
        turn = {'accepted': True, 'question': QUESTION, 'intent': 'recommend',
                'books': [BOOK, second], 'sources': [BOOK, second]}
        remember_focus(state, turn)
        state['turns'].append(turn)
        resolved = resolve_followup_context('¿Quién escribió el segundo libro?', state['turns'])
        self.assertEqual(resolved['books'][0]['title'], second['title'])
        prepare_focus(state, 'Háblame del segundo libro')
        self.assertEqual(state['active_work']['title'], second['title'])
        self.assertEqual(state['previous_work']['title'], active['title'])


@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies',
                   LITMATE_AI_QUICK_ANSWERS=False, LITMATE_USE_EXISTING_QUOTAS=False)
class RecommendationCardsTransportTests(TestCase):
    def test_single_suggestion_is_not_promoted_to_active_work_on_the_next_request(self):
        from django.core.cache import cache
        from .literary_ai_views import HISTORY_KEY
        cache.clear()
        with patch('core.ai_quick_answers._bundled', return_value=[]):
            recommended = quick_answer(QUESTION, search=lambda query: [deepcopy(BOOK)])
        client = Client()
        provider = SimpleNamespace(calls=0, usage={}, provider='fixture')
        with patch('core.literary_ai_views._compute_answer', return_value=(recommended, provider)), \
             patch('core.literary_ai_views.rate_allowed', return_value=True):
            for _ in range(2):
                response = client.post('/chatbot_query/', json.dumps({'message': QUESTION}),
                                       content_type='application/json')
                self.assertEqual(response.status_code, 200)
                b''.join(response.streaming_content)
                self.assertNotIn('active_work', client.session[HISTORY_KEY])

    def test_regular_and_progressive_sse_deliver_the_same_cards_and_preserve_focus(self):
        from django.core.cache import cache
        from .literary_ai_views import HISTORY_KEY
        cache.clear()
        active = {'kind': 'book', 'source': 'Open Library', 'title': 'Frankenstein',
                  'author': 'Mary Shelley', 'url': 'https://openlibrary.org/works/OL1W', 'id': 1}
        with patch('core.ai_quick_answers._bundled', return_value=[]):
            recommended = quick_answer(QUESTION, search=lambda query: [deepcopy(BOOK)])
        expected = build_book_cards(recommended)

        def compute(message, *args, **kwargs):
            result = deepcopy(recommended) if message == QUESTION else ChatResult(
                'Una novela de Mary Shelley.', 'answered', True, sources=[active],
                books=[{'title': active['title'], 'author': active['author'], 'source_id': 1}],
                basis='sources', intent='summary')
            return result, SimpleNamespace(calls=0, usage={}, provider='fixture')

        for progressive in (False, True):
            with self.subTest(progressive=progressive), \
                 patch('core.literary_ai_views._compute_answer', side_effect=compute), \
                 patch('core.literary_ai_views.rate_allowed', return_value=True):
                client = Client()
                for message in ('Háblame de Frankenstein', QUESTION):
                    response = client.post('/chatbot_query/', json.dumps(
                        {'message': message, 'progress': progressive}), content_type='application/json')
                    self.assertEqual(response.status_code, 200)
                    raw = b''.join(response.streaming_content).decode('utf-8')
                    self.assertIn('data: [DONE]', raw)
                    events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith('data: {')]
                    if progressive:
                        ready = next(event['ready'] for event in events if event.get('ready'))
                        final = client.post('/chatbot_finalize/', json.dumps({'ready': ready}),
                                            content_type='application/json')
                        self.assertEqual(final.status_code, 200)
                        received = final.json()['books']
                    else:
                        received = next(event['books'] for event in events if event.get('books'))
                self.assertEqual(received, expected)
                state = client.session[HISTORY_KEY]
                self.assertEqual(state['active_work']['title'], active['title'])
                self.assertEqual(state['turns'][-1]['intent'], 'recommend')
                self.assertEqual(state['turns'][-1]['books'][0]['title'], BOOK['title'])
