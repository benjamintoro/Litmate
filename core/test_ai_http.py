"""Regresiones de límites HTTP y de esperas del asistente."""
import io
import json
import threading
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from django.test import TestCase as DjangoTestCase, override_settings

from .ai_budget import BudgetExpired, pool_in_budget
from .ai_http import read_bounded, read_json_url
from .literary_ai import LiteraryAssistant, validate_draft, ANSWER_SCHEMA
from .local_llm import OllamaJSON
from .test_local_ai import SHOW
from .test_literary_ai import BOOK, ROUTE, DRAFT, REVIEW, FakeLLM


class BoundedReadTests(TestCase):
    def test_unicode_json_survives_small_byte_chunks(self):
        body = json.dumps({'respuesta': 'Sí, mañana'}, ensure_ascii=False).encode()
        response = io.BytesIO(body)
        with patch('core.ai_http.time.monotonic', return_value=10):
            self.assertEqual(read_bounded(response, 1000, 11), body)

    def test_oversized_body_is_rejected_before_json_parsing(self):
        with patch('core.ai_http.time.monotonic', return_value=10):
            with self.assertRaises(ValueError):
                read_bounded(io.BytesIO(b'x' * 101), 100, 11)

    def test_slow_chunks_cannot_keep_renewing_total_timeout(self):
        current = [10.0]
        class Drip:
            def read1(self, size):
                current[0] += 0.6
                return b'x'
        with patch('core.ai_http.time.monotonic', side_effect=lambda: current[0]):
            with self.assertRaises(BudgetExpired):
                read_bounded(Drip(), 100, 11)

    def test_expired_deadline_does_not_start_read(self):
        response = Mock()
        with patch('core.ai_http.time.monotonic', return_value=11):
            with self.assertRaises(BudgetExpired):
                read_bounded(response, 100, 10)
        response.read1.assert_not_called()

    def test_socket_timeout_is_reduced_as_budget_is_spent(self):
        current = [10.0]
        sock = Mock()
        class Response:
            fp = SimpleNamespace(raw=SimpleNamespace(_sock=sock))
            chunks = [b'hello', b'']
            def read1(self, size):
                current[0] += 0.2
                return self.chunks.pop(0)
        with patch('core.ai_http.time.monotonic', side_effect=lambda: current[0]):
            self.assertEqual(read_bounded(Response(), 100, 11), b'hello')
        timeouts = [call.args[0] for call in sock.settimeout.call_args_list]
        self.assertGreater(timeouts[0], timeouts[-1])
        self.assertTrue(all(value > 0 for value in timeouts))

    def test_finished_request_does_not_wait_for_stalled_search_thread(self):
        entered, release = threading.Event(), threading.Event()
        def stalled():
            entered.set()
            release.wait(2)
        try:
            with pool_in_budget(1) as pool:
                future = pool.submit(stalled)
                self.assertTrue(entered.wait(1))
            # El future sigue bloqueado, pero el context manager ya retornó.
            self.assertFalse(future.done())
        finally:
            release.set()
            future.result(timeout=1)


class GroundedRecommendationsTests(TestCase):
    def test_recommendation_without_catalog_does_not_publish_model_invention(self):
        llm = FakeLLM()
        assistant = LiteraryAssistant(llm, lambda q: [], require_book_sources=True)
        result = assistant.reply('Recomiéndame un libro de guerra')
        self.assertEqual(result.status, 'clarification')
        self.assertTrue(result.diagnostics['book_sources_missing'])
        self.assertNotIn('answer', [record[0] for record in llm.records])
        self.assertNotIn(BOOK['title'], result.text)

    def test_unverified_recommendation_cannot_override_received_books(self):
        draft = {**DRAFT, 'books': [{'title': 'Un título inventado', 'author': 'Autor inexistente', 'source_id': 0}]}
        llm = FakeLLM(answer=draft, repair=draft)
        result = LiteraryAssistant(llm, lambda q: [BOOK], require_book_sources=True).reply('Recomiéndame un libro')
        self.assertEqual(result.status, 'unavailable')
        self.assertNotIn('Un título inventado', result.text)

    def test_verified_recommendation_remains_useful(self):
        result = LiteraryAssistant(FakeLLM(), lambda q: [BOOK], require_book_sources=True).reply('Recomiéndame un libro')
        self.assertEqual(result.status, 'answered')
        self.assertEqual(result.books[0]['title'], BOOK['title'])
        self.assertIn(BOOK['title'], result.text)

    def test_unverified_router_candidates_cannot_be_echoed_as_extra_options(self):
        route = {**ROUTE, 'candidates': [{'title': 'La obra inexistente', 'author': 'Autor inexistente'}]}
        draft = {**DRAFT, 'text': DRAFT['text'] + ' Otra opción no verificada es La obra inexistente de Autor inexistente.'}
        llm = FakeLLM(route=route, answer=draft, repair=DRAFT)
        result = LiteraryAssistant(llm, lambda q: [BOOK], require_book_sources=True).reply('Recomiéndame un libro')
        self.assertEqual(result.status, 'answered')
        self.assertNotIn('La obra inexistente', result.text)
        self.assertNotIn('Autor inexistente', result.text)
        self.assertEqual(result.diagnostics['repairs'], 1)


