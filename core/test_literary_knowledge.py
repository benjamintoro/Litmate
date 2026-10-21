import io
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from .literary_evidence import exact_context_available
from .literary_identity import same_work
from .literary_knowledge import (lookup_work, lookup_facts, remember_work,
    prepare_seed_knowledge, search_knowledge, search_knowledge_semantic, knowledge_revision)
from .local_rag import index_documents, retrieve_fragments


class CountingLocalEmbeddings:
    """Vectores deterministas; comprueba reutilización sin consultar Ollama."""
    def __init__(self):
        self.calls = 0

    def identity(self):
        return 'embeddinggemma:latest', 'a' * 64

    def embed(self, texts, *, query=False):
        self.calls += 1
        return [[1., 0., 0.] for _ in texts]


class KnowledgeTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'facts.sqlite3'
        self.index = self.root / 'facts-rag.sqlite3'
        self.user_index = self.root / 'novels.sqlite3'
        self.options = override_settings(LITMATE_KNOWLEDGE_DB=self.db,
            LITMATE_KNOWLEDGE_RAG_DB=self.index, LITMATE_RAG_DB=self.user_index,
            LITMATE_RAG_SEMANTIC=False)
        self.options.enable()

    def tearDown(self):
        self.options.disable()
        self.temp.cleanup()

    def prepare(self):
        return prepare_seed_knowledge(self.db)

    def test_missing_database_does_not_create_data_or_call_external_sources(self):
        self.assertEqual(search_knowledge('Raskólnikov', database=self.db), [])
        self.assertFalse(self.db.exists())

    def test_confirmed_alias_resolves_same_work_but_other_volume_does_not(self):
        self.prepare()
        short = lookup_work('Papelucho y el marciano', database=self.db)
        full = lookup_work('Diario secreto de Papelucho y el marciano', database=self.db)
        self.assertEqual(short['work_id'], full['work_id'])
        self.assertTrue(same_work(short, full))
        self.assertIn('ci.nii.ac.jp', short['confirmed_aliases'][0]['source_url'])
        self.assertIsNone(lookup_work('Papelucho detective', database=self.db))
        self.assertEqual(search_knowledge('Papelucho detective', database=self.db), [])

    def test_known_memory_queries_return_verified_candidates(self):
        self.prepare()
        for query, title in [
            ('Recuerdo un niño que vivía en un planeta pequeño y cuidaba una rosa y conocía a un zorro', 'El principito'),
            ('Busco un libro que menciona que todos los animales son iguales', 'Rebelión en la granja'),
            ('¿En qué libro aparece Raskólnikov?', 'Crimen y castigo'),
            ('Un personaje llamado Raskolnikof', 'Crimen y castigo'),
            ('Dime los personajes de Papelucho y el marciano', 'Diario secreto de Papelucho y el marciano'),
        ]:
            with self.subTest(query=query):
                sources = search_knowledge(query, database=self.db)
                self.assertTrue(sources)
                self.assertEqual(sources[0]['title'], title)
                self.assertEqual(sources[0]['kind'], 'book')
                self.assertTrue(any(source.get('kind') == 'web' and source.get('url') for source in sources))

    def test_vague_memory_does_not_force_candidate(self):
        self.prepare()
        self.assertEqual(search_knowledge('Era un libro sobre una mujer que viajaba', database=self.db), [])
        self.assertEqual(search_knowledge('Recuerdo una escena de un libro pero no su título', database=self.db), [])

    def test_det_context_reuses_verified_work_and_partial_characters(self):
        self.prepare()
        work = lookup_work('Papelucho y el marciano', database=self.db)
        sources = search_knowledge('¿Qué sucede con Det?', work_id=work['work_id'], database=self.db)
        web = next(source for source in sources if source['kind'] == 'web')
        self.assertTrue(same_work(web, work))
        self.assertEqual({fact['name'] for fact in web['character_facts']}, {'Papelucho', 'Det'})
        self.assertEqual(web['character_scope'], 'partial')
        for fact in web['character_facts']:
            self.assertIn(fact['role'], web['description'])
        self.assertIn('literaturasm.cl', web['url'])

    def test_local_factual_summary_cannot_authorize_novel_quotes_or_pages(self):
        self.prepare()
        sources = search_knowledge('Rebelión en la granja', database=self.db)
        self.assertFalse(any(source['kind'] == 'excerpt' for source in sources))
        self.assertFalse(exact_context_available('Dame una cita exacta', sources))
        self.assertTrue(all(source.get('license') for source in sources))

    def test_idempotent_seed_keeps_custom_fiches_and_replaces_obsolete_facts(self):
        self.prepare()
        work = {'title': 'Ficha propia', 'author': 'Autora',
            'url': 'https://example.org/ficha', 'license': 'redacción autorizada',
            'indexing_authorized': True, 'facts': [
                {'text': 'Una descripción original y autorizada del personaje anterior.',
                 'source_url': 'https://example.org/ficha', 'topic': 'characters'}]}
        stored = remember_work(work, database=self.db)
        self.prepare()
        self.assertIsNotNone(lookup_work('Ficha propia', database=self.db))
        self.assertEqual(len(lookup_facts(stored['work_id'], database=self.db)), 1)
        work['facts'] = [{'text': 'La descripción corregida elimina el dato obsoleto.',
            'source_url': 'https://example.org/ficha', 'topic': 'summary'}]
        remember_work(work, database=self.db)
        facts = lookup_facts(stored['work_id'], database=self.db)
        self.assertEqual(len(facts), 1)
        self.assertIn('corregida', facts[0]['text'])

    def test_permanent_storage_requires_explicit_rights_and_valid_provenance(self):
        work = {'title': 'Obra', 'author': 'Autora', 'url': 'https://example.org/ficha'}
        with self.assertRaises(ValueError):
            remember_work(work, database=self.db)
        self.assertFalse(self.db.exists())

    def test_prepare_command_builds_separate_fts_index_with_safe_source_types(self):
        self.user_index.write_bytes(b'datos del usuario que no deben modificarse')
        out = io.StringIO()
        call_command('preparar_conocimiento', stdout=out)
        self.assertIn('4 iniciales', out.getvalue())
        sources = retrieve_fragments('rosa zorro', self.index)
        self.assertTrue(sources)
        self.assertTrue(all(source['kind'] == 'web' for source in sources))
        self.assertTrue(all(source.get('work_binding_verified') for source in sources))
        self.assertTrue(all('no texto de la novela' in source['read_mode'] for source in sources))
        self.assertEqual(self.user_index.read_bytes(), b'datos del usuario que no deben modificarse')
        call_command('preparar_conocimiento', stdout=io.StringIO())

    def test_prepare_command_refuses_overwriting_unknown_index(self):
        self.index.write_bytes(b'otra base de datos que pertenece al usuario')
        with self.assertRaises(CommandError):
            call_command('preparar_conocimiento', stdout=io.StringIO())
        self.assertEqual(self.index.read_bytes(), b'otra base de datos que pertenece al usuario')
        self.assertFalse(self.db.exists())

    @override_settings(LITMATE_RAG_SEMANTIC=True)
    def test_repeated_semantic_preparation_preserves_factual_metadata_and_adds_new_work(self):
        first, second = CountingLocalEmbeddings(), CountingLocalEmbeddings()
        with patch('core.local_embeddings.configured_embedder', return_value=first):
            call_command('preparar_conocimiento', semantico=True, stdout=io.StringIO())
        self.assertGreater(first.calls, 0)
        with patch('core.local_embeddings.configured_embedder', return_value=second):
            call_command('preparar_conocimiento', semantico=True, stdout=io.StringIO())
        self.assertEqual(second.calls, 0)
        results = retrieve_fragments('rosa', self.index)
        self.assertTrue(results)
        self.assertTrue(all(source['kind'] == 'web' for source in results))
        self.assertTrue(all(source.get('license') and source.get('work_binding_verified') for source in results))
        self.assertEqual(results[0]['title'], 'El principito')
        remember_work({'title': 'Obra nueva', 'author': 'Autora propia',
            'url': 'https://example.org/nueva', 'license': 'CC0-1.0',
            'indexing_authorized': True, 'facts': [{'topic': 'summary',
                'source_url': 'https://example.org/nueva',
                'text': 'Una protagonista explora una isla de cristales y conserva un mapa del archipiélago.'}]}, database=self.db)
        third = CountingLocalEmbeddings()
        with patch('core.local_embeddings.configured_embedder', return_value=third):
            call_command('preparar_conocimiento', semantico=True, stdout=io.StringIO())
        self.assertEqual(third.calls, 1)
        updated = retrieve_fragments('cristales', self.index)[0]
        self.assertEqual(updated['title'], 'Obra nueva')
        self.assertEqual(updated['kind'], 'web')
        self.assertEqual(updated['url'], 'https://example.org/nueva')
        self.assertEqual(updated['license'], 'CC0-1.0')
        self.assertEqual(retrieve_fragments('rosa', self.index)[0]['kind'], 'web')

    def test_prepare_command_rejects_using_novel_index_as_destination(self):
        with self.assertRaises(CommandError):
            call_command('preparar_conocimiento', indice=str(self.user_index), stdout=io.StringIO())

    def test_revision_invalidates_after_updates(self):
        first = knowledge_revision(database=self.db)
        self.prepare()
        self.assertNotEqual(first, knowledge_revision(database=self.db))


