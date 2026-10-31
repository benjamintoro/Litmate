"""Regresiones de acceso público y errores; SQLite aislado, sin servicios externos."""
import base64
import secrets
from unittest.mock import Mock
from django.test import SimpleTestCase, Client, override_settings
from django.urls import path, include
from .demo_gateway import DemoGateway


def failure_view(request):
    raise RuntimeError('internal-preflight-marker-not-for-the-reader')


urlpatterns = [path('preflight-failure/', failure_view), path('', include('litmate_project.demo_urls'))]


class DemoPreflightSecurityTests(SimpleTestCase):
    def setUp(self):
        self.password = secrets.token_urlsafe(32)
        self.app = Mock(return_value=[])
        self.gateway = DemoGateway(self.app, password=self.password, hosts=['demo.test'])

    def call(self, path, *, password=None, host='demo.test', **headers):
        status = []
        environ = {'PATH_INFO': path, 'HTTP_HOST': host, **headers}
        if password is not None:
            environ['HTTP_AUTHORIZATION'] = 'Basic ' + base64.b64encode(('demo:' + password).encode()).decode()
        self.gateway(environ, lambda value, _: status.append(value[:3]))
        return status[0] if status else None

    def test_sensitive_routes_are_blocked_even_with_valid_credentials(self):
        for url in ('/.env', '/backups/', '/admin/login/', '/perfil/', '/test-error/500/',
                    '/suscripciones/iniciar-pago/', '/media/private.pdf', '/static/../.env'):
            self.assertEqual(self.call(url, password=self.password), '404')
        self.app.assert_not_called()

    def test_forwarded_host_cannot_override_the_real_host(self):
        self.assertEqual(self.call('/chat/', host='attacker.test', password=self.password,
            HTTP_X_FORWARDED_HOST='demo.test', HTTP_X_FORWARDED_PROTO='https'), '400')
        self.app.assert_not_called()

    def test_rate_limited_bad_credentials_do_not_lock_out_a_valid_reader(self):
        for _ in range(11):
            status = self.call('/chat/', password='wrong')
        self.assertEqual(status, '429')
        self.call('/chat/', password=self.password)
        self.app.assert_called_once()
        self.assertNotIn('HTTP_AUTHORIZATION', self.app.call_args.args[0])

    @override_settings(DEBUG=False, ROOT_URLCONF=__name__, ALLOWED_HOSTS=['testserver'])
    def test_internal_exceptions_are_not_shown_with_debug_false(self):
        with self.assertLogs('django.request', level='ERROR'):
            response = Client(raise_request_exception=False).get('/preflight-failure/', secure=True)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(b'internal-preflight-marker', response.content)
        self.assertNotIn(b'Traceback', response.content)
