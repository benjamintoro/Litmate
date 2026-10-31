"""Acceso a la web real sin cuentas privadas ni escrituras en la demo."""
import base64
import inspect
from unittest.mock import Mock, patch

from django.test import Client, SimpleTestCase, override_settings
from django.urls import resolve
from django.http import HttpResponse
from django.contrib.sessions.backends.file import SessionStore

from .demo_gateway import DemoGateway


@override_settings(ROOT_URLCONF='litmate_project.demo_urls', LITMATE_DEMO_READ_ONLY=True,
                   SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class DemoFrontendTests(SimpleTestCase):
    def test_all_public_pages_require_the_existing_basic_auth(self):
        app = Mock(return_value=[])
        password = 'a-fixture-only-long-demo-password'
        gateway = DemoGateway(app, password=password, hosts=['localhost'])
        for path in ('/', '/about/', '/post/', '/contact/', '/libros/', '/login/',
                     '/registro/', '/password-reset/', '/suscripciones/planes/',
                     '/terminos-y-condiciones/', '/politica-de-privacidad/',
                     '/politica-de-cookies/', '/api/quick-search/', '/api/libro/precios/'):
            with self.subTest(path=path):
                statuses = []
                environ = {'PATH_INFO': path, 'HTTP_HOST': 'localhost', 'REQUEST_METHOD': 'GET'}
                gateway(environ.copy(), lambda status, _: statuses.append(status[:3]))
                self.assertEqual(statuses, ['401'])
                environ['HTTP_AUTHORIZATION'] = 'Basic ' + base64.b64encode(
                    ('demo:' + password).encode()).decode()
                gateway(environ, lambda *_: None)
        self.assertEqual(app.call_count, 14)

    def test_root_uses_the_real_homepage_instead_of_a_chat_redirect(self):
        from . import views
        self.assertIs(inspect.unwrap(resolve('/').func), views.index)

    def test_homepage_does_not_scrape_or_store_missing_prices(self):
        from .views import get_featured_books
        with patch('core.models.PrecioLibroTienda.objects.filter', return_value=[]), patch(
                'core.scraper.obtener_datos_comparador_libro', return_value={}) as scrape, patch(
                'core.views.generar_enlaces_tiendas', return_value=[{'url': 'https://example.org/book'}]):
            books = get_featured_books()
        self.assertEqual(len(books), 6)
        scrape.assert_not_called()
        self.assertTrue(all(book['portada'] and book['tiendas'] for book in books))

    def test_readonly_price_lookup_never_refreshes_even_when_forced(self):
        from .scraper import obtener_datos_comparador_libro
        queryset = Mock()
        queryset.filter.return_value = []
        with patch('core.models.PrecioLibroTienda.objects.filter', return_value=queryset), patch(
                'core.scraper.generar_enlaces_completos', return_value=[]) as scrape:
            result = obtener_datos_comparador_libro(titulo='Una obra', force_refresh=True)
        self.assertEqual(result['status'], 'success')
        scrape.assert_not_called()

    def test_forms_are_honest_previews_without_authentication_or_writes(self):
        client = Client()
        for path in ('/login/', '/registro/', '/password-reset/', '/contact/'):
            for method in ('get', 'post'):
                with self.subTest(path=path, method=method), patch(
                        'core.views.login') as login, patch('core.views.send_mail') as mail, patch(
                        'core.models.MensajeContacto.objects.create') as contact:
                    response = getattr(client, method)(path, {'password': 'must-not-be-echoed'})
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, 'Vista previa' if path != '/login/' else 'vista previa')
                    self.assertNotContains(response, 'must-not-be-echoed')
                    self.assertFalse(client.session.get('_auth_user_id'))
                    login.assert_not_called()
                    mail.assert_not_called()
                    contact.assert_not_called()

    def test_demo_forms_keep_csrf_protection(self):
        with self.assertLogs('django.security.csrf', level='WARNING'):
            response = Client(enforce_csrf_checks=True).post('/login/', {'username': 'demo'})
        self.assertEqual(response.status_code, 403)

    def test_payments_and_social_buttons_return_to_public_pages_without_external_calls(self):
        client = Client()
        for path, target in (('/suscripciones/checkout/lector-pro/', '/suscripciones/planes/'),
                             ('/auth/social/google/', '/login/'), ('/auth/social/github/', '/login/')):
            response = client.get(path)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response['Location'], target)

    def test_tracking_does_not_claim_a_saved_conversion(self):
        response = Client().post('/api/track-conversion/', {}, content_type='application/json')
        self.assertEqual(response.json(), {'status': 'ok', 'tracked': False, 'demo_read_only': True})

    def test_catalog_search_never_writes_analytics_and_preserves_chat_context(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temporary, override_settings(
                SESSION_ENGINE='django.contrib.sessions.backends.file', SESSION_FILE_PATH=temporary), patch.object(
                SessionStore, '_storage_path', temporary, create=True):
            client = Client()
            session = client.session
            session['literary-context-fixture'] = {'title': 'Obra verificada', 'character': 'Luz'}
            session.save()
            with patch('core.views.buscar_libros_hibrido', return_value=[]), patch(
                    'core.models.EventoAnalitica.objects.create') as analytics, patch(
                    'core.models.Genero.objects.values_list', return_value=[]), patch(
                    'core.models.Libro.objects.values_list') as values, patch(
                    'core.views.render', return_value=HttpResponse('catalogue')):
                values.return_value.distinct.return_value = []
                response = client.get('/libros/?q=Novela')
            self.assertEqual(response.status_code, 200)
            analytics.assert_not_called()
            self.assertEqual(client.session['literary-context-fixture']['character'], 'Luz')
            self.assertEqual(client.session['search_history'][0]['query'], 'Novela')

    def test_gateway_rejects_write_methods_on_readonly_pages(self):
        app = Mock(return_value=[])
        password = 'a-fixture-only-long-demo-password'
        gateway = DemoGateway(app, password=password, hosts=['localhost'])
        statuses = []
        gateway({'HTTP_HOST': 'localhost', 'PATH_INFO': '/libros/', 'REQUEST_METHOD': 'POST',
                 'HTTP_AUTHORIZATION': 'Basic ' + base64.b64encode(('demo:' + password).encode()).decode()},
                lambda status, _: statuses.append(status[:3]))
        self.assertEqual(statuses, ['405'])
        app.assert_not_called()

    def test_logout_preview_does_not_flush_the_conversation(self):
        client = Client()
        session = client.session
        session['literary-context-fixture'] = 'Obra activa'
        session.save()
        client.cookies['sessionid'] = session.session_key
        response = client.post('/logout/')
        self.assertEqual(response['Location'], '/')
        self.assertEqual(client.session['literary-context-fixture'], 'Obra activa')

    @override_settings(ROOT_URLCONF='litmate_project.urls', LITMATE_DEMO_READ_ONLY=False)
    def test_regular_site_keeps_original_account_and_contact_views(self):
        from . import views
        self.assertIs(resolve('/login/').func, views.login_view)
        self.assertIs(inspect.unwrap(resolve('/contact/').func), inspect.unwrap(views.contact))

    def test_price_errors_do_not_expose_internal_messages_in_demo(self):
        with (patch('core.scraper.obtener_datos_comparador_libro', side_effect=ValueError('private-path-fixture')),
              self.assertLogs('litmate', level='ERROR')):
            response = Client().get('/api/libro/precios/?titulo=Novela')
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('private-path-fixture', response.json()['msg'])

    @override_settings(LITMATE_DEMO_READ_ONLY=False)
    def test_normal_price_refresh_is_preserved(self):
        from .scraper import obtener_datos_comparador_libro
        with patch('core.scraper.generar_enlaces_completos', return_value=[]) as scrape:
            obtener_datos_comparador_libro(titulo='Una obra', force_refresh=True)
        scrape.assert_called_once()
