"""Casos literarios conocidos y controles negativos con proveedores simulados.

Estas pruebas no acreditan latencia de Internet ni precisión del LLM real.
Las búsquedas HTTP reales se registran por separado en reportes/sinopsis_20261026.
"""
from types import SimpleNamespace
import json
from unittest.mock import patch

from django.test import SimpleTestCase

from .ai_narrative_answers import (bound_sources, direct_answer, narrative_answer,
                                    request_for, synthesize_answer, work_type)
from .literary_ai import canonical_sources
from .literary_quality import required_fact_statements


HISTORY_BOOK = {'kind': 'book', 'title': 'The Unfinished Nation', 'author': 'Alan Brinkley',
    'source': 'Open Library', 'url': 'https://openlibrary.org/works/OL176193W',
    'description': 'Temas del catálogo: History, Textbooks, United States.',
    'categories': ['History', 'Textbooks', 'United States']}
PUBLISHER = {'kind': 'web', 'title': 'The Unfinished Nation: A Concise History of the American People',
    'author': 'Fuente web', 'source': 'DuckDuckGo',
    'url': 'https://www.mheducation.com/highered/product/the-unfinished-nation-brinkley.html',
    'description': "The Unfinished Nation: A Concise History of the American People continues the evolution of Alan Brinkley's influential work, with a focus on making history relatable and accessible to today's students.",
    'identity_text': 'The Unfinished Nation: A Concise History of the American People by Alan Brinkley.',
    'read_mode': 'pasaje de página pública', 'permanent_index_allowed': False}
TOLKIEN_PAGE = {'kind': 'web', 'title': 'El Señor de los Anillos', 'author': 'Fuente web',
    'source': 'Wikipedia', 'url': 'https://es.wikipedia.org/wiki/El_Se%C3%B1or_de_los_Anillos',
    'identity_text': 'El Señor de los Anillos es una novela de fantasía épica escrita por J. R. R. Tolkien.',
    'description': 'La novela narra el viaje del protagonista principal, Frodo Bolsón, hobbit de la Comarca, para destruir el Anillo Único y la consiguiente guerra que provocará el enemigo para recuperarlo, ya que es la principal fuente de poder de su creador, el señor oscuro Sauron.',
    'license': 'CC-BY-SA-4.0', 'read_mode': 'extracto de introducción'}


