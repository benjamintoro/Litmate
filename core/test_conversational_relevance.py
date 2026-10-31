"""Regresiones de pertinencia e intención; fichas sintéticas, sin servicios."""
from unittest.mock import Mock, patch
from urllib.error import URLError
from types import SimpleNamespace
import time

from django.test import SimpleTestCase

from .ai_presentation import build_book_cards
from .ai_related_recommendations import related_recommendation_answer
from .literary_ai import LiteraryAssistant, ProviderUnavailable, simple_literary_route
from .literary_research import publication_matches, public_research_queries
from .literary_sources import SearchResults
from .local_llm import OllamaJSON
from .test_local_ai import SHOW
from .test_related_recommendation_cards import book, history


class ConversationalRelevanceTests(SimpleTestCase):
    def test_elliptical_singular_request_keeps_one_option(self):
        from .literary_ai import requested_book_count
        from .ai_quick_answers import _simple_topic_request
        self.assertEqual(requested_book_count('Dame otro que trate sobre química en la cocina'), 1)
        self.assertTrue(_simple_topic_request('Dame otro que trate sobre química en la cocina',
                                              'Dame otro que trate sobre química en la cocina'))
    def test_science_alone_does_not_make_a_culinary_science_recommendation(self):
        base = book('El laboratorio de los alimentos', 'Elena Robles',
                    ['Science', 'Cooking', 'Food science'])
        wrong = book('Océanos profundos', 'Bruno Paz', ['Science', 'Oceanography'], 2)
        good = book('Transformaciones de los alimentos', 'Clara Lagos',
                    ['Cooking', 'Food science', 'Chemistry'], 3)
        result = related_recommendation_answer('Recomiéndame otros tres similares', history(base),
                                               Mock(return_value=[wrong, good]))
        self.assertIsNotNone(result)
        self.assertEqual([card['title'] for card in build_book_cards(result)], [good['title']])
        self.assertNotIn(wrong['title'], result.text)

    def test_science_cooking_reference_does_not_become_generic_recipes(self):
        base = book('Laboratorio de alimentos', 'Elena Robles', ['Science'])
        base['description'] = 'La cocina se explica mediante química. La cocina transforma alimentos.'
        generic = book('Recetas para principiantes', 'Bruno Paz', ['Cooking'], 2)
        self.assertIsNone(related_recommendation_answer('Otro similar', history(base),
                                                       Mock(return_value=[generic])))

    def test_specific_child_subject_beats_its_parent_in_queries_and_candidates(self):
        base = book('La torre negra', 'Elena Robles', ['Fiction', 'Fantasy', 'Dark fantasy'])
        broad = book('Aventuras encantadas', 'Bruno Paz', ['Fiction', 'Fantasy'], 2)
        narrow = book('El castillo de sombras', 'Clara Lagos', ['Dark fantasy'], 3)
        search = Mock(return_value=[broad, narrow])
        result = related_recommendation_answer('Otro similar', history(base), search)
        self.assertEqual([item['title'] for item in result.books], [narrow['title']])
        self.assertIn('Dark fantasy', search.call_args_list[0].args[0])

    def test_shared_history_does_not_erase_country(self):
        base = book('Una historia del Perú', 'Elena Robles', ['History', 'Peru'])
        wrong = book('Europa antigua', 'Bruno Paz', ['History', 'Europe'], 2)
        good = book('Historia andina', 'Clara Lagos', ['History', 'Peru'], 3)
        result = related_recommendation_answer('Otro similar', history(base),
                                               Mock(return_value=[wrong, good]))
        self.assertEqual([item['title'] for item in result.books], [good['title']])

    def test_independent_themes_do_not_accept_only_a_broad_parent_or_format(self):
        cases = (
            (['Fantasy', 'Dark fantasy'], ['Dark fantasy'], ['Fantasy']),
            (['History', 'Chile'], ['History', 'Chile'], ['History', 'Peru']),
            (['History', 'Peru'], ['History', 'Peru'], ['History', 'Chile']),
            (['Philosophy', 'Ethics'], ['Ethics'], ['Philosophy', 'Logic']),
            (['Astronomy', 'Stellar evolution'], ['Astronomy', 'Stellar evolution'], ['Astronomy']),
            (['Manga', 'Martial arts'], ['Manga', 'Martial arts'], ['Manga', 'Romance']),
            (['Romance', 'Historical romance'], ['Historical romance'], ['Romance']),
            (['Science', 'Microbiology'], ['Science', 'Microbiology'], ['Science', 'Astronomy']),
            (['Cooking', 'Food preservation'], ['Food preservation'], ['Cooking']),
            # Independent holdouts: not cooking, countries or the named failures.
            (['Art', 'Wood engraving'], ['Wood engraving'], ['Art', 'Watercolors']),
            (['Reference', 'Polar exploration'], ['Polar exploration'], ['Reference', 'Gardening']),
        )
        for base_tags, valid_tags, wrong_tags in cases:
            with self.subTest(tags=base_tags):
                base = book('Una obra de referencia', 'Elena Robles', base_tags)
                good = book('Otra lectura documentada', 'Clara Lagos', valid_tags, 2)
                wrong = book('Una lectura distinta', 'Irene Sol', wrong_tags, 3)
                result = related_recommendation_answer('Recomiéndame otros tres similares', history(base),
                                                       Mock(return_value=[wrong, good]))
                self.assertIsNotNone(result)
                self.assertEqual([item['title'] for item in result.books], [good['title']])

    def test_audience_categories_are_not_a_subject_and_synopsis_can_supply_it(self):
        base = book('Aprender a pensar', 'Elena Robles',
                    ['Juvenile Fiction / General', 'Juvenile Nonfiction / General'])
        base['description'] = 'Esta novela recorre la historia de la filosofía y enseña filosofía.'
        wrong = book('Una aventura de elefantes', 'Irene Sol', ['Juvenile Fiction / Animals'], 2)
        good = book('Preguntas filosóficas', 'Clara Lagos', ['Philosophy'], 3)
        result = related_recommendation_answer('Recomiéndame otros tres similares', history(base),
                                               Mock(return_value=[wrong, good]))
        self.assertIsNotNone(result)
        self.assertEqual([item['title'] for item in result.books], [good['title']])

    def test_medical_subject_in_a_romance_is_not_a_scientific_manual(self):
        base = book('Principios de bacteriología', 'Elena Robles', ['Medical'])
        wrong = book('Bodas en el hospital', 'Irene Sol', ['Fiction, Romance, Medical'], 2)
        good = book('Una introducción clínica', 'Clara Lagos', ['Medical'], 3)
        result = related_recommendation_answer('Recomiéndame otros tres similares', history(base),
                                               Mock(return_value=[wrong, good]))
        self.assertEqual([item['title'] for item in result.books], [good['title']])

    def test_foreign_categories_share_existing_bilingual_topic_vocabulary(self):
        base = book('La cocina explicada', 'Elena Robles', ['Cocina', 'Química'])
        good = book('Cooking experiments', 'Clara Lagos', ['Cooking', 'Chemistry'], 3)
        result = related_recommendation_answer('Otro similar', history(base), Mock(return_value=[good]))
        self.assertIsNotNone(result)

    def test_genre_followup_uses_verified_description_and_preserves_active_work(self):
        from .ai_quick_answers import catalogue_lookup_answer
        from .literary_identity import resolve_followup_context
        base = book('Laboratorio de alimentos', 'Elena Robles', ['Science'])
        base['description'] = 'Este libro explica la ciencia detrás de la cocina y sus transformaciones.'
        search = Mock(return_value=[base])
        result = catalogue_lookup_answer('¿De qué género es ese libro?', history(base), search)
        self.assertIsNotNone(result)
        self.assertIn('cocina', result.text)
        self.assertEqual(result.books[0]['title'], base['title'])
        turns = history(base) + [{'accepted': True, 'question': '¿De qué género es ese libro?',
            'answer': result.text, 'books': result.books, 'sources': result.sources}]
        self.assertEqual(resolve_followup_context('Recomiéndame otros similares', turns)['books'][0]['title'],
                         base['title'])

    def test_why_similar_is_an_explanation_not_a_new_recommendation(self):
        from .ai_related_recommendations import related_explanation_answer
        base = book('Laboratorio de alimentos', 'Elena Robles', ['Science', 'Cooking'])
        base['description'] = 'Este libro explica la ciencia detrás de la cocina y sus transformaciones.'
        other = book('Experimentos culinarios', 'Irene Sol', ['Science', 'Cooking'], 2)
        other['description'] = 'Este libro estudia la ciencia de los alimentos en la cocina.'
        turns = history(base) + [{'accepted': True, 'question': 'Recomiéndame otros similares',
            'intent': 'recommend', 'books': [other], 'sources': [other]}]
        result = related_explanation_answer('¿Por qué se parece el primero?', turns)
        self.assertIsNotNone(result)
        self.assertNotEqual(result.intent, 'recommend')
        self.assertIn('cocina', result.text)
        self.assertEqual(result.diagnostics['model_calls'], 0)

    def test_translation_label_variant_is_not_offered_as_another_book(self):
        base = book('Ciencia & alimentos', 'Elena Robles', ['Science', 'Cooking'])
        edition = book('Ciencia y alimentos / Science and food', 'Elena Robles', ['Science', 'Cooking'], 2)
        other = book('Transformaciones culinarias', 'Irene Sol', ['Science', 'Cooking'], 3)
        result = related_recommendation_answer('Recomiéndame otros tres similares', history(base),
                                               Mock(return_value=[edition, other]))
        self.assertEqual([item['title'] for item in result.books], [other['title']])

    def test_outer_catalogue_fallback_cannot_replace_a_similar_lookup_with_its_base(self):
        from .literary_ai import ChatResult
        from .literary_ai_views import _model_answer
        from django.test import override_settings
        assistant = Mock()
        assistant.reply.return_value = ChatResult('Sin evidencia suficiente.', 'unavailable')
        client = SimpleNamespace(deadline=time.monotonic() + 20)
        with override_settings(LITMATE_AI_USE_WEB=False), \
                patch('core.literary_ai_views.build_assistant', return_value=(assistant, client)), \
                patch('core.ai_catalog_fallback.catalog_fallback') as fallback:
            _model_answer('Recomiéndame otros similares', history(), {}, 'libros sobre ciencia')
        fallback.assert_not_called()

    def test_named_publication_search_never_invents_a_candidate(self):
        for query, term in (
            ('hola quiero leer los libros de el mundo de las sombras me lo recomienda', 'el mundo de las sombras'),
            ('Quiero leer los libros de El mundo de las sombras, ¿me los recomiendas?', 'el mundo de las sombras'),
            ('Quiero leer un libro de Elena Robles', 'elena robles'),
            ('holan quiero leer el libro de Irene Sol', 'irene sol'),
        ):
            with self.subTest(query=query):
                route = simple_literary_route(query)
                self.assertIsNotNone(route)
                self.assertEqual(route['intent'], 'recommend')
                self.assertEqual(route['candidates'], [])
                self.assertIn(term, route['queries'])

    def test_scoped_lookup_does_not_capture_topic_or_multiple_private_tasks(self):
        # These remain the existing topic/general routes, never an inferred author.
        for query in ('Quiero leer un libro de cocina',
                      'Quiero leer un libro de Elena Robles y explica su final',
                      'Quiero leer un libro de Elena Robles mi correo es x@example.org'):
            with self.subTest(query=query):
                route = simple_literary_route(query)
                self.assertTrue(route is None or route['queries'] != ['elena robles'])
        from .literary_research import publication_lookup_target
        for message in ('Quiero leer un libro de lector@example.org',
                        'Quiero leer un libro de https://private.example.org/reader'):
            self.assertEqual(publication_lookup_target(message), '')

    def test_search_keeps_literal_identity_and_not_a_model_guessed_replacement(self):
        message = 'hola quiero leer los libros de el mundo de las sombras me lo recomienda'
        self.assertEqual(public_research_queries(message),
                         ['el mundo de las sombras libros', 'el mundo de las sombras editorial libro'])
        wrong = book('Una casa extraña', 'Elena Robles', ['Fantasy'])
        wrong['description'] = 'Un personaje llamado Sombras viaja por el mundo.'
        self.assertFalse(publication_matches(wrong, 'el mundo de las sombras'))
        self.assertTrue(publication_matches(book('El mundo de las sombras: adaptación', 'Irene Sol'),
                                            'el mundo de las sombras'))


