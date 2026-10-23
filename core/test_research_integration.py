"""Regresiones del recorrido configurado: investigación gratuita y contexto real.

Se simula únicamente la generación y las redes. La identidad, recuperación de
fichas, suficiencia, historial, validadores y construcción del asistente son reales.
"""
import copy
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from .literary_ai import build_assistant, canonical_sources, ProviderUnavailable
from .literary_identity import same_work
from .literary_knowledge import prepare_seed_knowledge, search_knowledge
from .literary_search import retrieve_web, retrieve_books, search_wikipedia
from .literary_sources import SearchResults
from .literary_wikidata import search_wikidata
from .local_llm import OllamaJSON
from .test_literary_ai import FakeLLM, ROUTE


class EvidenceFixtureLLM(FakeLLM):
    """Respuesta esperada fija con IDs del contexto real, nunca ejecuta herramientas."""
    def __init__(self, route, explanation, *, title='', invalid_answer=False, research_again=False, proofs=None):
        super().__init__(route=route)
        self.explanation, self.title = explanation, title
        self.invalid_answer, self.research_again = invalid_answer, research_again
        self.audit_count = 0
        self.proofs = proofs or {}

    def __call__(self, stage, prompt, data, model):
        if stage not in {'answer', 'answer_web', 'repair', 'plan', 'audit'}:
            return super().__call__(stage, prompt, data, model)
        self.calls += 1
        self.records.append((stage, copy.deepcopy(data), model))
        if stage == 'plan':
            return {'questions': ['Responder la pregunta literaria'], 'search_queries': [],
                    'needs_contents': True, 'needs_fresh_sources': False, 'spoilers_requested': False}
        if stage == 'audit':
            self.audit_count += 1
            research = self.research_again and self.audit_count == 1 and data['research_remaining']
            claims = []
            for statement in re.split(r'(?<=[.!?])\s+|\n', data['draft']['text']):
                statement = statement.strip()
                if not statement:
                    continue
                proof = self.proofs.get(statement, statement)
                source = next((source for source in data['sources']
                    if source['id'] in data['draft']['citations'] and len(proof) >= 8
                    and proof in source.get('description', '')), None)
                if source:
                    claims.append({'statement': statement, 'verdict': 'supported',
                                   'source_id': source['id'], 'evidence': proof})
                else:
                    # Esta simulación no convierte una frase plausible en prueba.
                    if data.get('specific_factual_question') and not re.search(
                            r'(?i)no puedo|no se puede|no consta|no sabemos|incertidumbre|no encontr|no dispongo', statement):
                        raise AssertionError('Falta evidencia en la fixture para: ' + statement)
                    claims.append({'statement': statement, 'verdict': 'unverified',
                                   'source_id': 0, 'evidence': ''})
            return {'decision': 'research' if research else 'approve', 'only_books': True,
                    'coverage': [{'question_id': 1, 'status': 'uncertain' if research else 'answered'}],
                    'claims': claims,
                    'search_queries': ['Una consulta adicional de personajes'] if research else [],
                    'issues': ['Falta un detalle verificable'] if research else []}
        if self.invalid_answer and stage == 'answer':
            return {'status': 'answer', 'text': 'JSON incompleto'}
        books = [source for source in data['sources'] if source['kind'] == 'book'
                 and (not self.title or source['title'] == self.title)]
        if not books:
            return {'status': 'clarify', 'basis': 'knowledge', 'text': self.explanation,
                    'citations': [], 'needs_web': False, 'books': []}
        book = books[0]
        used = [source for source in data['sources'] if same_work(source, book)]
        return {'status': 'answer', 'basis': 'sources', 'text': self.explanation,
                'citations': [source['id'] for source in used], 'needs_web': False,
                'books': [{'title': book['title'], 'author': book['author'], 'source_id': book['id']}]}


class ConfiguredResearchIntegrationTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / 'knowledge.sqlite3'
        self.works = prepare_seed_knowledge(self.database)

    def build(self, route, explanation, *, search=None, web=None, quality=False, **llm_options):
        llm = EvidenceFixtureLLM(route, explanation, **llm_options)
        config = SimpleNamespace(LITMATE_RESEARCH_ENABLED=True, LITMATE_AI_QUALITY_CHECKS=quality,
            LITMATE_AI_FAST_RECOMMENDATIONS=False, LITMATE_AI_REQUIRE_BOOK_SOURCES=True,
            LITMATE_RESEARCH_MAX_SEARCHES=2, LITMATE_RESEARCH_TIMEOUT=15,
            LITMATE_LOCAL_MODEL='qwen3.5:9b-q4_K_M')
        search = search if search is not None else Mock(side_effect=lambda query: search_knowledge(query, database=self.database))
        web = web if web is not None else Mock(return_value=SearchResults(status='empty'))
        with patch('core.local_llm.OllamaJSON', return_value=llm):
            bot, _ = build_assistant(config, search=search, web_search=web)
        return bot, llm, search, web

    def test_known_memories_use_real_local_knowledge_without_external_search(self):
        cases = [
            ('Recuerdo un niño que vivía en un planeta pequeño, tenía una rosa y conocía a un zorro',
             'El principito', 'Las pistas de la rosa, el planeta pequeño y el zorro apuntan a El principito.',
             {'Las pistas de la rosa, el planeta pequeño y el zorro apuntan a El principito.':
              'El principito, de Antoine de Saint-Exupéry, trata de un niño que vive en un planeta muy pequeño '
              'y se siente responsable de una rosa. Visita otros planetas. En la Tierra entabla amistad '
              'con un zorro y encuentra a un aviador en el desierto del Sahara.'}),
            ('Recuerdo un libro donde decían que todos los animales son iguales',
             'Rebelión en la granja', 'Las pistas apuntan a Rebelión en la granja. La frase recordada se identifica como paráfrasis; no confirmo una traducción ni página exactas.',
             {'Las pistas apuntan a Rebelión en la granja.':
              'Rebelión en la granja, de George Orwell, se publicó originalmente como Animal Farm.',
              'La frase recordada se identifica como paráfrasis; no confirmo una traducción ni página exactas.':
              'La idea recordada de que todos los animales son iguales pertenece a esta obra; aquí se '
              'parafrasea, sin establecer una traducción textual, página o edición española.'}),
            ('¿En qué libro aparece Raskólnikov?', 'Crimen y castigo',
             'Raskólnikov es el protagonista de Crimen y castigo.',
             {'Raskólnikov es el protagonista de Crimen y castigo.':
              'Raskólnikov es el joven estudiante protagonista de Crimen y castigo, de Fiódor M. Dostoievski.'}),
        ]
        for message, title, text, proofs in cases:
            with self.subTest(title=title):
                sources = search_knowledge(title, database=self.database)
                for proof in proofs.values():
                    self.assertLessEqual(len(proof), 300)
                    self.assertTrue(any(proof in source.get('description', '') for source in sources))
                bot, llm, _, web = self.build({**ROUTE, 'intent': 'identify', 'queries': [message]},
                    text, title=title, quality=True, proofs=proofs)
                result = bot.reply(message)
                self.assertEqual(result.status, 'answered', result.diagnostics)
                self.assertEqual(result.books[0]['title'], title)
                self.assertTrue(result.sources)
                self.assertTrue(all(source['url'].startswith('https://') for source in result.sources))
                web.assert_not_called()
                answer_context = next(record[1] for record in llm.records if record[0] == 'answer')
                self.assertTrue(answer_context['evidence_assessment']['sufficient'])
                self.assertTrue(answer_context['all_factual_claims_required'])
                self.assertFalse(answer_context['specific_factual_question'])
                self.assertNotIn('pagina 42', result.text.lower())

    def test_identification_cannot_hide_a_second_fact_missing_from_the_received_sources(self):
        message = 'Recuerdo un niño en un planeta pequeño con una rosa y un zorro'
        first = ('El principito, de Antoine de Saint-Exupéry, trata de un niño que vive '
                 'en un planeta muy pequeño y se siente responsable de una rosa.')
        added = 'El niño vive en el asteroide B612.'
        received = search_knowledge('El principito', database=self.database)
        self.assertTrue(any(first in source.get('description', '') for source in received))
        self.assertFalse(any('B612' in source.get('description', '') for source in received))
        for omit_second_check in (True, False):
            with self.subTest(omit_second_check=omit_second_check):
                bot, llm, _, web = self.build({**ROUTE, 'intent': 'identify', 'queries': [message]},
                    first + ' ' + added, title='El principito', quality=True)
                generate = bot.llm

                def incomplete_audit(stage, prompt, data, model):
                    response = generate(stage, prompt, data, model)
                    if stage == 'audit' and omit_second_check:
                        return {**response, 'claims': response['claims'][:1]}
                    return response

                bot.llm = incomplete_audit
                result = bot.reply(message)
                self.assertEqual(result.status, 'unavailable', result.diagnostics)
                self.assertNotIn('B612', result.text)
                expected = 'todas las frases' if omit_second_check else 'sin respaldo'
                self.assertTrue(any(expected in issue['issue']
                                    for issue in result.diagnostics['validation_issues']))
                web.assert_not_called()

    def test_recollection_without_word_book_supplies_local_evidence_before_classification(self):
        message = 'Recuerdo un niño que vivía en un planeta pequeño, tenía una rosa y conocía a un zorro'
        previous = search_knowledge('Papelucho y el marciano', database=self.database)
        history = [{'accepted': True, 'question': '¿Qué sucede con Det?',
                    'answer': 'Seguimos hablando de Det.', 'books': [previous[0]], 'sources': previous}]
        bot, llm, _, web = self.build({**ROUTE, 'intent': 'identify', 'queries': [message]},
            'Las pistas de la rosa, el planeta pequeño y el zorro apuntan a El principito.',
            title='El principito')
        generate = bot.llm
        observed = []

        def inspect_before_classification(stage, prompt, data, model):
            if stage == 'route':
                local = data['local_identification_evidence']
                observed.append(local)
                self.assertTrue(local['recollection_not_creation'])
                self.assertTrue(local['sufficient'])
                self.assertEqual(local['candidates'][0]['title'], 'El principito')
                self.assertTrue({'rosa', 'zorro', 'planeta'} <= set(local['candidates'][0]['matched_clues']))
                self.assertTrue(local['candidates'][0]['evidence'])
                self.assertNotIn('active_work', data)
                self.assertEqual(data['verified_current_books'], [])
            return generate(stage, prompt, data, model)

        bot.llm = inspect_before_classification
        with override_settings(LITMATE_KNOWLEDGE_DB=self.database):
            result = bot.reply(message, history)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertEqual(result.books[0]['title'], 'El principito')
        self.assertEqual(len(observed), 1)
        web.assert_not_called()

    def test_evidence_backed_recollection_without_history_gets_same_scope_rescue(self):
        message = 'Recuerdo un niño que vivía en un planeta pequeño, tenía una rosa y conocía a un zorro'
        rejected = {**ROUTE, 'decision': 'reject', 'intent': 'identify', 'queries': []}
        bot, llm, _, web = self.build(rejected,
            'Las pistas de la rosa, el planeta pequeño y el zorro apuntan a El principito.',
            title='El principito')
        llm.outputs['route_rescue'] = {**ROUTE, 'intent': 'identify', 'queries': [message]}
        with override_settings(LITMATE_KNOWLEDGE_DB=self.database):
            result = bot.reply(message)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        contexts = [record[1]['local_identification_evidence'] for record in llm.records
                    if record[0] in {'route', 'route_rescue'}]
        self.assertEqual(len(contexts), 2)
        self.assertEqual(contexts[0], contexts[1])
        self.assertTrue(result.diagnostics['route_rescue'])
        web.assert_not_called()

    def test_local_identification_evidence_does_not_override_mixed_task_rejection(self):
        message = ('Recuerdo un niño que vivía en un planeta pequeño, tenía una rosa y conocía a un zorro; '
                   'además calcula cuánto es 1 + 1')
        rejected = {**ROUTE, 'decision': 'reject', 'intent': 'identify', 'queries': []}
        bot, llm, search, web = self.build(rejected, 'Esta respuesta no debe publicarse.')
        llm.outputs['route_rescue'] = rejected
        with override_settings(LITMATE_KNOWLEDGE_DB=self.database):
            result = bot.reply(message)
        self.assertEqual(result.status, 'rejected')
        classification = [record for record in llm.records if record[0] in {'route', 'route_rescue'}]
        self.assertEqual(len(classification), 2)
        for _, data, _ in classification:
            self.assertEqual(data['local_identification_evidence']['candidates'][0]['title'], 'El principito')
        self.assertFalse(any(record[0] in {'answer', 'answer_web', 'repair'} for record in llm.records))
        search.assert_not_called()
        web.assert_not_called()

    def test_specific_papelucho_characters_accept_confirmed_alias_and_local_evidence(self):
        message = 'Dime los personajes de Papelucho y el marciano'
        route = {**ROUTE, 'intent': 'analysis', 'queries': ['Papelucho y el marciano'],
                 'candidates': [{'title': 'Papelucho y el marciano', 'author': 'Marcela Paz'}]}
        bot, llm, _, web = self.build(route,
            'Papelucho y Det están verificados para esta obra. Det es el amigo extraterrestre de Papelucho; la fuente no ofrece una lista completa.',
            title='Diario secreto de Papelucho y el marciano', quality=True)
        result = bot.reply(message)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertEqual(result.books[0]['author'], 'Marcela Paz')
        web.assert_not_called()
        context = next(record[1] for record in llm.records if record[0] == 'answer')
        self.assertTrue(context['evidence_assessment']['sufficient'])
        self.assertTrue(any(source.get('character_facts') for source in context['sources']))

    def test_explicit_later_volume_does_not_reuse_first_volume_history(self):
        first_volume = {'kind': 'book', 'title': 'Papelucho', 'author': 'Marcela Paz'}
        history = [{'accepted': True, 'question': 'Háblame de Papelucho',
                    'answer': 'Comentamos el primer volumen.', 'books': [first_volume],
                    'sources': [first_volume]}]
        # Incluso una clasificación equivocada no prevalece sobre la ficha
        # bibliográfica local de la obra nombrada en el mensaje actual.
        route = {**ROUTE, 'intent': 'analysis', 'queries': ['Papelucho'],
                 'candidates': [first_volume], 'followup': True}
        with override_settings(LITMATE_KNOWLEDGE_DB=self.database):
            bot, llm, _, web = self.build(route, 'Det es el amigo extraterrestre de Papelucho.',
                                         title='Diario secreto de Papelucho y el marciano')
            result = bot.reply('Dime los personajes de Papelucho y el marciano', history)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertEqual(result.books[0]['title'], 'Diario secreto de Papelucho y el marciano')
        self.assertTrue(result.diagnostics['verified_identity_override'])
        route_context = next(record[1] for record in llm.records if record[0] == 'route')
        self.assertNotIn('active_work', route_context)
        web.assert_not_called()

    def test_verified_current_work_precedes_stale_or_ambiguous_followup(self):
        first_volume = {'kind': 'book', 'title': 'Papelucho', 'author': 'Marcela Paz'}
        for stale in ({'books': [first_volume], 'ambiguous': False, 'entities': []},
                      {'books': [], 'ambiguous': True, 'entities': []}):
            with self.subTest(stale=stale), override_settings(LITMATE_KNOWLEDGE_DB=self.database), \
                    patch('core.literary_identity.followup_context', return_value=stale):
                bot, _, _, web = self.build({**ROUTE, 'intent': 'analysis', 'queries': []},
                    'Det es el amigo extraterrestre de Papelucho.',
                    title='Diario secreto de Papelucho y el marciano')
                result = bot.reply('Dime los personajes de Papelucho y el marciano',
                                   [{'accepted': True, 'books': [first_volume]}])
                self.assertEqual(result.status, 'answered', result.diagnostics)
                self.assertEqual(result.books[0]['title'], 'Diario secreto de Papelucho y el marciano')
                web.assert_not_called()

    def test_third_source_survives_followup_and_prevents_repeat_character_search(self):
        sources = search_knowledge('Papelucho y el marciano', database=self.database)
        book = sources[0]
        irrelevant = {'kind': 'book', 'title': 'Otro libro', 'author': 'Otra autora', 'description': 'No es esta obra.'}
        history = [{'accepted': True, 'question': 'Papelucho y el marciano', 'answer': 'La obra de Marcela Paz.',
                    'books': [book], 'sources': [book, irrelevant, sources[1]]}]
        # El clasificador no marca seguimiento: la identidad recibida debe resolverlo.
        route = {**ROUTE, 'intent': 'analysis', 'queries': [], 'followup': False}
        bot, llm, _, web = self.build(route, 'Det es el amigo extraterrestre de Papelucho.',
                                     search=Mock(return_value=[]), quality=True)
        result = bot.reply('¿Y sus personajes cuáles son?', history)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        web.assert_not_called()
        context = next(record[1] for record in llm.records if record[0] == 'answer')
        self.assertEqual(context['selected_books'][0]['author'], 'Marcela Paz')
        self.assertTrue(any(source.get('character_facts') for source in context['sources']))
        self.assertNotIn('Otro libro', {source['title'] for source in context['sources']})

    def test_det_followup_searches_only_the_active_work_for_the_missing_event(self):
        sources = search_knowledge('Papelucho y el marciano', database=self.database)
        # Simula una conversación anterior que conservó personajes, pero no
        # el acontecimiento (la colección actual ya incluye un hecho parcial).
        for source in sources:
            if source.get('kind') == 'web':
                source['literary_facts'] = [fact for fact in source.get('literary_facts', [])
                                           if fact.get('topic') != 'events']
        history = [{'accepted': True, 'books': [sources[0]], 'sources': sources}]
        det = next(fact for source in sources for fact in source.get('character_facts', []) if fact['name'] == 'Det')
        statement = 'Det es el amigo extraterrestre de Papelucho.'
        bot, llm, _, web = self.build({**ROUTE, 'intent': 'analysis', 'queries': []},
            statement + ' No puedo confirmar el desenlace con estas fuentes.', search=Mock(return_value=[]),
            quality=True, proofs={statement: 'Det: ' + det['role']})
        result = bot.reply('¿Qué sucede con Det?', history)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertGreater(web.call_count, 0)
        self.assertLessEqual(web.call_count, 2)
        for call in web.call_args_list:
            self.assertIn('Papelucho', call.args[0])
            self.assertIn('Marcela Paz', call.args[0])
            self.assertIn('Det', call.args[0])

    def test_model_format_failure_does_not_trigger_external_research(self):
        message = 'Dime los personajes de Papelucho y el marciano'
        route = {**ROUTE, 'intent': 'analysis', 'queries': ['Papelucho y el marciano']}
        bot, llm, _, web = self.build(route, 'Papelucho y Det son personajes verificados de esta obra.', invalid_answer=True)
        result = bot.reply(message)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertEqual(result.diagnostics['repairs'], 1)
        web.assert_not_called()

    def test_recalled_phrase_repair_discards_rejected_wording_and_keeps_evidence(self):
        message = 'Recuerdo un libro donde decían que todos los animales son iguales'
        text = ('Las pistas apuntan a Rebelión en la granja, de George Orwell. '
                'La idea recordada se trata como paráfrasis, sin confirmar una traducción exacta.')
        proofs = {
            'Las pistas apuntan a Rebelión en la granja, de George Orwell.':
            'Rebelión en la granja, de George Orwell, se publicó originalmente como Animal Farm.',
            'La idea recordada se trata como paráfrasis, sin confirmar una traducción exacta.':
            'La idea recordada de que todos los animales son iguales pertenece a esta obra; aquí se '
            'parafrasea, sin establecer una traducción textual, página o edición española.',
        }
        received = search_knowledge('Rebelión en la granja', database=self.database)
        for proof in proofs.values():
            self.assertTrue(any(proof in source.get('description', '') for source in received))
        bot, llm, _, web = self.build({**ROUTE, 'intent': 'identify', 'queries': [message]},
                                     text, title='Rebelión en la granja', quality=True, proofs=proofs)
        generate = bot.llm
        repair_data = []

        def answer_with_unsupported_quote(stage, prompt, data, model):
            response = generate(stage, prompt, data, model)
            if stage == 'answer':
                return {**response, 'text': 'La cita exacta es «Un lema inventado que no aparece en las fuentes».'}
            if stage == 'repair':
                repair_data.append(data)
            return response

        bot.llm = answer_with_unsupported_quote
        result = bot.reply(message)
        self.assertEqual(result.status, 'answered', result.diagnostics)
        self.assertEqual(result.diagnostics['repairs'], 1)
        self.assertNotIn('lema inventado', result.text)
        self.assertEqual(result.books[0]['title'], 'Rebelión en la granja')
        self.assertEqual(len(repair_data), 1)
        self.assertNotIn('previous_draft', repair_data[0])
        self.assertTrue(repair_data[0]['sources'])
        self.assertTrue(repair_data[0]['corrections'])
        self.assertTrue(repair_data[0]['identification_task']['remembered_phrase_is_not_a_verified_quote'])
        web.assert_not_called()

    def test_conflicting_pages_stay_visible_as_conflicting_evidence(self):
        sources = search_knowledge('Papelucho y el marciano', database=self.database)
        book = sources[0]
        base = {**sources[1], 'character_facts': [], 'literary_facts': []}
        statements = [('Det permanece con Papelucho al terminar la aventura.', 'permanece',
                       'https://literaturasm.cl/fuente-uno/'),
                      ('Det abandona a Papelucho al terminar la aventura.', 'abandona',
                       'https://es.wikipedia.org/wiki/Fuente_dos')]
        pages = [{**base, 'url': url, 'description': text,
                  'literary_facts': [{'topic': 'events', 'subject': 'Det', 'relation': 'ending',
                                     'value': value, 'evidence': text}]}
                 for text, value, url in statements]
        route = {**ROUTE, 'intent': 'analysis', 'queries': ['Papelucho y el marciano'],
                 'candidates': [{'title': book['title'], 'author': book['author']}]}
        bot, llm, _, web = self.build(route, 'Las fuentes discrepan sobre Det; no puedo confirmar ese desenlace.',
                                     search=Mock(return_value=[book, *pages]))
        result = bot.reply('¿Qué sucede con Det en Papelucho y el marciano?')
        self.assertEqual(result.status, 'answered', result.diagnostics)
        context = next(record[1] for record in llm.records if record[0] == 'answer')
        self.assertTrue(context['evidence_assessment']['contradictory'])
        self.assertFalse(context['evidence_assessment']['sufficient'])
        self.assertEqual(len([source for source in context['sources'] if source.get('literary_facts')]), 2)
        self.assertIn('no puedo confirmar', result.text)

    def test_private_recollection_is_not_sent_to_web_when_query_builder_rejects_it(self):
        route = {**ROUTE, 'intent': 'identify', 'queries': []}
        bot, _, _, web = self.build(route, '¿Qué recuerdas de la historia?', search=Mock(return_value=[]))
        result = bot.reply('Mi amigo Pedro recuerda un libro de rosas y viajes planetarios')
        self.assertIn(result.status, {'answered', 'clarification'})
        web.assert_not_called()

    def test_research_limit_applies_across_initial_and_audit_research(self):
        first, second = self.works[:2]
        route = {**ROUTE, 'intent': 'analysis', 'queries': [],
                 'candidates': [{'title': item['title'], 'author': item['author']} for item in (first, second)]}
        bot, _, _, web = self.build(route, 'No puedo confirmar esos acontecimientos con estas fuentes.',
            search=Mock(return_value=[first, second]), quality=True, research_again=True)
        bot.reply('Explica qué sucede con los protagonistas de ambas obras')
        self.assertGreater(web.call_count, 0)
        self.assertLessEqual(web.call_count, 2)

    def test_old_paid_credentials_do_not_select_a_remote_model(self):
        config = SimpleNamespace(LITMATE_AI_PROVIDER='groq', GROQ_API_KEY='unused-test-key',
            PINECONE_API_KEY='unused-test-key', LITMATE_RESEARCH_ENABLED=True)
        with patch('core.local_llm.read_json_url') as network:
            bot, client = build_assistant(config, search=Mock(return_value=[]), web_search=Mock(return_value=[]))
            self.assertIsInstance(client, OllamaJSON)
            self.assertEqual(client.provider, 'ollama-local')
            with self.assertRaises(ProviderUnavailable):
                client.inspect_model('qwen-cloud')
            network.assert_not_called()


class FreeResearchFallbackIntegrationTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @override_settings(LITMATE_AI_USE_SEARXNG=True, LITMATE_AI_USE_WIKIDATA=False,
                       LITMATE_RESEARCH_MAX_PAGES=0)
    def test_general_search_outage_keeps_wikipedia_evidence_and_reports_partial_status(self):
        source = {'kind': 'web', 'title': 'Una novela', 'author': 'Fuente web',
                  'description': 'Información pública recuperada de la API oficial.',
                  'url': 'https://es.wikipedia.org/wiki/Una_novela', 'source': 'Wikipedia'}
        with patch('core.literary_search.search_searx') as searx, \
                patch('core.literary_search.search_duckduckgo', return_value=SearchResults(status='unavailable')), \
                patch('core.literary_search.search_wikipedia', return_value=SearchResults([source])):
            result = retrieve_web('Una novela personajes')
        self.assertEqual(len(result), 1)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.providers['DuckDuckGo'], 'unavailable')
        self.assertEqual(result.providers['Wikipedia'], 'ok')
        searx.assert_not_called()

    @override_settings(LITMATE_AI_USE_SEARXNG=True, LITMATE_AI_USE_WIKIDATA=True,
                       LITMATE_RESEARCH_MAX_PAGES=0)
    def test_empty_searches_can_use_official_wikidata_without_a_paid_provider(self):
        source = {'kind': 'book', 'title': 'Una novela', 'author': 'Una autora',
                  'description': 'Identidad bibliográfica pública.', 'url': 'https://www.wikidata.org/wiki/Q123',
                  'source': 'Wikidata'}
        with patch('core.literary_search.search_searx', return_value=SearchResults(status='empty')), \
                patch('core.literary_search.search_duckduckgo', return_value=SearchResults(status='empty')), \
                patch('core.literary_search.search_wikipedia', return_value=SearchResults(status='empty')), \
                patch('core.literary_wikidata.search_wikidata', return_value=SearchResults([source])) as wikidata:
            result = retrieve_web('Una novela')
        wikidata.assert_called_once()
        self.assertEqual(result[0]['author'], 'Una autora')
        self.assertEqual(result.status, 'ok')

    def test_wikidata_empty_rate_limit_and_failure_are_distinct(self):
        with patch('core.literary_wikidata.read_public_json', return_value={'search': []}) as request:
            self.assertEqual(search_wikidata('Título de prueba').status, 'empty')
            self.assertEqual(search_wikidata('Título de prueba').status, 'rate_limited')
            request.assert_called_once()
        cache.clear()
        with patch('core.literary_wikidata.read_public_json', side_effect=TimeoutError):
            self.assertEqual(search_wikidata('Título de prueba').status, 'timeout')
        cache.clear()
        with patch('core.literary_wikidata.read_public_json', side_effect=HTTPError(
                'https://www.wikidata.org/w/api.php', 429, 'limited', {}, None)):
            self.assertEqual(search_wikidata('Título de prueba').status, 'rate_limited')

    def test_wikidata_character_relations_do_not_invent_plot_or_a_complete_roster(self):
        def claim(identifier):
            return {'mainsnak': {'datavalue': {'value': {'id': identifier}}}}
        responses = [{'search': [{'id': 'Q100'}]},
            {'entities': {'Q100': {'labels': {'es': {'value': 'Una novela'}},
                'claims': {'P50': [claim('Q200')], 'P674': [claim('Q300')]}}}},
            {'entities': {'Q200': {'labels': {'es': {'value': 'Una autora'}}},
                          'Q300': {'labels': {'es': {'value': 'Un personaje'}}}}}]
        with patch('core.literary_wikidata.read_public_json', side_effect=responses) as request:
            result = search_wikidata('Una novela')
        self.assertEqual(result.status, 'ok')
        self.assertEqual(request.call_count, 3)
        self.assertEqual(result[0]['author'], 'Una autora')
        self.assertEqual(result[1]['character_facts'][0]['name'], 'Un personaje')
        self.assertNotIn('muere', result[1]['description'])
        self.assertNotIn('lista completa', result[1]['description'])

    @override_settings(LITMATE_AI_USE_OPENLIBRARY=True, LITMATE_USE_GOOGLE_BOOKS_API=False,
                       LITMATE_RAG_SEMANTIC=False)
    def test_bibliographic_fallback_does_not_send_personal_recollection_to_apis(self):
        with tempfile.TemporaryDirectory() as temporary, override_settings(
                LITMATE_RAG_DB=Path(temporary) / 'rag.sqlite3',
                LITMATE_KNOWLEDGE_DB=Path(temporary) / 'facts.sqlite3'):
            with patch('core.literary_search.search_catalog', return_value=[]), \
                    patch('core.literary_search.retrieve_fragments', return_value=[]), \
                    patch('core.literary_search.search_google', return_value=[]) as google, \
                    patch('core.literary_search.search_openlibrary', return_value=[]) as openlibrary:
                retrieve_books('Mi amigo Pedro recuerda una novela sobre rosas y viajes planetarios')
        google.assert_not_called()
        openlibrary.assert_not_called()

    def test_wikipedia_plot_evidence_binds_using_confirmed_alias_without_claiming_novel_verbatim(self):
        from .test_literary_identity import BOOK
        from .literary_identity import bind_source
        from .literary_research import assess_evidence
        introduction = 'Papelucho y el marciano es una novela de Marcela Paz.'
        plot = ('Papelucho y el marciano\n== Argumento ==\n'
                'Det vive dentro de Papelucho. Papelucho ayuda a Det a regresar a su planeta.\n'
                '== Adaptaciones ==\nExiste una película diferente.')
        responses = [{'query': {'pages': {'123': {'pageid': 123, 'title': 'Papelucho y el marciano',
            'extract': introduction, 'fullurl': 'https://es.wikipedia.org/wiki/Papelucho_y_el_marciano'}}}},
            {'query': {'pages': {'123': {'pageid': 123, 'title': 'Papelucho y el marciano',
                'extract': introduction + '\n' + plot,
                'fullurl': 'https://es.wikipedia.org/wiki/Papelucho_y_el_marciano'}}}}]
        with patch('core.literary_search.read_json_url', side_effect=responses):
            result = search_wikipedia('"Papelucho y el marciano" Marcela Paz Det argumento acontecimientos')
        self.assertEqual(len(result), 1)
        source = bind_source(result[0], BOOK)
        self.assertTrue(source['work_binding_verified'])
        self.assertEqual(source['kind'], 'web')
        self.assertIn('sección de artículo', source['read_mode'])
        self.assertEqual(source['literary_facts'][0]['topic'], 'events')
        self.assertNotIn('película diferente', source['description'])
        self.assertTrue(assess_evidence('¿Qué sucede con Det?', [source], [BOOK])['sufficient'])
