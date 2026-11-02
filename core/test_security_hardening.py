"""Regresiones de endurecimiento web: demo social y CSRF en endpoints activos."""
import json
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse


class SocialDemoSecurityTests(TestCase):
    def test_demo_login_is_disabled_outside_debug_without_explicit_flag(self):
        with override_settings(DEBUG=False, LITMATE_SOCIAL_DEMO=False,
                               GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET=''):
            response = self.client.get(reverse('social_login', args=['google']) + '?demo=1')
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertFalse(get_user_model().objects.filter(username='google_lector').exists())

    def test_demo_login_works_only_with_explicit_flag(self):
        with override_settings(DEBUG=False, LITMATE_SOCIAL_DEMO=True,
                               GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET=''):
            response = self.client.get(reverse('social_login', args=['google']) + '?demo=1')
        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)
        self.assertTrue(get_user_model().objects.filter(username='google_lector').exists())

    def test_demo_never_takes_over_an_existing_password_account(self):
        user = get_user_model().objects.create_user(
            username='google_lector', email='real@example.com', password='real-password')
        with override_settings(DEBUG=True, LITMATE_SOCIAL_DEMO=True,
                               GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET=''):
            response = self.client.get(reverse('social_login', args=['google']) + '?demo=1')
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(get_user_model().objects.get(pk=user.pk).email, 'real@example.com')

    def test_oauth_callback_requires_a_matching_state(self):
        # El callback debe rechazar un state ausente antes de intercambiar el código.
        response = self.client.get(
            reverse('social_login_callback', args=['google']) + '?code=test&state=forged')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('login'))


class SocialOAuthCallbackTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='victim', email='victim@example.com', password='real-password')

    def callback(self, provider, *, profile=None, emails=None, google=None):
        session = self.client.session
        session['oauth_state'] = 'state-123'
        session.save()
        token_response = Mock(status_code=200)
        token_response.json.return_value = {'access_token': 'token'}

        def get_response(url, **kwargs):
            if 'user/emails' in url:
                return Mock(status_code=200, json=lambda: emails or [])
            if 'api.github.com/user' in url:
                return Mock(status_code=200, json=lambda: profile or {})
            if 'googleapis.com' in url:
                return Mock(status_code=200, json=lambda: google or {})
            return Mock(status_code=200, json=lambda: {})

        with patch('core.views.requests.post', return_value=token_response), \
                patch('core.views.requests.get', side_effect=get_response):
            with override_settings(DEBUG=False,
                                   GITHUB_CLIENT_ID='client',
                                   GITHUB_CLIENT_SECRET='secret',
                                   GOOGLE_CLIENT_ID='client',
                                   GOOGLE_CLIENT_SECRET='secret'):
                return self.client.get(
                    reverse('social_login_callback', args=[provider])
                    + '?code=abc&state=state-123')

    def test_github_unverified_email_cannot_take_over_password_account(self):
        response = self.callback(
            'github',
            profile={'id': 2, 'login': 'victim', 'name': 'Victim',
                     'email': 'victim@example.com'},
            emails=[{'email': 'victim@example.com', 'primary': True, 'verified': False}])
        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)
        self.assertNotEqual(self.client.session.get('_auth_user_id'), str(self.user.pk))
        self.assertTrue(get_user_model().objects.get(pk=self.user.pk)
                        .check_password('real-password'))

    def test_github_username_cannot_take_over_a_password_account(self):
        response = self.callback(
            'github',
            profile={'id': 3, 'login': 'victim', 'name': 'Otra persona',
                     'email': 'otra@example.com'},
            emails=[{'email': 'otra@example.com', 'primary': True, 'verified': True}])
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(self.client.session.get('_auth_user_id'), str(self.user.pk))

    def test_github_verified_email_links_an_existing_account(self):
        reader = get_user_model().objects.create_user(
            username='reader', email='reader@example.com', password='reader-password')
        response = self.callback(
            'github',
            profile={'id': 4, 'login': 'github-reader', 'name': 'Reader',
                     'email': 'reader@example.com'},
            emails=[{'email': 'reader@example.com', 'primary': True, 'verified': True}])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session.get('_auth_user_id'), str(reader.pk))

    def test_google_unverified_email_cannot_take_over_password_account(self):
        response = self.callback(
            'google',
            google={'id': 'google-1', 'email': 'victim@example.com',
                    'verified_email': False, 'given_name': 'Victim'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)
        self.assertNotEqual(self.client.session.get('_auth_user_id'), str(self.user.pk))


class CsrfEndpointTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='csrf-reader', password='test-password')
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.client.get('/chat/')
        self.token = self.client.cookies['csrftoken'].value

    def post(self, name, data, *, token=True):
        headers = {'HTTP_X_CSRFTOKEN': self.token} if token else {}
        return self.client.post(reverse(name), json.dumps(data),
                                content_type='application/json', **headers)

    def test_favoritos_requires_csrf(self):
        data = {'google_id': 'csrf-book', 'titulo': 'Libro', 'autores': 'Autora'}
        self.assertEqual(self.post('agregar_favorito', data, token=False).status_code, 403)
        self.assertEqual(self.post('agregar_favorito', data).status_code, 200)

    def test_estado_lectura_requires_csrf(self):
        data = {'google_id': 'csrf-book-2', 'titulo': 'Libro 2',
                'autor': 'Autor', 'estado': 'leyendo'}
        self.assertEqual(self.post('actualizar_estado_lectura', data, token=False).status_code, 403)
        self.assertEqual(self.post('actualizar_estado_lectura', data).status_code, 200)

    def test_track_conversion_requires_csrf(self):
        data = {'titulo': 'Libro', 'proveedor': 'Buscalibre', 'precio': '1000'}
        self.assertEqual(self.post('track_conversion', data, token=False).status_code, 403)
        self.assertEqual(self.post('track_conversion', data).status_code, 200)
