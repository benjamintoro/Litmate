"""Persisted web evidence must keep its bibliographic identity in the chat."""
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import SimpleTestCase, override_settings
from .literary_memory import remember_evidence
from .test_profile_depth import profile
from .ai_character_answers import _profile_facts, bind_character_profile, answer_from_sources, request_for
from .ai_quick_answers import quick_knowledge_sources


class PersistentDepthBridgeTests(SimpleTestCase):
    def test_web_only_evidence_does_not_lose_its_separate_work_metadata(self):
        book = {'title': 'Las rutas', 'author': 'Ana Escritora'}
        page = _profile_facts(bind_character_profile(profile(), book), {'names': ['Lena']})
        with TemporaryDirectory() as folder, override_settings(
                LITMATE_LITERARY_MEMORY_DB=Path(folder) / 'memory.sqlite3'):
            remember_evidence([book], [page])
            found = quick_knowledge_sources('Las rutas', maximum=16)
            self.assertTrue(any(source['kind'] == 'book' and source['title'] == book['title'] for source in found))
            request = request_for('¿Quién es Lena?', [{'accepted': True, 'books': [book], 'sources': found}])
            self.assertIsNotNone(answer_from_sources('¿Quién es Lena?', request, found))
