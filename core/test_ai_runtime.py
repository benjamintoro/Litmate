"""Regresiones offline del runtime local y del respaldo bibliográfico de la IA."""
import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase, override_settings

from .ai_concurrency import acquire, release, rate_increment
from .ai_catalog_fallback import bibliographic_answer, catalog_fallback
from .literary_ai import ChatResult
from .literary_evidence import validate_evidence


GOOGLE_BOOK = {
    'title': '1984', 'author': 'George Orwell', 'year': '1949',
    'description': 'Editorial: Penguin. Sinopsis editorial: Una sociedad sometida a vigilancia.',
    'source': 'Google Books API', 'book_id': 'volume_1984', 'kind': 'book',
    'url': 'https://books.google.com/books?id=volume_1984',
    'publisher': 'Penguin', 'read_mode': 'ficha y sinopsis bibliográfica',
}
FULL_METADATA = {**GOOGLE_BOOK, 'page_count': 328, 'published_date': '2003-05-06', 'year': '2003',
                 'isbns': ['9780451524935'], 'preview_url': 'https://books.google.com/books?id=volume_1984&printsec=frontcover'}


class SQLiteCoordinationTests(SimpleTestCase):
    """SQLite propio del test; no usa las tablas ni la base del proyecto."""

    def setUp(self):
        folder = Path(settings.BASE_DIR) / '.testtmp'
        folder.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='ia-runtime-', dir=folder)
        self.addCleanup(temporary.cleanup)
        self.runtime_path = Path(temporary.name) / 'runtime.sqlite3'
        override = override_settings(LITMATE_AI_LOCK_BACKEND='sqlite',
                                     LITMATE_AI_RUNTIME_DB=self.runtime_path)
        override.enable()
        self.addCleanup(override.disable)

    def test_competing_threads_obtain_only_one_global_lease(self):
        tokens = ['request-' + str(index) for index in range(16)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda token: acquire('inference', token, 60), tokens))
        self.assertEqual(sum(results), 1)
        owner = tokens[results.index(True)]
        release('inference', 'another-request')
        self.assertFalse(acquire('inference', 'unexpected-owner', 60))
        release('inference', owner)
        self.assertTrue(acquire('inference', 'next-owner', 60))

    def test_old_owner_cannot_release_a_replacement_after_expiry(self):
        with patch('core.ai_concurrency.time.time', return_value=100):
            self.assertTrue(acquire('inference', 'old-owner', 1))
        with patch('core.ai_concurrency.time.time', return_value=102):
            self.assertTrue(acquire('inference', 'new-owner', 60))
            release('inference', 'old-owner')
            self.assertFalse(acquire('inference', 'third-owner', 60))
            release('inference', 'new-owner')
            self.assertTrue(acquire('inference', 'third-owner', 60))

    def test_counter_increments_are_not_lost_between_threads(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            counts = list(pool.map(lambda _: rate_increment('rate:user-hash', 120), range(24)))
        self.assertEqual(sorted(counts), list(range(1, 25)))

    def test_counter_resets_after_its_window_expires(self):
        with patch('core.ai_concurrency.time.time', return_value=100):
            self.assertEqual(rate_increment('rate:user-hash', 2), 1)
            self.assertEqual(rate_increment('rate:user-hash', 2), 2)
        with patch('core.ai_concurrency.time.time', return_value=103):
            self.assertEqual(rate_increment('rate:user-hash', 2), 1)


class BibliographicFallbackTests(SimpleTestCase):
    def test_numeric_book_title_is_a_searchable_fallback(self):
        search = Mock(return_value=[GOOGLE_BOOK])
        result = catalog_fallback('Háblame del libro «1984»', [], search)
        self.assertIsNotNone(result)
        self.assertEqual(search.call_args.args[0], '1984')
        self.assertEqual(result.books[0]['author'], 'George Orwell')
        self.assertIn('sinopsis', result.text)
        self.assertNotIn('no está disponible', result.text)
        self.assertNotIn('Editorial:', result.text)
        self.assertNotIn('capítulo 1', result.text)

    def test_private_passage_never_triggers_fallback_search(self):
        search = Mock()
        self.assertIsNone(catalog_fallback(
            'Analiza este fragmento: La biblioteca conservaba los recuerdos de una familia de lectores.', [], search))
        search.assert_not_called()

    def test_exact_chapter_question_does_not_become_a_bibliographic_answer(self):
        search = Mock()
        self.assertIsNone(catalog_fallback('Resume el capítulo 3 del libro 1984', [], search))
        search.assert_not_called()

    def test_private_passage_with_qualified_marker_never_triggers_search(self):
        search = Mock(return_value=[GOOGLE_BOOK])
        result = catalog_fallback('Analiza este fragmento de ficción: '
                                  'La biblioteca conservaba un cuaderno de recuerdos familiares.', [], search)
        self.assertIsNone(result)
        search.assert_not_called()

    def test_failed_catalog_or_non_google_source_keeps_unavailable_state(self):
        self.assertIsNone(catalog_fallback('Recomienda libros de Orwell', [], Mock(side_effect=TimeoutError)))
        source = {**GOOGLE_BOOK, 'source': 'Catálogo LitMate'}
        self.assertIsNone(catalog_fallback('Recomienda libros de Orwell', [], Mock(return_value=[source])))


class EvidenceTitleTests(SimpleTestCase):
    def draft(self, text):
        return {'status': 'answer', 'text': text, 'basis': 'knowledge', 'citations': [],
                'needs_web': False, 'books': [{'title': 'Historia de Chile', 'author': 'Autor de prueba', 'source_id': 0}]}

    def test_recommended_title_in_quotes_is_not_a_passage_from_the_book(self):
        validate_evidence(self.draft('Una opción de lectura es "Historia de Chile", de Autor de prueba.'),
                          [], 'Recomienda un libro de historia de Chile')

    def test_short_narrative_quote_still_requires_literal_evidence(self):
        with self.assertRaises(ValueError):
            validate_evidence(self.draft('El narrador escribe "El pasado nunca termina".'), [], 'Analiza el libro')

    def test_title_cannot_replace_the_requested_exact_quote(self):
        with self.assertRaises(ValueError):
            validate_evidence(self.draft('La cita textual es "Historia de Chile".'), [], 'Dame una cita textual del libro')


class BibliographicFastPathTests(SimpleTestCase):
    def history(self, books):
        return [{'accepted': True, 'question': 'Libros para leer', 'answer': 'Estas son las obras.',
                 'books': books, 'sources': []}]

    def test_fields_are_copied_from_received_edition_and_reference_is_included(self):
        result = bibliographic_answer('¿Quién escribió «1984», cuántas páginas tiene, en qué año se publicó, '
                                      'cuál es la editorial, ISBN y vista previa?', [], Mock(return_value=[FULL_METADATA]))
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'answered')
        for value in ('George Orwell', '328 páginas', '2003-05-06', 'Penguin', '9780451524935'):
            self.assertIn(value, result.text)
        self.assertEqual(result.sources[0]['preview_url'], FULL_METADATA['preview_url'])
        self.assertEqual(result.sources[0]['url'], FULL_METADATA['url'])
        self.assertNotIn('Referencia:', result.text)
        self.assertEqual(result.books[0]['source_id'], result.sources[0]['id'])
        self.assertTrue(result.diagnostics['bibliographic_fast_path'])

    def test_non_google_catalog_data_does_not_enter_fast_path(self):
        source = {**FULL_METADATA, 'source': 'Catálogo LitMate'}
        self.assertIsNone(bibliographic_answer('¿Cuántas páginas tiene «1984»?', [], Mock(return_value=[source])))

    def test_missing_fields_are_declared_and_never_generated(self):
        source = {'title': 'Libro de prueba', 'author': '', 'kind': 'book', 'book_id': 'missing_metadata',
                  'source': 'Google Books API', 'url': 'https://books.google.com/books?id=missing_metadata'}
        result = bibliographic_answer('¿Quién escribió «Libro de prueba», cuántas páginas tiene, en qué año '
                                      'se publicó, cuál es la editorial, ISBN y vista previa?', [], Mock(return_value=[source]))
        # Un fast path sin los datos pedidos deja continuar al motor y su búsqueda.
        self.assertIsNone(result)

    def test_different_editions_do_not_combine_page_count_and_publication(self):
        other = {**FULL_METADATA, 'book_id': 'another_edition', 'page_count': 246, 'published_date': '1995-01-01',
                 'year': '1995', 'publisher': 'Otra editorial', 'url': 'https://books.google.com/books?id=another_edition'}
        result = bibliographic_answer('¿Cuántas páginas tiene «1984» y en qué año se publicó?', [],
                                      Mock(return_value=[FULL_METADATA, other]))
        self.assertIsNotNone(result)
        # The answer may ask for an edition or explicitly report one received edition.
        if result.status == 'answered':
            source = result.sources[0]
            self.assertIn(str(source['page_count']), result.text)
            self.assertIn(source['published_date'], result.text)
            self.assertFalse('328' in result.text and '1995-01-01' in result.text)
        else:
            self.assertEqual(result.status, 'clarification')

    def test_isbn_in_message_selects_that_edition_even_when_title_is_quoted(self):
        def edition(query):
            return [FULL_METADATA] if '9780451524935' in query else [{**FULL_METADATA, 'page_count': 246}]
        search = Mock(side_effect=edition)
        result = bibliographic_answer('¿Cuántas páginas tiene «1984», ISBN 9780451524935?', [], search)
        self.assertIsNotNone(result)
        self.assertIn('9780451524935', search.call_args.args[0])
        self.assertIn('328 páginas', result.text)

    def test_followup_ordinal_keeps_selected_book_identity(self):
        hobbit = {**FULL_METADATA, 'title': 'El Hobbit', 'author': 'J. R. R. Tolkien', 'book_id': 'hobbit', 'page_count': 310}
        search = Mock(return_value=[hobbit])
        result = bibliographic_answer('¿Cuántas páginas tiene el segundo?', self.history([GOOGLE_BOOK, hobbit]), search)
        self.assertIsNotNone(result)
        self.assertIn('El Hobbit', search.call_args.args[0])
        self.assertIn('J. R. R. Tolkien', result.text)

    def test_followup_this_book_uses_the_single_book_from_history(self):
        search = Mock(return_value=[FULL_METADATA])
        result = bibliographic_answer('¿Quién es el autor de este libro?', self.history([GOOGLE_BOOK]), search)
        self.assertIsNotNone(result)
        self.assertIn('1984', search.call_args.args[0])
        self.assertIn('lo escribió **George Orwell**', result.text)

    def test_ambiguous_followup_does_not_choose_first_recommendation_silently(self):
        other = {**FULL_METADATA, 'title': 'El Hobbit', 'author': 'J. R. R. Tolkien'}
        search = Mock()
        result = bibliographic_answer('¿Quién es el autor de este libro?', self.history([GOOGLE_BOOK, other]), search)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'clarification')
        search.assert_not_called()

    def test_nonmatching_isbn_cannot_be_reported_as_the_requested_edition(self):
        result = bibliographic_answer('¿Cuántas páginas tiene «1984», ISBN 9780141036144?', [],
                                      Mock(return_value=[FULL_METADATA]))
        self.assertIsNone(result)

    def test_request_words_inside_quoted_title_do_not_disable_metadata_answer(self):
        book = {**FULL_METADATA, 'title': 'Como agua para chocolate', 'author': 'Laura Esquivel',
                'book_id': 'agua', 'page_count': 256}
        result = bibliographic_answer('¿Cuántas páginas tiene «Como agua para chocolate»?', [], Mock(return_value=[book]))
        self.assertIsNotNone(result)
        self.assertIn('256 páginas', result.text)

    def test_same_title_with_different_authors_requires_clarification(self):
        other = {**FULL_METADATA, 'author': 'Otro autor', 'book_id': 'same_title_other_author'}
        result = bibliographic_answer('¿Quién escribió «1984»?', [], Mock(return_value=[FULL_METADATA, other]))
        self.assertEqual(result.status, 'clarification')
        self.assertIn('George Orwell', result.text)
        self.assertIn('Otro autor', result.text)

    def test_content_and_mixed_tasks_keep_full_model_review(self):
        for message in ('¿Quién escribió «1984» y analiza sus personajes?',
                        '¿Quién escribió «1984» y resume el argumento?',
                        '¿Quién escribió «1984» y por qué eligió ese final?',
                        '¿Quién escribió «1984» y compara sus ideas con Sapiens?',
                        '¿Quién escribió «1984» y cuál es el clima mañana?',
                        '¿Quién escribió «1984»? Calcula cuánto impuesto debo pagar.'):
            with self.subTest(message=message):
                search = Mock(return_value=[FULL_METADATA])
                self.assertIsNone(bibliographic_answer(message, [], search))
                search.assert_not_called()

    def test_private_excerpt_and_exact_quote_never_trigger_metadata_search(self):
        for message in ('¿Quién escribió este fragmento de ficción: La biblioteca ocultaba todos sus recuerdos familiares?',
                        '¿Quién escribió «1984»? Dame una cita textual.'):
            with self.subTest(message=message):
                search = Mock()
                self.assertIsNone(bibliographic_answer(message, [], search))
                search.assert_not_called()


