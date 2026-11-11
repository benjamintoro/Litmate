"""Sólo usuarios sintéticos en SQLite aislado; sin entregas de correo reales."""
import datetime
import json
import re
from io import BytesIO
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core import mail
from django.db import connections
from django.test import Client, TestCase, LiveServerTestCase, override_settings
from django.utils import timezone
from core.models import LibroFavorito, ListaLectura, ElementoListaLectura, PerfilUsuario
from suscripciones.models import PlanSuscripcion, SuscripcionUsuario

HTTP_PERSONAL_CHECKS = {}


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonalTests(TestCase):
    databases = {'accounts'}

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('personal', email='personal@example.invalid', password='Abeto-9-Libros-Seguro!')
        cls.other = User.objects.create_user('ajeno', email='ajeno@example.invalid', password='Otro-Seguro-4-Libro!')
        cls.plan = PlanSuscripcion.objects.create(nombre='Gratis', slug='gratis', precio=0, limite_favoritos=2)
        SuscripcionUsuario.objects.create(usuario=cls.user, plan=cls.plan)

    def setUp(self):
        temp = self.enterContext(TemporaryDirectory(dir=Path.cwd()/'.testtmp'))
        self.enterContext(override_settings(LITMATE_AI_RUNTIME_DB=Path(temp)/'runtime.sqlite3'))
        self.client.get('/chat/')
        self.client.force_login(self.user)

    def post(self, url, data):
        return self.client.post(url, json.dumps(data), content_type='application/json')

    @staticmethod
    def book(id='fixture-book'):
        return {'google_id': id, 'titulo': 'Una obra de prueba', 'autores': 'Autora sintética',
                'imagen_url': 'https://covers.openlibrary.org/b/id/1-M.jpg'}

    def test_favorite_duplicate_limit_remove_and_persistence(self):
        first = self.post('/favoritos/agregar/', self.book())
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.post('/favoritos/agregar/', self.book()).json()['status'], 'exists')
        self.post('/favoritos/agregar/', self.book('second'))
        self.assertEqual(self.post('/favoritos/agregar/', self.book('third')).status_code, 403)
        self.client.logout()
        self.client.force_login(self.user)
        self.assertContains(self.client.get('/cuenta/biblioteca/'), 'Una obra de prueba')
        self.assertEqual(self.post(f'/favoritos/eliminar/{first.json()["id"]}/', {}).status_code, 200)
        self.assertEqual(LibroFavorito.objects.count(), 1)

    def test_favorites_cannot_be_modified_by_other_user_or_get(self):
        pk = self.post('/favoritos/agregar/', self.book()).json()['id']
        self.assertEqual(self.client.get(f'/favoritos/eliminar/{pk}/').status_code, 405)
        self.client.force_login(self.other)
        self.assertEqual(self.post(f'/favoritos/eliminar/{pk}/', {}).status_code, 404)
        self.assertNotContains(self.client.get('/cuenta/biblioteca/'), 'Una obra de prueba')

    def test_lists_create_rename_add_idempotent_remove_and_confirm_delete(self):
        result = self.post('/api/listas/crear/', {'nombre': 'Mis novelas', 'es_publica': True})
        pk = result.json()['id']
        self.assertFalse(ListaLectura.objects.get(pk=pk).es_publica)
        self.assertEqual(self.client.post(f'/cuenta/listas/{pk}/editar/', {'nombre': 'Mi nueva lista'}).status_code, 302)
        data = {**self.book(), 'lista_id': pk}
        self.assertEqual(self.post('/api/listas/agregar-libro/', data).status_code, 200)
        self.post('/api/listas/agregar-libro/', data)
        self.assertEqual(ElementoListaLectura.objects.count(), 1)
        rows = self.client.get('/api/listas/obtener/?book_id=fixture-book').json()['listas']
        self.assertTrue(rows[0]['contiene_libro'])
        self.assertEqual(rows[0]['nombre'], 'Mi nueva lista')
        item = ElementoListaLectura.objects.get()
        self.assertEqual(self.post(f'/api/listas/quitar-libro/{item.pk}/', {}).status_code, 200)
        self.assertEqual(self.post(f'/api/listas/eliminar/{pk}/', {}).status_code, 400)
        self.assertEqual(self.post(f'/api/listas/eliminar/{pk}/', {'confirmar': True}).status_code, 200)

    def test_lists_ownership_and_forged_owner(self):
        reading_list = ListaLectura.objects.create(usuario=self.other, nombre='Privada')
        for url, data in ((f'/api/listas/eliminar/{reading_list.pk}/', {'confirmar': True}),
                          ('/api/listas/agregar-libro/', {**self.book(), 'lista_id': reading_list.pk})):
            self.assertEqual(self.post(url, data).status_code, 404)
        self.assertEqual(self.client.post(f'/cuenta/listas/{reading_list.pk}/editar/', {'nombre': 'Ataque'}).status_code, 404)
        result = self.post('/api/listas/crear/', {'nombre': 'Propia', 'usuario_id': self.other.pk})
        self.assertEqual(ListaLectura.objects.get(pk=result.json()['id']).usuario_id, self.user.pk)

    def test_list_name_retry_does_not_create_duplicates(self):
        first = self.post('/api/listas/crear/', {'nombre': 'Lecturas'})
        repeat = self.post('/api/listas/crear/', {'nombre': 'LECTURAS'})
        self.assertEqual(first.json()['id'], repeat.json()['id'])
        self.assertEqual(ListaLectura.objects.count(), 1)

    def test_existing_reading_selector_persists_in_private_list(self):
        data = {**self.book(), 'estado': 'leyendo'}
        self.assertEqual(self.post('/api/estado-lectura/', data).status_code, 200)
        self.assertEqual(ElementoListaLectura.objects.get().estado_lectura, 'leyendo')
        self.assertEqual(self.client.get('/api/listas/obtener/?book_id=fixture-book').json()['estado_actual'], 'leyendo')

    def test_invalid_payload_images_and_states_are_rejected_safely(self):
        self.assertEqual(self.client.post('/favoritos/agregar/', '[]', content_type='application/json').status_code, 400)
        self.assertEqual(self.post('/favoritos/agregar/', {'google_id': 'x'}).status_code, 400)
        self.post('/favoritos/agregar/', {**self.book(), 'imagen_url': 'http://127.0.0.1/private'})
        self.assertEqual(LibroFavorito.objects.get().imagen_url, '')
        pk = self.post('/api/listas/crear/', {'nombre': 'Libros'}).json()['id']
        self.assertEqual(self.post('/api/listas/agregar-libro/', {**self.book(), 'lista_id': pk,
            'estado_lectura': 'inventado'}).status_code, 400)

    def test_profile_updates_only_allowed_fields_and_offers_validated_photo(self):
        response = self.client.post('/perfil/editar/', {'nombre': 'Lectora', 'apellido': 'Prueba',
            'pais': 'Chile', 'meta_anual_libros': 30, 'biografia': '<script>evil</script>',
            'email': 'forged@example.invalid', 'usuario_id': self.other.pk, 'is_staff': True})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'personal@example.invalid')
        self.assertFalse(self.user.is_staff)
        self.assertEqual(PerfilUsuario.objects.get(usuario=self.user).meta_anual_libros, 30)
        page = self.client.get('/perfil/editar/')
        self.assertContains(page, '&lt;script&gt;')
        self.assertContains(page, 'JPEG o PNG')
        self.assertContains(page, 'type="file"')

    @staticmethod
    def image_upload(*, size=(80, 60), exif=False):
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        output = BytesIO()
        image = Image.new('RGB', size, '#227d8e')
        extra = {}
        if exif:
            metadata = Image.Exif()
            metadata[270] = 'PRIVATE-EXIF-NOT-TO-BE-STORED'
            extra['exif'] = metadata
            extra['comment'] = b'PRIVATE-JPEG-COMMENT'
        image.save(output, 'JPEG', **extra)
        return SimpleUploadedFile('original-private-name.jpg', output.getvalue(), content_type='image/jpeg')

    def test_private_avatar_normalized_without_metadata_and_isolated_by_owner(self):
        from PIL import Image
        with TemporaryDirectory(dir=Path.cwd()/'.testtmp') as temp, override_settings(LITMATE_AVATAR_ROOT=Path(temp)/'avatars'):
            data = {'nombre': 'Lectora', 'meta_anual_libros': 12, 'photo': self.image_upload(size=(800, 400), exif=True)}
            self.assertEqual(self.client.post('/perfil/editar/', data).status_code, 302)
            profile = PerfilUsuario.objects.get(usuario=self.user)
            self.assertRegex(profile.imagen.name, r'^avatars/[a-f0-9]{32}\.jpg$')
            response = self.client.get('/cuenta/avatar/')
            image_bytes = b''.join(response.streaming_content)
            self.assertEqual(response['Content-Type'], 'image/jpeg')
            self.assertIn('no-store', response['Cache-Control'])
            self.assertNotIn(b'PRIVATE-EXIF', image_bytes)
            self.assertNotIn(b'PRIVATE-JPEG-COMMENT', image_bytes)
            with Image.open(BytesIO(image_bytes)) as image:
                self.assertEqual(image.size, (256, 128))
                self.assertFalse(image.getexif())
            self.client.force_login(self.other)
            self.assertEqual(self.client.get('/cuenta/avatar/').status_code, 404)

    def test_avatar_rejects_arbitrary_files_size_pixels_and_traversal(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.exceptions import ValidationError
        from .avatars import normalize, own_path
        for upload in (SimpleUploadedFile('fake.png', b'<svg onload=alert(1)>', content_type='image/png'),
                       SimpleUploadedFile('huge.png', b'x' * (2 * 1024 * 1024 + 1), content_type='image/png'),
                       self.image_upload(size=(3000, 2000))):
            with self.assertRaises(ValidationError):
                normalize(upload)
        self.assertIsNone(own_path('../private.jpg'))
        self.assertIsNone(own_path('profile_pics/legacy.jpg'))

    def test_avatar_requires_login_and_storage_failure_is_safe(self):
        self.client.logout()
        self.assertEqual(self.client.get('/cuenta/avatar/').status_code, 302)
        self.client.force_login(self.user)
        with patch('reader_accounts.avatars.store', side_effect=OSError):
            page = self.client.post('/perfil/editar/', {'nombre': 'Prueba', 'meta_anual_libros': 12, 'photo': self.image_upload()})
        self.assertEqual(page.status_code, 503)
        self.assertContains(page, 'No pudimos guardar', status_code=503)

    def test_csrf_is_enforced_on_personal_mutations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post('/favoritos/agregar/', self.book()).status_code, 403)
        self.assertEqual(client.post('/perfil/editar/', {}).status_code, 403)

    def test_library_database_failure_does_not_touch_catalogue(self):
        from django.db import DatabaseError
        with patch('reader_accounts.library.snapshot', side_effect=DatabaseError):
            self.assertEqual(self.post('/favoritos/agregar/', self.book()).status_code, 503)

    def test_guest_personal_apis_are_blocked(self):
        self.client.logout()
        self.assertEqual(self.post('/favoritos/agregar/', self.book()).status_code, 401)
        self.assertEqual(self.client.get('/cuenta/biblioteca/').status_code, 302)

    def test_private_tables_have_owner_keys_but_no_cross_database_fk(self):
        with connections['accounts'].cursor() as cursor:
            cursor.execute('PRAGMA foreign_key_list(core_librofavorito)')
            tables = {row[2] for row in cursor.fetchall()}
        self.assertIn('auth_user', tables)
        self.assertNotIn('core_libro', tables)

    def test_legacy_cover_is_filtered_without_altering_its_stored_value(self):
        item = LibroFavorito.objects.create(usuario=self.user, google_id='legacy', titulo='Legado',
            autores='Autora', imagen_url='https://127.0.0.1/private')
        page = self.client.get('/cuenta/biblioteca/')
        self.assertNotContains(page, 'https://127.0.0.1/private')
        item.refresh_from_db()
        self.assertEqual(item.imagen_url, 'https://127.0.0.1/private')

    def test_disabled_mail_never_claims_or_sends_delivery(self):
        self.client.logout()
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', LITMATE_READER_EMAIL_ENABLED=False):
            page = self.client.post('/password-reset/', {'email': self.user.email})
            self.assertContains(page, 'No se ha enviado ningún enlace')
            self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', LITMATE_READER_EMAIL_ENABLED=True)
    def test_password_reset_expiry_tampering_single_use_and_no_account_enumeration(self):
        from django.contrib.auth.tokens import default_token_generator
        self.client.logout()
        self.assertEqual(self.client.post('/password-reset/', {'email': self.user.email}).status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/reset/', mail.outbox[0].body)
        path = re.search(r'https?://[^/]+(/reset/\S+)', mail.outbox[0].body).group(1)
        self.assertContains(self.client.get(path.rstrip('/') + 'bad/'), 'no es válido')
        with patch.object(default_token_generator, '_now', return_value=datetime.datetime.now() + datetime.timedelta(days=2)):
            self.assertContains(self.client.get(path), 'no es válido')
        first = self.client.get(path)
        self.assertEqual(first.status_code, 302)
        change = self.client.post(first.url, {'new_password1': 'Nuevo-Abeto-Seguro-39!', 'new_password2': 'Nuevo-Abeto-Seguro-39!'})
        self.assertEqual(change.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Nuevo-Abeto-Seguro-39!'))
        self.assertContains(Client().get(path), 'no es válido')
        missing = self.client.post('/password-reset/', {'email': 'nobody@example.invalid'})
        self.assertEqual(missing.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', LITMATE_READER_EMAIL_ENABLED=True)
    def test_duplicate_email_sends_no_ambiguous_reset(self):
        User.objects.create_user('duplicado', email=self.user.email, password='Duplicada-8-Prueba!')
        self.client.post('/password-reset/', {'email': self.user.email})
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', LITMATE_READER_EMAIL_ENABLED=True)
    def test_mail_provider_failure_is_not_reported_as_sent(self):
        with patch('django.core.mail.EmailMultiAlternatives.send', side_effect=OSError):
            self.assertEqual(self.client.post('/password-reset/', {'email': self.user.email}).status_code, 503)

    def test_gateway_exposes_only_personal_routes_not_storage(self):
        from reader_accounts.gateway import reader_methods
        self.assertEqual(reader_methods('/api/listas/crear/'), {'POST'})
        for path in ('/data/accounts/users.sqlite3', '/backups/accounts.sqlite3', '/admin/', '/media/profile_pics/x.jpg'):
            self.assertEqual(reader_methods(path), set())

    def test_password_change_is_available_without_smtp(self):
        from reader_accounts.gateway import reader_methods
        self.assertContains(self.client.get('/perfil/'), '/cuenta/password/')
        self.assertEqual(reader_methods('/cuenta/password/'), {'GET', 'HEAD', 'POST'})
        page = self.client.get('/cuenta/password/')
        self.assertContains(page, 'name="old_password"')
        self.assertIn('no-store', page['Cache-Control'])
        self.client.logout()
        self.assertEqual(self.client.get('/cuenta/password/').status_code, 302)

    def test_password_change_keeps_current_session_and_invalidates_other_session(self):
        other_session = Client()
        other_session.force_login(self.user)
        other_hash = self.other.password
        response = self.client.post('/cuenta/password/', {
            'old_password': 'Abeto-9-Libros-Seguro!', 'new_password1': 'Cambio-Seguro-Alamo-57!',
            'new_password2': 'Cambio-Seguro-Alamo-57!', 'user_id': self.other.pk})
        self.assertRedirects(response, '/perfil/')
        self.user.refresh_from_db()
        self.other.refresh_from_db()
        self.assertTrue(self.user.check_password('Cambio-Seguro-Alamo-57!'))
        self.assertEqual(self.other.password, other_hash)
        self.assertEqual(self.client.get('/perfil/').status_code, 200)
        self.assertEqual(other_session.get('/perfil/').status_code, 302)

    def test_password_change_rejects_wrong_current_mismatch_and_weak_password(self):
        original = self.user.password
        for old, first, second in [('incorrecta', 'Cambio-Alamo-67!', 'Cambio-Alamo-67!'),
                                    ('Abeto-9-Libros-Seguro!', 'Cambio-Alamo-67!', 'diferente'),
                                    ('Abeto-9-Libros-Seguro!', '123', '123')]:
            page = self.client.post('/cuenta/password/', {
                'old_password': old, 'new_password1': first, 'new_password2': second})
            self.assertEqual(page.status_code, 200)
            self.assertTrue(page.context['form'].errors)
            self.assertNotContains(page, 'value="' + first + '"')
        self.user.refresh_from_db()
        self.assertEqual(self.user.password, original)

    def test_password_change_enforces_csrf_rate_limit_and_safe_storage_error(self):
        from django.db import DatabaseError
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post('/cuenta/password/', {}).status_code, 403)
        with patch('reader_accounts.auth_limits.rate_increment', return_value=7):
            self.assertEqual(self.client.post('/cuenta/password/', {}).status_code, 429)
        with patch('django.contrib.auth.forms.PasswordChangeForm.save', side_effect=DatabaseError('private-internal-detail')):
            page = self.client.post('/cuenta/password/', {'old_password': 'Abeto-9-Libros-Seguro!',
                'new_password1': 'Cambio-Seguro-Alamo-57!', 'new_password2': 'Cambio-Seguro-Alamo-57!'})
        self.assertContains(page, 'Inténtalo más tarde', status_code=503)
        self.assertNotContains(page, 'private-internal-detail', status_code=503)

    def test_avatar_can_be_detached_without_deleting_backups_or_another_users_image(self):
        from .avatars import own_path
        with TemporaryDirectory(dir=Path.cwd()/'.testtmp') as temp, override_settings(LITMATE_AVATAR_ROOT=Path(temp)/'avatars'):
            self.client.post('/perfil/editar/', {'nombre': 'Prueba', 'meta_anual_libros': 12, 'photo': self.image_upload()})
            profile = PerfilUsuario.objects.get(usuario=self.user)
            old_path = own_path(profile.imagen.name)
            other = PerfilUsuario.objects.create(usuario=self.other, imagen='profile_pics/original.jpg')
            self.assertContains(self.client.get('/perfil/editar/'), 'name="remove_photo"')
            response = self.client.post('/perfil/editar/', {'nombre': 'Prueba', 'meta_anual_libros': 12,
                'remove_photo': 'on', 'usuario_id': self.other.pk})
            self.assertEqual(response.status_code, 302)
            profile.refresh_from_db()
            other.refresh_from_db()
            self.assertFalse(profile.imagen.name)
            self.assertEqual(other.imagen.name, 'profile_pics/original.jpg')
            self.assertTrue(old_path.is_file())  # Conservación de respaldos y archivos anteriores.
            self.assertEqual(self.client.get('/cuenta/avatar/').status_code, 404)
            self.assertNotContains(self.client.get('/perfil/'), '<img src="/cuenta/avatar/"')

    def test_avatar_upload_and_removal_cannot_be_submitted_together(self):
        page = self.client.post('/perfil/editar/', {'nombre': 'Prueba', 'meta_anual_libros': 12,
            'remove_photo': 'on', 'photo': self.image_upload()})
        self.assertEqual(page.status_code, 200)
        self.assertIn('remove_photo', page.context['form'].errors)
        self.assertFalse(PerfilUsuario.objects.filter(usuario=self.user, imagen__startswith='avatars/').exists())

    def test_list_rename_rejects_duplicate_names_but_keeps_other_owners_independent(self):
        first = ListaLectura.objects.create(usuario=self.user, nombre='Novelas')
        second = ListaLectura.objects.create(usuario=self.user, nombre='Ensayos')
        ListaLectura.objects.create(usuario=self.other, nombre='Poesía')
        page = self.client.post(f'/cuenta/listas/{second.pk}/editar/', {'nombre': ' NOVELAS '})
        self.assertContains(page, 'Ya tienes una lista con ese nombre')
        second.refresh_from_db()
        self.assertEqual(second.nombre, 'Ensayos')
        self.assertEqual(self.client.post(f'/cuenta/listas/{second.pk}/editar/', {'nombre': 'Poesía'}).status_code, 302)
        self.assertEqual(self.client.post(f'/cuenta/listas/{first.pk}/editar/', {'nombre': 'NOVELAS'}).status_code, 302)

    def test_list_invalid_html_form_keeps_input_and_displays_field_errors(self):
        page = self.client.post('/api/listas/crear/', {'nombre': '', 'descripcion': 'Mi descripción'})
        self.assertContains(page, 'Mi descripción', status_code=400)
        self.assertContains(page, 'errorlist', status_code=400)
        self.assertEqual(ListaLectura.objects.count(), 0)
        self.assertEqual(self.post('/api/listas/crear/', {'nombre': ''}).status_code, 400)

    def test_profile_and_list_storage_errors_have_safe_form_feedback(self):
        from django.db import DatabaseError
        reading_list = ListaLectura.objects.create(usuario=self.user, nombre='Antes')
        with patch('core.models.ListaLectura.save', side_effect=DatabaseError('secret-storage')):
            page = self.client.post(f'/cuenta/listas/{reading_list.pk}/editar/', {'nombre': 'Después'})
        self.assertContains(page, 'Inténtalo más tarde', status_code=503)
        self.assertNotContains(page, 'secret-storage', status_code=503)
        with patch('core.models.PerfilUsuario.save', side_effect=DatabaseError('secret-storage')):
            page = self.client.post('/perfil/editar/', {'nombre': 'Después', 'meta_anual_libros': 12})
        self.assertContains(page, 'Inténtalo más tarde', status_code=503)
        reading_list.refresh_from_db()
        self.assertEqual(reading_list.nombre, 'Antes')

    def test_opening_or_invalid_profile_form_does_not_create_a_missing_profile(self):
        self.assertFalse(PerfilUsuario.objects.filter(usuario=self.user).exists())
        self.assertEqual(self.client.get('/perfil/editar/').status_code, 200)
        self.client.post('/perfil/editar/', {'nombre': 'Inválido', 'meta_anual_libros': 0})
        self.assertFalse(PerfilUsuario.objects.filter(usuario=self.user).exists())

    def test_all_history_is_reachable_with_pagination_and_no_other_users_conversations(self):
        from core.models import ConversacionIA
        conversations = [ConversacionIA.objects.create(usuario=self.user, titulo=f'Conversación propia {i}') for i in range(23)]
        ConversacionIA.objects.create(usuario=self.other, titulo='Hilo ajeno privado')
        first = self.client.get('/perfil/')
        second = self.client.get('/perfil/?page=2')
        self.assertEqual(len(first.context['conversaciones']), 20)
        self.assertEqual(len(second.context['conversaciones']), 3)
        recovered = {conv.pk for page in [first, second] for conv in page.context['conversaciones']}
        self.assertEqual(recovered, {conv.pk for conv in conversations})
        self.assertContains(first, '?page=2')
        self.assertNotContains(first, 'Hilo ajeno privado')
        self.assertNotContains(second, 'Hilo ajeno privado')
        self.assertEqual(self.client.get('/perfil/?page=not-a-number').status_code, 200)


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonalHTTPTests(LiveServerTestCase):
    """HTTP de verdad en puerto efímero, con base sintética y sin inferencia externa."""
    databases = {'accounts'}
    host = '127.0.0.1'

    def test_personal_flows_and_sse_replay_over_isolated_http(self):
        import time
        from http.cookiejar import CookieJar
        from urllib.error import HTTPError
        from urllib.parse import urlencode
        from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request
        from .tests import fixture_stream
        started = time.monotonic()
        HTTP_PERSONAL_CHECKS.clear()
        self.assertNotIn(':8003', self.live_server_url)
        temporary = self.enterContext(TemporaryDirectory(dir=Path.cwd()/'.testtmp'))
        self.enterContext(override_settings(LITMATE_AI_RUNTIME_DB=Path(temporary)/'runtime.sqlite3',
                                            LITMATE_AVATAR_ROOT=Path(temporary)/'avatars'))
        user = User.objects.create_user('http-synthetic', password='Abeto-9-Libros-Seguro!')
        plan = PlanSuscripcion.objects.create(nombre='Gratuito', slug='gratis', precio=0,
            limite_consultas_ia_diarias=15, limite_favoritos=20)
        SuscripcionUsuario.objects.create(usuario=user, plan=plan)
        jar = CookieJar()
        opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(jar))

        def request(path, data=None, *, is_json=False, upload=None):
            headers, body = {}, None
            if data is not None:
                headers = {'Origin': self.live_server_url,
                           'X-CSRFToken': next(cookie.value for cookie in jar if cookie.name == 'csrftoken')}
                headers['Content-Type'] = 'application/json' if is_json else 'application/x-www-form-urlencoded'
                body = json.dumps(data).encode() if is_json else urlencode(data).encode()
                if upload is not None:
                    boundary = 'LitmateIsolatedMultipartBoundary'
                    headers['Content-Type'] = 'multipart/form-data; boundary=' + boundary
                    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
                             for key, value in data.items()]
                    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="fixture.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
                                 + upload.read() + b'\r\n')
                    body = b''.join(parts) + f'--{boundary}--\r\n'.encode()
            try:
                response = opener.open(Request(self.live_server_url+path, headers=headers, data=body), timeout=15)
            except HTTPError as error:
                response = error
            with response:
                return response.status, response.headers, response.read()

        def check(name, condition):
            HTTP_PERSONAL_CHECKS[name] = bool(condition)
            self.assertTrue(condition, name)

        request('/chat/')
        status, _, body = request('/login/', {'username_or_email': user.username, 'password': 'Abeto-9-Libros-Seguro!'})
        check('login', status == 200 and b'Gratuito' in body)
        check('password_form', b'name="old_password"' in request('/cuenta/password/')[2])
        status, _, body = request('/cuenta/password/', {'old_password': 'Abeto-9-Libros-Seguro!',
            'new_password1': 'Nuevo-Olmo-Seguro-58!', 'new_password2': 'Nuevo-Olmo-Seguro-58!'})
        check('password_changed_session_preserved', status == 200 and b'Mi cuenta' in body)
        request('/perfil/editar/', {'nombre': 'Prueba HTTP', 'meta_anual_libros': 12}, upload=PersonalTests.image_upload())
        status, headers, body = request('/cuenta/avatar/')
        check('private_avatar_uploaded', status == 200 and headers.get('Content-Type') == 'image/jpeg' and body.startswith(b'\xff\xd8'))
        request('/perfil/editar/', {'nombre': 'Prueba HTTP', 'meta_anual_libros': 12, 'remove_photo': 'on'})
        check('avatar_detached', request('/cuenta/avatar/')[0] == 404)
        _, _, body = request('/api/listas/crear/', {'nombre': 'Lecturas HTTP'}, is_json=True)
        first = json.loads(body)['id']
        _, _, body = request('/api/listas/crear/', {'nombre': 'Otros libros HTTP'}, is_json=True)
        second = json.loads(body)['id']
        status, _, body = request(f'/cuenta/listas/{second}/editar/', {'nombre': 'LECTURAS HTTP'})
        check('duplicate_list_error', status == 200 and b'Ya tienes una lista con ese nombre' in body)
        check('invalid_html_form', request('/api/listas/crear/', {'nombre': ''})[0] == 400)
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query', side_effect=fixture_stream) as engine:
            data = {'message': 'Consulta de transporte sintética', 'request_id': 'synthetic-http-replay-01'}
            status, headers, body = request('/chatbot_query/', data, is_json=True)
            check('sse_transport', status == 200 and headers.get_content_type() == 'text/event-stream' and b'data: [DONE]' in body)
            status, headers, body = request('/chatbot_query/', data, is_json=True)
            check('sse_retry_no_second_generation', status == 200 and headers.get('X-LitMate-Idempotent-Replay') == '1' and engine.call_count == 1)
        check('quota_once', json.loads(request('/api/cuota-ia/')[2])['cuota']['usadas'] == 1)
        request('/logout/', {})
        check('logged_out', b'name="old_password"' not in request('/cuenta/password/')[2])
        request('/login/', {'username_or_email': user.username, 'password': 'Nuevo-Olmo-Seguro-58!'})
        check('new_password_login_and_list_persistence', b'Lecturas HTTP' in request('/cuenta/biblioteca/')[2])
        check('quota_persists', json.loads(request('/api/cuota-ia/')[2])['cuota']['usadas'] == 1)
        HTTP_PERSONAL_CHECKS['seconds'] = round(time.monotonic()-started, 4)
        HTTP_PERSONAL_CHECKS['real_llm_inference'] = False
        HTTP_PERSONAL_CHECKS['production_databases_used'] = False