class AuthorizedRAGTests(SimpleTestCase):
    def test_semantic_reindex_reuses_vectors_without_overwriting_authorized_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / 'documents'
            folder.mkdir()
            filename = 'Etiqueta__Archivo.txt'
            (folder / filename).write_text(
                'Una rosa crece en un planeta pequeño. Es una descripción original autorizada.', encoding='utf-8')
            metadata = {filename: {'kind': 'web', 'url': 'https://example.org/obra',
                'source': 'Biblioteca literaria local', 'work_title': 'Obra canónica',
                'work_author': 'Autora', 'work_id': 'test:work', 'license': 'CC0-1.0',
                'indexing_authorized': True, 'work_binding_verified': True}}
            index = root / 'rag.sqlite3'
            first, second = CountingLocalEmbeddings(), CountingLocalEmbeddings()
            index_documents(folder, index, metadata=metadata, embedder=first)
            self.assertGreater(first.calls, 0)
            index_documents(folder, index, metadata=metadata, embedder=second)
            # El contrato de permisos y procedencia debe sobrevivir incluso al
            # reutilizar el índice previo para no generar embeddings otra vez.
            self.assertEqual(second.calls, 0)
            source = retrieve_fragments('rosa', index)[0]
            self.assertEqual(source['kind'], 'web')
            self.assertEqual(source['title'], 'Obra canónica')
            self.assertEqual(source['work_id'], 'test:work')
            self.assertEqual(source['source'], 'Biblioteca literaria local')
            self.assertEqual(source['url'], 'https://example.org/obra')
            self.assertEqual(source['license'], 'CC0-1.0')
            self.assertTrue(source['work_binding_verified'])
            self.assertFalse(exact_context_available('Dame una cita exacta', [source]))
            # La API que filtra resúmenes factuales tampoco debe perderlos tras
            # reconstruir: la consulta no comparte palabras con el documento.
            semantic = search_knowledge_semantic('aroma floral', database=index, embedder=second)
            self.assertTrue(semantic)
            self.assertEqual(semantic[0]['kind'], 'web')
            self.assertEqual(semantic[0]['title'], 'Obra canónica')

    def test_manifest_summary_retains_provenance_and_never_becomes_novel_excerpt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / 'documents'
            folder.mkdir()
            filename = 'Semilla__Autora.txt'
            (folder / filename).write_text('Una rosa crece en un planeta pequeño. Es una descripción original autorizada.', encoding='utf-8')
            metadata = {filename: {'kind': 'web', 'url': 'https://example.org/obra',
                'source': 'Biblioteca literaria local', 'work_title': 'Obra canónica',
                'work_author': 'Autora', 'work_id': 'test:work', 'license': 'CC0-1.0',
                'indexing_authorized': True, 'work_binding_verified': True}}
            index = root / 'rag.sqlite3'
            index_documents(folder, index, metadata=metadata)
            source = retrieve_fragments('rosa', index)[0]
            self.assertEqual(source['title'], 'Obra canónica')
            self.assertEqual(source['kind'], 'web')
            self.assertEqual(source['url'], 'https://example.org/obra')
            self.assertEqual(source['author'], 'Fuente web')
            self.assertFalse(exact_context_available('página 1', [source]))
            (folder / filename).write_text('El documento corregido habla de un zorro; el dato anterior ha quedado obsoleto.', encoding='utf-8')
            index_documents(folder, index, metadata=metadata)
            self.assertEqual(retrieve_fragments('rosa', index), [])
            self.assertTrue(retrieve_fragments('zorro', index))

    def test_manifest_cannot_turn_unlicensed_external_page_into_permanent_fiche(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Libro__Autor.txt').write_text('Contenido externo sin autorización explícita para guardarlo permanentemente.')
            with self.assertRaises(ValueError):
                index_documents(root, root / 'rag.sqlite3', metadata={
                    'Libro__Autor.txt': {'kind': 'web', 'url': 'https://example.org/ficha'}})
