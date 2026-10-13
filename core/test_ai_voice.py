"""Pruebas de voz sin red: proveedor simulado y caché temporal."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from . import services_voice as voice

AUDIO = b'ID3' + b'a' * 125


class FakeCommunication:
    calls = []

    def __init__(self, **kwargs):
        self.calls.append(kwargs)

    async def stream(self):
        yield {'type': 'WordBoundary', 'text': 'texto'}
        yield {'type': 'audio', 'data': AUDIO}


class VoiceCacheTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = override_settings(MEDIA_ROOT=self.temp.name, MEDIA_URL='/media/', LITMATE_TTS_ENABLED=True)
        self.config.enable()
        self.addCleanup(self.config.disable)
        FakeCommunication.calls = []
        self.provider = patch.dict(sys.modules, {'edge_tts': SimpleNamespace(Communicate=FakeCommunication)})
        self.provider.start()
        self.addCleanup(self.provider.stop)

    def audio_files(self):
        return list((Path(self.temp.name) / 'tts_cache').glob('miku_*.mp3'))

    def test_import_has_no_filesystem_side_effect(self):
        with patch.object(Path, 'mkdir') as mkdir:
            importlib.reload(voice)
        mkdir.assert_not_called()
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    @override_settings(LITMATE_TTS_ENABLED=False)
    def test_disabled_voice_creates_no_files_and_contacts_no_provider(self):
        with self.assertRaises(voice.VoiceUnavailable):
            voice.obtener_audio_miku('Una novela literaria.')
        self.assertEqual(FakeCommunication.calls, [])
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_rejects_empty_non_text_and_oversized_requests(self):
        for text in ('', ' ', None, 10, 'a' * 3501, '[LIBRO: Dune] https://example.com'):
            with self.subTest(text_type=type(text).__name__), self.assertRaises(voice.VoiceInputError):
                voice.obtener_audio_miku(text)
        self.assertEqual(FakeCommunication.calls, [])

    def test_completed_audio_is_cached_without_second_provider_call(self):
        first = voice.obtener_audio_miku('**Dune** es una novela. https://example.com')
        second = voice.obtener_audio_miku('Dune es una novela.')
        self.assertEqual(first, second)
        self.assertTrue(first.startswith('/media/tts_cache/miku_'))
        self.assertEqual(len(FakeCommunication.calls), 1)
        self.assertEqual(self.audio_files()[0].read_bytes(), AUDIO)
        self.assertEqual(list((Path(self.temp.name) / 'tts_cache').glob('*.part')), [])

    def test_voice_options_participate_in_cache_identity(self):
        first = voice.obtener_audio_miku('Dune es una novela.')
        with override_settings(LITMATE_TTS_RATE='+0%'):
            second = voice.obtener_audio_miku('Dune es una novela.')
        self.assertNotEqual(first, second)
        self.assertEqual(len(FakeCommunication.calls), 2)

    def test_failed_generation_never_publishes_partial_audio(self):
        async def fail(text, output):
            Path(output).write_bytes(b'ID3partial')
            raise OSError('simulated offline failure')
        with patch.object(voice, 'generar_audio_edge', side_effect=fail), self.assertRaises(voice.VoiceServiceError):
            voice.obtener_audio_miku('Texto para audio.')
        self.assertEqual(self.audio_files(), [])
        self.assertEqual(list((Path(self.temp.name) / 'tts_cache').glob('*.part')), [])

    def test_invalid_provider_audio_is_rejected(self):
        async def invalid(text, output):
            Path(output).write_bytes(b'<html>' + b'a' * 100)
        with patch.object(voice, 'generar_audio_edge', side_effect=invalid), self.assertRaises(voice.VoiceServiceError):
            voice.obtener_audio_miku('Texto para audio.')
        self.assertEqual(self.audio_files(), [])

    @override_settings(LITMATE_TTS_MAX_AUDIO_BYTES=64)
    def test_stream_size_limit_stops_before_writing_oversized_chunk(self):
        with self.assertRaises(voice.VoiceServiceError):
            voice.obtener_audio_miku('Texto para audio.')
        self.assertEqual(self.audio_files(), [])
        self.assertEqual(list((Path(self.temp.name) / 'tts_cache').glob('*.part')), [])

    @override_settings(LITMATE_TTS_TIMEOUT_SECONDS=1)
    def test_timeout_cancels_and_removes_partial_output(self):
        async def slow(text, output):
            Path(output).write_bytes(b'ID3partial')
            await asyncio.sleep(10)
        started = time.monotonic()
        with patch.object(voice, 'generar_audio_edge', side_effect=slow), self.assertRaises(voice.VoiceServiceError):
            voice.obtener_audio_miku('Texto para audio.')
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(self.audio_files(), [])
        self.assertEqual(list((Path(self.temp.name) / 'tts_cache').glob('*.part')), [])

    @override_settings(LITMATE_TTS_CACHE_MAX_FILES=2, LITMATE_TTS_CACHE_MAX_BYTES=256)
    def test_cache_file_and_byte_budgets_are_enforced(self):
        for text in ('primero', 'segundo', 'tercero'):
            voice.obtener_audio_miku(text)
        files = self.audio_files()
        self.assertEqual(len(files), 2)
        self.assertLessEqual(sum(path.stat().st_size for path in files), 256)

    @override_settings(LITMATE_TTS_CACHE_TTL_SECONDS=2)
    def test_expired_audio_is_regenerated(self):
        first = voice.obtener_audio_miku('Texto para audio.')
        path = self.audio_files()[0]
        past = time.time() - 10
        os.utime(path, (past, past))
        self.assertEqual(first, voice.obtener_audio_miku('Texto para audio.'))
        self.assertEqual(len(FakeCommunication.calls), 2)

    def test_concurrent_generation_is_rejected_and_lock_is_released(self):
        started, finish = threading.Event(), threading.Event()
        async def slow(text, output):
            started.set()
            while not finish.is_set():
                await asyncio.sleep(0.01)
            Path(output).write_bytes(AUDIO)
        with patch.object(voice, 'generar_audio_edge', side_effect=slow), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(voice.obtener_audio_miku, 'Primera solicitud.')
            try:
                self.assertTrue(started.wait(timeout=3))
                with self.assertRaises(voice.VoiceBusy):
                    voice.obtener_audio_miku('Otra solicitud.')
            finally:
                finish.set()
            self.assertTrue(future.result(timeout=3).startswith('/media/'))
        self.assertTrue(voice.obtener_audio_miku('Después de liberar el bloqueo.').startswith('/media/'))

    @override_settings(MEDIA_URL='https://cdn.example.com/media/')
    def test_audio_url_requires_same_origin_path(self):
        with self.assertRaises(voice.VoiceUnavailable):
            voice.obtener_audio_miku('Texto para audio.')
        self.assertEqual(FakeCommunication.calls, [])
