"""Biblioteca y chat personal: únicamente cuentas sintéticas en SQLite de ensayo."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth.models import User
from django.db import connections
from django.test import TestCase, RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from core.models import LibroFavorito, ListaLectura, ElementoListaLectura
from suscripciones.models import PlanSuscripcion, SuscripcionUsuario
from django.contrib.staticfiles.testing import StaticLiveServerTestCase


@override_settings(SECURE_SSL_REDIRECT=False)
class LibraryPlatformTests(TestCase):
    databases = {'accounts'}

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('library-owner', password='Seguro-Arce-64-Libros!')
        cls.other = User.objects.create_user('library-other')
        cls.plan = PlanSuscripcion.objects.create(nombre='Gratuito', slug='gratis', precio=0,
            limite_consultas_ia_diarias=15, limite_favoritos=20)
        SuscripcionUsuario.objects.create(usuario=cls.user, plan=cls.plan)
        cls.reading_list = ListaLectura.objects.create(usuario=cls.user, nombre='Lecturas')
        cls.foreign_list = ListaLectura.objects.create(usuario=cls.other, nombre='Privada ajena')

    def setUp(self):
        temp = self.enterContext(TemporaryDirectory(dir=Path.cwd()/'.testtmp'))
        self.enterContext(override_settings(LITMATE_AI_RUNTIME_DB=Path(temp)/'runtime.sqlite3'))
        self.client.get('/chat/')
        self.client.force_login(self.user)

    def book(self, book_id='library-fixture', **changes):
        return {'google_id': book_id, 'titulo': 'Una novela guardada', 'autores': 'Autora sintética',
                'imagen_url': 'https://covers.openlibrary.org/b/id/1-M.jpg', **changes}

    def item(self, **changes):
        return ElementoListaLectura.objects.create(lista=self.reading_list, **self.book(**changes))

    def post(self, path, data):
        return self.client.post(path, json.dumps(data), content_type='application/json')

    def test_reading_organizer_groups_and_deduplicates_shared_book(self):
        item = self.item(estado_lectura='leyendo')
        second = ListaLectura.objects.create(usuario=self.user, nombre='Otra lista')
        ElementoListaLectura.objects.create(lista=second, **self.book(), estado_lectura='completado')
        ElementoListaLectura.objects.create(lista=self.foreign_list, **self.book('private', titulo='SECRETO AJENO'))
        page = self.client.get('/cuenta/biblioteca/')
        self.assertContains(page, 'Mi organizador de lectura')
        self.assertEqual(sum(len(group['books']) for group in page.context['reading_groups']), 1)
        self.assertEqual(next(group for group in page.context['reading_groups'] if group['books'])['state'], 'completado')
        self.assertNotContains(page, 'SECRETO AJENO')
        self.assertEqual(ElementoListaLectura.objects.filter(google_id=item.google_id).count(), 2)

    def test_html_reading_state_is_saved_without_duplicating_existing_lists(self):
        self.item()
        other = ListaLectura.objects.create(usuario=self.user, nombre='Otras')
        ElementoListaLectura.objects.create(lista=other, **self.book())
        response = self.client.post('/api/estado-lectura/', {**self.book(), 'estado': 'leyendo'})
        self.assertRedirects(response, '/cuenta/biblioteca/')
        self.assertEqual(ElementoListaLectura.objects.filter(estado_lectura='leyendo').count(), 2)
        self.assertEqual(ListaLectura.objects.filter(usuario=self.user).count(), 2)

    def test_private_book_detail_only_uses_owned_snapshots_and_has_real_links(self):
        self.item()
        page = self.client.get('/cuenta/libro/?id=library-fixture')
        self.assertContains(page, 'Una novela guardada')
        self.assertContains(page, 'https://www.amazon.com/s?')
        self.assertContains(page, 'https://www.buscalibre.cl/libros/search?')
        self.assertIn('no-store', page['Cache-Control'])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/cuenta/libro/?id=library-fixture').status_code, 404)

    def test_private_book_and_notes_escape_untrusted_text(self):
        self.item(titulo='<script>not-a-title</script>', nota_personal='<img src=x onerror=alert(1)>')
        page = self.client.get('/cuenta/libro/?id=library-fixture')
        self.assertNotContains(page, '<script>not-a-title</script>')
        self.assertNotContains(page, '<img src=x onerror=alert(1)>')

    def test_note_updates_only_owned_item_and_is_bounded(self):
        item = self.item()
        path = f'/cuenta/lecturas/{item.pk}/nota/'
        self.assertEqual(self.client.post(path, {'nota_personal': 'Para leer en invierno'}).status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.nota_personal, 'Para leer en invierno')
        self.assertEqual(self.client.post(path, {'nota_personal': 'x'*256}).status_code, 400)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(path, {'nota_personal': 'forjada'}).status_code, 404)

    def test_favorite_status_is_batched_private_and_capped(self):
        favorite = LibroFavorito.objects.create(usuario=self.user, **self.book())
        LibroFavorito.objects.create(usuario=self.other, **self.book('foreign'))
        response = self.client.get('/api/biblioteca/estado/?id=library-fixture&id=foreign')
        data = response.json()['books']
        self.assertEqual(data['library-fixture']['favorite_id'], favorite.pk)
        self.assertIsNone(data['foreign']['favorite_id'])
        self.assertEqual(self.client.get('/api/biblioteca/estado/?'+'&'.join('id='+str(i) for i in range(51))).status_code, 400)

    def test_list_picker_does_not_fetch_every_item(self):
        from .library import list_get
        for n in range(12): self.item(book_id='fixture-'+str(n))
        request = RequestFactory().get('/api/listas/obtener/?book_id=fixture-1')
        request.user = self.user
        with CaptureQueriesContext(connections['accounts']) as queries:
            response = list_get(request)
        self.assertEqual(json.loads(response.content)['listas'][0]['total_libros'], 12)
        self.assertLessEqual(len(queries), 2)
        self.assertFalse(any('nota_personal' in query['sql'] for query in queries))

    def test_personal_query_never_calls_model_and_replays_with_one_quota_unit(self):
        LibroFavorito.objects.create(usuario=self.user, **self.book())
        data = {'message': 'Muéstrame mis favoritos', 'request_id': 'personal-library-replay-001'}
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query') as engine:
            response = self.post('/chatbot_query/', data)
            self.assertIn('Una novela guardada', b''.join(response.streaming_content).decode())
            repeat = self.post('/chatbot_query/', data)
            self.assertIn('Una novela guardada', b''.join(repeat.streaming_content).decode())
        engine.assert_not_called()
        from .models import UsageBucket
        self.assertEqual(UsageBucket.objects.get().used, 1)
        from core.models import ConversacionIA, MensajeIA
        self.assertEqual(ConversacionIA.objects.filter(usuario=self.user).count(), 1)
        self.assertEqual(MensajeIA.objects.count(), 2)
        self.assertEqual(MensajeIA.objects.get(rol='assistant').metadata_json['provider_calls'], 0)

    def test_personal_pending_query_recommendation_and_no_unauthorized_writes(self):
        self.item()
        ElementoListaLectura.objects.create(lista=self.foreign_list, **self.book('foreign', titulo='SECRETO AJENO'))
        for i, message in enumerate(['¿Qué libros tengo pendientes?', 'Recomiéndame algo de mi lista', 'Elimina todos mis favoritos']):
            with patch('reader_accounts.chat.literary_ai_views.chatbot_query') as engine:
                response = self.post('/chatbot_query/', {'message': message, 'request_id': 'private-query-'+str(i).zfill(16)})
                text = b''.join(response.streaming_content).decode()
            engine.assert_not_called()
            self.assertNotIn('SECRETO AJENO', text)
        self.assertEqual(ElementoListaLectura.objects.count(), 2)

    def test_thematic_recommendations_do_not_enter_the_personal_route(self):
        from .personal_chat import intent
        for message in ['Recomiéndame libros de historia', '¿De qué trata una lista de deseos?',
                        'Recomiéndame una novela sobre la amistad', 'Mis favoritos son los clásicos, recomiéndame fantasía']:
            self.assertIsNone(intent(message))

    def test_guest_cannot_read_another_library_or_status(self):
        self.client.logout()
        self.assertEqual(self.client.get('/api/biblioteca/estado/?id=x').status_code, 401)
        self.assertEqual(self.client.get('/cuenta/libro/?id=x').status_code, 302)

    def test_account_has_real_library_totals_and_profile_values(self):
        from core.models import PerfilUsuario
        PerfilUsuario.objects.create(usuario=self.user, nombre='Lectora', pais='Chile', biografia='Mi perfil real', meta_anual_libros=24)
        self.item(estado_lectura='leyendo')
        page = self.client.get('/perfil/')
        self.assertContains(page, 'Mi perfil real')
        self.assertContains(page, 'Organizador de lectura')
        self.assertEqual(page.context['library_counts']['leyendo'], 1)

    def test_note_requires_csrf_and_get_cannot_mutate(self):
        from django.test import Client
        item = self.item()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        path = f'/cuenta/lecturas/{item.pk}/nota/'
        self.assertEqual(client.post(path, {'nota_personal': 'forjada'}).status_code, 403)
        self.assertEqual(self.client.get(path).status_code, 405)

    def test_book_detail_keeps_the_existing_reading_selection(self):
        self.item(estado_lectura='completado')
        page = self.client.get('/cuenta/libro/?id=library-fixture')
        self.assertContains(page, 'value="completado" selected')

    def test_private_queries_do_not_enter_global_enrichment(self):
        self.item(nota_personal='PRIVATE NOTE NEVER INDEX')
        with patch('core.continuous_knowledge.observe_answer') as observe:
            response = self.post('/chatbot_query/', {'message': '¿Qué libros tengo pendientes?', 'request_id': 'private-no-enrich-001'})
            text = b''.join(response.streaming_content).decode()
        observe.assert_not_called()
        self.assertNotIn('PRIVATE NOTE NEVER INDEX', text)

    def test_library_lookup_failure_is_safe_and_refunds_the_reservation(self):
        from django.db import DatabaseError
        from .models import UsageBucket
        with patch('reader_accounts.personal_chat.answer', side_effect=DatabaseError('DO NOT DISCLOSE')):
            response = self.post('/chatbot_query/', {'message': 'Muéstrame mis favoritos', 'request_id':'private-failure-0001'})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('DO NOT DISCLOSE', response.content.decode())
        self.assertEqual(UsageBucket.objects.get().used, 0)


@override_settings(SECURE_SSL_REDIRECT=False)
class PlatformOperationsTests(TestCase):
    databases = {'accounts'}

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('operation-user', email='operation@example.invalid', password='Abeto-19-Prueba-Segura!')
        cls.other = User.objects.create_user('operation-other')
        cls.plan = PlanSuscripcion.objects.create(nombre='Pro', slug='pro', precio=4990, moneda='CLP')

    def setUp(self):
        temp = self.enterContext(TemporaryDirectory(dir=Path.cwd()/'.testtmp'))
        self.enterContext(override_settings(LITMATE_AI_RUNTIME_DB=Path(temp)/'runtime.sqlite3'))

    def test_pending_checkout_retries_are_idempotent_and_do_not_activate(self):
        from .payment_lifecycle import prepare_checkout
        from suscripciones.models import HistorialPago
        options = {'provider': 'fixture', 'adapter_authorized': True, 'idempotency_key': 'checkout-key-fixture-001'}
        first = prepare_checkout(self.user, self.plan, **options)
        self.plan.refresh_from_db()
        again = prepare_checkout(self.user, self.plan, **options)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(HistorialPago.objects.count(), 1)
        self.assertFalse(SuscripcionUsuario.objects.exists())
        self.plan.precio = 9990
        with self.assertRaises(ValueError): prepare_checkout(self.user, self.plan, **options)
        other = prepare_checkout(self.other, self.plan, **options)
        self.assertNotEqual(first.pk, other.pk)

    def test_checkout_key_cannot_enable_an_unauthorized_adapter(self):
        from .payment_lifecycle import prepare_checkout, PaymentUnavailable
        with self.assertRaises(PaymentUnavailable):
            prepare_checkout(self.user, self.plan, provider='fixture', idempotency_key='checkout-key-fixture-001')
        with self.assertRaises(ValueError):
            prepare_checkout(self.user, self.plan, provider='fixture', adapter_authorized=True, idempotency_key='short')

    def test_private_payment_history_has_no_other_users_or_provider_secrets(self):
        from suscripciones.models import HistorialPago
        HistorialPago.objects.create(usuario=self.user, plan=self.plan, monto=4990, estado='pendiente', referencia_transaccion='PRIVATE-REFERENCE')
        HistorialPago.objects.create(usuario=self.other, monto=123456, estado='fallido')
        self.client.force_login(self.user)
        page = self.client.get('/cuenta/pagos/?usuario_id='+str(self.other.pk))
        self.assertContains(page, 'Pendiente')
        self.assertNotContains(page, '123456')
        self.assertNotContains(page, 'PRIVATE-REFERENCE')
        self.assertEqual(len(page.context['payments']), 1)
        self.assertIn('no-store', page['Cache-Control'])
        self.client.logout()
        self.assertEqual(self.client.get('/cuenta/pagos/').status_code, 302)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', LITMATE_READER_EMAIL_ENABLED=True)
    def test_recovery_has_professional_html_and_plaintext_without_external_trackers(self):
        from django.core import mail
        self.client.get('/chat/')
        self.client.post('/password-reset/', {'email': self.user.email})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].alternatives), 1)
        html, mimetype = mail.outbox[0].alternatives[0]
        self.assertEqual(mimetype, 'text/html')
        self.assertIn('Elegir una nueva contraseña', html)
        self.assertIn('/reset/', mail.outbox[0].body)
        self.assertNotIn('<script', html)
        self.assertNotIn('<img', html)

    def test_admin_only_shows_operational_metadata_and_cannot_change_records(self):
        from django.contrib import admin
        from .models import QueryOperation, UsageBucket, PaymentEvent
        from core.models import ConversacionIA, MensajeIA, HistorialChatbot
        request = RequestFactory().get('/admin/')
        request.user = self.user
        for model in [QueryOperation, UsageBucket, PaymentEvent, User]:
            controller = admin.site._registry[model]
            self.assertFalse(controller.has_add_permission(request))
            self.assertFalse(controller.has_change_permission(request))
            self.assertFalse(controller.has_delete_permission(request))
            self.assertFalse(controller.has_view_permission(request))
            self.assertFalse({'password', 'result', 'stream_token', 'fingerprint', 'email', 'contenido'} & set(controller.fields))
        for model in [ConversacionIA, MensajeIA, HistorialChatbot]:
            self.assertFalse(admin.site.is_registered(model))
        from .gateway import reader_methods
        self.assertEqual(reader_methods('/admin/'), set())

    def test_health_aggregates_are_readonly_and_do_not_reveal_private_values(self):
        import sqlite3
        import hashlib
        from contextlib import closing
        from .operations import account_health
        with TemporaryDirectory(dir=Path.cwd()/'.testtmp') as temporary:
            path = Path(temporary)/'synthetic-health.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                for table in ['auth_user','core_conversacionia','core_librofavorito','core_listalectura',
                              'reader_accounts_queryoperation','suscripciones_historialpago']:
                    db.execute('CREATE TABLE '+table+'(id INTEGER PRIMARY KEY, private_text TEXT)')
                    db.execute('INSERT INTO '+table+' VALUES(1,?)', ['PRIVATE DATA MUST NEVER APPEAR'])
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            result = account_health(path)
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['counts']['accounts'], 1)
            self.assertNotIn('PRIVATE DATA', json.dumps(result))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_health_missing_or_invalid_file_does_not_create_a_database(self):
        from .operations import account_health
        with TemporaryDirectory(dir=Path.cwd()/'.testtmp') as temporary:
            path = Path(temporary)/'missing.sqlite3'
            self.assertEqual(account_health(path), {'status':'unavailable'})
            self.assertFalse(path.exists())
            path.write_bytes(b'not a database')
            self.assertEqual(account_health(path), {'status':'unavailable'})


@override_settings(SECURE_SSL_REDIRECT=False)
class PlatformBrowserTests(StaticLiveServerTestCase):
    """Edge real, SQLite sintético, puerto efímero y cero llamadas a Ollama."""
    databases = {'accounts'}
    host = '127.0.0.1'

    def test_library_controls_in_real_mobile_browser(self):
        import subprocess
        import secrets
        root = Path.cwd()
        temporary = self.enterContext(TemporaryDirectory(dir=root/'.testtmp'))
        self.enterContext(override_settings(LITMATE_AI_RUNTIME_DB=Path(temporary)/'runtime.sqlite3'))
        user = User.objects.create_user('browser-platform', password='Prueba-Navegador-64-Libros!')
        plan = PlanSuscripcion.objects.create(nombre='Gratuito', slug='gratis', precio=0,
            limite_consultas_ia_diarias=15, limite_favoritos=20)
        SuscripcionUsuario.objects.create(usuario=user, plan=plan)
        reading_list = ListaLectura.objects.create(usuario=user, nombre='Mis lecturas')
        data = {'google_id':'platform-a', 'titulo':'La isla de prueba', 'autores':'Autora sintética'}
        LibroFavorito.objects.create(usuario=user, **data)
        ElementoListaLectura.objects.create(lista=reading_list, **data)
        port = int(self.live_server_url.rsplit(':', 1)[1])
        self.assertNotEqual(port, 8003)
        folder = root/'reports/gran_salto_20261108'/('navegador-'+secrets.token_hex(4))
        config = {'folder': str(folder), 'port': port, 'password': secrets.token_urlsafe(32),
                  'platform': True, 'platformUser':user.username, 'platformPassword':'Prueba-Navegador-64-Libros!'}
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query') as engine:
            result = subprocess.run(['node', str(root/'scripts/demo/capturar_demo.mjs')], input=json.dumps(config),
                text=True, encoding='utf8', capture_output=True, timeout=110, cwd=root)
        engine.assert_not_called()
        evidence = json.loads((folder/'captura.json').read_text(encoding='utf8'))
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        self.assertFalse(evidence['errors'])
        self.assertEqual({check['case'] for check in evidence['mobileChecks']}, {
            'existing_favorite_restored_on_card', 'duplicate_card_buttons_stay_synchronized',
            'favorite_survives_navigation', 'favorite_state_on_private_detail',
            'note_saved_by_visible_form', 'reading_state_saved', 'organizer_width_320',
            'organizer_width_390', 'organizer_width_768',
            'favorite_removed_and_duplicate_controls_updated', 'personal_sse_answer_uses_saved_library',
        })
        self.assertTrue(all(check['passed'] for check in evidence['mobileChecks']), evidence['mobileChecks'])
        self.assertEqual(LibroFavorito.objects.filter(usuario=user).count(), 1)
        self.assertEqual(ElementoListaLectura.objects.get(lista=reading_list).nota_personal, 'Nota privada desde el navegador')
