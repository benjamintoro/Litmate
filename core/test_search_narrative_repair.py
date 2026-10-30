"""Regresiones sintéticas de recuperación y contenido, sin servicios externos."""
from copy import deepcopy
from unittest.mock import patch
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from .test_narrative_answers import BOOK, PAGE
from .literary_ai import canonical_sources
from .ai_narrative_answers import request_for, bound_sources, retrieve_sources


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
                   LITMATE_AI_USE_SEARXNG=True, LITMATE_SEARXNG_URL='http://127.0.0.1:8080')
class SearchRecoveryTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def search(self, payload):
        from .literary_search import search_searx
        with patch('core.literary_search.read_json_url', return_value=payload):
            return search_searx('Cuaderno lunar')

    def test_one_failed_engine_preserves_other_results(self):
        result = self.search({'results': [{'title': 'Cuaderno lunar', 'url': PAGE['url'], 'content': 'Una novela.'}],
                             'unresponsive_engines': [['openlibrary', 'timeout']]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.providers['openlibrary'], 'timeout')

    def test_malformed_rows_do_not_poison_valid_rows(self):
        result = self.search({'results': [None, {'title': ['bad'], 'url': PAGE['url'], 'content': {'bad': True}},
            {'title': 'Cuaderno lunar', 'url': PAGE['url'], 'content': 'Una novela.'}], 'unresponsive_engines': []})
        self.assertEqual(len(result), 1)

    def test_bibliographic_hit_without_snippet_is_not_dropped(self):
        result = self.search({'results': [{'title': BOOK['title'], 'url': BOOK['url'], 'content': ''}],
                             'unresponsive_engines': []})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['description'], '')

    def test_successful_search_is_cached_but_empty_and_failure_differ(self):
        from .literary_search import search_searx
        payload = {'results': [{'title': BOOK['title'], 'url': BOOK['url'], 'content': 'Una novela.'}],
                   'unresponsive_engines': []}
        with patch('core.literary_search.read_json_url', return_value=payload) as fetch:
            search_searx('Cuaderno lunar'); search_searx('Cuaderno lunar')
        self.assertEqual(fetch.call_count, 1)
        cache.clear()
        self.assertEqual(self.search({'results': [], 'unresponsive_engines': []}).status, 'empty')
        cache.clear()
        self.assertEqual(self.search({'results': [], 'unresponsive_engines': [['mwmbl', 'timeout']]}).status,
                         'unavailable')

    def test_timeout_is_not_reported_as_empty_and_does_not_leak_errors(self):
        from .literary_search import search_searx
        with patch('core.literary_search.read_json_url', side_effect=TimeoutError('private-token')) as fetch:
            first = search_searx('Cuaderno lunar'); second = search_searx('Otra novela')
        self.assertEqual(first.status, 'timeout')
        self.assertEqual(second.status, 'cooldown')
        self.assertEqual(fetch.call_count, 1)
        self.assertNotIn('private-token', str(first.providers))

    def test_malformed_envelopes_do_not_masquerade_as_empty_results(self):
        for payload in (None, [], {'results': {}}, {'results': [], 'unresponsive_engines': 'invalid'}):
            cache.clear()
            self.assertEqual(self.search(payload).status, 'invalid_response')


