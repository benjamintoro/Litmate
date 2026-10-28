"""Regresiones de la petición real: presupuesto ampliado, lenguaje natural y fuentes.

Las fuentes externas y Ollama se sustituyen explícitamente en estas pruebas;
el benchmark HTTP separado sí usa los servicios locales y públicos reales.
"""
import copy
import json
import re
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from .ai_budget import (BudgetExpired, WorkerBusy, chat_timeout, current_deadline,
                        request_budget, run_before_deadline)
from .ai_quick_answers import quick_answer, _bundled, catalogue_lookup_answer
from .books_google import book_topic_profile, topic_matches
from .literary_ai import ChatResult, simple_literary_route
from .literary_conversation import resolve_topic_context
from .literary_research import is_topic_recommendation
from .local_llm import OllamaJSON


EXAMPLE = 'hola recomiendame libros sobre la segunda guerra mundial'


class DeadlineBudgetTests(SimpleTestCase):
    def test_chat_never_uses_the_legacy_six_minute_budget(self):
        self.assertEqual(chat_timeout(SimpleNamespace(LITMATE_AI_TOTAL_TIMEOUT=360)), 36)
        self.assertEqual(chat_timeout(SimpleNamespace(LITMATE_CHAT_TIMEOUT=360)), 36)
        self.assertEqual(chat_timeout(SimpleNamespace(LITMATE_CHAT_TIMEOUT='bad')), 36)

    def test_local_provider_does_not_force_a_minimum_of_sixty_seconds(self):
        start = time.monotonic()
        client = OllamaJSON(total_timeout=.25, timeout=.25)
        self.assertLessEqual(client.deadline - start, .26)
        self.assertLessEqual(client.timeout, .25)

    def test_provider_constructed_after_search_inherits_remaining_deadline(self):
        deadline = time.monotonic() + .5
        with request_budget(deadline):
            client = OllamaJSON(total_timeout=360)
        self.assertEqual(client.deadline, deadline)
        self.assertLessEqual(client.answer_tokens, 512)

    def test_worker_inherits_the_original_deadline(self):
        deadline = time.monotonic() + 1
        observed = run_before_deadline(current_deadline, deadline)
        self.assertEqual(observed, deadline)

    def test_noncooperative_dependency_does_not_block_http_thread(self):
        stop, finished = threading.Event(), threading.Event()
        def blocked():
            try:
                stop.wait(2)
            finally:
                finished.set()
        start = time.monotonic()
        try:
            with self.assertRaises(BudgetExpired):
                run_before_deadline(blocked, start + .05)
            self.assertLess(time.monotonic() - start, .4)
            self.assertFalse(finished.is_set())
        finally:
            stop.set()
            self.assertTrue(finished.wait(2))

    def test_expired_budget_cannot_start_new_work(self):
        work = Mock()
        with self.assertRaises(BudgetExpired):
            run_before_deadline(work, time.monotonic() - 1)
        work.assert_not_called()

    def test_stalled_worker_keeps_its_slot_instead_of_growing_an_unbounded_queue(self):
        from threading import BoundedSemaphore
        stop = threading.Event()
        slots = BoundedSemaphore(1)
        with patch('core.ai_budget._chat_slots', slots):
            try:
                with self.assertRaises(BudgetExpired):
                    run_before_deadline(lambda: stop.wait(2), time.monotonic() + .03)
                never_started = Mock()
                with self.assertRaises(WorkerBusy):
                    run_before_deadline(never_started, time.monotonic() + 1)
                never_started.assert_not_called()
            finally:
                stop.set()
                self.assertTrue(slots.acquire(timeout=2))
                slots.release()


