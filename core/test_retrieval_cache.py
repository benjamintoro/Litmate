"""Identidades de embeddings y matrices RAG: todo offline y en carpetas temporales."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .literary_ai import ProviderUnavailable
from .local_embeddings import (IDENTITY_CACHE_SECONDS, OllamaEmbeddings,
                               _manifest_digest, clear_identity_cache)
from .local_rag import _vector_matrix, index_documents, retrieve_fragments


SHOW = {'details': {'format': 'gguf'}, 'model_info': {'general.architecture': 'gemma3'},
        'capabilities': ['embedding']}


def tags(digest='a' * 64, name='embeddinggemma:latest'):
    return {'models': [{'name': name, 'digest': digest}]}


class EmbeddingIdentityCacheTests(unittest.TestCase):
    def setUp(self):
        clear_identity_cache()

    def tearDown(self):
        clear_identity_cache()

    def test_verified_manifest_reuses_identity_between_instances_without_http(self):
        with patch('core.local_embeddings._manifest_digest', return_value='a' * 64), \
                patch('core.local_embeddings.read_json_url', side_effect=[SHOW, tags()]) as fetch:
            first = OllamaEmbeddings().identity()
            second = OllamaEmbeddings(model='embeddinggemma:latest').identity()
        self.assertEqual(first, second)
        self.assertEqual(fetch.call_count, 2)
        self.assertIsInstance(second, tuple)  # No mutable model-info is shared.

    def test_no_identifiable_manifest_keeps_http_inspection_for_each_new_instance(self):
        with patch('core.local_embeddings._manifest_digest', return_value=None), \
                patch('core.local_embeddings.read_json_url', side_effect=[SHOW, tags(), SHOW, tags()]) as fetch:
            client = OllamaEmbeddings()
            client.identity()
            client.identity()
            OllamaEmbeddings().identity()
        self.assertEqual(fetch.call_count, 4)

    def test_manifest_changed_digest_invalidates_same_instance_and_shared_cache_immediately(self):
        fingerprint = ['a' * 64]
        with patch('core.local_embeddings._manifest_digest', side_effect=lambda *args: fingerprint[0]), \
                patch('core.local_embeddings.read_json_url',
                      side_effect=[SHOW, tags(), SHOW, tags('b' * 64)]) as fetch:
            client = OllamaEmbeddings()
            self.assertEqual(client.identity()[1], 'a' * 64)
            fingerprint[0] = 'b' * 64
            self.assertEqual(client.identity()[1], 'b' * 64)
            self.assertEqual(OllamaEmbeddings().identity()[1], 'b' * 64)
        self.assertEqual(fetch.call_count, 4)

    def test_ttl_expiration_revalidates_even_when_manifest_unchanged(self):
        clock = [100.]
        with patch('core.local_embeddings.time.monotonic', side_effect=lambda: clock[0]), \
                patch('core.local_embeddings._manifest_digest', return_value='a' * 64), \
                patch('core.local_embeddings.read_json_url', side_effect=[SHOW, tags(), SHOW, tags()]) as fetch:
            client = OllamaEmbeddings()
            client.identity()
            clock[0] += IDENTITY_CACHE_SECONDS + 1
            client.identity()
        self.assertEqual(fetch.call_count, 4)

    def test_same_manifest_on_different_endpoint_does_not_share_authorization(self):
        with patch('core.local_embeddings._manifest_digest', return_value='a' * 64), \
                patch('core.local_embeddings.read_json_url', side_effect=[SHOW, tags(), SHOW, tags()]) as fetch:
            OllamaEmbeddings().identity()
            OllamaEmbeddings(base_url='http://127.0.0.1:11435').identity()
        self.assertEqual(fetch.call_count, 4)

    def test_manifest_and_api_digest_must_agree_before_cross_instance_reuse(self):
        with patch('core.local_embeddings._manifest_digest', return_value='b' * 64), \
                patch('core.local_embeddings.read_json_url', side_effect=[SHOW, tags(), SHOW, tags()]) as fetch:
            OllamaEmbeddings().identity()
            OllamaEmbeddings().identity()
        self.assertEqual(fetch.call_count, 4)

    def test_replaced_cloud_alias_is_rejected_before_embedding(self):
        fingerprint = ['a' * 64]
        remote = {'remote_host': 'https://ollama.com', 'details': {'format': 'gguf'}}
        with patch('core.local_embeddings._manifest_digest', side_effect=lambda *args: fingerprint[0]), \
                patch('core.local_embeddings.read_json_url', side_effect=[SHOW, tags(), remote]) as fetch:
            client = OllamaEmbeddings()
            client.identity()
            fingerprint[0] = 'b' * 64
            with self.assertRaises(ProviderUnavailable):
                client.embed(['Consulta de prueba'])
        self.assertEqual(fetch.call_count, 3)
        self.assertTrue(all('/api/embed' not in call.args[0] for call in fetch.call_args_list))

    def test_failed_inspection_is_not_cached_as_local_identity(self):
        with patch('core.local_embeddings._manifest_digest', return_value='a' * 64), \
                patch('core.local_embeddings.read_json_url', side_effect=[{}, SHOW, tags()]) as fetch:
            with self.assertRaises(ProviderUnavailable):
                OllamaEmbeddings().identity()
            self.assertEqual(OllamaEmbeddings().identity()[1], 'a' * 64)
        self.assertEqual(fetch.call_count, 3)

    def test_real_manifest_bytes_change_fingerprint_and_unknown_layouts_fall_back(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict('os.environ', {'OLLAMA_MODELS': temporary}):
            manifest = Path(temporary) / 'manifests/registry.ollama.ai/library/embeddinggemma/latest'
            manifest.parent.mkdir(parents=True)
            raw = json.dumps({'layers': [{'digest': 'sha256:example'}]}).encode()
            manifest.write_bytes(raw)
            before = _manifest_digest('http://127.0.0.1:11434', 'embeddinggemma:latest')
            self.assertEqual(before, hashlib.sha256(raw).hexdigest())
            manifest.write_bytes(raw + b' ')
            self.assertNotEqual(before, _manifest_digest('http://127.0.0.1:11434', 'embeddinggemma'))
            self.assertIsNone(_manifest_digest('http://127.0.0.1:11435', 'embeddinggemma'))
            self.assertIsNone(_manifest_digest('http://127.0.0.1:11434', '../embeddinggemma'))
            manifest.write_bytes(b'x' * 131073)
            self.assertIsNone(_manifest_digest('http://127.0.0.1:11434', 'embeddinggemma'))


class DeterministicEmbeddings:
    """Vectores de control: prueban cachés, no calidad semántica de una red."""
    def identity(self):
        return 'controlled-embedding', 'a' * 64

    def embed(self, texts, *, query=False):
        return [[1., 0.] for text in texts]


class AlternatingCorpusCacheTests(unittest.TestCase):
    def test_two_corpora_reuse_both_matrices_without_mixing_their_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            indexes = []
            for number in (1, 2):
                folder = root / str(number)
                folder.mkdir()
                (folder / f'Obra {number}__Autora.txt').write_text(
                    f'El protagonista del documento {number} explora una isla imaginaria.', encoding='utf-8')
                database = root / f'index-{number}.sqlite3'
                index_documents(folder, database, embedder=DeterministicEmbeddings())
                indexes.append(database)
            _vector_matrix.cache_clear()
            for database in indexes * 2:
                fragments = retrieve_fragments('isla', database, embedder=DeterministicEmbeddings())
                self.assertEqual(len(fragments), 1)
                self.assertIn(database.stem[-1], fragments[0]['title'])
            info = _vector_matrix.cache_info()
            self.assertEqual(info.misses, 2)
            self.assertEqual(info.hits, 2)
            self.assertEqual(info.currsize, 2)

    def test_reindex_invalidates_cached_matrix_even_when_path_is_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / 'text'
            folder.mkdir()
            document = folder / 'Obra__Autora.txt'
            database = root / 'index.sqlite3'
            document.write_text('Una viajera guarda un mapa durante el recorrido por la isla.', encoding='utf-8')
            index_documents(folder, database, embedder=DeterministicEmbeddings())
            retrieve_fragments('isla', database, embedder=DeterministicEmbeddings())
            self.assertEqual(_vector_matrix.cache_info().currsize, 1)
            document.write_text('Una viajera descubre un planeta lejano durante su recorrido espacial.', encoding='utf-8')
            index_documents(folder, database, embedder=DeterministicEmbeddings())
            self.assertEqual(_vector_matrix.cache_info().currsize, 0)
            result = retrieve_fragments('planeta', database, embedder=DeterministicEmbeddings())
            self.assertIn('planeta', result[0]['description'])
            self.assertNotIn('isla', result[0]['description'])
