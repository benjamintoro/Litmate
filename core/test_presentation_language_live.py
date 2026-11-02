"""Prueba optativa: HTTP/SSE, Ollama y Open Library reales.

Ejecutar con LITMATE_RUN_LANGUAGE_LIVE=1 mediante verificar_proyecto.py.
No usa MySQL: sesiones firmadas e índices temporales del ejecutor aislado.
Una ficha obtenida de la API oficial se inyecta en el límite de presentación
para forzar el caso de idioma. No evalúa el ranking ni la búsqueda de SearXNG.
"""
import copy
import json
import os
import threading
import time
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from socketserver import ThreadingMixIn
from types import SimpleNamespace
from urllib.request import Request, build_opener, HTTPCookieProcessor, ProxyHandler, urlopen
from unittest.mock import patch
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server
from django.conf import settings
from django.core.handlers.wsgi import WSGIHandler
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings


@unittest.skipUnless(os.environ.get('LITMATE_RUN_LANGUAGE_LIVE') == '1', 'Ollama real optativo')
@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies',
    LITMATE_LOCAL_MODEL='litmate-qwen35-text:9b-q4_K_M', LITMATE_AI_QUICK_ANSWERS=False,
    LITMATE_USE_EXISTING_QUOTAS=False, LITMATE_ANONYMOUS_AI_DAILY_LIMIT=100,
    LITMATE_AI_REQUESTS_PER_MINUTE=100)
class LanguageLiveHTTPTests(SimpleTestCase):
    def test_real_local_model_and_http_sse_presentation(self):
        from .test_presentation_language import PresentationLanguageTests
        class Server(ThreadingMixIn, WSGIServer):
            daemon_threads = True
        class Quiet(WSGIRequestHandler):
            def log_message(self, *args):
                pass
        cache.clear()
        fixture = PresentationLanguageTests()
        fixture.setUp()
        url = 'https://openlibrary.org/works/OL1388255W.json'
        with urlopen(Request(url, headers={'User-Agent': 'LitMate/1.0 (local presentation verification)'}), timeout=8) as response:
            work = json.load(response)
        description = work['description']['value']
        fixture.book.update(title=work['title'], author='Ralph Henry Carless Davis',
            description=description, synopsis=description,
            url='https://openlibrary.org/works/OL1388255W',
            image_url='https://covers.openlibrary.org/b/id/' + str(work['covers'][0]) + '-M.jpg')
        report = {'retrieval': 'real Open Library official work API, injected at presentation boundary',
                  'source_url': url, 'ollama': 'real local',
                  'database': 'isolated test settings; signed cookies, no MySQL', 'cases': []}
        def compute(message, *args, **kwargs):
            result = fixture.result()
            if 'sinopsis' in message:
                result.intent = 'summary'
                result.text = description + '\n\nFuente: ' + fixture.book['url']
            return copy.deepcopy(result), SimpleNamespace(usage={}, provider='fixture', calls=0)
        with patch('core.literary_ai_views._compute_answer_impl', side_effect=compute):
            with make_server('127.0.0.1', 0, WSGIHandler(), server_class=Server, handler_class=Quiet) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                origin = 'http://127.0.0.1:' + str(server.server_port)
                cookies = CookieJar()
                client = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies))
                try:
                    with client.open(origin + '/chat/', timeout=10) as response:
                        response.read()
                    csrf = next(cookie.value for cookie in cookies if cookie.name == 'csrftoken')
                    for message, expected in [
                        ('Dime libros sobre historia medieval', 'es'),
                        ('Dime otra vez libros sobre historia medieval', 'es'),
                        ('Dime la sinopsis de A History of Medieval Europe', 'es'),
                        ('Responde en inglés: dime libros sobre historia medieval', 'en')]:
                        started = time.monotonic()
                        headers = {'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'Origin': origin}
                        req = Request(origin + '/chatbot_query/', data=json.dumps(
                            {'message': message, 'progress': True}).encode(), headers=headers, method='POST')
                        with client.open(req, timeout=50) as response:
                            raw = response.read().decode()
                        events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith('data: {')]
                        ready = next(event['ready'] for event in events if 'ready' in event)
                        req = Request(origin + '/chatbot_finalize/', data=json.dumps({'ready': ready}).encode(),
                                      headers=headers, method='POST')
                        with client.open(req, timeout=20) as response:
                            final = json.load(response)
                        report['cases'].append({'question': message, 'expected_language': expected,
                            'seconds': round(time.monotonic() - started, 3), 'http_status': response.status,
                            'sse_done': 'data: [DONE]' in raw, 'result': final})
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
        target = Path(settings.BASE_DIR) / 'reportes/idioma_20261028'
        target.mkdir(parents=True, exist_ok=True)
        (target / 'http_sse_ollama_real.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        for case in report['cases']:
            self.assertEqual(case['result']['status'], 'answered')
            self.assertTrue(case['sse_done'])
            answer = case['result']['response']
            self.assertNotIn('Fuentes de las fichas', answer)
            if case['expected_language'] == 'es':
                self.assertNotIn('An introduction', answer)
                self.assertNotIn('The novel follows', answer)
                self.assertNotIn('No pude preparar', answer)
                self.assertNotIn('Alta Edad Media', answer)  # High Middle Ages != Early Middle Ages.
            else:
                self.assertIn('An introduction', answer)
            for card in case['result']['books']:
                self.assertEqual(card['title'], fixture.book['title'])
                self.assertTrue(card['image_url'])
                self.assertEqual(len(card['links']), 4)
                if case['expected_language'] == 'es':
                    self.assertNotIn('An introduction', card['synopsis'])
                    self.assertNotIn('No pude preparar', card['synopsis'])