class NaturalRequestTests(SimpleTestCase):
    def test_colloquial_requests_have_verified_recommendations_without_http(self):
        messages = [EXAMPLE, 'porfa recomendame 2 libros de la II guerra mundial',
                    '¿Qué puedo leer sobre la Segunda Guerra Mundial?',
                    'me gustaria leer sobre la segunda guerra mundial',
                    '¿Me recomiendas libros sobre la segunda guerra mundial?',
                    'dame tres libros sobre la segunda guerra mundial',
                    'libros de la segunda guerra mundial',
                    'recomiedame libros sobre la segunda guerra mundial',
                    'buenas, recomendame un libro sobre WWII']
        with patch('core.ai_http.read_json_url') as network:
            for message in messages:
                with self.subTest(message=message):
                    self.assertTrue(is_topic_recommendation(message))
                    context = resolve_topic_context(message, {'turns': []})
                    result = quick_answer(message, topic_context=context)
                    self.assertIsNotNone(result)
                    self.assertEqual(result.status, 'answered')
                    self.assertIn('Antony Beevor', result.text)
                    self.assertTrue(result.sources)
        network.assert_not_called()

    def test_curated_wwi_and_ancient_greece_answer_without_network(self):
        cases = [
            ('recomiendame tambien libros sobre la primera guerra mundial',
             ('David Stevenson', 'Max Hastings', 'Barbara W. Tuchman')),
            ('libros sobre la antigua grecia',
             ('Indro Montanelli', 'Isaac Asimov', 'Tucídides')),
        ]
        with patch('core.ai_http.read_json_url') as network:
            for message, expected in cases:
                with self.subTest(message=message):
                    result = quick_answer(message)
                    self.assertIsNotNone(result)
                    self.assertEqual(result.status, 'answered')
                    for author in expected:
                        self.assertIn(author, result.text)
        network.assert_not_called()

    def test_quantity_and_source_identity_are_kept(self):
        result = quick_answer('porfa recomendame dos libros de la segunda guerra mundial')
        self.assertEqual(len(result.books), 2)
        lookup = {source['id']: source for source in result.sources}
        for book in result.books:
            self.assertEqual(book['title'], lookup[book['source_id']]['title'])
            self.assertEqual(book['author'], lookup[book['source_id']]['author'])
        self.assertIn('Max Hastings', result.text)

    def test_capitalized_topic_after_de_is_not_mistaken_for_an_author(self):
        result = quick_answer('Recomiéndame libros de Segunda Guerra Mundial')
        self.assertIsNotNone(result)
        self.assertIn('Antony Beevor', result.text)

    def test_request_for_other_books_excludes_already_recommended_works_from_search(self):
        from .test_grounded_topic_fallback import KOREA, CONCISE
        history = [{'accepted': True, 'question': 'libros sobre historia de Corea',
                    'answer': 'Una lectura.', 'books': [KOREA], 'sources': [KOREA]}]
        context = {'intent': 'recommend', 'query': 'libros sobre historia de Corea', 'followup': True}
        result = quick_answer('Recomiéndame otro libro', history, topic_context=context,
                              search=Mock(return_value=[KOREA, CONCISE]))
        self.assertIsNotNone(result)
        self.assertEqual([book['title'] for book in result.books], [CONCISE['title']])

    def test_descriptive_fast_recommendation_cannot_ignore_distinct_authors(self):
        from .test_grounded_topic_fallback import KOREA, CONCISE
        description = 'Un estudio de la historia de Corea.'
        sources = [{**source, 'author': 'Una misma autora', 'description': description,
                    'synopsis': description} for source in [KOREA, CONCISE]]
        message = 'Recomiéndame dos libros de distintos autores sobre historia de Corea'
        result = quick_answer(message, search=Mock(return_value=sources))
        self.assertIsNone(result)

    def test_world_war_query_is_specific_and_does_not_match_world_war_one(self):
        profile = book_topic_profile(EXAMPLE)
        self.assertIn('subject:"world war, 1939-1945"', profile['query'])
        wrong = {'kind': 'book', 'title': 'Primera guerra mundial', 'author': 'Autora',
                 'categories': ['Historia', 'World War, 1914-1918']}
        self.assertFalse(topic_matches(wrong, EXAMPLE))

    def test_nonfiction_metadata_is_not_misread_as_fiction(self):
        book = next(source for source in _bundled() if source['author'] == 'Antony Beevor')
        self.assertTrue(topic_matches(book, EXAMPLE))

    def test_clear_topic_can_route_without_a_model(self):
        route = simple_literary_route(EXAMPLE)
        self.assertEqual(route['intent'], 'recommend')
        self.assertEqual(route['decision'], 'allow')

    def test_unknown_qualifiers_and_extra_tasks_are_not_silently_ignored(self):
        for message in ['recomiendame libros sobre submarinos de la segunda guerra mundial',
                        'recomiendame novelas sobre la segunda guerra mundial',
                        'recomiendame libros cortos sobre la segunda guerra mundial',
                        'recomiendame libros de la segunda guerra mundial publicados en 2025',
                        'recomiendame libros sobre la segunda guerra mundial y calcula mis impuestos',
                        'recomiendame libros sobre la segunda guerra mundial y explica sus diferencias',
                        'recomiendame diez libros sobre la segunda guerra mundial']:
            with self.subTest(message=message):
                self.assertIsNone(quick_answer(message))

    def test_a_private_passage_never_calls_search(self):
        search = Mock()
        self.assertIsNone(quick_answer('recomiendame algo como este fragmento: '
                                      'El niño encontró un diario durante la guerra.', search=search))
        search.assert_not_called()

    def test_every_statement_is_audited_and_copied_from_the_same_book(self):
        result = quick_answer(EXAMPLE)
        self.assertGreaterEqual(result.diagnostics['claim_checks'], 3)
        by_id = {source['id']: source for source in result.sources}
        for claim in result.diagnostics['audit']['claims']:
            self.assertIn(claim['evidence'], by_id[claim['source_id']]['description'])

    def test_validation_is_not_bypassed_to_publish_a_quick_answer(self):
        for validator in ['core.literary_quality.validate_audit',
                          'core.literary_evidence.validate_evidence']:
            with self.subTest(validator=validator), patch(validator, side_effect=ValueError('failed')):
                self.assertIsNone(quick_answer(EXAMPLE))

    def test_summary_and_author_do_not_need_a_model_for_known_facts(self):
        summary = quick_answer('Cuentame de que trata El principito')
        self.assertIsNotNone(summary)
        self.assertIn('rosa', summary.text)
        author = quick_answer('Quien escribio El principito')
        self.assertIn('Antoine de Saint-Exupéry', author.text)

    def test_spanish_question_marks_and_accents_do_not_force_author_generation(self):
        for question, author in [('¿Quién escribió Cien años de soledad?', 'Gabriel García Márquez'),
                                 ('¿Quién escribió Pedro Páramo?', 'Juan Rulfo'),
                                 ('¿Quién escribió El Aleph?', 'Jorge Luis Borges'),
                                 ('¿Quién escribió El Quijote, Gabriel García Márquez?', 'Miguel de Cervantes')]:
            with self.subTest(question=question):
                result = quick_answer(question)
                self.assertIsNotNone(result)
                self.assertIn(author, result.text)

    def test_author_fast_path_does_not_drop_a_second_requested_task(self):
        for message in ['¿Quién escribió El Aleph y cuáles son sus personajes?',
                        '¿Quién escribió Pedro Páramo y su argumento?',
                        '¿Quién escribió Cien años de soledad? Dime sus personajes.']:
            with self.subTest(message=message):
                self.assertIsNone(quick_answer(message))

    def test_ordinal_inside_a_new_title_is_not_the_previous_second_book(self):
        first = quick_answer(EXAMPLE)
        history = [{'accepted': True, 'question': EXAMPLE, 'answer': first.text,
                    'books': first.books, 'sources': first.sources}]
        message = '¿Quién escribió El segundo sexo?'
        self.assertIsNone(quick_answer(message, history))
        from .literary_identity import resolve_followup_context
        self.assertEqual(resolve_followup_context(message, history)['books'], [])

    def test_recollections_allow_a_semicolon_and_question_after_the_scene(self):
        from .ai_identification_details import identification_answer
        for message, title in [('Recuerdo un libro sobre un burro llamado Platero; ¿cuál es?', 'Platero y yo'),
                               ('Un hombre se despierta convertido en un insecto; ¿qué libro es?', 'La metamorfosis')]:
            with self.subTest(message=message):
                from .ai_quick_answers import quick_knowledge_sources
                result = identification_answer(message, search=quick_knowledge_sources)
                self.assertIsNotNone(result)
                self.assertIn(title, result.text)
                self.assertIn('podrías', result.text)

    def test_short_work_alias_keeps_documented_quixote_characters(self):
        from .ai_quick_answers import quick_knowledge_sources
        from .ai_public_details import character_answer
        result = character_answer('¿Quiénes son los personajes principales de Don Quijote?', [],
                                  quick_knowledge_sources, lambda query: [])
        self.assertIsNotNone(result)
        self.assertIn('Sancho Panza', result.text)
        self.assertEqual(result.books[0]['author'], 'Miguel de Cervantes')

    def test_initial_y_in_a_character_followup_is_not_a_second_task(self):
        from .ai_quick_answers import quick_knowledge_sources
        from .ai_public_details import character_answer
        question = 'Dime los personajes de Papelucho y el marciano'
        first = character_answer(question, [], quick_knowledge_sources, lambda query: [])
        history = [{'accepted': True, 'question': question, 'answer': first.text,
                    'sources': first.sources, 'books': first.books}]
        result = quick_answer('¿Y qué sucede con Det?', history)
        self.assertIsNotNone(result)
        self.assertIn('Amigo extraterrestre', result.text)
        self.assertTrue(result.diagnostics['verified_character_followup'])
        self.assertNotIn('muere', result.text)

    def test_interactive_retrieval_keeps_lexical_search_without_loading_an_embedding_model(self):
        from .literary_search import _retrieval_embedder
        with patch('core.local_embeddings.configured_embedder') as embedder:
            with request_budget(time.monotonic() + 8):
                self.assertIsNone(_retrieval_embedder())
            embedder.assert_not_called()
            self.assertEqual(_retrieval_embedder(), embedder.return_value)

    def test_second_book_followup_uses_the_published_list(self):
        first = quick_answer(EXAMPLE)
        history = [{'accepted': True, 'question': EXAMPLE, 'answer': first.text,
                    'books': first.books, 'sources': first.sources}]
        result = quick_answer('Cuéntame más del segundo', history)
        self.assertIsNotNone(result)
        self.assertIn('Se desataron todos los infiernos', result.text)
        self.assertNotIn('Antony Beevor', result.text)

    def test_bundled_facts_are_not_mutated_by_recommendation_or_summary(self):
        before = copy.deepcopy(_bundled())
        quick_answer(EXAMPLE)
        quick_answer('Cuéntame de qué trata El principito')
        self.assertEqual(_bundled(), before)

    def test_a_readers_local_record_is_not_replaced_by_a_longer_bundled_description(self):
        bundled = next(book for book in _bundled() if book['author'] == 'Gabriel García Márquez')
        own_description = 'La ficha propia comenta las relaciones familiares.'
        own = {**bundled, 'description': own_description, 'synopsis': own_description}
        with patch('core.ai_quick_answers.quick_knowledge_sources', return_value=[own]):
            result = quick_answer('Cuéntame de qué trata Cien años de soledad')
        self.assertIsNotNone(result)
        self.assertIn(own_description, result.text)
        self.assertNotIn('entrelazando', result.text)
        self.assertEqual(own['description'], own_description)

    def test_quick_catalogue_author_works_without_google_or_generation(self):
        from .test_grounded_topic_fallback import KOREA
        search = Mock(return_value=[KOREA])
        result = catalogue_lookup_answer('¿Quién escribió A history of Korea?', [], search)
        self.assertIsNotNone(result)
        self.assertIn('Kyung Moon Hwang', result.text)
        self.assertIn(KOREA['url'], result.text)
        self.assertEqual(search.call_args.args[0], 'a history of korea')

    def test_catalogue_lookup_does_not_take_a_similar_title_or_homonym(self):
        from .test_grounded_topic_fallback import KOREA, CONCISE
        result = catalogue_lookup_answer('¿Quién escribió A history of Korea?', [], Mock(return_value=[CONCISE]))
        self.assertIsNone(result)
        other = {**KOREA, 'author': 'Otra persona', 'url': 'https://openlibrary.org/works/OL98765W'}
        result = catalogue_lookup_answer('¿Quién escribió A history of Korea?', [], Mock(return_value=[KOREA, other]))
        self.assertIsNone(result)

    def test_failed_catalogue_does_not_invent_bibliographic_metadata(self):
        search = Mock(return_value=[])
        self.assertIsNone(catalogue_lookup_answer('¿Quién escribió Pedro Páramo?', [], search))

    def test_fresh_sources_and_book_content_are_not_replaced_with_a_plain_synopsis(self):
        search = Mock()
        for message in ('Cuéntame el final de El principito',
                        '¿En qué año se publicó El principito?',
                        '¿Quién escribió El principito y qué ocurre después?',
                        'Analiza este fragmento: texto privado de un lector.'):
            with self.subTest(message=message):
                self.assertIsNone(catalogue_lookup_answer(message, [], search))
        search.assert_not_called()


