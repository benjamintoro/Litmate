"""IDs compactos no permiten separar título, autor e identidad bibliográfica."""
import copy
import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .literary_ai import ANSWER_SCHEMA, ProviderUnavailable, canonical_sources, validate_draft
from .local_llm import OllamaJSON
from .test_local_ai import SHOW, response


SOURCES = canonical_sources([
    {'kind': 'book', 'title': 'Libro del cielo', 'author': 'Autora celeste',
     'description': 'El cielo y sus estrellas.'},
    {'kind': 'book', 'title': 'Libro del campo', 'author': 'Autor terrestre',
     'description': 'El campo y sus animales.'},
    {'kind': 'web', 'title': 'Página de análisis', 'author': 'Fuente web',
     'description': 'Una página complementaria.'},
])
DRAFT = {'status': 'answer', 'text': 'Libro del campo, de Autor terrestre.',
         'basis': 'sources', 'citations': [1, 2], 'needs_web': False, 'books': [2, 1]}


class CompactBookTransportTests(SimpleTestCase):
    def generate(self, draft=None, *, stage='answer', **extra):
        data = {'sources': SOURCES, 'require_book_sources': True, 'intent': 'recommend', **extra}
        fetch = Mock(side_effect=[SHOW, response(DRAFT if draft is None else draft)])
        with patch('core.local_llm.read_json_url', fetch):
            parsed = OllamaJSON()(stage, 'Respuesta cálida y natural.', data, 'local-test')
        return parsed, fetch.call_args.kwargs['payload']

    def test_source_ids_hydrate_exact_identities_in_the_same_order(self):
        parsed, payload = self.generate()
        self.assertEqual(parsed['books'], [
            {'title': SOURCES[index - 1]['title'], 'author': SOURCES[index - 1]['author'], 'source_id': index}
            for index in (2, 1)])
        self.assertEqual(payload['format']['properties']['books']['items'], {'type': 'integer', 'enum': [1, 2]})
        self.assertEqual(parsed['text'], DRAFT['text'])
        self.assertNotIn('const', payload['format']['properties']['text'])
        self.assertIn('IDs enteros', payload['messages'][0]['content'])
        validate_draft(parsed, SOURCES)

    def test_unknown_web_zero_boolean_float_string_and_duplicate_ids_are_rejected(self):
        for ids in ([99], [3], [0], [True], [1.0], ['1'], [1, 1]):
            with self.subTest(ids=ids), self.assertRaises(ProviderUnavailable):
                self.generate({**DRAFT, 'books': ids})

    def test_legacy_objects_cannot_smuggle_a_different_title_or_author(self):
        for title, author in [('Título inventado', SOURCES[0]['author']),
                              (SOURCES[0]['title'], 'Autor distinto')]:
            draft = {**DRAFT, 'books': [{'title': title, 'author': author, 'source_id': 1}]}
            with self.subTest(title=title, author=author), self.assertRaises(ProviderUnavailable):
                self.generate(draft)

    def test_requested_count_constrains_both_schema_and_transport_decoder(self):
        parsed, payload = self.generate({**DRAFT, 'books': [1]}, requested_book_count=1)
        self.assertEqual(len(parsed['books']), 1)
        self.assertEqual(payload['format']['properties']['books']['maxItems'], 1)
        with self.assertRaises(ProviderUnavailable):
            self.generate(requested_book_count=1)

    def test_repair_and_web_answer_use_the_same_identity_contract(self):
        for stage in ('repair', 'answer_web'):
            with self.subTest(stage=stage):
                parsed, _ = self.generate({**DRAFT, 'books': [1]}, stage=stage)
                self.assertEqual(parsed['books'][0]['title'], SOURCES[0]['title'])

    def test_no_sources_means_only_empty_book_selection_is_allowed(self):
        draft = {**DRAFT, 'status': 'clarify', 'text': '¿Qué obra buscas?', 'citations': [], 'books': []}
        parsed, payload = self.generate(draft, sources=[])
        self.assertEqual(parsed['books'], [])
        self.assertEqual(payload['format']['properties']['books']['maxItems'], 0)
        with self.assertRaises(ProviderUnavailable):
            self.generate({**draft, 'books': [1]}, sources=[])

    def test_ground_identity_flag_also_uses_compact_ids(self):
        parsed, _ = self.generate({**DRAFT, 'books': [1]}, require_book_sources=False, ground_book_identity=True)
        self.assertEqual(parsed['books'][0]['source_id'], 1)

    def test_non_grounded_knowledge_answer_keeps_the_classic_transport(self):
        book = {'title': 'Una obra conocida', 'author': 'Su autora', 'source_id': 0}
        draft = {**DRAFT, 'books': [book], 'basis': 'knowledge', 'citations': []}
        parsed, payload = self.generate(draft, require_book_sources=False, ground_book_identity=False)
        self.assertEqual(parsed, draft)
        self.assertEqual(payload['format']['properties']['books']['items']['type'], 'object')

    def test_shared_schema_and_input_sources_are_not_modified(self):
        before, sources_before = copy.deepcopy(ANSWER_SCHEMA), copy.deepcopy(SOURCES)
        self.generate()
        self.assertEqual(ANSWER_SCHEMA, before)
        self.assertEqual(SOURCES, sources_before)

    def test_failure_diagnostics_identify_legacy_objects_without_copying_content(self):
        client = OllamaJSON()
        private_marker = 'NEVER_LOG_THIS_PRIVATE_CONTENT'
        result = {**DRAFT, 'books': [{'source_id': 1, 'title': private_marker, 'author': 'Otro'}]}
        with patch('core.local_llm.read_json_url', side_effect=[SHOW, response(result)]), \
                self.assertRaises(ProviderUnavailable):
            client('answer', 'Respuesta literaria.', {'sources': SOURCES, 'require_book_sources': True}, 'local-test')
        self.assertEqual(client.last_error_detail, 'book_selection_legacy_objects')
        self.assertEqual(client.stage_timings[0]['failure_detail'], 'book_selection_legacy_objects')
        self.assertNotIn(private_marker, json.dumps(client.stage_timings))

