"""Aceptación de identificación con recuerdos difusos, hipótesis y sugerencias.

Las pruebas usan las fichas locales incluidas y un catálogo temporal. No
consultan Internet, no escriben en la base de producción y distinguen una
identificación respaldada de una hipótesis o de una sugerencia temática.
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings

from .ai_identification_details import identification_recall_answer
from .ai_presentation import build_book_cards
from .literary_ai import (adjust_route_for_message, literary_scope_hint,
                          looks_literary, simple_literary_route)
from .literary_ai_views import HISTORY_KEY
from .literary_identity import same_work
from .literary_knowledge import prepare_seed_knowledge
from .literary_research import is_plot_description, is_topic_recommendation
from .models import Autor, Libro


Q1 = 'Un niño que vivía en un planeta diminuto, cuidaba una rosa y conoció a un zorro'
Q2 = 'Alguien despierta convertido en un insecto horrible y su familia lo rechaza'
Q3 = 'Una sociedad donde se prohíben los libros y los queman'
Q4 = 'Una historia sobre vigilancia constante y ausencia de libertad'
Q5 = 'Una historia sobre la soledad y la búsqueda de identidad'
Q6 = 'Una persona comete un crimen y luego la culpa la destruye'
Q7_FIRST = 'Una persona despierta convertida en un insecto'
Q7_SECOND = 'Además, su familia lo rechaza'
Q8 = ('Una historia sobre una familia que vive durante generaciones en un pueblo, '
      'con tragedia y fantasía')


class CandidateBoundaryTests(SimpleTestCase):
    def test_vague_remembered_novel_is_not_replaced_by_a_generic_suggestion(self):
        from .literary_research import rank_candidates
        message = 'Recuerdo una novela en la que dos amigos viajan y cambian su forma de ver la vida'
        source = {'kind': 'book', 'title': 'Otro relato', 'author': 'Autora',
                  'description': 'Novela sobre la vida de los habitantes de un pueblo.',
                  'candidate_origin': 'catalog'}
        self.assertEqual(rank_candidates(message, [source]), [])
        with patch('core.ai_identification_details.identification_answer', return_value=None), \
             patch('core.literary_candidates.candidate_sources', return_value=([source], message, False)):
            result = identification_recall_answer(message)
        self.assertEqual(result.status, 'clarification')
        self.assertEqual(result.books, [])

    def test_generic_friends_and_form_cannot_identify_a_work(self):
        from .literary_research import rank_candidates
        source = {'kind': 'book', 'title': 'Un relato distinto', 'author': 'Autora',
                  'description': 'Siete amigos se enfrentan a una entidad que adopta otra forma.'}
        self.assertEqual(rank_candidates('Recuerdo dos amigos que viajan y cambian su forma de ver la vida', [source]), [])

    def test_explicit_incompatible_counts_are_not_a_match(self):
        from .literary_research import rank_candidates
        source = {'kind': 'book', 'title': 'Obra sintética', 'author': 'Autora',
                  'description': 'Siete dragones custodian un diamante dentro de un volcán.'}
        self.assertEqual(rank_candidates('Recuerdo dos dragones que custodian un diamante en un volcán', [source]), [])
        self.assertTrue(rank_candidates('Recuerdo siete dragones que custodian un diamante en un volcán', [source]))

    def test_abstract_topic_with_metadata_only_does_not_generate_and_repair(self):
        from unittest.mock import Mock
        from .literary_ai import LiteraryAssistant
        message = 'Busco un libro sobre el deseo de pertenecer y el miedo a ser diferente'
        route = {'decision': 'allow', 'intent': 'recommend', 'queries': [message],
                 'candidates': [], 'followup': False, 'clarification': ''}
        llm = Mock(side_effect=[route])
        recorded = json.loads((Path(__file__).parents[1] / 'reports' /
            'recuerdos_opencode_20261031' / 'http_final_10.json').read_text(encoding='utf8'))
        source = recorded['rows'][-1]['evidence'][0]
        search = Mock(return_value=[source])
        web = Mock(return_value=[])
        assistant = LiteraryAssistant(llm, search, web_search=web, quality_checks=True,
            require_book_sources=True, fast_recommendations=True, research_enabled=True)
        result = assistant.reply(message, [])
        self.assertEqual(result.status, 'clarification')
        self.assertEqual(result.intent, 'recommend')
        self.assertEqual(result.books, [])
        self.assertEqual(llm.call_count, 1)
        self.assertEqual(search.call_count, 1)
        self.assertTrue(result.diagnostics.get('insufficient_topic_metadata'), str(result))
        web.assert_not_called()

    def test_clarification_without_a_book_keeps_the_readers_clues(self):
        from .literary_candidates import contextual_query
        previous = 'Recuerdo una niña que sigue a un conejo blanco'
        current = 'Además, cae por una madriguera'
        history = [{'accepted': True, 'intent': 'identify', 'question': previous,
                    'books': [], 'sources': []}]
        self.assertEqual(contextual_query(current, history), (previous + ' ' + current, True))

    def test_generic_verbs_alone_do_not_propose_a_candidate(self):
        from .literary_research import rank_candidates
        source = {'kind': 'book', 'title': 'Una obra distinta', 'author': 'Autora',
                  'description': 'La novela sigue a una persona que vive y conoce gente.'}
        for verb in ('sigue', 'vive', 'conoce'):
            with self.subTest(verb=verb):
                self.assertEqual(rank_candidates('Recuerdo una niña que ' + verb + ' un conejo', [source]), [])

    def test_distinctive_clues_retrieve_a_synthetic_work_despite_generic_distractor(self):
        from .literary_research import rank_candidates
        sources = [
            {'kind': 'book', 'title': 'Distractor', 'author': 'Autor',
             'description': 'La novela sigue a una familia.'},
            {'kind': 'book', 'title': 'Obra sintética', 'author': 'Autora',
             'description': 'Una niña sigue un conejo blanco hasta una madriguera.'}]
        ranked = rank_candidates('Recuerdo una niña que sigue a un conejo blanco y cae por una madriguera', sources)
        self.assertEqual([item['title'] for item in ranked], ['Obra sintética'])
        self.assertEqual(ranked[0]['confidence'], 'supported')

    def test_a_shared_colour_alone_is_not_narrative_identity(self):
        from .literary_research import rank_candidates
        source = {'kind': 'book', 'title': 'Otra obra', 'author': 'Autora',
                  'description': 'Una reina blanca gobierna un castillo.'}
        self.assertEqual(rank_candidates('Una niña sigue un conejo blanco hasta una madriguera', [source]), [])

    def test_alice_clues_without_matching_evidence_ask_for_more_clues(self):
        source = {'kind': 'book', 'title': 'Cien años de soledad', 'author': 'Gabriel García Márquez',
                  'description': 'La novela sigue la historia de la familia Buendía en Macondo.',
                  'candidate_origin': 'catalog'}
        message = 'Recuerdo una niña que sigue a un conejo blanco y cae por una madriguera'
        with patch('core.ai_identification_details.identification_answer', return_value=None), \
             patch('core.literary_candidates.candidate_sources', return_value=([source], message, False)):
            result = identification_recall_answer(message)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'clarification')
        self.assertEqual(result.books, [])
        self.assertNotIn('Cien años', result.text)

    def test_six_real_queries_replayed_with_recorded_evidence(self):
        evidence = json.loads((Path(__file__).parents[1] / 'reports' /
            'recuerdos_opencode_20261031' / 'real_readonly.json').read_text(encoding='utf8'))
        for row in evidence['rows']:
            message = row['query']
            with self.subTest(expected=row['expected']), \
                 patch('core.ai_identification_details.identification_answer', return_value=None), \
                 patch('core.literary_candidates.candidate_sources', return_value=(row['retrieved'], message, False)):
                result = identification_recall_answer(message)
                self.assertIsNotNone(result)
                if row['expected'].startswith('Alicia'):
                    self.assertEqual(result.status, 'clarification')
                    self.assertEqual(result.books, [])
                else:
                    self.assertIn(row['expected'].casefold(), result.books[0]['title'].casefold())

    def test_changed_topic_does_not_reuse_an_old_identification(self):
        from .literary_candidates import contextual_query
        history = [
            {'accepted': True, 'intent': 'identify', 'question': Q1,
             'books': [{'title': 'El principito', 'author': 'Antoine de Saint-Exupéry'}]},
            {'accepted': True, 'intent': 'summary', 'question': 'Resume otra novela'}]
        self.assertEqual(contextual_query(Q7_SECOND, history), (Q7_SECOND, False))

    def test_relevant_catalogue_result_survives_candidate_limit(self):
        from .literary_candidates import candidate_sources
        unrelated = [{'kind': 'book', 'title': f'Ficha {index}', 'author': 'Autor',
                      'description': 'Una receta de cocina.'} for index in range(45)]
        target = {'kind': 'book', 'title': 'Registro de prueba', 'author': 'Autora',
                  'description': 'Vigilancia constante y ausencia de libertad.'}
        with patch('core.literary_knowledge.search_knowledge', return_value=[]), \
             patch('core.literary_candidates._bundled_candidates', return_value=unrelated), \
             patch('core.literary_search.search_catalog', return_value=[target]):
            sources, _, _ = candidate_sources(Q4, include_memory=False)
        self.assertIn(target, sources)

    def test_memory_cannot_reintroduce_an_explicitly_rejected_work(self):
        from .literary_candidates import candidate_sources
        rejected = {'kind': 'book', 'title': 'Obra descartada', 'author': 'Autora',
                    'description': 'Una familia en un pueblo.'}
        history = [{'accepted': True, 'intent': 'identify', 'question': Q8,
                    'books': [rejected]}]
        with patch('core.literary_knowledge.search_knowledge', return_value=[]), \
             patch('core.literary_candidates._bundled_candidates', return_value=[]), \
             patch('core.literary_search.search_catalog', return_value=[]), \
             patch('core.literary_candidates._memory_candidates', return_value=[rejected]):
            sources, _, _ = candidate_sources('No es Obra descartada', history=history)
        self.assertEqual(sources, [])


class RecallKnowledgeMixin:
    def prepare_local_knowledge(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.knowledge_database = Path(directory.name) / 'knowledge.sqlite3'
        prepare_seed_knowledge(self.knowledge_database)
        settings = override_settings(
            LITMATE_KNOWLEDGE_DB=self.knowledge_database,
            LITMATE_AI_REQUIRE_BOOK_SOURCES=True)
        settings.enable()
        self.addCleanup(settings.disable)


class LiteraryRecallAcceptanceTests(RecallKnowledgeMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        def book(title, author, description, cover=''):
            writer = Autor.objects.create(nombre=author)
            return Libro.objects.create(titulo=title, autor=writer, sinopsis=description,
                                        portada_url=cover or None)

        book('1984', 'George Orwell',
             'Una sociedad vigilada constantemente por el Gran Hermano, donde la '
             'ausencia de libertad y la represión dominan la vida de sus habitantes.',
             'https://covers.openlibrary.org/b/id/1984-M.jpg')
        book('Fahrenheit 451', 'Ray Bradbury',
             'En un futuro donde los libros están prohibidos y los bomberos se '
             'dedican a quemar cualquier ejemplar que encuentran.',
             'https://covers.openlibrary.org/b/id/451-M.jpg')
        book('Un mundo feliz', 'Aldous Huxley',
             'Una sociedad futura que sacrifica la libertad individual en nombre '
             'del orden y la estabilidad.')
        book('La casa de los espíritus', 'Isabel Allende',
             'La novela sigue a la familia Trueba a lo largo de cuatro generaciones '
             'en un país latinoamericano, entre tragedias y elementos fantásticos.')
        book('Historia de una escalera', 'Antonio Buero Vallejo',
             'Una historia sobre una persona y su familia a lo largo del tiempo.')

    def setUp(self):
        cache.clear()
        self.prepare_local_knowledge()

    def assert_identified(self, result, title, author):
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'answered')
        self.assertEqual(result.intent, 'identify')
        self.assertEqual(result.books[0]['title'], title)
        self.assertEqual(result.books[0]['author'], author)
        self.assertIn(title, result.text)
        self.assertTrue(result.diagnostics['local_identification_fast_path'])
        self.assertTrue(all(source.get('kind') == 'book' for source in result.sources))
        self.assertTrue(all(same_work(source, result.sources[0]) for source in result.sources))

    def test_q1_child_planet_and_fox_identifies_the_little_prince(self):
        self.assert_identified(identification_recall_answer(Q1), 'El principito',
                               'Antoine de Saint-Exupéry')

    def test_q2_insect_and_family_identifies_the_metamorphosis_from_bundled_reading(self):
        result = identification_recall_answer(Q2)
        self.assert_identified(result, 'La metamorfosis', 'Franz Kafka')

    def test_q3_burning_books_identifies_fahrenheit_451_through_expanded_catalogue(self):
        self.assert_identified(identification_recall_answer(Q3), 'Fahrenheit 451',
                               'Ray Bradbury')

    def test_q4_surveillance_without_the_word_book_identifies_1984(self):
        self.assert_identified(identification_recall_answer(Q4), '1984', 'George Orwell')

    def test_q5_abstract_solitude_returns_a_grounded_hypothesis(self):
        result = identification_recall_answer(Q5)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'answered')
        self.assertEqual(result.intent, 'identify')
        self.assertEqual(len(result.books), 1)
        self.assertEqual(result.diagnostics['candidate_confidence'], 'possible')
        self.assertIn('hipótesis', result.text.casefold())
        self.assertNotIn('podrías estar buscando', result.text.casefold())

    def test_q6_plot_without_names_or_distinct_objects_identifies_crime_and_punishment(self):
        self.assert_identified(identification_recall_answer(Q6), 'Crimen y castigo',
                               'Fiódor M. Dostoievski')

    def test_q7_second_message_adds_a_clue_to_the_previous_hypothesis(self):
        first = identification_recall_answer(Q7_FIRST)
        self.assert_identified(first, 'La metamorfosis', 'Franz Kafka')
        history = [{'accepted': True, 'intent': 'identify', 'question': Q7_FIRST,
                    'books': first.books, 'sources': first.sources}]
        second = identification_recall_answer(Q7_SECOND, history=history)
        self.assert_identified(second, 'La metamorfosis', 'Franz Kafka')
        self.assertIn('familia', second.diagnostics['matched_clues'])
        self.assertTrue(second.diagnostics.get('used_conversation_context'))

    def test_alternative_suggestion_is_not_presented_as_an_identification(self):
        result = identification_recall_answer('Una historia sobre una persona')
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'answered')
        self.assertEqual(result.diagnostics['candidate_confidence'], 'suggestion')
        self.assertTrue(result.diagnostics.get('alternative_suggestion'))
        self.assertEqual(result.books[0]['title'], 'Historia de una escalera')
        self.assertIn('sugerencia', result.text.casefold())
        self.assertNotIn('podrías estar buscando', result.text.casefold())

    def test_negative_correction_discards_the_previous_candidate(self):
        first = identification_recall_answer(Q7_FIRST)
        history = [{'accepted': True, 'intent': 'identify', 'question': Q7_FIRST,
                    'books': first.books, 'sources': first.sources}]
        result = identification_recall_answer(
            'No es La metamorfosis; una persona se convierte en un animal y su familia lo rechaza',
            history=history)
        self.assertIsNotNone(result)
        self.assertNotIn('La metamorfosis', {book['title'] for book in result.books})

    def test_q8_two_similar_family_sagas_are_presented_as_two_possibilities(self):
        result = identification_recall_answer(Q8)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'answered')
        self.assertEqual(result.intent, 'identify')
        self.assertEqual(result.diagnostics['candidate_confidence'], 'ambiguous')
        titles = {book['title'] for book in result.books}
        self.assertIn('Cien años de soledad', titles)
        self.assertIn('La casa de los espíritus', titles)
        self.assertIn('posibilidad', result.text.casefold())
        self.assertNotIn('podrías estar buscando', result.text.casefold())

    def test_catalog_identification_keeps_cover_for_cards(self):
        result = identification_recall_answer(Q4)
        self.assertIsNotNone(result)
        cards = build_book_cards(result)
        self.assertEqual(cards[0]['title'], '1984')
        self.assertEqual(cards[0]['image_url'],
                         'https://covers.openlibrary.org/b/id/1984-M.jpg')

    def test_explicit_recommendation_is_not_captured_by_identification(self):
        self.assertIsNone(identification_recall_answer(
            'Recomiéndame libros sobre la soledad y la identidad'))
        self.assertTrue(is_topic_recommendation(
            'Recomiéndame libros sobre la soledad y la identidad'))

    def test_author_and_summary_questions_keep_their_normal_routes(self):
        for message in ('¿Quién escribió 1984?', 'Resume 1984'):
            with self.subTest(message=message):
                self.assertIsNone(identification_recall_answer(message))
        self.assertEqual(simple_literary_route('¿Quién escribió la novela 1984?')['intent'],
                         'author')

    def test_non_literary_queries_are_not_identified(self):
        for message in ('¿Cómo se prepara una tortilla?', 'Calcula 2 + 2'):
            with self.subTest(message=message):
                self.assertIsNone(identification_recall_answer(message))

    def test_narrative_descriptions_reach_the_literary_route(self):
        self.assertTrue(is_plot_description(Q4))
        self.assertFalse(is_plot_description(
            'Recomiéndame una historia sobre la soledad'))
        self.assertTrue(looks_literary(Q4, []))
        self.assertTrue(literary_scope_hint(Q4))
        route = adjust_route_for_message(
            {'decision': 'reject', 'intent': 'conversation', 'queries': []}, Q4)
        self.assertEqual(route['decision'], 'allow')
        self.assertEqual(route['intent'], 'identify')
        self.assertEqual(simple_literary_route(Q4)['intent'], 'identify')

    def test_book_source_requirement_remains_enabled(self):
        from django.conf import settings
        self.assertTrue(settings.LITMATE_AI_REQUIRE_BOOK_SOURCES)


class IdentificationEndpointCompatibilityTests(RecallKnowledgeMixin, TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.prepare_local_knowledge()
        author = Autor.objects.create(nombre='George Orwell')
        Libro.objects.create(
            titulo='1984', autor=author,
            sinopsis=('Una sociedad vigilada constantemente por el Gran Hermano, '
                      'donde la ausencia de libertad y la represión dominan la vida.'),
            portada_url='https://covers.openlibrary.org/b/id/1984-M.jpg')

    def test_sse_identification_publishes_cards_covers_and_history(self):
        user = get_user_model().objects.create_user(username='recall-endpoint-reader')
        self.client.force_login(user)
        with patch('core.literary_ai_views.build_assistant') as model, \
                patch('core.literary_search.retrieve_books') as catalog, \
                patch('core.literary_search.retrieve_web') as web, \
                patch('core.literary_search.search_google') as google, \
                patch('core.literary_ai_views.acquire') as lock:
            response = self.client.post('/chatbot_query/', json.dumps({'message': Q4}),
                                        content_type='application/json')
            if not hasattr(response, 'streaming_content'):
                self.fail(response.content.decode('utf-8'))
            events = b''.join(response.streaming_content).decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertIn('1984', events)
        self.assertIn('covers.openlibrary.org/b/id/1984-M.jpg', events)
        for dependency in (model, catalog, web, google, lock):
            dependency.assert_not_called()
        turn = self.client.session[HISTORY_KEY]['turns'][-1]
        self.assertEqual(turn['intent'], 'identify')
        self.assertEqual(turn['books'][0]['title'], '1984')