@override_settings(LITMATE_AI_QUICK_ANSWERS=True, LITMATE_AI_LOCK_BACKEND='cache',
                   LITMATE_AI_USE_WEB=False,
                   LITMATE_AI_BIBLIOGRAPHIC_FAST_PATH=False,
                   LITMATE_AI_CATALOG_FALLBACK=False)
class FastChatEndpointTests(TestCase):
    def setUp(self):
        cache.clear()

    def post(self, message):
        return self.client.post('/chatbot_query/', json.dumps({'message': message}),
                                content_type='application/json')

    def text(self, response):
        events = b''.join(response.streaming_content).decode('utf-8')
        self.assertTrue(events.endswith('data: [DONE]\n\n'))
        return ''.join(json.loads(line[6:]).get('token', '') for line in events.splitlines()
                       if line.startswith('data: {'))

    def test_reported_question_returns_books_without_model_or_external_search(self):
        with patch('core.literary_ai_views.build_assistant') as model, \
                patch('core.literary_search.retrieve_books') as search:
            response = self.post(EXAMPLE)
            text = self.text(response)
        # El trabajo del endpoint se mide aparte del guardado de sesión de la
        # base de pruebas MySQL, que no forma parte de la respuesta literaria.
        work_ms = int(re.search(r'dur=(\d+)', response['Server-Timing']).group(1))
        self.assertLess(work_ms, 2000)
        self.assertIn('Antony Beevor', text)
        self.assertIn('Primo Levi', text)
        self.assertEqual(response['X-LitMate-Status'], 'answered')
        self.assertIn('chat;dur=', response['Server-Timing'])
        model.assert_not_called()
        search.assert_not_called()

    @override_settings(LITMATE_AI_USE_WEB=True)
    def test_empty_verified_discovery_uses_web_grounded_answer_without_inventing_books(self):
        web_source = {'id': 1, 'title': 'Página pública sobre la Revolución francesa',
                      'author': 'Fuente web', 'description': 'Resumen documentado del tema.',
                      'source': 'DuckDuckGo', 'url': 'https://example.org/revolucion-francesa',
                      'kind': 'web', 'year': '', 'book_id': '', 'locator': '',
                      'read_mode': 'pasaje de página pública', 'retrieved_at': ''}
        assistant = Mock()
        assistant.reply.return_value = ChatResult(
            'Encontré información documentada sobre el tema [1].', 'answered', True,
            sources=[web_source], basis='sources', intent='recommend')
        provider = SimpleNamespace(usage={}, provider='test', calls=1)
        with patch('core.literary_search.retrieve_discovery_books', return_value=[]) as discovery, \
                patch('core.ai_quick_answers.web_reference_answer', return_value=None), \
                patch('core.literary_search.retrieve_web', return_value=[]), \
                patch('core.literary_ai_views.build_assistant',
                      return_value=(assistant, provider)) as model:
            start = time.monotonic()
            response = self.post('recomiendame libros sobre la revolucion francesa')
            text = self.text(response)
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(response['X-LitMate-Status'], 'answered')
        self.assertIn('información documentada', text)
        self.assertNotIn('No encontré fichas verificables', text)
        model.assert_called_once()
        assistant.reply.assert_called_once()
        discovery.assert_called_once()

    @override_settings(LITMATE_AI_USE_WEB=True)
    def test_empty_recommendation_discovery_does_not_publish_articles_as_books(self):
        web_source = {'id': 1, 'title': 'Página pública sobre la Revolución francesa',
                      'author': 'Fuente web', 'description': 'Resumen documentado del tema.',
                      'source': 'DuckDuckGo', 'url': 'https://example.org/revolucion-francesa',
                      'kind': 'web', 'year': '', 'book_id': '', 'locator': '',
                      'read_mode': 'pasaje de página pública', 'retrieved_at': ''}
        answer = ChatResult('Referencias web documentadas [1].', 'answered', True,
                            sources=[web_source], basis='sources', intent='recommend')
        # The old contract explicitly required an article dump. The reader's
        # recommendation contract now requires verified books or an honest
        # failure; the existing model/tool route gets a chance to resolve them.
        assistant = Mock()
        assistant.reply.return_value = ChatResult('No pude verificar libros con esos filtros.', 'unavailable')
        provider = SimpleNamespace(usage={}, provider='test', calls=1)
        with patch('core.literary_search.retrieve_discovery_books', return_value=[]), \
                patch('core.ai_quick_answers.web_reference_answer', return_value=answer) as references, \
                patch('core.literary_search.retrieve_web', return_value=[web_source]), \
                patch('core.literary_ai_views.build_assistant', return_value=(assistant, provider)) as model:
            response = self.post('recomiendame libros sobre la revolucion francesa')
            text = self.text(response)
        self.assertEqual(response['X-LitMate-Status'], 'unavailable')
        self.assertNotIn('Referencias web documentadas', text)
        references.assert_not_called()
        model.assert_called_once()

    def test_exact_quote_without_local_text_asks_for_the_passage_without_inference(self):
        with patch('core.literary_search.retrieve_book_content', return_value=[]), \
                patch('core.literary_ai_views.build_assistant') as model:
            response = self.post('Cita textualmente la primera frase de Pedro Páramo.')
        self.assertEqual(response['X-LitMate-Status'], 'clarification')
        self.assertNotIn('límite de tiempo', self.text(response))
        model.assert_not_called()

    @override_settings(LITMATE_AI_QUICK_ANSWERS=False)
    def test_clear_topic_source_failure_is_not_blame_on_the_readers_wording(self):
        assistant = Mock()
        assistant.reply.return_value = ChatResult('¿Prefieres una introducción o algo más específico?', 'clarification')
        provider = SimpleNamespace(usage={}, provider='test', calls=1)
        with patch('core.literary_ai_views.build_assistant', return_value=(assistant, provider)):
            response = self.post(EXAMPLE)
        text = self.text(response)
        self.assertEqual(response['X-LitMate-Status'], 'unavailable')
        self.assertIn('No necesitas reformular', text)
        self.assertNotIn('¿Prefieres', text)

    @override_settings(LITMATE_USE_EXISTING_QUOTAS=True)
    def test_exhausted_quota_prevents_even_the_local_fast_work(self):
        with patch('core.literary_ai_views.cuota_disponible', return_value=(False, {})), \
                patch('core.literary_ai_views._compute_answer') as work:
            response = self.post(EXAMPLE)
        self.assertEqual(response.status_code, 429)
        work.assert_not_called()

    @override_settings(LITMATE_USE_EXISTING_QUOTAS=True)
    def test_fast_result_consumes_once_and_does_not_use_the_model(self):
        with patch('core.literary_ai_views.cuota_disponible', return_value=(True, {})), \
                patch('core.literary_ai_views.verificar_y_consumir_cuota', return_value=(True, {})) as consume, \
                patch('core.literary_ai_views.build_assistant') as model:
            response = self.post(EXAMPLE)
        self.assertIn('Max Hastings', self.text(response))
        consume.assert_called_once()
        model.assert_not_called()

    @override_settings(LITMATE_CHAT_TIMEOUT=2, LITMATE_USE_EXISTING_QUOTAS=True)
    def test_late_answer_is_not_charged_published_or_remembered(self):
        stop, finished = threading.Event(), threading.Event()
        def blocked(*args):
            try:
                stop.wait(10)
                return ChatResult('INVENTED-LATE-TEXT', 'answered', True), SimpleNamespace()
            finally:
                finished.set()
        start = time.monotonic()
        try:
            with patch('core.literary_ai_views.cuota_disponible', return_value=(True, {})), \
                    patch('core.literary_ai_views.verificar_y_consumir_cuota') as consume, \
                    patch('core.literary_ai_views._compute_answer', side_effect=blocked):
                response = self.post(EXAMPLE)
                text = self.text(response)
            work_ms = int(re.search(r'dur=(\d+)', response['Server-Timing']).group(1))
            self.assertLess(work_ms, 2500)
            self.assertLess(time.monotonic() - start, 6)
            self.assertIn('límite de tiempo', text)
            self.assertNotIn('INVENTED', text)
            self.assertEqual(response['X-LitMate-Status'], 'unavailable')
            self.assertNotIn('X-LitMate-Model-Calls', response)
            consume.assert_not_called()
            from .literary_ai_views import HISTORY_KEY
            self.assertEqual(self.client.session[HISTORY_KEY]['turns'], [])
        finally:
            stop.set()
            self.assertTrue(finished.wait(2))

    @override_settings(LITMATE_CHAT_TIMEOUT=2, LITMATE_AI_QUICK_ANSWERS=False)
    def test_timed_out_inference_keeps_lease_until_worker_really_finishes(self):
        from .ai_concurrency import release
        stop, released = threading.Event(), threading.Event()
        assistant = Mock()
        def slow_reply(*args, **kwargs):
            stop.wait(10)
            return ChatResult('TARDE', 'answered', True)
        def release_and_notify(*args):
            try:
                release(*args)
            finally:
                released.set()
        assistant.reply.side_effect = slow_reply
        client = SimpleNamespace(usage={}, provider='test-only', calls=1)
        try:
            with patch('core.literary_ai_views.build_assistant', return_value=(assistant, client)), \
                    patch('core.literary_ai_views.release', side_effect=release_and_notify):
                response = self.post('Explícame la soledad en la literatura')
                self.assertIn('límite de tiempo', self.text(response))
                self.assertIsNotNone(cache.get('litmate_local_inference_lock'))
                busy = self.post('Otra consulta literaria compleja')
                self.assertEqual(busy.status_code, 503)
                assistant.reply.assert_called_once()
                stop.set()
                self.assertTrue(released.wait(5))
                self.assertIsNone(cache.get('litmate_local_inference_lock'))
        finally:
            stop.set()
            self.assertTrue(released.wait(5))
