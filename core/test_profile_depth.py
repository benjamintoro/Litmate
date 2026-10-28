"""Profile scope and quoted alias evidence across ingestion and retrieval."""
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import SimpleTestCase
from .ai_character_answers import bind_character_profile, answer_from_sources
from .literary_memory import _character_aliases, _character_passage, remember_evidence, retrieve_character_entities


def profile():
    title, url = 'Elena Sol', 'https://es.wikipedia.org/wiki/Elena_Sol'
    text = 'Elena "Lena" Sol es uno de los personajes principales de la novela Las rutas, de Ana Escritora.'
    return {'title': title, 'kind': 'web', 'author': 'Fuente web', 'source': 'Wikipedia',
            'description': text, 'identity_text': text, 'url': url,
            'read_mode': 'extracto de introducción', 'license': 'CC-BY-SA-4.0',
            'storage_policy': 'wikipedia-cc-by-sa-4.0-v1',
            'attribution': {'title': title, 'url': url, 'authors': 'Wikipedia contributors',
                            'revision_id': '123', 'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/'}}


class ProfileDepthTests(SimpleTestCase):
    def test_quoted_alias_keeps_complete_name_and_same_clause(self):
        source = profile()
        self.assertEqual(_character_aliases('Elena Sol', source['description']), ['Lena'])
        role = 'es uno de los personajes principales de la novela Las rutas, de Ana Escritora.'
        fact = {'name': 'Elena Sol', 'role': role, 'evidence': source['description']}
        self.assertEqual(_character_passage(fact, source['description']), source['description'])
        self.assertEqual(_character_aliases('Elena Sol', 'Elena conversa con "Lena" y con Irene Sol.'), [])

    def test_scoped_profile_answers_alias_and_survives_ingestion(self):
        from .ai_character_answers import _profile_facts
        book = {'title': 'Las rutas', 'author': 'Ana Escritora'}
        source = bind_character_profile(profile(), book)
        self.assertIsNotNone(source)
        request = {'task': 'character', 'focus': 'all', 'title': book['title'], 'targets': [book],
                   'names': ['Lena'], 'ambiguous': False}
        self.assertIsNotNone(answer_from_sources('¿Quién es Lena?', request, [source]))
        with TemporaryDirectory() as folder:
            database = Path(folder) / 'memory.sqlite3'
            source = _profile_facts(source, request)
            self.assertEqual(remember_evidence([book], [source], database=database)['sources'], 1)
            found = retrieve_character_entities('Lena', books=[book], names=['Lena'], database=database)
            self.assertEqual(len(found), 1)
            self.assertIn('Lena', found[0]['aliases'])

    def test_profile_does_not_infer_a_different_volume_or_author(self):
        for book in ({'title': 'Las rutas II', 'author': 'Ana Escritora'},
                     {'title': 'Las rutas', 'author': 'Otra Autora'}):
            self.assertIsNone(bind_character_profile(profile(), book))
