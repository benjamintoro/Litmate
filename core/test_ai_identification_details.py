"""Identificación local de identidad: fichas reales temporales y controles adversos."""
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from .ai_identification_details import identification_answer
from .literary_ai_views import HISTORY_KEY
from .literary_evidence import validate_evidence
from .literary_ai import validate_draft
from .literary_quality import validate_audit
from .literary_identity import same_work
from .literary_knowledge import (ORIGINAL_LICENSE, prepare_seed_knowledge, remember_work,
                                search_knowledge)


ROSE = 'Recuerdo un libro donde un niño vive en un planeta pequeño y cuida una rosa'
ANIMALS = 'Busco un libro que menciona que todos los animales son iguales'


class IdentificationFixtures:
    def prepare(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / 'knowledge.sqlite3'
        prepare_seed_knowledge(self.database)
        settings = override_settings(LITMATE_KNOWLEDGE_DB=self.database)
        settings.enable()
        self.addCleanup(settings.disable)


class LocalIdentificationTests(IdentificationFixtures, SimpleTestCase):
    def setUp(self):
        self.prepare()

    def test_known_recollections_only_propose_the_verified_title_and_author(self):
        for message, title, author in [(ROSE, 'El principito', 'Antoine de Saint-Exupéry'),
                                        (ANIMALS, 'Rebelión en la granja', 'George Orwell')]:
            with self.subTest(title=title), patch('core.ai_http.read_json_url', side_effect=AssertionError('No network')):
                result = identification_answer(message)
                self.assertEqual(result.status, 'answered')
                self.assertEqual(result.text,
                    f'Por tus pistas, podrías estar buscando **{title}**, de **{author}**. ¿Te suena?')
                self.assertTrue(result.diagnostics['local_identification_fast_path'])
                self.assertGreaterEqual(len(result.diagnostics['matched_clues']), 2)
                self.assertEqual(result.books[0]['title'], title)
                self.assertTrue(all(same_work(source, result.sources[0]) for source in result.sources))
                self.assertTrue(all(source['license'] == ORIGINAL_LICENSE and source['url']
                                    for source in result.sources))
                self.assertNotIn('flor silvestre', result.text)
                self.assertNotIn('todos los animales son iguales', result.text)

    def test_all_three_real_validators_run_and_audit_is_strict(self):
        with patch('core.ai_identification_details.validate_draft', wraps=validate_draft) as draft, \
                patch('core.ai_identification_details.validate_evidence', wraps=validate_evidence) as evidence, \
                patch('core.ai_identification_details.validate_audit', wraps=validate_audit) as audit:
            self.assertIsNotNone(identification_answer(ROSE))
        draft.assert_called_once()
        evidence.assert_called_once()
        audit.assert_called_once()
        self.assertTrue(audit.call_args.kwargs['strict_facts'])
        proof = audit.call_args.args[0]['claims'][0]
        sources = audit.call_args.args[3]
        self.assertIn(proof['evidence'], sources[proof['source_id'] - 1]['title'])

    def test_validation_failure_defers_instead_of_publishing_the_proposal(self):
        with patch('core.ai_identification_details.validate_audit', side_effect=ValueError('Invalid proof')):
            self.assertIsNone(identification_answer(ROSE))

    def test_incomplete_clues_and_unrelated_memories_are_left_to_the_pipeline(self):
        for message in ('Recuerdo un niño en un planeta',
                        'Recuerdo una escena de un libro, pero no su título',
                        'Recuerdo un libro sobre una cantante en una ciudad submarina',
                        'Recuerdo un libro de George Orwell'):
            with self.subTest(message=message):
                self.assertIsNone(identification_answer(message))

    def test_competing_supported_book_defers_instead_of_choosing_the_first(self):
        remember_work({'title': 'La rosa del satélite', 'author': 'Autora de fixture',
            'description': 'Un niño vive en un planeta pequeño y cuida una rosa.',
            'url': 'https://openlibrary.org/works/OL999W', 'license': ORIGINAL_LICENSE,
            'indexing_authorized': True}, database=self.database)
        self.assertIsNone(identification_answer(ROSE))

    def test_conflicting_verified_facts_do_not_enable_the_fast_proposal(self):
        received = search_knowledge(ROSE, maximum=8, database=self.database)
        bound = next(source for source in received if source['kind'] == 'web')
        for suffix, identity in [('uno', 'Un aviador'), ('dos', 'Un rey')]:
            statement = 'La identidad del niño es ' + identity + '.'
            received.append({**copy.deepcopy(bound), 'description': statement,
                'url': 'https://es.wikipedia.org/wiki/Fixture_' + suffix,
                'literary_facts': [{'subject': 'Niño', 'relation': 'identity',
                                   'value': identity, 'evidence': statement}]})
        with patch('core.ai_identification_details.search_knowledge', return_value=received):
            self.assertIsNone(identification_answer(ROSE))

    def test_unlicensed_external_or_missing_provenance_defers(self):
        original = search_knowledge(ROSE, maximum=8, database=self.database)
        for changes in ({'license': ''}, {'license': 'CC0'}, {'source': 'Wikipedia'},
                        {'url': 'http://127.0.0.1/private'}):
            with self.subTest(changes=changes), patch('core.ai_identification_details.search_knowledge',
                    return_value=[{**source, **changes} for source in original]):
                self.assertIsNone(identification_answer(ROSE))

    def test_private_mixed_exact_and_topic_requests_do_not_even_read_the_index(self):
        messages = [ROSE + ' y calcula cuánto es 1 + 1', ROSE + ' y explica su final',
                    ROSE + ' mi contraseña es secreto123', ROSE + ' mi amigo Pedro lo recuerda',
                    ROSE + '. Analiza este fragmento: un pasaje privado.',
                    ROSE + ' dame la cita textual exacta',
                    'Recomiéndame libros sobre rosas y planetas',
                    'Busco libros sobre animales e igualdad',
                    'Recuerdo un libro y sus personajes', ROSE + ' además traduce al inglés']
        for message in messages:
            with self.subTest(message=message), patch('core.ai_identification_details.search_knowledge') as search:
                self.assertIsNone(identification_answer(message))
                search.assert_not_called()


@override_settings(LITMATE_AI_BIBLIOGRAPHIC_FAST_PATH=True,
                   LITMATE_AI_PUBLIC_DETAILS_FAST_PATH=True, LITMATE_AI_USE_WEB=True,
                   LITMATE_USE_EXISTING_QUOTAS=False, LITMATE_AI_LOCK_BACKEND='cache')
class LocalIdentificationEndpointTests(IdentificationFixtures, TestCase):
    def setUp(self):
        cache.clear()
        self.prepare()

    def test_authenticated_proposal_records_sources_and_no_model_usage(self):
        from .models import MensajeIA
        user = get_user_model().objects.create_user(username='local-identification-reader')
        self.client.force_login(user)
        with patch('core.literary_ai_views.build_assistant') as model, \
                patch('core.literary_search.retrieve_books') as catalog, \
                patch('core.literary_search.retrieve_web') as web, \
                patch('core.literary_search.search_google') as google, \
                patch('core.literary_ai_views.acquire') as lock:
            response = self.client.post('/chatbot_query/', json.dumps({'message': ROSE}),
                                        content_type='application/json')
            events = b''.join(response.streaming_content).decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertIn('El principito', events)
        for dependency in (model, catalog, web, google, lock):
            dependency.assert_not_called()
        answer = MensajeIA.objects.get(rol='assistant')
        self.assertEqual(answer.tokens_utilizados, 0)
        self.assertEqual(answer.metadata_json['provider'], 'local-identification')
        self.assertEqual(answer.metadata_json['provider_calls'], 0)
        self.assertTrue(answer.metadata_json['sources'])
        self.assertEqual(self.client.session[HISTORY_KEY]['turns'][-1]['books'][0]['title'], 'El principito')

    def test_enabled_quota_keeps_identification_fast_and_consumes_only_after_answer(self):
        from types import SimpleNamespace
        from .literary_ai import ChatResult
        from unittest.mock import Mock
        assistant = Mock()
        assistant.reply.return_value = ChatResult('Falta evidencia.', 'clarification')
        with override_settings(LITMATE_USE_EXISTING_QUOTAS=True), \
                patch('core.ai_identification_details.identification_answer', wraps=identification_answer) as fast, \
                patch('core.literary_ai_views.cuota_disponible', return_value=(True, {})), \
                patch('core.literary_ai_views.verificar_y_consumir_cuota', return_value=(True, {})) as consume, \
                patch('core.literary_ai_views.build_assistant',
                      return_value=(assistant, SimpleNamespace(usage={}, provider='ollama-local', calls=1))):
            response = self.client.post('/chatbot_query/', json.dumps({'message': ROSE}),
                                        content_type='application/json')
            b''.join(response.streaming_content)
        self.assertEqual(response.status_code, 200)
        fast.assert_called_once()
        assistant.reply.assert_not_called()
        consume.assert_called_once()
