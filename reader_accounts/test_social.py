"""Aceptación social con cuentas sintéticas. Nunca usa almacenes reales."""
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from PIL import Image
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.models import ConversacionIA, ElementoListaLectura, LibroFavorito, ListaLectura, PerfilUsuario
from suscripciones.models import PlanSuscripcion, SuscripcionUsuario

from .avatars import own_path
from .models import AnnualReading, Follow, PostLike, ProfileCover, SharedList, SharedReading
from .models import SocialComment, SocialPost, SocialProfile, SocialReport, UsageBucket
from .social_admin import SocialReportAdmin
from .social_forms import PostForm
from .social_policy import visible_posts
from .production_admin import site


def upload(name='photo.png', size=(900, 450), color='#7b5432'):
    data = BytesIO()
    Image.new('RGB', size, color).save(data, 'PNG')
    return SimpleUploadedFile(name, data.getvalue(), content_type='image/png')


@override_settings(LITMATE_COMMUNITY_ENABLED=True, ROOT_URLCONF='litmate_project.production_urls',
                   ALLOWED_HOSTS=['testserver'], SECURE_SSL_REDIRECT=False, LITMATE_AI_LOCK_BACKEND='cache')
class CommunityTests(TestCase):
    databases = {'accounts'}

    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user('private-a', 'private-a@example.invalid', 'Synthetic-Reader-64-Only!')
        cls.b = User.objects.create_user('private-b', 'private-b@example.invalid', 'Synthetic-Reader-64-Only!')
        cls.c = User.objects.create_user('private-c', 'private-c@example.invalid', 'Synthetic-Reader-64-Only!')
        cls.pa = SocialProfile.objects.create(user=cls.a, alias='lectora-a', display_name='Alicia lectora', published=True)
        cls.pb = SocialProfile.objects.create(user=cls.b, alias='lector-b', display_name='Bruno lector', published=True)
        cls.pc = SocialProfile.objects.create(user=cls.c)
        PerfilUsuario.objects.create(usuario=cls.a, biografia='BIOGRAFIA LEGACY PRIVADA', correo=cls.a.email)
        cls.list = ListaLectura.objects.create(usuario=cls.a, nombre='LISTA PRIVADA', descripcion='DESCRIPCION PRIVADA', es_publica=True)
        cls.item = ElementoListaLectura.objects.create(lista=cls.list, google_id='private-book', titulo='LECTURA PRIVADA',
            autores='Autora de prueba', nota_personal='NOTA PRIVADA')
        cls.conv = ConversacionIA.objects.create(usuario=cls.a, titulo='CHAT PRIVADO')
        cls.plan = PlanSuscripcion.objects.create(nombre='Gratuito', slug='gratis', precio=0, limite_consultas_ia_diarias=15)
        SuscripcionUsuario.objects.create(usuario=cls.a, plan=cls.plan, estado='activa')
        cls.public = SocialPost.objects.create(author=cls.pa, submission_id=uuid4(), body='Una opinión literaria.', visibility='public')
        cls.private = SocialPost.objects.create(author=cls.pa, submission_id=uuid4(), body='PUBLICACION PRIVADA')
        cls.followers = SocialPost.objects.create(author=cls.pa, submission_id=uuid4(), body='PARA SEGUIDORES', visibility='followers')

    def setUp(self):
        cache.clear()
        self.temp = TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / '.testtmp')
        self.images = override_settings(LITMATE_AVATAR_ROOT=Path(self.temp.name) / 'avatars')
        self.images.enable()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.images.disable)
        self.client.force_login(self.a)

    def route(self, name, *args):
        return reverse(name, args=args)

    def profile_data(self, **extra):
        return {'display_name': 'Alicia', 'alias': 'lectora-a', 'biography': 'Leo mundos imaginarios.',
                'genres': 'Ciencia ficción', 'favorite_author': 'Mary Shelley', 'favorite_book': 'Frankenstein',
                'annual_goal': 24, 'published': 'on', **extra}

    def post_data(self, **extra):
        return {'submission_id': str(uuid4()), 'body': 'Acabo de leer una novela.', 'visibility': 'private',
                'allow_comments': 'on', **extra}

    def test_profile_edit_and_safe_images(self):
        response = self.client.post(self.route('social_edit_profile'), self.profile_data(
            photo=upload(size=(320, 420)), cover=upload(), share_avatar='on', share_cover='on'))
        self.assertEqual(response.status_code, 302)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.biography, 'Leo mundos imaginarios.')
        personal = PerfilUsuario.objects.get(usuario=self.a)
        self.assertEqual(personal.biografia, 'BIOGRAFIA LEGACY PRIVADA')
        self.assertEqual(personal.meta_anual_libros, 24)
        with Image.open(own_path(personal.imagen.name)) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertFalse(image.getexif())
        with Image.open(BytesIO(ProfileCover.objects.get(profile=self.pa).jpeg)) as cover:
            self.assertEqual(cover.size, (1280, 420))
        self.client.force_login(self.b)
        for kind in ('avatar', 'portada'):
            response = self.client.get(self.route('social_image', self.pa.public_id, kind))
            self.assertEqual(response.status_code, 200)
            if response.streaming:
                self.assertTrue(b''.join(response.streaming_content))

    def test_invalid_images_and_dimensions(self):
        url = self.route('social_edit_profile')
        for file in [SimpleUploadedFile('fake.jpg', b'<script>alert(1)</script>', content_type='image/jpeg'),
                     upload(size=(10, 10)), SimpleUploadedFile('big.png', b'x' * (2 * 1024 * 1024 + 1))]:
            response = self.client.post(url, self.profile_data(cover=file))
            self.assertEqual(response.status_code, 400)
        self.assertFalse(ProfileCover.objects.exists())

    def test_replace_remove_and_revoke_images(self):
        url = self.route('social_edit_profile')
        self.client.post(url, self.profile_data(photo=upload(), cover=upload(), share_avatar='on', share_cover='on'))
        first = PerfilUsuario.objects.get(usuario=self.a).imagen.name
        self.client.post(url, self.profile_data(photo=upload(color='#112233'), cover=upload(color='#332211')))
        self.assertNotEqual(PerfilUsuario.objects.get(usuario=self.a).imagen.name, first)
        self.client.force_login(self.b)
        for kind in ('avatar', 'portada'):
            self.assertEqual(self.client.get(self.route('social_image', self.pa.public_id, kind)).status_code, 404)
        self.client.force_login(self.a)
        self.client.post(url, self.profile_data(remove_cover='on', remove_photo='on'))
        self.assertFalse(ProfileCover.objects.exists())
        self.assertFalse(PerfilUsuario.objects.get(usuario=self.a).imagen.name)

    def test_public_profile_excludes_private_data(self):
        self.client.force_login(self.b)
        response = self.client.get(self.route('social_public_profile', self.pa.public_id))
        self.assertEqual(response.status_code, 200)
        for secret in ('private-a@example.invalid', 'private-a', 'CHAT PRIVADO', 'LISTA PRIVADA',
                       'NOTA PRIVADA', 'PUBLICACION PRIVADA', 'BIOGRAFIA LEGACY PRIVADA', 'PARA SEGUIDORES',
                       'Cambiar contraseña', 'Editar perfil'):
            self.assertNotContains(response, secret)
        self.assertContains(response, 'Alicia lectora')
        self.assertNotContains(response, 'Meta anual')
        for tab in ('biblioteca', 'listas', 'informacion', 'actividad', 'configuracion'):
            response = self.client.get(self.route('social_public_profile', self.pa.public_id), {'seccion': tab})
            for secret in ('CHAT PRIVADO', 'LISTA PRIVADA', 'NOTA PRIVADA', 'LECTURA PRIVADA', 'PUBLICACION PRIVADA'):
                self.assertNotContains(response, secret)

    def test_legacy_data_and_unpublished_profile_are_private(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.route('social_public_profile', self.pc.public_id)).status_code, 404)
        self.assertEqual(self.client.get(self.route('social_shared_list', self.pa.public_id, self.list.pk)).status_code, 404)
        self.assertFalse(SharedReading.objects.exists())
        self.assertFalse(SharedList.objects.exists())

    def test_profile_owner_is_bound_to_session(self):
        self.client.force_login(self.b)
        response = self.client.post(self.route('social_edit_profile'), self.profile_data(alias='bruno-lector', user=self.a.pk))
        self.assertEqual(response.status_code, 302)
        self.pa.refresh_from_db()
        self.pb.refresh_from_db()
        self.assertEqual(self.pa.display_name, 'Alicia lectora')
        self.assertEqual(self.pb.alias, 'bruno-lector')

    def test_post_crud_idempotency_and_spoiler(self):
        data = self.post_data(visibility='public', spoiler='on')
        url = self.route('social_new_post')
        for _ in range(2):
            self.assertEqual(self.client.post(url, data).status_code, 302)
        saved = SocialPost.objects.get(submission_id=data['submission_id'])
        self.assertTrue(saved.spoiler)
        self.assertEqual(SocialPost.objects.filter(submission_id=data['submission_id']).count(), 1)
        response = self.client.post(self.route('social_edit_post', saved.pk),
                                    {'body': 'Texto actualizado', 'visibility': 'private'})
        self.assertEqual(response.status_code, 302)
        saved.refresh_from_db()
        self.assertEqual(saved.body, 'Texto actualizado')
        self.assertFalse(saved.spoiler)
        self.assertEqual(self.client.post(self.route('social_delete_post', saved.pk)).status_code, 400)
        self.assertEqual(self.client.post(self.route('social_delete_post', saved.pk), {'confirm': 'yes'}).status_code, 302)
        self.assertFalse(SocialPost.objects.filter(pk=saved.pk).exists())

    def test_book_reference_uses_existing_catalogue(self):
        fake = SimpleNamespace(pk=123, titulo='Frankenstein', autor=SimpleNamespace(nombre='Mary Shelley'))
        with patch('core.models.Libro.objects') as books:
            books.select_related.return_value.filter.return_value.first.return_value = fake
            form = PostForm(self.post_data(catalogue_id=123), profile=self.pa)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.selected_book.pk, 123)
            books.select_related.return_value.filter.return_value.first.return_value = None
            form = PostForm(self.post_data(catalogue_id=999), profile=self.pa)
            self.assertFalse(form.is_valid())

    def test_post_permission_matrix(self):
        self.client.force_login(self.b)
        for name in ('social_post', 'social_edit_post'):
            self.assertEqual(self.client.get(self.route(name, self.private.pk)).status_code, 404)
        for name in ('social_like', 'social_comment', 'social_report_post', 'social_delete_post', 'social_edit_post'):
            self.assertEqual(self.client.post(self.route(name, self.private.pk), self.post_data(confirm='yes')).status_code, 404)
        self.assertEqual(self.client.post(self.route('social_edit_post', self.public.pk), self.post_data()).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.route('social_post', self.private.pk)).status_code, 404)
        self.assertEqual(self.client.get(self.route('social_post', self.public.pk)).status_code, 200)

    def test_follow_idempotency_visibility_and_unfollow(self):
        self.client.force_login(self.b)
        url = self.route('social_follow', self.pa.public_id)
        self.assertEqual(self.client.get(self.route('social_post', self.followers.pk)).status_code, 404)
        for _ in range(2):
            self.assertEqual(self.client.post(url, {'action': 'add', 'follower': self.c.pk}).status_code, 302)
        self.assertEqual(Follow.objects.filter(target=self.pa, follower=self.pb).count(), 1)
        self.assertFalse(Follow.objects.filter(follower=self.pc).exists())
        self.assertEqual(self.client.get(self.route('social_post', self.followers.pk)).status_code, 200)
        self.assertContains(self.client.get(self.route('social_feed'), {'ver': 'seguidos'}), 'PARA SEGUIDORES')
        self.assertEqual(self.client.post(self.route('social_follow', self.pb.public_id), {'action': 'add'}).status_code, 400)
        self.client.post(url, {'action': 'remove'})
        self.assertFalse(Follow.objects.exists())
        self.assertEqual(self.client.get(self.route('social_post', self.followers.pk)).status_code, 404)

    def test_like_idempotency_and_remove(self):
        self.client.force_login(self.b)
        url = self.route('social_like', self.public.pk)
        for _ in range(2):
            self.assertEqual(self.client.post(url, {'action': 'add', 'author': self.a.pk}).status_code, 302)
        self.assertEqual(PostLike.objects.get().author_id, self.pb.pk)
        self.assertContains(self.client.get(self.route('social_post', self.public.pk)), '1 Me gusta')
        self.client.post(url, {'action': 'remove'})
        self.assertFalse(PostLike.objects.exists())

    def test_comments_idempotency_and_delete_permissions(self):
        self.client.force_login(self.b)
        url = self.route('social_comment', self.public.pk)
        data = {'submission_id': str(uuid4()), 'body': 'Una opinión sobre la lectura.'}
        for _ in range(2):
            self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(SocialComment.objects.count(), 1)
        comment = SocialComment.objects.get()
        self.client.force_login(self.c)
        delete = self.route('social_delete_comment', self.public.pk, comment.pk)
        self.assertEqual(self.client.post(delete, {'confirm': 'yes'}).status_code, 404)
        self.client.force_login(self.b)
        self.assertEqual(self.client.post(delete, {'confirm': 'yes'}).status_code, 302)
        self.client.force_login(self.b)
        self.client.post(url, {'submission_id': str(uuid4()), 'body': 'Otro comentario.'})
        comment = SocialComment.objects.get()
        self.client.force_login(self.a)
        self.assertEqual(self.client.post(self.route('social_delete_comment', self.public.pk, comment.pk),
                                          {'confirm': 'yes'}).status_code, 302)
        self.assertFalse(SocialComment.objects.exists())

    def test_disabled_comments_and_hidden_author(self):
        self.public.allow_comments = False
        self.public.save()
        self.client.force_login(self.b)
        self.assertEqual(self.client.post(self.route('social_comment', self.public.pk),
            {'submission_id': str(uuid4()), 'body': 'Texto'}).status_code, 404)
        self.pa.published = False
        self.pa.save()
        self.assertEqual(self.client.get(self.route('social_post', self.public.pk)).status_code, 404)
        self.assertNotContains(self.client.get(self.route('social_feed')), 'Una opinión literaria.')

    def test_xss_validation_csrf_and_throttle(self):
        payload = '<script>window.untrusted = true</script>'
        self.public.body = payload
        self.public.save()
        response = self.client.get(self.route('social_post', self.public.pk))
        self.assertNotContains(response, payload)
        self.assertContains(response, '&lt;script&gt;')
        data = self.post_data(body='x' * 2401)
        self.assertEqual(self.client.post(self.route('social_new_post'), data).status_code, 400)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.b)
        self.assertEqual(csrf_client.post(self.route('social_like', self.public.pk), {'action': 'add'}).status_code, 403)
        self.client.force_login(self.b)
        statuses = [self.client.post(self.route('social_comment', self.public.pk),
                    {'submission_id': str(uuid4()), 'body': 'Comentario'}).status_code for _ in range(11)]
        self.assertEqual(statuses[-1], 429)

    def test_reports_admin_and_content_withdrawal(self):
        self.client.force_login(self.b)
        url = self.route('social_report_post', self.public.pk)
        for _ in range(2):
            self.assertEqual(self.client.post(url, {'reason': 'Contenido a revisar.'}).status_code, 302)
        report = SocialReport.objects.get()
        request = RequestFactory().get('/')
        request.user = self.b
        moderator = SocialReportAdmin(SocialReport, site)
        self.assertFalse(moderator.has_view_permission(request))
        self.assertNotEqual(self.client.get('/operacion/reader_accounts/socialreport/').status_code, 200)
        self.a.is_staff = self.a.is_superuser = True
        self.a.save()
        request.user = self.a
        self.assertTrue(moderator.has_change_permission(request))
        with patch.object(moderator, 'message_user'):
            moderator.withdraw_content(request, SocialReport.objects.filter(pk=report.pk))
        self.assertEqual(self.client.get(self.route('social_post', self.public.pk)).status_code, 404)
        report.refresh_from_db()
        self.assertTrue(report.resolved)

    def test_explicit_library_sharing_and_revocation(self):
        public_books = self.route('social_public_profile', self.pa.public_id) + '?seccion=biblioteca'
        share = self.route('social_share_library', 'lectura', self.item.pk)
        self.assertEqual(self.client.post(share, {'action': 'add'}).status_code, 400)
        self.client.force_login(self.b)
        self.assertEqual(self.client.post(share, {'action': 'add', 'confirm': 'yes'}).status_code, 404)
        self.client.force_login(self.a)
        self.assertEqual(self.client.post(share, {'action': 'add', 'confirm': 'yes'}).status_code, 302)
        self.client.force_login(self.b)
        response = self.client.get(public_books)
        self.assertContains(response, 'LECTURA PRIVADA')
        self.assertNotContains(response, 'NOTA PRIVADA')
        self.client.force_login(self.a)
        self.client.post(share, {'action': 'remove'})
        self.assertNotContains(self.client.get(public_books), 'LECTURA PRIVADA')
        share = self.route('social_share_library', 'lista', self.list.pk)
        self.client.post(share, {'action': 'add', 'confirm': 'yes'})
        self.client.force_login(self.b)
        response = self.client.get(self.route('social_shared_list', self.pa.public_id, self.list.pk))
        self.assertContains(response, 'LECTURA PRIVADA')
        self.assertNotContains(response, 'NOTA PRIVADA')
        self.assertNotContains(response, 'DESCRIPCION PRIVADA')

    def test_library_preservation_and_stats(self):
        data = {'google_id': self.item.google_id, 'titulo': self.item.titulo,
                'autores': self.item.autores, 'estado': 'leyendo'}
        self.assertEqual(self.client.post('/api/estado-lectura/', data).status_code, 302)
        for _ in range(2):
            data['estado'] = 'completado'
            self.client.post('/api/estado-lectura/', data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.estado_lectura, 'completado')
        self.assertEqual(self.item.nota_personal, 'NOTA PRIVADA')
        self.assertEqual(AnnualReading.objects.count(), 1)
        self.assertFalse(SharedReading.objects.exists())
        data = {'google_id': 'favorite-book', 'titulo': 'Un favorito', 'autores': 'Autora'}
        response = self.client.post('/favoritos/agregar/', data=json.dumps(data), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(LibroFavorito.objects.get().titulo, 'Un favorito')
        self.assertEqual(UsageBucket.objects.count(), 0)
        self.assertContains(self.client.get('/perfil/?seccion=configuracion'), 'CHAT PRIVADO')

    def test_feature_flag_and_pagination(self):
        self.assertEqual(self.client.get('/perfil/').status_code, 200)
        with override_settings(LITMATE_COMMUNITY_ENABLED=False):
            self.assertEqual(self.client.get('/comunidad/').status_code, 404)
            self.assertContains(self.client.get('/perfil/'), 'Mis conversaciones')
            self.assertNotContains(self.client.get('/perfil/'), 'Nueva publicación')
        SocialPost.objects.bulk_create([SocialPost(author=self.pa, submission_id=uuid4(), body=f'Opinion {n}', visibility='public')
                                        for n in range(12)])
        response = self.client.get('/comunidad/')
        self.assertContains(response, 'Siguiente')
        self.assertEqual(len(response.context['posts']), 10)
        self.assertEqual(self.client.get('/comunidad/?page=2').status_code, 200)

    def test_annual_stats_do_not_date_legacy_completions(self):
        self.item.estado_lectura = 'completado'
        self.item.save()
        self.client.post('/api/estado-lectura/', {
            'google_id': self.item.google_id, 'titulo': self.item.titulo,
            'autores': self.item.autores, 'estado': 'completado',
        })
        self.assertFalse(AnnualReading.objects.exists())

    def test_profile_revoke_hides_followers_posts_and_shared_lists(self):
        Follow.objects.create(follower=self.pb, target=self.pa)
        SharedList.objects.create(reading_list=self.list)
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(self.route('social_post', self.followers.pk)).status_code, 200)
        self.pa.published = False
        self.pa.save()
        self.assertEqual(self.client.get(self.route('social_post', self.followers.pk)).status_code, 404)
        self.assertEqual(self.client.get(self.route('social_shared_list', self.pa.public_id, self.list.pk)).status_code, 404)
        self.assertNotContains(self.client.get('/comunidad/?ver=seguidos'), 'PARA SEGUIDORES')

    def test_account_navigation_and_route_policy(self):
        from .gateway import reader_methods
        for tab in ('publicaciones', 'biblioteca', 'listas', 'actividad', 'informacion', 'configuracion'):
            response = self.client.get('/perfil/', {'seccion': tab})
            self.assertEqual(response.status_code, 200)
        self.assertContains(self.client.get('/cuenta/biblioteca/'), 'Mi biblioteca')
        for path, method in [
            (self.route('social_public_profile', self.pa.public_id), 'GET'),
            (self.route('social_follow', self.pa.public_id), 'POST'),
            (self.route('social_post', self.public.pk), 'GET'),
            (self.route('social_like', self.public.pk), 'POST'),
            (self.route('social_edit_profile'), 'POST'),
        ]:
            self.assertIn(method, reader_methods(path))
        self.assertFalse(reader_methods('/lectores/123/fotos/secreto.jpg'))
