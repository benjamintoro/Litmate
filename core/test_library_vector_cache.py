"""Reanudación con proveedor simulado; no mide Ollama ni llama a Internet."""
from contextlib import closing
import hashlib
import math
from pathlib import Path
import sqlite3
import tempfile
import time
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from .ai_budget import BudgetExpired, request_budget
from .local_rag import index_documents


class ControlledEmbeddings:
    def __init__(self, *, fail_after=None, digest='a' * 64, dimension=3, sleep=0):
        self.fail_after, self.digest, self.dimension = fail_after, digest, dimension
        self.sleep, self.calls, self.batches = sleep, 0, []

    def identity(self):
        return 'embeddinggemma:latest', self.digest

    def embed(self, texts):
        self.calls += 1
        self.batches.append(len(texts))
        if self.fail_after is not None and self.calls > self.fail_after:
            raise OSError('Interrupción simulada del proveedor')
        if self.sleep:
            time.sleep(self.sleep)
        return [[1.0] + [0.0] * (self.dimension - 1) for _ in texts]


class LibraryVectorCacheTests(SimpleTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / 'originals'
        self.folder.mkdir()
        self.path = self.folder / 'Jardín__Autora.txt'
        body = ('Alicia descubre una rosa azul. Elena conversa con Alicia sobre el jardín.\n\n' * 500)
        self.path.write_bytes(body.encode())
        self.index, self.cache = self.root / 'index.sqlite3', self.root / 'vectors.sqlite3'
        self.metadata = {self.path.name: {'kind': 'excerpt', 'indexing_authorized': True,
            'library_document_id': 'c' * 32, 'original_sha256': hashlib.sha256(body.encode()).hexdigest(),
            'license': 'CC0-1.0', 'rights': {'jurisdiction': 'CL', 'edition_covered': True,
                                           'status': 'open_license'}}}

    def _index(self, embedder, **kwargs):
        return index_documents(self.folder, self.index, metadata=self.metadata,
            embedder=embedder, vector_cache=self.cache, **kwargs)

    def _count(self):
        with closing(sqlite3.connect(self.cache)) as db:
            return db.execute('SELECT COUNT(*) FROM vectors').fetchone()[0]

    def test_interruption_retains_two_batches_and_resume_saves_calls(self):
        index_documents(self.folder, self.index)
        original = self.index.read_bytes()
        interrupted = ControlledEmbeddings(fail_after=2)
        with self.assertRaises(OSError):
            self._index(interrupted)
        self.assertEqual(self._count(), 16)
        self.assertEqual(self.index.read_bytes(), original)
        resumed = ControlledEmbeddings()
        _, chunks = self._index(resumed)
        self.assertEqual(resumed.calls, math.ceil(chunks / 8) - 2)
        self.assertEqual(self._count(), chunks)
        self.assertEqual(list(self.root.glob('litmate-rag-*.sqlite3')), [])

    def test_new_model_digest_does_not_reuse_other_model_vectors(self):
        first = ControlledEmbeddings()
        _, chunks = self._index(first)
        changed = ControlledEmbeddings(digest='b' * 64)
        self._index(changed)
        self.assertEqual(changed.calls, math.ceil(chunks / 8))

    def test_personal_documents_cannot_activate_library_vector_cache(self):
        with self.assertRaises(ValueError):
            index_documents(self.folder, self.index, embedder=ControlledEmbeddings(), vector_cache=self.cache)
        self.assertFalse(self.index.exists())
        self.assertFalse(self.cache.exists())

    def test_foreign_sqlite_cache_and_main_index_are_not_overwritten(self):
        with closing(sqlite3.connect(self.cache)) as db, db:
            db.execute('CREATE TABLE personal(value TEXT)')
        original = self.cache.read_bytes()
        with self.assertRaises(ValueError):
            self._index(ControlledEmbeddings())
        self.assertEqual(self.cache.read_bytes(), original)
        with self.assertRaises(ValueError):
            index_documents(self.folder, self.index, metadata=self.metadata,
                embedder=ControlledEmbeddings(), vector_cache=self.index)
        self.assertFalse(self.index.exists())

    def test_cache_cannot_replace_configured_databases_or_originals(self):
        for forbidden in (settings.LITMATE_RAG_DB, settings.LITMATE_LITERARY_MEMORY_DB, self.path):
            with self.subTest(path=forbidden), self.assertRaises(ValueError):
                index_documents(self.folder, self.index, metadata=self.metadata,
                    embedder=ControlledEmbeddings(), vector_cache=forbidden)

    def test_corrupted_vector_is_regenerated_and_does_not_poison_index(self):
        with self.assertRaises(OSError):
            self._index(ControlledEmbeddings(fail_after=2))
        with closing(sqlite3.connect(self.cache)) as db, db:
            db.execute('UPDATE vectors SET vector=? WHERE rowid=(SELECT MIN(rowid) FROM vectors)', (b'bad',))
        repaired = ControlledEmbeddings()
        _, chunks = self._index(repaired)
        self.assertEqual(repaired.batches[0], 1)
        self.assertEqual(self._count(), chunks)

    def test_storage_limit_stops_cache_growth_without_disabling_index(self):
        provider = ControlledEmbeddings(dimension=2048)
        self._index(provider, vector_cache_max_bytes=65536)
        self.assertTrue(self.index.is_file())
        self.assertLessEqual(self.cache.stat().st_size, 65536)

    def test_deadline_keeps_confirmed_batch_without_publishing_partial_index(self):
        provider = ControlledEmbeddings()
        def deadline_checkpoint():
            # Simula expiración justo después de completar el primer lote; no
            # depende de la velocidad de disco ni compite con el Ollama real.
            if provider.calls:
                raise BudgetExpired('tiempo_total_agotado')
        with self.assertRaises(BudgetExpired):
            with request_budget(time.monotonic() + 60), patch('core.local_rag.check_budget', deadline_checkpoint):
                self._index(provider)
        self.assertEqual(self._count(), 8)
        self.assertFalse(self.index.exists())
        self._index(ControlledEmbeddings())
        self.assertTrue(self.index.is_file())

    def test_invalid_model_identity_and_dimension_are_rejected(self):
        with self.assertRaises(ValueError):
            self._index(ControlledEmbeddings(digest='not-a-model-digest'))
        with self.assertRaises(ValueError):
            self._index(ControlledEmbeddings(dimension=2049))
        self.assertFalse(self.index.exists())

    def test_same_hash_does_not_allow_incompatible_dimensions(self):
        with self.assertRaises(OSError):
            self._index(ControlledEmbeddings(fail_after=2))
        with self.assertRaises(ValueError):
            self._index(ControlledEmbeddings(dimension=2))
        self.assertEqual(self._count(), 16)
        self._index(ControlledEmbeddings())
        self.assertTrue(self.index.is_file())
