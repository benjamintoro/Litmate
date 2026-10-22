"""Regresiones de contexto pequeño con evidencia y validadores reales, sin inferencia."""
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock

from django.test import SimpleTestCase, override_settings

from .literary_ai import (ANSWER_PROMPT, SHORT_FACTUAL_PROMPT, LiteraryAssistant,
                          ProviderUnavailable, simple_research_plan)
from .literary_knowledge import prepare_seed_knowledge, search_knowledge
from .local_llm import OllamaJSON
from .test_literary_ai import ROUTE
from .test_research_integration import EvidenceFixtureLLM


class SimpleResearchPlanTests(SimpleTestCase):
    def test_remembered_clues_remain_one_exact_request_without_added_questions(self):
        messages = ['Recuerdo un libro donde decían que todos los animales son iguales',
                    'Recuerdo un niño en un planeta pequeño que cuida una rosa y conoce un zorro',
                    '¿En qué libro aparece Raskólnikov?']
        for message in messages:
            with self.subTest(message=message):
                plan = simple_research_plan(message, 'identify')
                self.assertEqual(plan['questions'], [message])
                self.assertFalse(plan['spoilers_requested'])

    def test_followup_does_not_turn_an_event_question_into_a_request_for_the_ending(self):
        plan = simple_research_plan('¿Y qué sucede con Det?', 'analysis',
                                    followup=True, selected_books=[{'title': 'Una obra'}])
        self.assertEqual(plan['questions'], ['¿Y qué sucede con Det?'])
        self.assertTrue(plan['needs_contents'])
        self.assertFalse(plan['spoilers_requested'])

    def test_explicit_ending_keeps_the_spoiler_permission(self):
        plan = simple_research_plan('¿Cómo termina?', 'analysis', followup=True,
                                    selected_books=[{'title': 'Una obra'}])
        self.assertTrue(plan['spoilers_requested'])

    def test_compound_and_conceptual_tasks_keep_the_full_planner(self):
        for message, intent in [
            ('Recuerdo un libro sobre animales; explica también su simbolismo', 'identify'),
            ('Recuerdo una rosa y un niño. ¿Cuál es y quién lo escribió?', 'identify'),
            ('Recuerdo un libro sobre animales y analiza sus personajes', 'identify'),
            ('Recuerdo un libro sobre animales, además dime su final', 'identify'),
            ('Recuerdo un libro, ¿cuál es? ¿Cómo termina?', 'identify'),
            ('¿Qué sucede con él y cómo termina su historia?', 'analysis'),
            ('Explica la metáfora y su relación con la alegoría', 'concept'),
            ('¿Qué sucede con él? Analiza también el simbolismo.', 'analysis'),
            ('Analiza este fragmento: El árbol preservaba sus recuerdos.', 'analysis'),
            ('¿Quién es y en qué página exacta aparece?', 'analysis'),
            ('Recuerdo ' + 'una escena muy lejana ' * 15, 'identify'),
        ]:
            with self.subTest(message=message):
                self.assertIsNone(simple_research_plan(message, intent, followup=True,
                                                       selected_books=[{'title': 'Una obra'}]))

    def test_detail_needs_an_accepted_work_and_a_followup(self):
        for followup, books in [(False, [{'title': 'Una obra'}]), (True, [])]:
            self.assertIsNone(simple_research_plan('¿Qué sucede con él?', 'analysis',
                                                  followup=followup, selected_books=books))