class ProviderSchemaRegressionTests(TestCase):
    def test_grounding_title_and_author_does_not_constrain_response_text(self):
        client = OllamaJSON()
        client._models['test-model'] = SHOW
        response = {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({**DRAFT, 'books': [1]})}}
        context = {'sources': [{**BOOK, 'id': 1, 'kind': 'book'}], 'require_book_sources': True}
        with patch('core.local_llm.read_json_url', return_value=response) as fetch:
            parsed = client('answer', 'JSON', context, 'test-model')
        schema = fetch.call_args.kwargs['payload']['format']
        items = schema['properties']['books']['items']
        self.assertNotIn('properties', items)
        self.assertEqual(items, {'type': 'integer', 'enum': [1]})
        self.assertEqual(parsed['books'], [{'title': BOOK['title'], 'author': BOOK['author'], 'source_id': 1}])
        self.assertNotIn('enum', schema['properties']['text'])
        self.assertNotIn('enum', ANSWER_SCHEMA['properties']['text'])

    def test_two_book_identities_cannot_mix_title_author_and_identifier(self):
        client = OllamaJSON()
        client._models['test-model'] = SHOW
        second = {'title': '1984', 'author': 'George Orwell', 'id': 2, 'kind': 'book'}
        response = {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps({**DRAFT, 'books': [1, 2]})}}
        context = {'sources': [{**BOOK, 'id': 1, 'kind': 'book'}, second], 'require_book_sources': True}
        with patch('core.local_llm.read_json_url', return_value=response) as fetch:
            parsed = client('answer', 'JSON', context, 'test-model')
        schema = fetch.call_args.kwargs['payload']['format']
        items = schema['properties']['books']['items']
        allowed = {tuple(book[name] for name in ('title', 'author', 'source_id'))
                   for book in parsed['books']}
        self.assertEqual(allowed, {(BOOK['title'], BOOK['author'], 1), ('1984', 'George Orwell', 2)})
        self.assertNotIn((BOOK['title'], 'George Orwell', 2), allowed)
        self.assertNotIn(('1984', BOOK['author'], 1), allowed)
        self.assertNotIn('properties', items)
        self.assertNotIn('const', schema['properties']['text'])
        self.assertNotIn('const', ANSWER_SCHEMA['properties']['text'])

    def test_audit_statements_and_evidence_have_independent_choices(self):
        client = OllamaJSON()
        client._models['test-model'] = SHOW
        response = {'done': True, 'done_reason': 'stop', 'message': {'content': '{}'}}
        draft = {'text': 'Esta obra desarrolla la memoria y la identidad.', 'citations': [1]}
        context = {'draft': draft, 'sources': [{**BOOK, 'id': 1}], 'plan': {'questions': ['Una pregunta']}}
        with patch('core.local_llm.read_json_url', return_value=response) as fetch:
            client('audit', 'JSON', context, 'test-model')
        items = fetch.call_args.kwargs['payload']['format']['properties']['claims']['items']
        self.assertNotIn('properties', items)
        supported = next(option['properties'] for option in items['anyOf']
                         if option['properties']['verdict'].get('const') == 'supported')
        self.assertIn(draft['text'], supported['statement']['enum'])
        self.assertIn(BOOK['title'], supported['evidence']['enum'])
        self.assertNotIn('', supported['statement']['enum'])
        self.assertNotIn('', supported['evidence']['enum'])
        from .literary_quality import AUDIT_SCHEMA
        shared = AUDIT_SCHEMA['properties']['claims']['items']['properties']
        self.assertNotIn('enum', shared['statement'])
        self.assertNotIn('enum', shared['evidence'])
        self.assertNotIn('enum', ANSWER_SCHEMA['properties']['text'])

    def audit_schema(self, sources, draft, message='Compara las obras', **options):
        client = OllamaJSON()
        client._models['test-model'] = SHOW
        response = {'done': True, 'done_reason': 'stop', 'message': {'content': '{}'}}
        context = {'draft': draft, 'sources': sources, 'message': message,
                   'plan': {'questions': ['Una pregunta']}, **options}
        with patch('core.local_llm.read_json_url', return_value=response) as fetch:
            client('audit', 'JSON', context, 'test-model')
        return fetch.call_args.kwargs['payload']['format']['properties']['claims']['items']

    def test_audit_evidence_is_paired_with_its_own_source_identifier(self):
        first = {**BOOK, 'id': 1}
        second = {'id': 2, 'kind': 'book', 'title': 'La biblioteca de la memoria', 'author': 'Autora del segundo libro',
                  'description': 'La memoria y la identidad de una isla están preservadas en su biblioteca.'}
        draft = {'text': 'La primera novela trata la guerra. La segunda desarrolla la memoria y la identidad.',
                 'citations': [1, 2]}
        items = self.audit_schema([first, second], draft)
        self.assertNotIn('properties', items)
        supported = {option['properties']['source_id']['const']: option['properties']
                     for option in items['anyOf'] if option['properties']['verdict'].get('const') == 'supported'}
        self.assertEqual(set(supported), {1, 2})
        self.assertIn(first['description'], supported[1]['evidence']['enum'])
        self.assertIn(second['description'], supported[2]['evidence']['enum'])
        self.assertNotIn(second['description'], supported[1]['evidence']['enum'])
        self.assertNotIn(second['title'], supported[1]['evidence']['enum'])
        self.assertNotIn(first['description'], supported[2]['evidence']['enum'])
        for identifier, properties in supported.items():
            self.assertEqual(properties['source_id']['const'], identifier)
            self.assertNotIn('', properties['evidence']['enum'])
            self.assertTrue(all(8 <= len(value.strip()) <= 300 for value in properties['evidence']['enum']))
        unsupported = [option['properties'] for option in items['anyOf']
                       if 'enum' in option['properties']['verdict']]
        self.assertEqual(len(unsupported), 1)
        self.assertEqual(set(unsupported[0]['verdict']['enum']), {'inference', 'unverified', 'contradicted'})
        self.assertEqual(unsupported[0]['evidence']['const'], '')
        self.assertEqual(set(unsupported[0]['source_id']['enum']), {0, 1, 2})

    def test_audit_cannot_mark_an_uncited_source_as_supported(self):
        sources = [{**BOOK, 'id': 1}, {**BOOK, 'id': 2, 'title': 'Otra novela de guerra'}]
        items = self.audit_schema(sources, {'text': 'La novela trata la guerra.', 'citations': [1]})
        identifiers = {option['properties']['source_id']['const'] for option in items['anyOf']
                       if option['properties']['verdict'].get('const') == 'supported'}
        self.assertEqual(identifiers, {1})

    def test_private_reader_excerpt_can_still_supply_source_zero_evidence(self):
        passage = 'El faro guardaba todos los recuerdos de la isla en su biblioteca.'
        items = self.audit_schema([], {'text': 'El pasaje relaciona el faro con la memoria.', 'citations': []},
                                  'Analiza este fragmento: ' + passage)
        supported = next(option['properties'] for option in items['anyOf']
                         if option['properties']['verdict'].get('const') == 'supported')
        self.assertEqual(supported['source_id']['const'], 0)
        self.assertIn(passage, supported['evidence']['enum'])

    def test_character_audit_schema_binds_each_statement_to_proof_naming_that_character(self):
        paul = 'Paul Atreides: Joven heredero de la Casa Atreides.'
        jessica = 'Lady Jessica: Madre de Paul y miembro de la orden Bene Gesserit.'
        synopsis = 'Una novela de ciencia ficción ambientada en Arrakis.'
        sources = [{'id': 1, 'title': 'Dune', 'author': 'Frank Herbert', 'description': synopsis},
                   {'id': 2, 'title': 'Dune (novela)', 'author': 'Fuente web',
                    'description': paul + '\n' + jessica}]
        statement = '**Lady Jessica**: Madre de Paul.'
        items = self.audit_schema(sources, {'text': statement, 'citations': [1, 2]},
                                  'Dime los personajes de Dune', facts_only=True)
        supported = [option['properties'] for option in items['anyOf']
                     if option['properties']['verdict'].get('const') == 'supported']
        self.assertTrue(supported)
        self.assertEqual({properties['source_id']['const'] for properties in supported}, {2})
        for properties in supported:
            self.assertEqual(properties['statement']['const'], statement)
            self.assertNotIn(synopsis, properties['evidence']['enum'])
            self.assertNotIn(paul, properties['evidence']['enum'])
            self.assertTrue(all('Jessica' in proof for proof in properties['evidence']['enum']))


@override_settings(ROOT_URLCONF='litmate_project.urls')
class ActualChatTemplateTests(DjangoTestCase):
    def test_shared_client_is_loaded_once_before_the_full_page_chat(self):
        for path in ('/chat/', '/chatbot/'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertEqual(html.count('js/litmate_safe.js'), 1)
                self.assertLess(html.index('js/litmate_safe.js'), html.index('js/chatbot.js'))
                self.assertNotIn('js/floating_chat.js', html)

    def test_shared_client_is_loaded_before_the_floating_chat(self):
        response = self.client.get('/about/')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertEqual(html.count('js/litmate_safe.js'), 1)
        self.assertLess(html.index('js/litmate_safe.js'), html.index('js/floating_chat.js'))