@override_settings(LITMATE_AI_LOCK_BACKEND='cache', LITMATE_AI_BIBLIOGRAPHIC_FAST_PATH=True,
                   LITMATE_USE_EXISTING_QUOTAS=False)
class BibliographicEndpointTests(TestCase):
    def setUp(self):
        cache.clear()

    def text(self, response):
        events = b''.join(response.streaming_content).decode('utf-8')
        self.assertTrue(events.endswith('data: [DONE]\n\n'))
        return ''.join(json.loads(line[6:])['token'] for line in events.splitlines() if line.startswith('data: {'))

    def test_metadata_answers_without_model_even_when_inference_is_busy(self):
        cache.set('litmate_local_inference_lock', 'ongoing-inference', timeout=60)
        with patch('core.literary_search.search_google', return_value=[FULL_METADATA]), \
                patch('core.ai_identification_details.identification_answer', return_value=None), \
                patch('core.literary_search.search_openlibrary', return_value=[]), \
                patch('core.literary_ai_views.build_assistant') as builder:
            response = self.client.post('/chatbot_query/', json.dumps({'message': '¿Quién escribió «1984»?'}),
                                        content_type='application/json')
        self.assertEqual(response.status_code, 200)
        chunks = list(response.streaming_content)
        response.streaming_content = chunks
        text = self.text(response)
        # La ruta rápida de catálogo puede responder antes que la ficha de
        # Google Books; en ambos casos la autoría queda respaldada por fuente.
        self.assertIn('1984', text)
        self.assertIn('George Orwell', text)
        # Las referencias bibliográficas se muestran en las tarjetas SSE.
        self.assertIn(b'https://books.google.com/books?id=volume_1984', b''.join(chunks))
        builder.assert_not_called()
        self.assertEqual(cache.get('litmate_local_inference_lock'), 'ongoing-inference')

    def test_authenticated_fast_response_persists_zero_inference_telemetry(self):
        from django.contrib.auth import get_user_model
        from .models import MensajeIA
        user = get_user_model().objects.create_user(username='metadata-reader')
        self.client.force_login(user)
        with patch('core.literary_search.search_google', return_value=[FULL_METADATA]), \
                patch('core.literary_ai_views.build_assistant') as builder:
            response = self.client.post('/chatbot_query/', json.dumps({'message': '¿Cuántas páginas tiene «1984»?'}),
                                        content_type='application/json')
        self.assertIn('328 páginas', self.text(response))
        builder.assert_not_called()
        answer = MensajeIA.objects.get(rol='assistant')
        self.assertEqual(answer.metadata_json['provider'], 'google-books-metadata')
        self.assertEqual(answer.metadata_json['provider_calls'], 0)
        self.assertEqual(answer.tokens_utilizados, 0)

    def test_empty_catalog_uses_the_model_instead_of_inventing_metadata(self):
        assistant = Mock()
        assistant.reply.return_value = ChatResult('Falta información de esta edición.', 'clarification')
        provider = SimpleNamespace(usage={}, provider='ollama-local', calls=0)
        with patch('core.literary_search.search_google', return_value=[]), \
                patch('core.literary_ai_views.build_assistant', return_value=(assistant, provider)):
            response = self.client.post('/chatbot_query/', json.dumps({'message': '¿Cuántas páginas tiene «1984»?'}),
                                        content_type='application/json')
        self.assertIn('Falta información de esta edición.', self.text(response))
        assistant.reply.assert_called_once()


