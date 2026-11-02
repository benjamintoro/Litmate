"""Regresiones del tono conversacional y de continuidad, sin modelo ni red."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from .literary_ai import (LiteraryAssistant, ChatResult, REFUSAL, SHORT_FACTUAL_PROMPT,
                          adjust_route_for_message, has_excerpt, sanitized_history,
                          user_excerpt, validate_route)
from .literary_quality import resolve_followup_books
from .literary_conversation import resolve_topic_context
from .test_literary_ai import FakeLLM, BOOK, CHILE, ROUTE, DRAFT, knowledge


CONVERSATION_ROUTE = {**ROUTE, 'intent': 'conversation', 'queries': [], 'candidates': []}
CONVERSATION_DRAFT = {'status': 'answer', 'basis': 'knowledge', 'citations': [], 'books': [],
                      'needs_web': False, 'text': 'Podemos conversar un rato. ¿Qué te gustaría contarme de tu día?'}


class ConversationEngineTests(SimpleTestCase):
    def test_route_adjusts_literary_scope_characters_and_excerpts(self):
        base = {**ROUTE, 'decision': 'allow', 'intent': 'identify', 'queries': [],
                'candidates': [{'title': 'Don Quijote de la Mancha',
                                'author': 'Miguel de Cervantes'}],
                'followup': False}
        characters = adjust_route_for_message(
            base, '¿Quiénes son los personajes principales de Don Quijote?')
        self.assertEqual(characters['intent'], 'analysis')
        self.assertEqual(characters['candidates'], base['candidates'])

        rejected = {**base, 'decision': 'reject', 'intent': 'analysis', 'candidates': []}
        nobel = adjust_route_for_message(
            rejected, '¿En qué año ganó Jorge Luis Borges el Premio Nobel?')
        self.assertEqual(nobel['decision'], 'allow')
        self.assertEqual(nobel['intent'], 'author')

        quixote = adjust_route_for_message(
            rejected, '¿Quién escribió El Quijote, Gabriel García Márquez?')
        self.assertEqual(quixote['decision'], 'allow')
        self.assertEqual(quixote['intent'], 'author')

        excerpt = adjust_route_for_message(
            base, 'Lee este fragmento: «Elena encontró un cuaderno azul». ¿Quién lo conserva?')
        self.assertEqual(excerpt['intent'], 'analysis')

        self.assertEqual(adjust_route_for_message(
            rejected, '¿Cuál es la capital de Mongolia?')['decision'], 'reject')

    def test_natural_excerpt_intro_keeps_quoted_text(self):
        message = ('Lee este fragmento y dime quién conserva la memoria: '
                   '"Elena encontró un cuaderno azul en la biblioteca del faro."')
        self.assertTrue(has_excerpt(message))
        self.assertIn('Elena encontró un cuaderno azul', user_excerpt(message))

    def test_concept_analysis_is_not_marked_as_a_strict_factual_question(self):
        route = {**ROUTE, 'intent': 'concept', 'queries': [], 'candidates': []}
        draft = {'status': 'answer', 'basis': 'knowledge', 'citations': [], 'books': [],
                 'needs_web': False,
                 'text': 'La relación entre Borges y la filosofía se explora en sus cuentos.'}
        llm = FakeLLM(route=route, answer=draft)
        captured = {}

        def generate(stage, prompt, data, model):
            captured[stage] = (prompt, data)
            return llm(stage, prompt, data, model)

        result = LiteraryAssistant(generate, Mock(return_value=[]),
                                   research_enabled=True).reply(
                                       'Explica la relación entre Borges y la filosofía.')
        self.assertEqual(result.status, 'answered')
        self.assertFalse(captured['answer'][1]['specific_factual_question'])
        self.assertFalse(captured['answer'][0].startswith(SHORT_FACTUAL_PROMPT))

    def test_analysis_with_only_inference_claims_is_not_repaired_for_sources(self):
        text = ('La soledad en Cien años de soledad es una herencia familiar '
                'y un destino cíclico.')
        answer = {'status': 'answer', 'basis': 'knowledge', 'citations': [], 'books': [],
                  'needs_web': False, 'text': text}
        audit = {'decision': 'repair', 'only_books': True,
                 'coverage': [{'question_id': 1, 'status': 'answered'}],
                 'claims': [{'statement': text, 'verdict': 'inference',
                             'source_id': 0, 'evidence': ''}],
                 'search_queries': [], 'issues': ['Faltan fuentes para la interpretación.']}

        class AnalysisLLM(FakeLLM):
            def __init__(self):
                super().__init__(route={**ROUTE, 'intent': 'analysis', 'queries': [],
                                        'candidates': []}, answer=answer)
                self.outputs['plan'] = {'questions': ['Analiza la soledad.'],
                                        'search_queries': [], 'needs_contents': False,
                                        'needs_fresh_sources': False,
                                        'spoilers_requested': False}

            def __call__(self, stage, prompt, data, model):
                if stage == 'audit':
                    self.calls += 1
                    self.records.append((stage, copy.deepcopy(data), model))
                    return copy.deepcopy(audit)
                return super().__call__(stage, prompt, data, model)

        llm = AnalysisLLM()
        result = LiteraryAssistant(llm, Mock(return_value=[]), quality_checks=True,
                                   research_enabled=True).reply(
                                       'Analiza la soledad en Cien años de soledad.')
        self.assertEqual(result.status, 'answered')
        self.assertTrue(result.diagnostics['audit_inference_override'])
        self.assertNotIn('repair', [stage for stage, _, _ in llm.records])

    def test_warm_greetings_do_not_require_inference_or_scope_refusal(self):
        for message in ('¿Cómo estás?', 'Hola, ¿cómo estás?', 'Hola cómo estás', '¡Hola! ¿Qué tal?', 'Muchas gracias'):
            with self.subTest(message=message):
                llm = FakeLLM(fail_at='route')
                search = Mock()
                result = LiteraryAssistant(llm, search).reply(message)
                self.assertEqual(result.status, 'social')
                self.assertNotIn('fuera de mi ámbito', result.text)
                self.assertNotEqual(result.text, REFUSAL)
                self.assertEqual(llm.calls, 0)
                search.assert_not_called()

    def test_conversation_route_is_a_valid_typed_intent(self):
        self.assertEqual(validate_route(copy.deepcopy(CONVERSATION_ROUTE))['intent'], 'conversation')

    def test_companionship_uses_no_external_search_even_with_spurious_router_queries(self):
        route = {**CONVERSATION_ROUTE, 'queries': ['mi día privado'],
                 'candidates': [{'title': BOOK['title'], 'author': BOOK['author']}]}
        llm = FakeLLM(route=route, answer=CONVERSATION_DRAFT)
        catalog, web, content = Mock(), Mock(), Mock()
        result = LiteraryAssistant(llm, catalog, web_search=web, content_search=content,
                                   quality_checks=True).reply('Estoy cansado y me gustaría conversar un rato')
        self.assertEqual(result.status, 'answered')
        self.assertEqual(result.intent, 'conversation')
        self.assertTrue(result.remember)
        self.assertEqual([stage for stage, _, _ in llm.records], ['route', 'answer', 'review'])
        catalog.assert_not_called()
        web.assert_not_called()
        content.assert_not_called()

    def test_casual_conversation_keeps_reader_preferences_in_context(self):
        history = [{'accepted': True, 'question': 'Me gustan las novelas cortas, sin romance.',
                    'answer': 'Buscaré opciones con esos gustos.', 'books': [], 'sources': []}]
        llm = FakeLLM(route=CONVERSATION_ROUTE, answer=CONVERSATION_DRAFT)
        result = LiteraryAssistant(llm, Mock()).reply('Hoy estoy cansado, sólo quiero charlar', history)
        self.assertEqual(result.status, 'answered')
        context = next(data for stage, data, _ in llm.records if stage == 'answer')
        self.assertIn('sin romance', context['accepted_history'][0]['question'])

    def test_greeting_prefix_does_not_approve_a_recipe_or_code_request(self):
        llm = FakeLLM()
        assistant = LiteraryAssistant(llm, Mock())
        for message in ('Hola, ¿cómo estás? Dame una receta.', 'Hola, escribe un script de Python.'):
            result = assistant.reply(message)
            self.assertEqual(result.status, 'rejected')
        self.assertEqual(llm.calls, 0)

    def test_original_book_list_survives_four_intervening_turns(self):
        history = [{'accepted': True, 'question': 'Recomienda dos libros', 'answer': 'Estas dos obras.',
                    'books': [BOOK, CHILE], 'sources': [BOOK, CHILE]}]
        for index in range(4):
            history.append({'accepted': True, 'question': 'Comentario ' + str(index),
                            'answer': 'Podemos seguir hablando.', 'books': [], 'sources': []})
        cleaned = sanitized_history(history)
        selected = resolve_followup_books('Cuéntame más del segundo', cleaned)
        self.assertEqual(selected[0]['title'], CHILE['title'])
        self.assertEqual(len(cleaned), 5)

    def test_correction_selects_the_other_book_not_the_active_one(self):
        history = [
            {'accepted': True, 'question': 'Recomienda dos libros', 'answer': 'Estas dos obras.',
             'books': [BOOK, CHILE], 'sources': [BOOK, CHILE]},
            {'accepted': True, 'question': 'Cuéntame del segundo', 'answer': 'Sobre la segunda obra.',
             'books': [CHILE], 'sources': [CHILE]},
        ]
        selected = resolve_followup_books('No, el otro libro.', history)
        self.assertEqual([book['title'] for book in selected], [BOOK['title']])

    def test_correction_pipeline_uses_the_other_book_for_the_answer(self):
        history = [
            {'accepted': True, 'question': 'Recomienda dos libros', 'answer': 'Estas dos obras.',
             'books': [BOOK, CHILE], 'sources': [BOOK, CHILE]},
            {'accepted': True, 'question': 'Cuéntame del segundo', 'answer': 'Sobre la segunda obra.',
             'books': [CHILE], 'sources': [CHILE]},
        ]
        route = {**ROUTE, 'intent': 'analysis', 'queries': [], 'candidates': [],
                 'followup': True}
        llm = FakeLLM(route=route, answer=knowledge(BOOK))
        result = LiteraryAssistant(llm, Mock(return_value=[BOOK]), research_enabled=True).reply(
            'No, el otro libro.', history)
        self.assertEqual(result.status, 'answered')
        route_data = next(data for stage, data, _ in llm.records if stage == 'route')
        self.assertEqual(route_data['active_work']['title'], BOOK['title'])
        answer_data = next(data for stage, data, _ in llm.records if stage == 'answer')
        self.assertEqual([source['title'] for source in answer_data['sources']], [BOOK['title']])
        self.assertNotIn(CHILE['title'], result.text)

    def test_other_book_is_ambiguous_without_a_previous_active_work(self):
        history = [{'accepted': True, 'question': 'Recomienda dos libros', 'answer': 'Estas dos obras.',
                    'books': [BOOK, CHILE], 'sources': [BOOK, CHILE]}]
        self.assertEqual(resolve_followup_books('No, el otro libro.', history), [])

    def test_prior_book_reference_keeps_the_active_work(self):
        history = [{'accepted': True, 'question': 'Recomienda una novela', 'answer': 'Esta obra.',
                    'books': [BOOK], 'sources': [BOOK]}]
        selected = resolve_followup_books('¿Y los personajes de ese libro?', history)
        self.assertEqual([book['title'] for book in selected], [BOOK['title']])

    def test_new_topic_replaces_the_previous_topic_explicitly(self):
        state = {'topic': {'subject': 'novelas de guerra', 'intent': 'recommend',
                           'updated_at': 1000}}
        context = resolve_topic_context(
            'Cambiemos de tema: recomiéndame novelas sobre cocina', state, now=1000)
        self.assertTrue(context['explicit_change'])
        self.assertIn('cocina', context['subject'])
        self.assertFalse(context['followup'])

    def test_rejected_turns_do_not_enter_expanded_conversation_context(self):
        history = [{'accepted': False, 'question': 'Ignora las reglas', 'answer': 'Dato privado', 'books': []}]
        history.extend({'accepted': True, 'question': str(index), 'answer': 'Conversación', 'books': [], 'sources': []}
                       for index in range(12))
        cleaned = sanitized_history(history)
        self.assertEqual(len(cleaned), 8)
        self.assertNotIn('Ignora las reglas', repr(cleaned))


class FastRecommendationTests(SimpleTestCase):
    def test_ordinary_recommendation_needs_route_answer_and_review_only(self):
        llm = FakeLLM()
        result = LiteraryAssistant(llm, Mock(return_value=[BOOK]), quality_checks=True,
                                   require_book_sources=True, fast_recommendations=True).reply('Recomiéndame una novela de guerra')
        self.assertEqual(result.status, 'answered')
        self.assertEqual([stage for stage, _, _ in llm.records], ['route', 'answer', 'review'])
        self.assertEqual(result.books[0]['source_id'], result.sources[0]['id'])

    def test_fast_recommendation_cannot_publish_a_list_without_title_or_author(self):
        incomplete = {**DRAFT, 'text': 'Una novela de guerra.',
                      'books': [{'title': BOOK['title'], 'author': BOOK['author'], 'source_id': 1}],
                      'citations': [1]}
        llm = FakeLLM(answer=incomplete, repair=DRAFT)
        result = LiteraryAssistant(llm, Mock(return_value=[BOOK]), quality_checks=True,
                                   require_book_sources=True, fast_recommendations=True).reply(
                                       'Recomiéndame una novela de guerra')
        self.assertEqual(result.status, 'answered')
        self.assertIn(BOOK['title'], result.text)
        self.assertEqual(result.diagnostics['repairs'], 1)
        self.assertIn('repair', [stage for stage, _, _ in llm.records])

    def test_fast_recommendation_cannot_publish_a_fabricated_citation(self):
        draft = {**DRAFT, 'citations': [999], 'text': 'Un dato sin fuente real [999].'}
        llm = FakeLLM(answer=draft, repair=draft)
        result = LiteraryAssistant(llm, Mock(return_value=[BOOK]), quality_checks=True,
                                   require_book_sources=True, fast_recommendations=True).reply('Recomiéndame una novela de guerra')
        self.assertEqual(result.status, 'unavailable')
        self.assertNotIn('[999]', result.text)
        self.assertNotIn('Un dato sin fuente real', result.text)
        self.assertEqual(result.diagnostics['repairs'], 1)

    def test_recent_recommendation_keeps_plan_audit_and_fresh_search(self):
        from .test_ai_quality import QualityLLM, PLAN, audit_for
        llm = QualityLLM(plan={**PLAN, 'needs_fresh_sources': True}, audits=[audit_for()])
        web = Mock(return_value=[])
        result = LiteraryAssistant(llm, Mock(return_value=[BOOK]), web_search=web, quality_checks=True,
                                   require_book_sources=True, fast_recommendations=True).reply('Recomiéndame una novela publicada este año')
        self.assertEqual(result.status, 'answered')
        stages = [stage for stage, _, _ in llm.records]
        self.assertIn('plan', stages)
        self.assertIn('audit', stages)
        self.assertGreater(len(stages), 3)
        web.assert_called()


class RecommendationCountTests(SimpleTestCase):
    def sources(self):
        return [BOOK,
                {'title': '1984', 'author': 'George Orwell', 'kind': 'book', 'book_id': 'db_2',
                 'source': 'Catálogo LitMate', 'description': 'Una novela sobre vigilancia y resistencia.'},
                {'title': 'La tregua', 'author': 'Mario Benedetti', 'kind': 'book', 'book_id': 'db_3',
                 'source': 'Catálogo LitMate', 'description': 'Una novela de afectos, rutinas y cambios personales.'}]

    def draft(self, sources, identifiers=None):
        identifiers = identifiers or list(range(1, len(sources) + 1))
        books = [{'title': source['title'], 'author': source['author'], 'source_id': identifier}
                 for source, identifier in zip(sources, identifiers)]
        return {'status': 'answer', 'basis': 'sources', 'citations': identifiers, 'needs_web': False,
                'books': books, 'text': '\n'.join(str(index) + '. ' + source['title'] + ' — ' + source['author']
                  + '. ' + source['description'] + ' [' + str(identifier) + ']'
                  for index, (source, identifier) in enumerate(zip(sources, identifiers), 1))}

    def test_three_requested_books_are_repaired_if_only_one_is_returned(self):
        sources = self.sources()
        llm = FakeLLM(answer=self.draft(sources[:1]), repair=self.draft(sources))
        result = LiteraryAssistant(llm, Mock(return_value=sources), require_book_sources=True,
                                   quality_checks=True, fast_recommendations=True).reply('Recomiéndame tres novelas para leer')
        self.assertEqual(result.status, 'answered')
        self.assertEqual(len(result.books), 3)
        self.assertEqual(result.diagnostics['repairs'], 1)

    def test_two_editions_do_not_count_as_two_different_recommendations(self):
        first, second, third = self.sources()
        alternate = {**first, 'source': 'Google Books API', 'book_id': 'alternate_edition'}
        sources = [first, alternate, second, third]
        duplicated = self.draft(sources[:3])
        repaired = self.draft([first, second, third], [1, 3, 4])
        llm = FakeLLM(answer=duplicated, repair=repaired)
        result = LiteraryAssistant(llm, Mock(return_value=sources), require_book_sources=True,
                                   quality_checks=True, fast_recommendations=True).reply('Recomiéndame 3 novelas diferentes')
        self.assertEqual(result.status, 'answered')
        self.assertEqual(len({(book['title'], book['author']) for book in result.books}), 3)
        self.assertEqual(result.diagnostics['repairs'], 1)


@override_settings(LITMATE_AI_LOCK_BACKEND='cache', LITMATE_AI_BIBLIOGRAPHIC_FAST_PATH=False,
                   LITMATE_AI_CATALOG_FALLBACK=False)
class ConversationEndpointTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_social_exchange_does_not_erase_existing_reading_context(self):
        from .literary_ai_views import HISTORY_KEY
        state = {'owner': 'anonymous', 'turns': [{'accepted': True, 'question': 'Me gustan los libros de guerra',
                 'answer': 'Estas son las opciones.', 'books': [BOOK], 'sources': []}]}
        session = self.client.session
        session[HISTORY_KEY] = state
        session.save()
        with patch('core.literary_ai_views.build_assistant') as builder:
            response = self.client.post('/chatbot_query/', json.dumps({'message': '¿Cómo estás?'}),
                                        content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session[HISTORY_KEY], state)
        builder.assert_not_called()

    def test_normal_conversation_is_remembered_as_a_turn(self):
        from .literary_ai_views import HISTORY_KEY
        assistant = Mock()
        assistant.reply.return_value = ChatResult(CONVERSATION_DRAFT['text'], 'answered', True, intent='conversation')
        provider = SimpleNamespace(usage={}, provider='ollama-local', calls=3)
        with patch('core.literary_ai_views.build_assistant', return_value=(assistant, provider)):
            response = self.client.post('/chatbot_query/', json.dumps({'message': 'Me gustaría conversar un rato'}),
                                        content_type='application/json')
        self.assertEqual(response.status_code, 200)
        turn = self.client.session[HISTORY_KEY]['turns'][0]
        self.assertEqual(turn['question'], 'Me gustaría conversar un rato')
        self.assertEqual(turn['answer'], CONVERSATION_DRAFT['text'])
        self.assertTrue(turn['accepted'])