class SynopsisRegressionTests(SimpleTestCase):
    def test_verified_research_summary_survives_content_selection(self):
        from .ai_narrative_answers import _content
        candidate = {**HISTORY_BOOK, 'synopsis': '',
                     'research_summary': 'El texto investiga la vida en una ciudad portuaria.',
                     'synopsis_source_url': 'https://example.org/descripcion'}
        self.assertEqual(_content(candidate), candidate['research_summary'])
        missing_provenance = {**candidate, 'synopsis_source_url': ''}
        self.assertEqual(_content(missing_provenance), '')

    def test_minimal_catalogue_metadata_is_not_evidence_of_plot(self):
        from .ai_narrative_answers import _content
        candidate = {**HISTORY_BOOK, 'policy': 'openlibrary-minimal-metadata-v1',
                     'description': 'Temas del catálogo: historia.'}
        self.assertEqual(_content(candidate), '')

    def test_synthesis_places_verified_enrichment_in_auditable_context(self):
        from .ai_narrative_answers import synthesize_answer
        from .literary_ai import canonical_sources
        title = 'Historia del puerto'
        message = 'Dime la trama de Historia del puerto de Ana Robles'
        summary = 'La obra estudia el comercio y la navegación en la ciudad portuaria.'
        candidate = {**HISTORY_BOOK, 'title': title, 'author': 'Ana Robles',
                     'research_summary': summary,
                     'synopsis_source_url': 'https://example.org/descripcion'}
        seen = []
        class Stub:
            calls = 0
            usage = {}
            stage_timings = []
            def __call__(self, stage, prompt, context, model):
                seen.append((stage, context['sources'][0]))
                raise TimeoutError('prueba controlada sin modelo')
        with patch('core.literary_ai.build_assistant', return_value=(
                SimpleNamespace(answer_model='dummy', guard_model='dummy'), Stub())):
            result, _ = synthesize_answer(message, request_for(message),
                                          canonical_sources([candidate]), SimpleNamespace())
        self.assertEqual(result.status, 'unavailable')
        self.assertEqual(seen[0][1]['narrative_context'], summary)

    def test_explicit_author_and_short_title_bind_to_real_publisher_subtitle(self):
        req = request_for('Dime la trama de The Unfinished Nation de Alan Brinkley')
        self.assertEqual(req['title'], HISTORY_BOOK['title'])
        self.assertEqual(req['author_hint'], HISTORY_BOOK['author'])
        bound = bound_sources(req, [HISTORY_BOOK, PUBLISHER])
        self.assertEqual(len(bound), 2)
        self.assertEqual(bound[1]['work_author'], 'Alan Brinkley')
        self.assertEqual(work_type(bound), 'nonfiction')
        self.assertFalse(bound[1]['permanent_index_allowed'])

    def test_papelucho_keeps_verified_story_and_context(self):
        from .ai_quick_answers import quick_knowledge_sources
        message = 'Dime la trama de Papelucho y el marciano'
        result = direct_answer(message, request_for(message), quick_knowledge_sources(message, 12))
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'answered')
        self.assertIn('Papelucho', result.text)
        self.assertIn('Det', result.text)
        self.assertNotIn('Pasaje recuperado', result.text)
        self.assertTrue(result.diagnostics['audit']['claims'])

    def test_lord_of_the_rings_is_a_coherent_plot_without_wrong_catalogue_author(self):
        wrong = {**HISTORY_BOOK, 'title': TOLKIEN_PAGE['title'], 'author': 'Gary Russell',
                 'url': 'https://openlibrary.org/works/OL5758746W'}
        message = 'Dime la trama de El señor de los anillos'
        result = direct_answer(message, request_for(message), [wrong, TOLKIEN_PAGE])
        self.assertIsNotNone(result)
        for name in ('Frodo', 'Anillo Único', 'Sauron'):
            self.assertIn(name, result.text)
        self.assertNotIn('Gary Russell', result.text)
        self.assertNotIn('Pasaje recuperado', result.text)
        self.assertEqual(result.diagnostics['work_type'], 'fiction')
        self.assertEqual(result.books, [])  # Nunca una tarjeta del libro homónimo.

    def test_nonfiction_uses_actual_generation_and_full_audit_without_router_or_plan(self):
        message = 'Dime la trama de The Unfinished Nation de Alan Brinkley'
        req = request_for(message)
        sources = bound_sources(req, [HISTORY_BOOK, PUBLISHER])
        text = 'La obra presenta una historia concisa del pueblo estadounidense.'
        calls = []

        class Client:
            calls = 0
            usage = {'prompt_tokens': 8, 'completion_tokens': 9, 'total_tokens': 17}
            stage_timings = []

            def __call__(self, stage, prompt, context, model):
                self.calls += 1
                calls.append(stage)
                if stage == 'answer':
                    assert context['work_type'] == 'nonfiction'
                    return {'status': 'answer', 'basis': 'sources', 'text': text,
                            'citations': [2], 'books': [], 'needs_web': False}
                return {'decision': 'approve', 'only_books': True,
                    'coverage': [{'question_id': 1, 'status': 'answered'}], 'issues': [], 'search_queries': [],
                    'claims': [{'statement': sentence, 'source_id': 2, 'verdict': 'supported',
                                'evidence': PUBLISHER['description']} for sentence in required_fact_statements(text)]}

        client = Client()
        with patch('core.literary_ai.build_assistant', return_value=(
                SimpleNamespace(answer_model='local', guard_model='local'), client)):
            result, _ = synthesize_answer(message, req, sources, SimpleNamespace())
        self.assertEqual(result.status, 'answered')
        self.assertEqual(calls, ['answer', 'audit'])
        self.assertEqual(result.diagnostics['model_calls'], 2)
        self.assertIn('historia', result.text)
        self.assertNotIn('personajes novelescos', result.text)

    def test_missing_content_never_becomes_a_story_from_subject_tags(self):
        with patch('core.ai_narrative_answers.retrieve_sources', return_value=[HISTORY_BOOK]):
            result = narrative_answer('Dime la trama de The Unfinished Nation', [])
        self.assertEqual(result.status, 'unavailable')
        self.assertFalse(result.diagnostics.get('verified_narrative_answer'))

    def test_subtitle_is_not_permission_to_bind_a_sequel_or_another_author(self):
        message = 'Dime la trama de The Unfinished Nation de Alan Brinkley'
        req = request_for(message)
        for page in ({**PUBLISHER, 'title': 'The Unfinished Nation II'},
                     {**PUBLISHER, 'identity_text': 'The Unfinished Nation by A Different Author.'}):
            selected = bound_sources(req, [HISTORY_BOOK, page])
            self.assertFalse(any(source['kind'] == 'web' for source in selected))

    def test_war_in_title_does_not_make_a_novel_nonfiction(self):
        source = {**HISTORY_BOOK, 'title': 'La guerra del mañana', 'categories': ['Fiction', 'War'],
                  'synopsis': 'Una novela de ciencia ficción sobre un conflicto imaginario.'}
        self.assertEqual(work_type(canonical_sources([source])), 'fiction')

    def test_explicit_volume_is_not_an_interchangeable_subtitle(self):
        from .ai_narrative_answers import _has_subtitle
        self.assertFalse(_has_subtitle('The Unfinished Nation: Volume 2', 'The Unfinished Nation'))
        self.assertFalse(_has_subtitle('The Unfinished Nation II', 'The Unfinished Nation'))

    def test_an_auditor_cannot_approve_an_unmentioned_century(self):
        from .literary_quality import validate_audit, unsupported_century_claim
        self.assertTrue(unsupported_century_claim('La obra abarca hasta el siglo XXI.', PUBLISHER['description']))
        self.assertFalse(unsupported_century_claim('Describe el siglo XIX.', 'It examines the 19th century.'))
        self.assertFalse(unsupported_century_claim('Describe el siglo XX.', 'Analiza el siglo XX.'))
        sources = canonical_sources([PUBLISHER])
        text = 'La obra abarca hasta el siglo XXI.'
        audit = {'decision': 'approve', 'only_books': True, 'issues': [], 'search_queries': [],
            'coverage': [{'question_id': 1, 'status': 'answered'}], 'claims': [{
                'statement': text, 'verdict': 'supported', 'source_id': 1,
                'evidence': PUBLISHER['description']}]}
        draft = {'status': 'answer', 'text': text, 'citations': [1]}
        with self.assertRaisesRegex(ValueError, 'siglo'):
            validate_audit(audit, {'questions': ['Qué trata']}, draft, sources, 'Qué trata', strict_facts=True)

    def test_century_enumerations_and_ranges_require_all_the_claimed_periods(self):
        from .literary_quality import unsupported_century_claim
        for claim, proof in (
            ('La obra estudia los siglos XIX y XX.', 'Estudia el siglo XIX.'),
            ('La obra estudia los siglos XVI-XX.', 'Estudia el siglo XVI.'),
            ('La obra estudia los siglos XVI a XX.', 'Estudia los siglos XVI y XX.'),
            ('It covers the 19th and 20th centuries.', 'It covers the 19th century.'),
            ('It covers the 16th-20th centuries.', 'It covers the 16th century.'),
        ):
            with self.subTest(claim=claim):
                self.assertTrue(unsupported_century_claim(claim, proof))
        self.assertFalse(unsupported_century_claim(
            'La obra estudia los siglos XIX y XX.', 'It covers the 19th and 20th centuries.'))
        self.assertFalse(unsupported_century_claim(
            'La obra estudia los siglos XVI a XX.', 'It covers the 16th-20th centuries.'))

    def test_century_in_bibliographic_title_is_not_an_added_historical_scope(self):
        from .literary_quality import unsupported_century_claim, validate_audit
        source = canonical_sources([{**HISTORY_BOOK, 'title': 'Historia del siglo XX',
                                     'author': 'Ana Robles'}])[0]
        text = 'Historia del siglo XX es un libro de Ana Robles.'
        self.assertFalse(unsupported_century_claim(text, 'Ana Robles', source))
        self.assertTrue(unsupported_century_claim(
            'Historia del siglo XX estudia también el siglo XXI.', 'Ana Robles', source))
        audit = {'decision': 'approve', 'only_books': True, 'issues': [], 'search_queries': [],
            'coverage': [{'question_id': 1, 'status': 'answered'}], 'claims': [{
                'statement': text, 'verdict': 'supported', 'source_id': source['id'],
                'evidence': source['author']}]}
        draft = {'status': 'answer', 'basis': 'sources', 'text': text,
                 'citations': [source['id']], 'books': [], 'needs_web': False}
        self.assertEqual(validate_audit(audit, {'questions': ['Quién escribió esa obra']},
                                       draft, [source], 'Quién escribió esa obra', strict_facts=True), audit)

    def test_unsafe_pages_cannot_choose_between_homonymous_books(self):
        first = {**HISTORY_BOOK, 'title': TOLKIEN_PAGE['title'], 'author': 'J. R. R. Tolkien'}
        other = {**first, 'author': 'Otro Autor', 'url': 'https://openlibrary.org/works/OL99881W'}
        request = request_for('Dime la trama de El Señor de los Anillos')
        for flags in ({'injection_detected': True}, {'conflicts_with': ['a different source']}):
            with self.subTest(flags=flags):
                selected = bound_sources(request, [first, other, {**TOLKIEN_PAGE, **flags}])
                self.assertEqual({source['author'] for source in selected},
                                 {first['author'], other['author']})
                self.assertFalse(any(source['kind'] == 'web' for source in selected))

    def test_supported_sentences_survive_an_unsupported_temporal_scope(self):
        from .ai_narrative_answers import _supported_summary
        sources = canonical_sources([PUBLISHER])
        good = 'The Unfinished Nation presenta una historia concisa del pueblo estadounidense.'
        bad = 'El libro abarca hasta el siglo XXI.'
        draft = {'status': 'answer', 'basis': 'sources', 'text': good + ' ' + bad,
                 'citations': [1], 'books': [], 'needs_web': False}
        audit = {'decision': 'repair', 'only_books': True, 'issues': [], 'search_queries': [],
            'coverage': [{'question_id': 1, 'status': 'uncertain'}], 'claims': [
                {'statement': good, 'verdict': 'supported', 'source_id': 1, 'evidence': PUBLISHER['description']},
                {'statement': bad, 'verdict': 'unverified', 'source_id': 0, 'evidence': ''}]}
        revised = _supported_summary(draft, audit, {'questions': ['De qué trata']}, sources, 'De qué trata')
        self.assertIsNotNone(revised)
        self.assertEqual(revised[0]['text'], good)
        self.assertNotIn('XXI', revised[0]['text'])
        self.assertEqual(revised[1]['decision'], 'approve')

    def test_invalid_or_contradictory_proof_cannot_be_rescued_as_partial(self):
        from .ai_narrative_answers import _supported_summary
        sources = canonical_sources([PUBLISHER])
        text = 'La obra estudia una batalla inventada.'
        draft = {'status': 'answer', 'basis': 'sources', 'text': text + ' Otro dato sin respaldo.',
                 'citations': [1], 'books': [], 'needs_web': False}
        audit = {'decision': 'repair', 'only_books': True, 'issues': [], 'search_queries': [],
            'coverage': [{'question_id': 1, 'status': 'uncertain'}], 'claims': [
                {'statement': text, 'verdict': 'supported', 'source_id': 1, 'evidence': 'Esta cita no existe en la página.'},
                {'statement': 'Otro dato sin respaldo.', 'verdict': 'unverified', 'source_id': 0, 'evidence': ''}]}
        self.assertIsNone(_supported_summary(draft, audit, {'questions': ['De qué trata']}, sources, 'De qué trata'))

    def test_narrative_transport_does_not_ask_model_to_reselect_book_cards(self):
        from .local_llm import OllamaJSON
        client = OllamaJSON()
        sources = bound_sources(request_for('Dime la trama de The Unfinished Nation de Alan Brinkley'),
                                [HISTORY_BOOK, PUBLISHER])
        answer = {'status': 'answer', 'basis': 'sources', 'text': 'Un manual de historia estadounidense.',
                  'citations': [2], 'books': [], 'needs_web': False}
        captured = []

        def fetch(url, **kwargs):
            captured.append(kwargs['payload'])
            return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps(answer)}}

        with patch.object(client, 'inspect_model', return_value={'capabilities': ['completion']}), \
                patch('core.local_llm.read_json_url', side_effect=fetch):
            result = client('answer', 'Responde usando las fuentes.', {'sources': sources,
                'ground_book_identity': True, 'narrative_contract': {'book_cards_from_verified_identity': True}},
                'local-test')
        self.assertEqual(captured[0]['format']['properties']['books']['maxItems'], 0)
        self.assertEqual(result['books'], [])
        self.assertEqual(result['citations'], [2])

    def test_latest_verified_web_work_precedes_an_older_catalogue_book(self):
        history = [
            {'accepted': True, 'question': 'Otra lectura', 'answer': 'Una obra de historia.',
             'books': [HISTORY_BOOK], 'sources': canonical_sources([HISTORY_BOOK])},
            {'accepted': True, 'question': 'Dime la trama de El Señor de los Anillos',
             'answer': TOLKIEN_PAGE['description'], 'books': [], 'sources': canonical_sources([TOLKIEN_PAGE])},
        ]
        question = '¿De qué trata el libro que mencionaste anteriormente?'
        req = request_for(question, history)
        self.assertEqual(req['title'], TOLKIEN_PAGE['title'])
        self.assertEqual(req['targets'], [])
        with patch('core.literary_search.search_wikipedia') as wiki, \
                patch('core.literary_search.search_openlibrary') as catalogue:
            result = narrative_answer(question, history)
        self.assertEqual(result.status, 'answered')
        self.assertIn('Frodo', result.text)
        self.assertNotIn('Brinkley', result.text)
        wiki.assert_not_called()
        catalogue.assert_not_called()
