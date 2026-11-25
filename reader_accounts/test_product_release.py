"""Aceptación de lanzamiento con usuarios sintéticos; nunca usa producción."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings
from django.db import connections


class PublicRecoveryTests(TestCase):
    databases = {'accounts'}

    def setUp(self):
        folder = self.enterContext(TemporaryDirectory(dir=Path(settings.BASE_DIR) / '.testtmp'))
        self.enterContext(override_settings(
            LITMATE_AI_RUNTIME_DB=Path(folder) / 'limits.sqlite3',
            LITMATE_READER_EMAIL_ENABLED=True,
            EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        ))
        self.client.defaults['HTTP_HOST'] = settings.PRODUCTION.host
        self.user = User.objects.create_user('recovery-fixture', email='reader@example.invalid',
                                             password='Synthetic-Reader-64-Only!')
        self.client.get('/login/', secure=True)

    def test_smtp_failure_does_not_disclose_whether_account_exists(self):
        with patch('django.core.mail.EmailMultiAlternatives.send', side_effect=OSError('SMTP unavailable')):
            known = self.client.post('/password-reset/', {'email': self.user.email}, secure=True)
            unknown = self.client.post('/password-reset/', {'email': 'absent@example.invalid'}, secure=True)
        self.assertEqual(known.status_code, 302)
        self.assertEqual((known.status_code, known['Location']),
                         (unknown.status_code, unknown['Location']))
        page = self.client.get(known['Location'], secure=True)
        self.assertNotContains(page, 'correo enviado')

    def test_recovery_link_uses_configured_https_domain_and_not_forwarded_host(self):
        response = self.client.post('/password-reset/', {'email': self.user.email}, secure=True,
                                    HTTP_X_FORWARDED_HOST='attacker.invalid')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(settings.LITMATE_PUBLIC_ORIGIN + '/reset/', mail.outbox[0].body)
        self.assertNotIn('attacker.invalid', mail.outbox[0].body)

    def test_delivery_failure_log_does_not_contain_email_or_smtp_secret(self):
        with patch('django.core.mail.EmailMultiAlternatives.send', side_effect=OSError('PRIVATE-SMTP-SECRET')):
            with self.assertLogs('reader_accounts.recovery', level='WARNING') as logs:
                self.client.post('/password-reset/', {'email': self.user.email}, secure=True)
        self.assertIn('password_reset_delivery_failed', '\n'.join(logs.output))
        self.assertNotIn(self.user.email, '\n'.join(logs.output))
        self.assertNotIn('PRIVATE-SMTP-SECRET', '\n'.join(logs.output))


class ServiceReadinessTests(TestCase):
    databases = {'accounts'}

    def setUp(self):
        self.catalogue = self.enterContext(patch.object(connections['default'], 'cursor'))
        self.client.defaults['HTTP_HOST'] = settings.PRODUCTION.host

    def dependencies(self, search_error=False, model_missing=False):
        values = [{'models': [] if model_missing else [{'name': settings.LITMATE_LOCAL_MODEL}]},
                  OSError('PRIVATE NETWORK ERROR') if search_error else {'http_status': 200}]
        return patch('reader_accounts.production_runtime.local_json', side_effect=values)

    def test_unavailable_model_is_not_reported_as_ready(self):
        with self.dependencies(model_missing=True):
            response = self.client.get('/_health/ready/', secure=True)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'unavailable'})

    def test_optional_search_failure_is_degraded_and_local_service_remains_ready(self):
        with self.dependencies(search_error=True):
            response = self.client.get('/_health/ready/', secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'degraded'})

    def test_catalogue_failure_is_unavailable_without_private_details(self):
        self.catalogue.side_effect = OSError('PRIVATE DATABASE DETAILS')
        with self.dependencies():
            response = self.client.get('/_health/ready/', secure=True)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('PRIVATE', response.content.decode())


class PersonalExportTests(TestCase):
    databases = {'accounts'}
    password = 'Synthetic-Reader-64-Only!'

    def setUp(self):
        from core.models import ConversacionIA, MensajeIA, LibroFavorito
        folder = self.enterContext(TemporaryDirectory(dir=Path(settings.BASE_DIR) / '.testtmp'))
        self.enterContext(override_settings(LITMATE_AI_RUNTIME_DB=Path(folder) / 'limits.sqlite3'))
        self.client.defaults['HTTP_HOST'] = settings.PRODUCTION.host
        self.user = User.objects.create_user('export-fixture', password=self.password)
        other = User.objects.create_user('private-other')
        for user, text in ((self.user, 'OWN MESSAGE'), (other, 'OTHER PRIVATE MESSAGE')):
            conversation = ConversacionIA.objects.create(usuario=user, titulo=text)
            MensajeIA.objects.create(conversacion=conversation, rol='user', contenido=text)
            LibroFavorito.objects.create(usuario=user, google_id=text, titulo=text)
        self.client.force_login(self.user)

    def test_export_requires_reauthentication_and_is_readonly_and_owner_scoped(self):
        from core.models import MensajeIA
        before = MensajeIA.objects.count()
        wrong = self.client.post('/cuenta/exportar/', {'password': 'wrong'}, secure=True)
        self.assertEqual(wrong.status_code, 200)
        self.assertNotIn('OWN MESSAGE', wrong.content.decode())
        response = self.client.post('/cuenta/exportar/', {'password': self.password}, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])
        text = response.content.decode()
        self.assertIn('OWN MESSAGE', text)
        self.assertNotIn('OTHER PRIVATE MESSAGE', text)
        self.assertNotIn(self.user.password, text)
        self.assertNotIn('session_key', text)
        self.assertNotIn('provider_receipt', text)
        self.assertEqual(MensajeIA.objects.count(), before)

    def test_export_is_private_and_csrf_protected(self):
        from django.test import Client
        self.client.logout()
        self.assertEqual(self.client.get('/cuenta/exportar/', secure=True).status_code, 302)
        client = Client(enforce_csrf_checks=True, HTTP_HOST=settings.PRODUCTION.host)
        client.force_login(self.user)
        self.assertEqual(client.post('/cuenta/exportar/', {'password': self.password}, secure=True).status_code, 403)

    def test_export_failure_does_not_expose_database_error_or_password(self):
        from django.db import DatabaseError
        with patch('reader_accounts.privacy.own_export', side_effect=DatabaseError('PRIVATE DB ERROR')):
            response = self.client.post('/cuenta/exportar/', {'password': self.password}, secure=True)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('PRIVATE DB ERROR', response.content.decode())
        self.assertNotIn(self.password, response.content.decode())


class CostReportTests(SimpleTestCase):
    def test_energy_is_unknown_without_assumptions_and_validates_inputs(self):
        from scripts.production.usage_report import estimated_energy
        self.assertIsNone(estimated_energy(3600)['clp'])
        self.assertEqual(estimated_energy(3600, watts=1000, clp_kwh=200)['clp'], 200)
        for watts, tariff in ((float('nan'), 200), (-1, 200), (1000, None)):
            with self.assertRaises(ValueError):
                estimated_energy(3600, watts=watts, clp_kwh=tariff)

    def test_usage_report_does_not_read_message_content_or_write_database(self):
        from contextlib import closing
        import json
        import sqlite3
        from scripts.production.usage_report import summarize
        with TemporaryDirectory(dir=Path(settings.BASE_DIR) / '.testtmp') as temporary:
            path = Path(temporary) / 'fixture.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript('''
                    CREATE TABLE reader_accounts_queryoperation(actor TEXT,status TEXT);
                    CREATE TABLE core_mensajeia(rol TEXT,latencia_ms INTEGER,metadata_json TEXT,contenido TEXT);
                    CREATE TABLE suscripciones_suscripcionusuario(usuario_id INTEGER,plan_id INTEGER);
                    CREATE TABLE suscripciones_plansuscripcion(id INTEGER,slug TEXT,precio INTEGER,moneda TEXT,
                        periodo TEXT,limite_consultas_ia_diarias INTEGER);
                    INSERT INTO reader_accounts_queryoperation VALUES('u:1','completed');
                    INSERT INTO suscripciones_suscripcionusuario VALUES(1,1);
                    INSERT INTO suscripciones_plansuscripcion VALUES(1,'gratis',0,'CLP','mensual',15);
                ''')
                db.execute('INSERT INTO core_mensajeia VALUES(?,?,?,?)', ('assistant', 2000,
                    json.dumps({'provider_calls': 2, 'diagnostics': {'stage_timings': [{'elapsed_ms': 1000}]}}),
                    'PRIVATE MESSAGE DO NOT SELECT'))
            before = path.read_bytes()
            report = summarize(path)
            self.assertEqual(report['recorded_llm_calls'], 2)
            self.assertEqual(report['chat_p95_seconds'], 2)
            self.assertEqual(report['recorded_model_stage_seconds'], 1)
            self.assertEqual(report['operations_by_current_plan'], {'gratis': 1})
            self.assertNotIn('PRIVATE MESSAGE', json.dumps(report))
            self.assertNotIn('operations_by_local_user_id', report)
            self.assertEqual(before, path.read_bytes())


class LaunchGuardTests(TestCase):
    databases = {'accounts'}

    def setUp(self):
        self.client.defaults['HTTP_HOST'] = settings.PRODUCTION.host

    def test_public_information_does_not_claim_live_payments_or_legal_certification(self):
        privacy = self.client.get('/politica-de-privacidad/', secure=True)
        terms = self.client.get('/terminos-y-condiciones/', secure=True)
        cookies = self.client.get('/politica-de-cookies/', secure=True)
        self.assertContains(privacy, 'revisión legal pendiente')
        self.assertNotContains(privacy, 'en estricto cumplimiento')
        self.assertContains(terms, 'Los cobros reales están desactivados')
        self.assertNotContains(terms, 'Las transacciones se procesan mediante pasarelas certificadas')
        self.assertContains(cookies, 'litmate_visitor_v1')
        self.assertContains(cookies, 'litmate_reader_sessionid')

    def test_email_activation_flag_requires_an_additional_explicit_authorization(self):
        import contextlib
        import io
        import os
        from iniciar_produccion import main
        args = ['--origin', 'https://litmate.example.test', '--proxy', 'loopback-tls',
                '--accounts-db', str(Path(settings.BASE_DIR) / '.testtmp/not-created/users.sqlite3'),
                '--email-authorized']
        with patch.dict(os.environ, {'LITMATE_EMAIL_AUTHORIZED': '0'}):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    main(args)
        self.assertEqual(caught.exception.code, 2)

    def test_smtp_sender_is_independent_of_login_and_requires_tls(self):
        import os
        from litmate_project.account_settings import apply_account_settings
        from django.core.exceptions import ImproperlyConfigured
        folder = self.enterContext(TemporaryDirectory(dir=Path(settings.BASE_DIR) / '.testtmp'))
        config = {'DATABASES': {'default': {'NAME': str(Path(folder) / 'catalog.sqlite3')}},
                  'INSTALLED_APPS': [], 'MIDDLEWARE': [], 'TEMPLATES': [],
                  'EMAIL_HOST': 'smtp.example.invalid', 'EMAIL_HOST_USER': 'smtp-login',
                  'EMAIL_HOST_PASSWORD': 'synthetic-only', 'EMAIL_USE_TLS': True}
        with patch.dict(os.environ, {'LITMATE_ACCOUNTS_DB': str(Path(folder) / 'accounts.sqlite3'),
                 'LITMATE_READER_EMAIL_ENABLED': '1',
                 'LITMATE_READER_FROM_EMAIL': 'LitMate <reader@litmate.example.test>'}):
            apply_account_settings(config)
        self.assertEqual(config['DEFAULT_FROM_EMAIL'], 'LitMate <reader@litmate.example.test>')
        config['EMAIL_USE_TLS'] = False
        with patch.dict(os.environ, {'LITMATE_ACCOUNTS_DB': str(Path(folder) / 'other.sqlite3'),
                                    'LITMATE_READER_EMAIL_ENABLED': '1'}):
            with self.assertRaises(ImproperlyConfigured):
                apply_account_settings(config)
