"""Perfil de demo: acceso, streaming y aislamiento sin conectarse a MySQL."""
import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.sessions.backends.file import SessionStore
from django.test import SimpleTestCase, override_settings, Client
from .demo_gateway import DemoGateway

PASSWORD = 'fixture-only-long-password-not-for-deployment'


class DemoGatewayTests(SimpleTestCase):
    def test_browser_auth_challenges_do_not_count_as_wrong_passwords(self):
        gateway = DemoGateway(lambda environ, start: [], password=PASSWORD, hosts=['localhost'])
        status = []
        def start(value, headers):
            status.append(value[:3])
        for _ in range(35):
            gateway({'HTTP_HOST': 'localhost', 'PATH_INFO': '/static/js/chatbot.js'}, start)
        self.assertEqual(set(status), {'401'})
        for _ in range(11):
            gateway({'HTTP_HOST': 'localhost', 'PATH_INFO': '/chat/',
                     'HTTP_AUTHORIZATION': 'Basic ZGVtbzp3cm9uZw=='}, start)
        self.assertEqual(status[-1], '429')

    def call(self, path='/chat/', *, auth=True, host='localhost', app=None):
        self.response = None
        def start(status, headers):
            self.response = status, dict(headers)
        def application(environ, start_response):
            self.assertNotIn('HTTP_AUTHORIZATION', environ)
            start_response('200 OK', [('Content-Type', 'text/event-stream')])
            return iter([b'data: first\n\n', b'data: [DONE]\n\n'])
        gateway = DemoGateway(app or application, password=PASSWORD, hosts=['localhost'])
        environ = {'HTTP_HOST': host, 'PATH_INFO': path}
        if auth:
            environ['HTTP_AUTHORIZATION'] = 'Basic ' + base64.b64encode(('demo:' + PASSWORD).encode()).decode()
        result = gateway(environ, start)
        return result

    def test_chat_and_static_require_authentication(self):
        for path in ('/chat/', '/static/js/chatbot.js', '/api/miku-tts/'):
            self.call(path, auth=False)
            self.assertTrue(self.response[0].startswith('401'))
            self.assertIn('WWW-Authenticate', self.response[1])

    def test_host_validation_is_not_replaced_by_forwarded_headers(self):
        self.call(host='attacker.invalid')
        self.assertTrue(self.response[0].startswith('400'))

    def test_admin_private_accounts_payments_and_other_media_are_never_exposed(self):
        for path in ('/admin/', '/perfil/', '/perfil/editar/', '/suscripciones/iniciar-pago/',
                     '/suscripciones/webpay/commit/', '/auth/social/google/callback/',
                     '/reset/uid/token/', '/api/listas/obtener/',
                     '/media/private.pdf', '/static/../.env', '/static/.secret'):
            with self.subTest(path=path):
                self.call(path)
                self.assertTrue(self.response[0].startswith('404'))

    def test_wsgi_stream_is_passed_through_without_consuming_it(self):
        consumed = []
        def application(environ, start):
            start('200 OK', [('Content-Type', 'text/event-stream')])
            def events():
                consumed.append('first')
                yield b'data: first\n\n'
                consumed.append('last')
                yield b'data: [DONE]\n\n'
            return events()
        result = self.call(app=application)
        self.assertEqual(consumed, [])
        self.assertEqual(next(result), b'data: first\n\n')
        self.assertEqual(consumed, ['first'])

    def test_existing_sessions_do_not_have_to_fit_inside_a_browser_cookie(self):
        with TemporaryDirectory() as temporary, override_settings(
                SESSION_ENGINE='django.contrib.sessions.backends.file', SESSION_FILE_PATH=temporary,
                SESSION_COOKIE_NAME='litmate_demo_sessionid'), patch.object(
                SessionStore, '_storage_path', temporary, create=True):
            client = Client()
            session = client.session
            session['large_literary_context'] = 'public evidence ' * 5000
            session.save()
            self.assertLess(len(client.cookies.output()), 300)
            self.assertEqual(client.session['large_literary_context'], 'public evidence ' * 5000)

    def test_tts_route_does_not_serve_other_files(self):
        with TemporaryDirectory() as temporary, override_settings(ROOT_URLCONF='litmate_project.demo_urls',
                                                                 MEDIA_ROOT=Path(temporary)):
            client = Client()
            self.assertEqual(client.get('/media/tts_cache/miku_' + 'a' * 64 + '.mp3').status_code, 404)
            self.assertEqual(client.get('/media/tts_cache/../secret.txt').status_code, 404)