@override_settings(LITMATE_AI_LOCK_BACKEND='cache', LITMATE_AI_CATALOG_FALLBACK=True,
                   LITMATE_USE_EXISTING_QUOTAS=False, LITMATE_AI_QUICK_ANSWERS=False,
                   LITMATE_AI_USE_WEB=False)
class FallbackEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.assistant = Mock()
        self.assistant.reply.return_value = ChatResult('El modelo no respondió.', 'unavailable')
        self.provider = SimpleNamespace(usage={'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0},
                                        provider='ollama-local', calls=0, deadline=time.monotonic() + 60)

    def post(self, message, search=None):
        search = search or Mock(return_value=[GOOGLE_BOOK])
        with patch('core.literary_ai_views.build_assistant', return_value=(self.assistant, self.provider)), \
                patch('core.literary_search.search_google', search):
            response = self.client.post('/chatbot_query/', json.dumps({'message': message}),
                                        content_type='application/json')
        return response, search

    def text(self, response):
        events = b''.join(response.streaming_content).decode('utf-8')
        self.assertTrue(events.endswith('data: [DONE]\n\n'))
        return ''.join(json.loads(line[6:])['token'] for line in events.splitlines()
                       if line.startswith('data: {'))

    def test_model_failure_returns_only_actual_google_metadata(self):
        response, search = self.post('Recomienda un libro de George Orwell')
        self.assertEqual(response.status_code, 200)
        text = self.text(response)
        self.assertIn('1984 — George Orwell', text)
        self.assertIn('Trama: Una sociedad sometida a vigilancia.', text)
        self.assertIn('Google Books', text)
        self.assertNotIn('Editorial:', text)
        self.assertNotIn('El modelo no respondió.', text)
        search.assert_called_once()
        self.assertEqual(self.client.session['litmate_literary_chat_local_v1']['turns'][0]['books'][0]['title'], '1984')
        self.assertIsNone(cache.get('litmate_local_inference_lock'))

    @override_settings(LITMATE_AI_CATALOG_FALLBACK=False)
    def test_disabled_fallback_does_not_call_google(self):
        response, search = self.post('Recomienda un libro de Orwell')
        self.assertIn('El modelo no respondió.', self.text(response))
        search.assert_not_called()

    def test_failed_google_search_preserves_controlled_model_error(self):
        response, _ = self.post('Recomienda un libro de Orwell', Mock(side_effect=TimeoutError))
        self.assertIn('El modelo no respondió.', self.text(response))
        self.assertIsNone(cache.get('litmate_local_inference_lock'))

    def test_expired_deadline_never_starts_a_fresh_catalog_search(self):
        self.provider.deadline = time.monotonic() - 1
        response, search = self.post('Recomienda un libro de Orwell')
        self.assertIn('El modelo no respondió.', self.text(response))
        search.assert_not_called()
        self.assertIsNone(cache.get('litmate_local_inference_lock'))

    def test_busy_worker_has_retry_hint_and_does_not_search_or_generate(self):
        cache.set('litmate_local_inference_lock', 'other-request', timeout=60)
        response, search = self.post('Recomienda un libro de Orwell')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response['Retry-After'], '5')
        self.assertIn('ocupada', response.json()['response'])
        search.assert_not_called()
        self.assistant.reply.assert_not_called()
        self.assertEqual(cache.get('litmate_local_inference_lock'), 'other-request')

    def test_invalid_configuration_returns_json_and_releases_lease(self):
        with patch('core.literary_ai_views.build_assistant', side_effect=ValueError):
            response = self.client.post('/chatbot_query/', json.dumps({'message': 'Recomienda un libro'}),
                                        content_type='application/json')
        self.assertEqual(response.status_code, 503)
        self.assertIn('configuración', response.json()['response'])
        self.assertIsNone(cache.get('litmate_local_inference_lock'))

    def test_private_passage_is_never_sent_to_catalog_when_model_is_offline(self):
        response, search = self.post('Analiza este fragmento: La biblioteca conservaba todos los recuerdos de la isla.')
        self.assertIn('El modelo no respondió.', self.text(response))
        search.assert_not_called()


