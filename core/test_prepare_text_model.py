"""Preparación de alias con blobs pequeños controlados; nunca llama a Ollama."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from unittest.mock import Mock

from django.test import SimpleTestCase

from preparar_modelo_texto import (PREFIX, SOURCE, TARGET, existing_profile_matches,
                                   inspect_profile, prepare)


class PrepareTextModelTests(SimpleTestCase):
    def fixture(self, root):
        blobs = root / 'blobs'
        blobs.mkdir()
        layers = []
        contents = {'model': b'GGUFcontrolled-model-data', 'projector': b'GGUFcontrolled-projector',
                    'template': b'{{ .Prompt }}', 'params': b'{"top_p":0.95,"temperature":1,"top_k":20}',
                    'license': b'Controlled test license.\n'}
        for kind, body in contents.items():
            digest = 'sha256:' + hashlib.sha256(body).hexdigest()
            (blobs / digest.replace(':', '-')).write_bytes(body)
            layers.append({'mediaType': PREFIX + kind, 'digest': digest, 'size': len(body)})
        manifest = root / 'manifests' / 'registry.ollama.ai' / 'library' / 'qwen3.5' / '9b-q4_K_M'
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({'layers': layers}), encoding='utf-8')
        info = {'details': {'format': 'gguf', 'family': 'qwen35'},
                'model_info': {'general.architecture': 'qwen35'},
                'capabilities': ['completion', 'vision', 'thinking', 'tools'],
                'template': '{{ .Prompt }}', 'license': 'Controlled test license.\n',
                'parameters': 'top_k 20\ntemperature 1\ntop_p 0.95',
                'modelfile': 'FROM original\nRENDERER qwen3.5\nPARSER qwen3.5\n',
                'projector_info': {'general.architecture': 'clip'}}
        model_digest = next(layer['digest'] for layer in layers if layer['mediaType'] == PREFIX + 'model')
        target = {**info, 'capabilities': ['completion', 'thinking', 'tools'],
                  'modelfile': 'FROM C:/models/blobs/' + model_digest.replace(':', '-') +
                               '\nRENDERER qwen3.5\nPARSER qwen3.5\n'}
        target.pop('projector_info')
        return info, target, manifest

    def fake_api(self, source, existing=None):
        def fetch(url, **kwargs):
            self.assertTrue(kwargs['local'])
            self.assertTrue(url.startswith('http://127.0.0.1:11434/api/'))
            payload = kwargs['payload']
            if url.endswith('/api/show'):
                if payload['model'] == SOURCE:
                    return source
                if existing is None:
                    raise HTTPError(url, 404, 'not found', {}, None)
                return existing
            raise AssertionError('No se permite crear ni inferir en esta prueba.')
        return Mock(side_effect=fetch)

    def test_default_inspection_keeps_original_and_does_not_create_or_infer(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, _, manifest = self.fixture(root)
            before = manifest.read_bytes()
            fetch = self.fake_api(source)
            result = prepare(models_dir=root, fetch=fetch)
            self.assertEqual(result['status'], 'ready_not_created')
            self.assertFalse(result['inference_executed'])
            self.assertEqual(manifest.read_bytes(), before)
            self.assertTrue(all(call.args[0].endswith('/api/show') for call in fetch.call_args_list))

    def test_profile_preserves_exact_metadata_and_excludes_projector_and_from(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, _, _ = self.fixture(root)
            profile, _ = inspect_profile(root, SOURCE, source, verify_weights=True)
            self.assertEqual(set(profile['files']), {'model.gguf'})
            self.assertEqual(profile['renderer'], 'qwen3.5')
            self.assertEqual(profile['parser'], 'qwen3.5')
            self.assertEqual(profile['template'], source['template'])
            self.assertEqual(profile['license'], source['license'])
            self.assertEqual(profile['parameters'], {'top_p': .95, 'temperature': 1, 'top_k': 20})
            self.assertNotIn('from', profile)
            self.assertNotIn('quantize', profile)

    def test_explicit_creation_posts_only_the_model_and_preserved_profile(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, target, manifest = self.fixture(root)
            before, created = manifest.read_bytes(), []
            def fetch(url, **kwargs):
                payload = kwargs['payload']
                if url.endswith('/api/show'):
                    if payload['model'] == SOURCE:
                        return source
                    if created:
                        return target
                    raise HTTPError(url, 404, 'not found', {}, None)
                self.assertTrue(url.endswith('/api/create'))
                self.assertEqual(payload['model'], TARGET)
                self.assertFalse(payload['stream'])
                self.assertEqual(set(payload['files']), {'model.gguf'})
                self.assertNotIn('from', payload)
                self.assertNotIn('quantize', payload)
                self.assertEqual(payload['license'], source['license'])
                self.assertEqual(payload['renderer'], 'qwen3.5')
                self.assertEqual(payload['parser'], 'qwen3.5')
                created.append(payload)
                return {'status': 'success'}
            result = prepare(models_dir=root, create=True, fetch=fetch)
            self.assertEqual(result['status'], 'created_and_profile_verified')
            self.assertEqual(len(created), 1)
            self.assertEqual(manifest.read_bytes(), before)

    def test_existing_api_only_alias_reuses_same_profile_regardless_of_parameter_order(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, target, _ = self.fixture(root)
            fetch = self.fake_api(source, target)
            result = prepare(models_dir=root, create=True, fetch=fetch)
            self.assertEqual(result['status'], 'existing_profile_verified')
            self.assertFalse((root / 'manifests/registry.ollama.ai/library/litmate-qwen35-text').exists())
            self.assertTrue(all(call.args[0].endswith('/api/show') for call in fetch.call_args_list))

    def test_existing_different_weights_or_behavior_cannot_be_overwritten(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, target, _ = self.fixture(root)
            variations = [{'template': 'other'}, {'parameters': 'top_k 10'},
                          {'capabilities': ['completion', 'thinking', 'vision']},
                          {'modelfile': target['modelfile'].replace('qwen3.5', 'other')},
                          {'license': 'different'}, {'system': 'different behavior'}]
            for change in variations:
                with self.subTest(change=change), self.assertRaises(ValueError):
                    prepare(models_dir=root, create=True, fetch=self.fake_api(source, {**target, **change}))

    def test_public_origins_credentials_paths_and_redirect_destinations_are_rejected(self):
        for origin in ('http://192.168.1.10:11434', 'https://example.org:443',
                       'http://user:secret@localhost:11434', 'http://localhost:11434/path'):
            fetch = Mock()
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                prepare(base_url=origin, fetch=fetch)
            fetch.assert_not_called()

    def test_corrupt_digest_and_declared_size_fail_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, _, manifest = self.fixture(root)
            value = json.loads(manifest.read_text(encoding='utf-8'))
            layer = next(item for item in value['layers'] if item['mediaType'] == PREFIX + 'model')
            path = root / 'blobs' / layer['digest'].replace(':', '-')
            original = path.read_bytes()
            path.write_bytes(original[:-1] + b'X')
            with self.assertRaisesRegex(ValueError, 'hash del GGUF'):
                prepare(models_dir=root, fetch=self.fake_api(source))
            path.write_bytes(original + b'extra')
            with self.assertRaisesRegex(ValueError, 'tamaño'):
                prepare(models_dir=root, fetch=self.fake_api(source))

    def test_non_gguf_remote_or_wrong_architecture_source_is_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, _, _ = self.fixture(root)
            for change in ({'remote_host': 'https://remote'}, {'details': {'format': 'remote'}},
                           {'model_info': {'general.architecture': 'other'}}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    prepare(models_dir=root, fetch=self.fake_api({**source, **change}))

