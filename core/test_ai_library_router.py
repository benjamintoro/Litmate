"""Integración del corpus permitido con el asistente; sin HTTP ni Ollama."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .literary_ai import ChatResult
from .literary_library import import_manifest, retract_document


class LibraryRouterTests(SimpleTestCase):
    def test_table_of_contents_is_not_sufficient_local_narrative_evidence(self):
        from .ai_library_router import library_catalogue, sources_for_request
        self.imported()
        book = library_catalogue(self.item['title'])[0]
        fragments = [{**book,'kind':'excerpt','description':'CHAPTER II. A traveller journal'}]
        with patch('core.ai_library_router.library_fragments',return_value=fragments):
            self.assertEqual(sources_for_request('Dime la trama',self.request()),[])

    def test_main_character_classification_does_not_trigger_unfounded_local_inference(self):
        from .ai_library_router import character_answer_from_library
        source = {'kind':'excerpt','description':'Alicia busca una ciudad junto a Elena. Ambas viajan por el bosque.'}
        with patch('core.ai_library_router.sources_for_request',return_value=[source]), \
                patch('core.ai_narrative_answers.synthesize_answer',return_value=(
                    ChatResult('No puedo clasificar.', 'unavailable'),SimpleNamespace(calls=2,usage={}))) as model:
            self.assertIsNone(character_answer_from_library('Dime sus personajes principales',
                {**self.request(),'focus':'main'},SimpleNamespace()))
            model.assert_not_called()

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / 'library.sqlite3'
        self.override = override_settings(LITMATE_LIBRARY_DB=self.database,
            LITMATE_LIBRARY_RAG_DB=self.root / 'library-rag.sqlite3')
        self.override.enable()
        self.addCleanup(self.override.disable)
        raw = ('CAPÍTULO I\n\nAlicia es la protagonista de esta novela. Elena es amiga de Alicia '
               'y la acompaña al jardín. Ambas buscan una rosa junto a la ventana.').encode()
        (self.root / 'original.txt').write_bytes(raw)
        self.item = {'title': 'El jardín de prueba', 'author': 'Autora de prueba', 'language': 'es',
            'edition': 'Edición sintética', 'source_url': 'https://example.org/original',
            'path': 'original.txt', 'sha256': hashlib.sha256(raw).hexdigest(),
            'rights': {'status': 'open_license', 'license': 'CC0-1.0', 'jurisdiction': 'CL',
                'edition_covered': True, 'statement': 'Texto sintético creado para probar esta integración.',
                'reviewed_at': datetime.now(timezone.utc).date().isoformat(),
                'evidence_urls': ['https://creativecommons.org/publicdomain/zero/1.0/']}}
        self.manifest = self.root / 'manifest.json'
        self.manifest.write_text(json.dumps({'version': 1, 'books': [self.item]}), encoding='utf-8')

    def imported(self):
        report = import_manifest(self.manifest, self.database, self.root / 'stored')
        self.assertEqual(report['errors'], [])

    def request(self):
        return {'task': 'characters', 'title': self.item['title'], 'names': [],
                'targets': [], 'focus': 'all', 'ambiguous': False}

    def test_no_library_never_creates_a_database_or_intercepts_a_question(self):
        from .ai_library_router import library_catalogue, sources_for_request
        self.assertEqual(library_catalogue('Una obra desconocida'), [])
        self.assertEqual(sources_for_request('Dime sus personajes', self.request()), [])
        self.assertFalse(self.database.exists())

    def test_sources_preserve_original_hash_and_correct_work_and_edition(self):
        from .ai_library_router import sources_for_request
        self.imported()
        sources = sources_for_request('Dime los personajes de El jardín de prueba', self.request())
        self.assertTrue(sources)
        fragments = [source for source in sources if source['kind'] == 'excerpt']
        self.assertTrue(fragments)
        self.assertTrue(all(source['original_sha256'] == self.item['sha256'] for source in fragments))
        self.assertTrue(all(source['edition'] == self.item['edition'] for source in fragments))
        self.assertTrue(all(source['work_title'] == self.item['title'] for source in fragments))
        self.assertTrue(all('capítulo/sección' in source['locator'] for source in fragments))

    def test_active_author_and_sequel_are_not_interchangeable(self):
        from .ai_library_router import sources_for_request
        self.imported()
        request = self.request()
        request['targets'] = [{'title': self.item['title'], 'author': 'Otro autor'}]
        self.assertEqual(sources_for_request('Dime sus personajes', request), [])
        request.update(targets=[], title=self.item['title'] + ' II')
        self.assertEqual(sources_for_request('Dime sus personajes', request), [])

    def test_retraction_invalidates_retrieval_and_answer_cache_revision(self):
        from .ai_library_router import library_catalogue, sources_for_request, library_revision
        self.imported()
        book = library_catalogue(self.item['title'])[0]
        before = library_revision()
        retract_document(book['library_document_id'], self.database, reason='Prueba de retractación')
        self.assertNotEqual(library_revision(), before)
        self.assertEqual(sources_for_request('Dime sus personajes', self.request()), [])

    def test_synthesis_uses_existing_audit_and_never_calls_a_search_provider(self):
        from .ai_library_router import character_answer_from_library
        self.imported()
        expected = ChatResult('Alicia es la protagonista.', 'answered')
        client = SimpleNamespace(calls=2, usage={})
        with patch('core.ai_narrative_answers.synthesize_answer', return_value=(expected, client)) as synthesize, \
                patch('core.literary_search.search_wikipedia', side_effect=AssertionError('Sin red')), \
                patch('core.literary_search.search_openlibrary', side_effect=AssertionError('Sin red')):
            result = character_answer_from_library('Dime los personajes de El jardín de prueba',
                                                   self.request(), SimpleNamespace())
        self.assertIs(result, expected)
        self.assertTrue(result.diagnostics['local_library'])
        self.assertEqual(result.diagnostics['model_calls'], 2)
        self.assertTrue(any(source['kind'] == 'excerpt' for source in synthesize.call_args.args[2]))

    def test_a_rejected_draft_cannot_become_a_persistent_character_fact(self):
        from .ai_library_router import character_answer_from_library
        self.imported()
        declined = ChatResult('No está respaldado.', 'unavailable')
        with patch('core.ai_narrative_answers.synthesize_answer', return_value=(declined,
                   SimpleNamespace(calls=2, usage={}))), \
                patch('core.ai_persistent_router.persist_sources', side_effect=AssertionError('No guardar IA')):
            result = character_answer_from_library('Dime sus personajes', self.request(), SimpleNamespace())
        self.assertEqual(result.status, 'unavailable')
        self.assertIn('character_failure', result.diagnostics)

    def test_narrative_retrieval_uses_authorized_fragments_before_external_sources(self):
        from .ai_narrative_answers import retrieve_sources
        self.imported()
        request = {**self.request(), 'task': 'summary'}
        with patch('core.ai_quick_answers.quick_knowledge_sources', return_value=[]), \
                patch('core.literary_search.search_wikipedia', side_effect=AssertionError('No hace falta red')), \
                patch('core.literary_search.search_openlibrary', side_effect=AssertionError('No hace falta red')):
            sources = retrieve_sources('Dime la trama de El jardín de prueba', request, [])
        self.assertTrue(any(source['kind'] == 'excerpt' for source in sources))
        self.assertEqual(request['retrieval_trace'][0]['stage'], 'local_library')

    def test_catalog_subtitle_does_not_hide_the_verified_local_original(self):
        from .ai_library_router import library_books_for_query
        from .literary_search import retrieve_book_content
        self.imported()
        message = '¿Qué le dice Elena a Alicia en El jardín de prueba?'
        candidates = [{'title': 'El jardín de prueba; o, la rosa', 'author': 'Autora'}]
        books = library_books_for_query(message, candidates)
        self.assertEqual([book['title'] for book in books], [self.item['title']])
        with override_settings(LITMATE_RAG_DB=self.root / 'missing-rag.sqlite3'), \
                patch('core.literary_knowledge.search_knowledge', return_value=[]):
            sources = retrieve_book_content(message, candidates)
        self.assertTrue(any(source['kind'] == 'excerpt' for source in sources))
        self.assertTrue(all(source.get('library_document_id') for source in sources))

    def test_general_content_retrieval_never_uses_an_unrelated_local_work(self):
        from .literary_search import retrieve_book_content
        self.imported()
        message = '¿Qué expresa la melancolía en una obra desconocida?'
        with override_settings(LITMATE_RAG_DB=self.root / 'missing-rag.sqlite3'), \
                patch('core.literary_knowledge.search_knowledge', return_value=[]):
            sources = retrieve_book_content(message, [{'title': 'Obra desconocida',
                                                       'author': 'Autora desconocida'}])
        self.assertFalse(any(source.get('library_document_id') for source in sources))

    def test_ai_settings_define_optional_library_paths_and_semantic_flag(self):
        from litmate_project.ai_settings import apply_ai_settings
        target = {}
        with patch.dict('os.environ', {'LITMATE_LIBRARY_SEMANTIC_CHAT': 'false'}, clear=False):
            apply_ai_settings(target, self.root)
        self.assertEqual(target['LITMATE_LIBRARY_DB'],
                         self.root / 'data' / 'biblioteca' / 'biblioteca.sqlite3')
        self.assertEqual(target['LITMATE_LIBRARY_RAG_DB'],
                         self.root / 'data' / 'biblioteca' / 'rag.sqlite3')
        self.assertFalse(target['LITMATE_LIBRARY_SEMANTIC_CHAT'])

    def test_spanish_alias_is_limited_to_the_verified_work_and_author(self):
        from .literary_library import curated_aliases
        aliases = curated_aliases('Pride and Prejudice', 'Jane Austen')
        self.assertEqual([alias['title'] for alias in aliases], ['Orgullo y prejuicio'])
        self.assertEqual(aliases[0]['source_url'], 'https://openlibrary.org/works/OL19651512W')
        self.assertEqual(curated_aliases('Emma', 'Jane Austen'), [])
        self.assertEqual(curated_aliases('Pride and Prejudice', 'Otra autora'), [])

    def test_general_content_retrieval_honours_the_library_semantic_opt_in(self):
        from .literary_search import retrieve_book_content
        with override_settings(LITMATE_RAG_DB=self.root / 'missing-rag.sqlite3',
                               LITMATE_LIBRARY_SEMANTIC_CHAT=True), \
                patch('core.literary_knowledge.search_knowledge', return_value=[]), \
                patch('core.ai_library_router.library_fragments', return_value=[]) as fragments:
            retrieve_book_content('consulta sin obra local', [])
        self.assertTrue(fragments.call_args.kwargs['semantic'])
