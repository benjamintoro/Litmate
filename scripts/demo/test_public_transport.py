"""Pruebas sin red ni claves persistentes del comprobador HTTPS."""
import secrets
import unittest
from urllib.error import URLError
from urllib.request import Request
from .check_demo import SameOriginRedirect


class RedirectTests(unittest.TestCase):
    def setUp(self):
        self.origin = 'https://device.example.ts.net'
        self.handler = SameOriginRedirect(self.origin)
        self.request = Request(self.origin + '/', headers={'Authorization': secrets.token_urlsafe(32)})

    def test_same_origin_preserves_the_authenticated_request(self):
        result = self.handler.redirect_request(self.request, None, 302, 'Found', {}, self.origin + '/chat/')
        self.assertEqual(result.get_header('Authorization'), self.request.get_header('Authorization'))

    def test_other_host_is_blocked(self):
        with self.assertRaises(URLError):
            self.handler.redirect_request(self.request, None, 302, 'Found', {}, 'https://other.example/chat/')

    def test_https_cannot_be_downgraded(self):
        with self.assertRaises(URLError):
            self.handler.redirect_request(self.request, None, 302, 'Found', {}, self.origin.replace('https:', 'http:'))

    def test_embedded_credentials_are_blocked(self):
        with self.assertRaises(URLError):
            self.handler.redirect_request(self.request, None, 302, 'Found', {}, 'https://user@device.example.ts.net/')


if __name__ == '__main__':
    unittest.main()
