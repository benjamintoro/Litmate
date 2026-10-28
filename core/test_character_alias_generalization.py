"""Identity fixtures only: linguistic evidence, not a catalogue of answers."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from .ai_character_answers import answer_from_sources, request_for
from .test_character_quality_regression import evidence


class CharacterAliasDevelopmentTests(SimpleTestCase):
    def sources(self):
        return evidence('Los viajeros del norte', 'Autora de prueba', [
            ('Rafael de la Vega', 'También llamado Rafa, es el protagonista del viaje.'),
            ('Martín Robles', 'También conocido como Tino, es amigo de Rafa.'),
        ])

    def test_relationship_uses_two_explicit_aliases_without_rewriting_source(self):
        sources = self.sources()
        before = deepcopy(sources)
        history = [{'accepted': True, 'question': 'Los viajeros del norte', 'answer': '',
                    'books': sources[:1], 'sources': sources}]
        message = '¿Qué relación tienen Rafael de la Vega y Tino?'
        result = answer_from_sources(message, request_for(message, history), sources)
        self.assertIsNotNone(result)
        self.assertIn('amigo de Rafa', result.text)
        self.assertEqual(sources, before)

    def test_aliases_are_extracted_and_retrieved_from_persistent_evidence(self):
        from .literary_memory import remember_evidence, retrieve_character_entities
        sources = self.sources()
        sources[1].update(storage_policy='wikipedia-cc-by-sa-4.0-v1',
                          work_title=sources[0]['title'], work_author=sources[0]['author'],
                          work_binding_verified=True, attribution={
                              'authors': 'Wikipedia contributors', 'title': sources[1]['title'],
                              'url': sources[1]['url'], 'revision_id': '1',
                              'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/'})
        with TemporaryDirectory() as folder:
            database = Path(folder) / 'memory.sqlite3'
            remember_evidence(sources[:1], sources, database=database)
            result = retrieve_character_entities('Tino', books=sources[:1], names=['Tino'], database=database)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['canonical_name'], 'Martín Robles')
            self.assertTrue(result[0]['evidence'])

    def test_same_alias_for_different_people_is_ambiguous(self):
        sources = self.sources()
        role = 'También llamado Tino, es hermano de Rafa.'
        sources[1]['description'] += '\nErnesto Ruiz: ' + role
        sources[1]['character_facts'].append({'name': 'Ernesto Ruiz', 'role': role})
        history = [{'accepted': True, 'books': sources[:1], 'sources': sources}]
        message = '¿Quién es Tino?'
        self.assertIsNone(answer_from_sources(message, request_for(message, history), sources))