class NarrativeRecoveryTests(SimpleTestCase):
    def test_character_list_needs_its_named_entities_in_the_cited_proof_even_in_a_plot(self):
        from .literary_quality import validate_audit
        source = canonical_sources([PAGE])[0]
        statement = 'La obra presenta personajes secundarios como Bruno Salas y Celia Marín.'
        draft = {'status': 'answer', 'basis': 'sources', 'text': statement,
                 'citations': [source['id']], 'books': [], 'needs_web': False}
        plan = {'questions': ['Dime la trama de Cuaderno lunar'], 'search_queries': [],
                'needs_contents': True, 'needs_fresh_sources': False, 'spoilers_requested': False}
        audit = {'decision': 'approve', 'only_books': True, 'coverage': [{'question_id': 1, 'status': 'answered'}],
                 'claims': [{'statement': statement, 'verdict': 'supported', 'source_id': source['id'],
                             'evidence': 'Ana viaja a una estación lunar para buscar a su hermano.'}],
                 'issues': [], 'search_queries': []}
        with self.assertRaises(ValueError):
            validate_audit(audit, plan, draft, [source], plan['questions'][0], strict_facts=True)

    def test_greeting_does_not_hide_the_narrative_request(self):
        for prefix in ('Hola, ', 'Hola. ', 'Buenas tardes, '):
            request = request_for(prefix + 'dime la trama de Cuaderno lunar')
            self.assertIsNotNone(request)
            self.assertEqual(request['title'], BOOK['title'])
        self.assertIsNone(request_for('Hola, mi contraseña es privada'))

    def test_unrecognized_plot_phrasing_cannot_dump_search_fragments(self):
        from .ai_quick_answers import reference_answer
        self.assertIsNone(reference_answer('Puedes decirme algo sobre la trama de Cuaderno lunar', [PAGE]))

    def test_membership_and_character_scopes_are_not_a_plot(self):
        from .ai_narrative_answers import _task_content
        for description in ('Cuaderno lunar, de Ana Robles.',
                            'Personajes (descripciones del artículo): Ana busca una estación lunar.'):
            self.assertFalse(_task_content({'task': 'summary'}, {**PAGE, 'description': description}))
        self.assertFalse(_task_content({'task': 'summary'}, {**PAGE, 'evidence_scope': 'characters'}))

    def test_long_licensed_premise_can_omit_a_final_optional_purpose_clause(self):
        from .ai_narrative_answers import direct_answer
        premise = 'La novela narra el viaje de Ana a una estación lunar para encontrar a su hermano'
        purpose = ', con el propósito de ' + 'recuperar los documentos perdidos y comprender el misterio de la expedición ' * 4 + '.'
        page = {**PAGE, 'description': premise + purpose}
        result = direct_answer('Dime la trama de Cuaderno lunar', request_for('Dime la trama de Cuaderno lunar'), [BOOK, page])
        self.assertIsNotNone(result)
        self.assertIn(premise + '.', result.text)
        for claim in result.diagnostics['audit']['claims']:
            self.assertIn(claim['evidence'], page['description'])

    def test_manga_synthesis_preserves_the_original_medium_in_its_context(self):
        from types import SimpleNamespace
        from .ai_narrative_answers import synthesize_answer
        page = {**PAGE, 'identity_text': 'Cuaderno lunar es un manga escrito por Ana Robles. Adaptado a anime.'}
        seen = []
        class Client:
            calls = 0
            usage = {}
            stage_timings = []
            def __call__(self, stage, prompt, context, model):
                seen.append(context)
                raise TimeoutError('controlled')
        with patch('core.literary_ai.build_assistant', return_value=(
                SimpleNamespace(answer_model='local', guard_model='local'), Client())):
            synthesize_answer('Dime la trama de Cuaderno lunar', request_for('Dime la trama de Cuaderno lunar'),
                              canonical_sources([BOOK, page]), SimpleNamespace())
        self.assertEqual(seen[0]['literary_format'], 'manga')
        self.assertIn('manga original', seen[0]['message'])

    def test_supported_character_list_preserves_names_but_unrelated_proof_is_rejected(self):
        from .literary_quality import unsupported_character_list_claim
        text = 'Los personajes principales son Bruno Salas y Celia Marín, quienes viajan al puerto.'
        self.assertFalse(unsupported_character_list_claim(text, 'Bruno Salas y Celia Marín viajan al puerto.'))
        self.assertTrue(unsupported_character_list_claim(text, 'Un barco llega al puerto.'))

    def test_plot_generation_does_not_receive_membership_as_narrative_content(self):
        from types import SimpleNamespace
        from .ai_narrative_answers import synthesize_answer
        member = {**PAGE, 'url': 'https://www.wikidata.org/wiki/Q123', 'source': 'Wikidata',
                  'description': 'Bruno: Personaje registrado para esta obra en Wikidata',
                  'character_facts': [{'name': 'Bruno', 'role': 'Personaje registrado para esta obra en Wikidata'}]}
        seen = []
        class Client:
            calls = 0
            usage = {}
            stage_timings = []
            def __call__(self, stage, prompt, context, model):
                seen.extend(context['sources'])
                raise TimeoutError('controlled')
        with patch('core.literary_ai.build_assistant', return_value=(
                SimpleNamespace(answer_model='local', guard_model='local'), Client())):
            synthesize_answer('Dime la trama de Cuaderno lunar', request_for('Dime la trama de Cuaderno lunar'),
                              canonical_sources([BOOK, member, PAGE]), SimpleNamespace())
        self.assertFalse(any(source.get('url') == member['url'] for source in seen))
        self.assertTrue(any(source.get('url') == PAGE['url'] for source in seen))

    def test_series_of_novels_is_literary_evidence_not_an_adaptation(self):
        page = {**deepcopy(PAGE), 'title': 'Crónicas lunares',
                'identity_text': 'Crónicas lunares es una serie de novelas escritas por Ana Robles.'}
        self.assertTrue(bound_sources(request_for('Dime la trama de Crónicas lunares'), [page]))

    def test_manga_can_bind_to_its_author_despite_later_anime_mention(self):
        book = {**BOOK, 'categories': ['Manga']}
        page = {**PAGE, 'identity_text': 'Cuaderno lunar es un manga escrito por Ana Robles. '
                'Tiene una adaptación de anime.'}
        sources = bound_sources(request_for('Dime la trama del manga Cuaderno lunar'), [book, page])
        self.assertTrue(any(source['kind'] == 'web' for source in sources))

    def test_anime_only_information_is_not_used_for_the_manga(self):
        page = {**PAGE, 'identity_text': 'Cuaderno lunar es una serie de anime basada en el manga de Ana Robles.'}
        self.assertFalse(bound_sources(request_for('Dime la trama del manga Cuaderno lunar'), [page]))

    @override_settings(LITMATE_AI_USE_WEB=True, LITMATE_AI_USE_OPENLIBRARY=False,
                       LITMATE_AI_USE_WIKIDATA=False)
    def test_identity_only_does_not_stop_plot_research(self):
        identity = {**PAGE, 'description': PAGE['identity_text']}
        with patch('core.ai_quick_answers.quick_knowledge_sources', return_value=canonical_sources([BOOK, identity])), \
             patch('core.ai_library_router.sources_for_request', return_value=[]), \
             patch('core.literary_search.search_wikipedia', return_value=[PAGE]) as search, \
             patch('core.ai_persistent_router.persist_sources'):
            sources = retrieve_sources('Dime la trama de Cuaderno lunar', request_for('Dime la trama de Cuaderno lunar'), [])
        search.assert_called_once()
        self.assertTrue(any('estación lunar' in source['description'] for source in sources))