class FailureClassificationTests(SimpleTestCase):
    def test_scoped_publications_with_a_real_synopsis_do_not_regenerate_its_events(self):
        llm = Mock(side_effect=ProviderUnavailable('ollama_no_disponible'))
        source = book('El mundo de las sombras: una adaptación', 'Elena Robles', ['Fantasy'])
        source['description'] = 'La exploradora se pierde y busca el camino de vuelta a casa.'
        assistant = LiteraryAssistant(llm, Mock(return_value=[source]), research_enabled=True,
            quality_checks=True, fast_recommendations=True, require_book_sources=True)
        with patch('core.literary_knowledge.search_knowledge', return_value=[]):
            result = assistant.reply('Quiero leer los libros de el mundo de las sombras')
        self.assertEqual(result.status, 'answered')
        self.assertIn(source['description'], result.text)
        llm.assert_not_called()
    def test_unknown_topic_still_requires_complete_factual_audit(self):
        captured = {}
        def generate(stage, prompt, data, model):
            if stage == 'route':
                return {'decision': 'allow', 'intent': 'recommend',
                        'queries': ['mineralogía experimental'], 'candidates': [],
                        'followup': False, 'clarification': ''}
            if stage == 'answer':
                captured.update(data)
            raise ProviderUnavailable('ollama_no_disponible')
        source = book('Principios de mineralogía', 'Elena Robles', ['Science'])
        assistant = LiteraryAssistant(generate, Mock(return_value=[source]), research_enabled=True,
            quality_checks=True, fast_recommendations=True, require_book_sources=True)
        with patch('core.literary_knowledge.search_knowledge', return_value=[]):
            assistant.reply('Recomiéndame un libro sobre mineralogía experimental')
        self.assertTrue(captured['all_factual_claims_required'])
    def _lookup(self, search, web=None):
        llm = Mock(side_effect=AssertionError('A scoped empty lookup must not generate titles'))
        assistant = LiteraryAssistant(llm, search, web_search=web,
            research_enabled=True, fast_recommendations=True, require_book_sources=True)
        with patch('core.literary_knowledge.search_knowledge', return_value=[]):
            result = assistant.reply('Quiero leer un libro de Elena Robles')
        llm.assert_not_called()
        return result

    def test_real_empty_search_is_not_an_ollama_failure(self):
        result = self._lookup(Mock(return_value=SearchResults(status='empty')))
        self.assertEqual(result.diagnostics['failure_kind'], 'insufficient_evidence')
        self.assertEqual(result.status, 'clarification')
        self.assertFalse(result.books)

    def test_timeout_is_not_relabelled_as_no_such_books(self):
        result = self._lookup(Mock(side_effect=TimeoutError('private service details')))
        self.assertEqual(result.diagnostics['failure_kind'], 'technical_failure')
        self.assertEqual(result.status, 'unavailable')
        self.assertNotIn('private', result.text)

    def test_blocked_search_remains_a_dependency_failure(self):
        result = self._lookup(Mock(return_value=SearchResults(status='rate_limited')))
        self.assertEqual(result.diagnostics['failure_kind'], 'technical_failure')

    def test_unrelated_local_results_do_not_hide_a_failed_external_provider(self):
        result = self._lookup(Mock(return_value=SearchResults(
            [book('Otro mundo', 'Irene Sol')], status='partial',
            providers={'Google Books': 'timeout', 'Open Library': 'empty'})))
        self.assertEqual(result.diagnostics['failure_kind'], 'technical_failure')

    def test_model_failure_can_recover_verified_metadata_without_its_draft(self):
        llm = Mock(side_effect=ProviderUnavailable('ollama_no_disponible'))
        source = book('El mapa del bosque', 'Elena Robles')
        assistant = LiteraryAssistant(llm, Mock(return_value=[source]), research_enabled=True,
            fast_recommendations=True, require_book_sources=True)
        with patch('core.literary_knowledge.search_knowledge', return_value=[]):
            result = assistant.reply('Quiero leer un libro de Elena Robles')
        self.assertEqual(result.status, 'answered')
        self.assertEqual(result.books[0]['title'], source['title'])
        self.assertEqual(result.diagnostics['provider_error'], 'ollama_no_disponible')
        self.assertEqual(result.diagnostics['evidence_state'], 'partial')

    def test_web_failure_is_retained_in_diagnostics(self):
        result = self._lookup(Mock(return_value=[]), Mock(side_effect=OSError('network failed')))
        self.assertEqual(result.diagnostics['failure_kind'], 'technical_failure')
        self.assertTrue(result.diagnostics['dependency_errors'])

    def test_similar_lookup_timeout_is_not_a_claim_of_absent_alternatives(self):
        route = {'decision': 'allow', 'intent': 'recommend', 'queries': [],
                 'candidates': [], 'followup': False, 'clarification': ''}
        base = book('Ciencia de los alimentos', 'Elena Robles', ['Science', 'Cooking'])
        assistant = LiteraryAssistant(Mock(return_value=route), Mock(side_effect=TimeoutError()),
            research_enabled=True, fast_recommendations=True, require_book_sources=True)
        with patch('core.literary_knowledge.search_knowledge', return_value=[]):
            result = assistant.reply('Recomiéndame otros similares', history(base))
        self.assertEqual(result.diagnostics['failure_kind'], 'technical_failure')

    def test_transport_timeout_is_not_misreported_as_invalid_model_json(self):
        client = OllamaJSON()
        with patch('core.local_llm.read_json_url', side_effect=[SHOW, URLError(TimeoutError())]):
            with self.assertRaises(ProviderUnavailable) as raised:
                client('route', 'JSON', {}, 'qwen3.5:4b-q4_K_M')
        self.assertEqual(raised.exception.code, 'ollama_timeout')
        self.assertEqual(client.last_error_detail, 'transport_timeout')

    def test_disconnected_model_is_identified_as_a_transport_failure(self):
        client = OllamaJSON()
        with patch('core.local_llm.read_json_url', side_effect=[SHOW, URLError(ConnectionRefusedError())]):
            with self.assertRaises(ProviderUnavailable) as raised:
                client('route', 'JSON', {}, 'qwen3.5:4b-q4_K_M')
        self.assertEqual(raised.exception.code, 'ollama_no_disponible')
