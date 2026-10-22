"""Cuotas: la IP del cliente no se toma de una cabecera no confiable."""
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import timezone

from .quotas import cuota_disponible, generar_clave_cache_cuota


class QuotaKeyTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def tearDown(self):
        cache.clear()

    def request(self, **meta):
        request = self.factory.post('/chatbot_query/', **meta)
        request.user = AnonymousUser()
        return request

    def test_forwarded_header_is_ignored_by_default(self):
        request = self.request(REMOTE_ADDR='198.51.100.7',
                               HTTP_X_FORWARDED_FOR='203.0.113.9')
        key = generar_clave_cache_cuota(request)
        self.assertIn('198.51.100.7', key)
        self.assertNotIn('203.0.113.9', key)

    @override_settings(LITMATE_TRUST_X_FORWARDED_FOR=True,
                       LITMATE_TRUSTED_PROXY_IPS=('10.0.0.1',))
    def test_forwarded_header_is_used_only_from_a_trusted_proxy(self):
        trusted = self.request(REMOTE_ADDR='10.0.0.1',
                               HTTP_X_FORWARDED_FOR='203.0.113.9')
        untrusted = self.request(REMOTE_ADDR='198.51.100.7',
                                 HTTP_X_FORWARDED_FOR='203.0.113.9')
        self.assertIn('203.0.113.9', generar_clave_cache_cuota(trusted))
        self.assertIn('198.51.100.7', generar_clave_cache_cuota(untrusted))

    @override_settings(LITMATE_TRUST_X_FORWARDED_FOR=True,
                       LITMATE_TRUSTED_PROXY_IPS=('10.0.0.1',))
    def test_malformed_forwarded_value_falls_back_to_remote_addr(self):
        request = self.request(REMOTE_ADDR='10.0.0.1',
                               HTTP_X_FORWARDED_FOR='not-an-ip')
        self.assertIn('10.0.0.1', generar_clave_cache_cuota(request))

    def test_quota_check_does_not_consume_the_counter(self):
        key = f"cuota_ia_ip:198.51.100.7:{timezone.now().strftime('%Y-%m-%d')}"
        cache.set(key, 5, timeout=60)
        request = self.request(REMOTE_ADDR='198.51.100.7')
        allowed, info = cuota_disponible(request)
        self.assertFalse(allowed)
        self.assertEqual(info['restantes'], 0)
        self.assertEqual(cache.get(key), 5)