class CompactFactualEvidenceIntegrationTests(SimpleTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / 'knowledge.sqlite3'
        prepare_seed_knowledge(self.database)

    def assistant(self, route, statement, proof, title):
        model = EvidenceFixtureLLM(route, statement, title=title, proofs={statement: proof})
        prompts = {}
        def generate(stage, prompt, data, selected_model):
            prompts[stage] = prompt
            return model(stage, prompt, data, selected_model)
        search = Mock(side_effect=lambda query: search_knowledge(query, database=self.database))
        web = Mock(return_value=[])
        assistant = LiteraryAssistant(generate, search, web_search=web,
            quality_checks=True, require_book_sources=True, research_enabled=True)
        return assistant, model, prompts, web

    def test_det_response_preserves_work_evidence_and_audit_inside_8192_context(self):
        sources = search_knowledge('Papelucho y el marciano', database=self.database)
        title = sources[0]['title']
        statement = 'La convivencia de Papelucho con Det provoca problemas y enfados y ofrece la posibilidad de viajar a otros mundos.'
        self.assertTrue(any(statement in source.get('description', '') for source in sources))
        assistant, model, prompts, web = self.assistant(
            {**ROUTE, 'intent': 'analysis', 'queries': []}, statement, statement, title)
        history = [{'accepted': True, 'books': [sources[0]], 'sources': sources,
                    'answer': 'Comentamos esta obra de Marcela Paz.'}]
        with override_settings(LITMATE_KNOWLEDGE_DB=self.database):
            result = assistant.reply('¿Y qué sucede con Det?', history)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertEqual(result.books[0]['title'], title)
        self.assertNotIn('plan', [stage for stage, _, _ in model.records])
        self.assertIn('audit', [stage for stage, _, _ in model.records])
        context = next(data for stage, data, _ in model.records if stage == 'answer')
        self.assertEqual(context['plan']['questions'], ['¿Y qué sucede con Det?'])
        self.assertTrue(context['all_factual_claims_required'])
        self.assertTrue(prompts['answer'].startswith(SHORT_FACTUAL_PROMPT))
        self.assertIn('rejected_claims', prompts['answer'])
        self.assertLess(len(prompts['answer']), 2300)
        client = OllamaJSON(context=8192, answer_tokens=3072)
        fitted = json.loads(client._fit_context(prompts['answer'], context, 3072))
        self.assertEqual(fitted['plan']['questions'], ['¿Y qué sucede con Det?'])
        self.assertTrue(any(statement in source.get('description', '') for source in fitted['sources']))
        with self.assertRaisesRegex(ProviderUnavailable, 'contexto_demasiado_extenso'):
            client._fit_context(ANSWER_PROMPT, context, 3072)
        self.assertLessEqual(web.call_count, 2)
        for call in web.call_args_list:
            self.assertIn('Papelucho', call.args[0])
            self.assertIn('Marcela Paz', call.args[0])
            self.assertIn('Det', call.args[0])

    def test_identification_still_audits_the_literal_real_question(self):
        message = 'Recuerdo un libro donde decían que todos los animales son iguales'
        statement = 'Las pistas apuntan a Rebelión en la granja, de George Orwell.'
        proof = 'Rebelión en la granja, de George Orwell, se publicó originalmente como Animal Farm.'
        assistant, model, _, web = self.assistant(
            {**ROUTE, 'intent': 'identify', 'queries': [message]}, statement, proof,
            'Rebelión en la granja')
        with override_settings(LITMATE_KNOWLEDGE_DB=self.database):
            result = assistant.reply(message)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertNotIn('plan', [stage for stage, _, _ in model.records])
        audit = next(data for stage, data, _ in model.records if stage == 'audit')
        self.assertEqual(audit['plan']['questions'], [message])
        self.assertTrue(audit['all_factual_claims_required'])
        web.assert_not_called()

    def test_compact_prompt_does_not_allow_an_omitted_unsupported_event(self):
        sources = search_knowledge('Papelucho y el marciano', database=self.database)
        statement = 'La convivencia de Papelucho con Det provoca problemas y enfados y ofrece la posibilidad de viajar a otros mundos.'
        assistant, model, _, _ = self.assistant(
            {**ROUTE, 'intent': 'analysis', 'queries': []}, statement, statement,
            sources[0]['title'])
        generate = assistant.llm
        def omitted_fact(stage, prompt, data, selected_model):
            response = generate(stage, prompt, data, selected_model)
            if stage in {'answer', 'repair', 'answer_web'}:
                response['text'] += ' Det gana una batalla en Saturno.'
            return response
        # El auditor simulado intenta aprobar solo la frase respaldada. El
        # validador real debe rechazar la omisión de la segunda afirmación.
        def model_with_incomplete_audit(stage, prompt, data, selected_model):
            if stage == 'audit':
                clean = {**data, 'draft': {**data['draft'], 'text': statement}}
                return generate(stage, prompt, clean, selected_model)
            return omitted_fact(stage, prompt, data, selected_model)
        assistant.llm = model_with_incomplete_audit
        with override_settings(LITMATE_KNOWLEDGE_DB=self.database):
            result = assistant.reply('¿Y qué sucede con Det?',
                [{'accepted': True, 'books': [sources[0]], 'sources': sources}])
        self.assertEqual(result.status, 'unavailable', result.diagnostics)
        self.assertNotIn('Saturno', result.text)
        self.assertTrue(any('todas las frases' in issue['issue']
                            for issue in result.diagnostics['validation_issues']))