@override_settings(LITMATE_AI_LOCK_BACKEND='cache')
class VoiceEndpointTests(TestCase):
    def setUp(self):
        cache.clear()

    def post(self, text='Una lectura para compartir.'):
        return self.client.post('/api/miku-tts/', json.dumps({'text': text}), content_type='application/json')

    @override_settings(LITMATE_TTS_ENABLED=True)
    def test_voice_requires_csrf_cookie_and_header(self):
        client = Client(enforce_csrf_checks=True)
        with patch('core.services_voice.obtener_audio_miku', return_value='/media/tts_cache/mock.mp3') as voice:
            denied = client.post('/api/miku-tts/', json.dumps({'text': 'Una lectura para compartir.'}),
                                 content_type='application/json')
            self.assertEqual(denied.status_code, 403)
            voice.assert_not_called()
            client.get('/chat/')
            response = client.post('/api/miku-tts/', json.dumps({'text': 'Una lectura para compartir.'}),
                                   content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['audio_url'], '/media/tts_cache/mock.mp3')
        voice.assert_called_once_with('Una lectura para compartir.')

    @override_settings(LITMATE_TTS_ENABLED=False)
    def test_disabled_external_voice_does_not_contact_provider(self):
        with patch('core.services_voice.obtener_audio_miku') as voice:
            response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertIn('desactivada', response.json()['error'])
        voice.assert_not_called()

    @override_settings(LITMATE_TTS_ENABLED=True)
    def test_voice_rate_limit_stops_generation_and_returns_retry_hint(self):
        with patch('core.services_voice.obtener_audio_miku', return_value='/media/tts_cache/mock.mp3') as voice:
            for _ in range(5):
                self.assertEqual(self.post().status_code, 200)
            limited = self.post()
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited['Retry-After'], '60')
        self.assertEqual(voice.call_count, 5)

    @override_settings(LITMATE_TTS_ENABLED=True)
    def test_invalid_voice_payload_never_reaches_provider(self):
        with patch('core.services_voice.obtener_audio_miku') as voice:
            self.assertEqual(self.client.get('/api/miku-tts/').status_code, 405)
            self.assertEqual(self.client.post('/api/miku-tts/', '{}', content_type='text/plain').status_code, 415)
            self.assertEqual(self.client.post('/api/miku-tts/', '{invalid', content_type='application/json').status_code, 400)
            self.assertEqual(self.post('').status_code, 400)
            self.assertEqual(self.post('x' * 3501).status_code, 400)
        voice.assert_not_called()
