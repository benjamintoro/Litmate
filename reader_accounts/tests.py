import concurrent.futures
from contextlib import closing
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.auth.models import AnonymousUser, User
from django.db import connections
from django.http import JsonResponse, StreamingHttpResponse
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from core.models import ConversacionIA, MensajeIA, PerfilUsuario
from suscripciones.models import PlanSuscripcion, SuscripcionUsuario, HistorialPago
from .identity import COOKIE
from .models import UsageBucket, QueryOperation
from .usage import reserve, finish, info, UsageError


def verified_fixture(sub):
    """Recibo sintético exclusivamente de pruebas; no consulta ni simula un cobro real."""
    from django.core import signing
    from .payments import SALT
    reference = 'fixture-receipt-' + str(sub.pk)
    HistorialPago.objects.create(usuario=sub.usuario, suscripcion=sub, plan=sub.plan,
        monto=sub.plan.precio, moneda=sub.plan.moneda, referencia_transaccion=reference, estado='completado')
    sub.id_suscripcion_externa = reference
    sub.metadatos = {'provider_receipt': signing.dumps({'user': sub.usuario_id, 'plan':sub.plan_id,
        'amount':format(sub.plan.precio,'.2f'), 'currency':sub.plan.moneda, 'reference':reference},salt=SALT)}
    sub.save()


def fixture_stream(request):
    return StreamingHttpResponse(['data: {"token":"Respuesta verificada"}\n\n', 'data: [DONE]\n\n'],
                                 content_type='text/event-stream')


@override_settings(SECURE_SSL_REDIRECT=False,LITMATE_AI_REQUESTS_PER_MINUTE=10000)
class ReaderFlowTests(TestCase):
    databases = {'accounts'}

    @classmethod
    def setUpTestData(cls):
        cls.free = PlanSuscripcion.objects.create(nombre='Gratuito', slug='gratis', precio=0,
            limite_consultas_ia_diarias=15, limite_favoritos=20)
        cls.pro = PlanSuscripcion.objects.create(nombre='Lector Pro', slug='lector-pro', precio=4990,
            limite_consultas_ia_diarias=100)
        cls.vip = PlanSuscripcion.objects.create(nombre='Lector VIP', slug='lector-vip', precio=9990,
            limite_consultas_ia_diarias=0)
        cls.user = User.objects.create_user('lectora', email='lectora@example.invalid', password='Seguro-Portal-8Brisa!')
        cls.other = User.objects.create_user('otro', password='Seguro-Portal-8Brisa!')

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client.get('/chat/')

    def query(self, request_id='operation-fixture-0001', message='Dime una trama', client=None):
        response = (client or self.client).post('/chatbot_query/',
            json.dumps({'message': message, 'request_id': request_id}), content_type='application/json')
        if response.streaming:
            response.collected = b''.join(response.streaming_content)
        return response

    def test_guest_first_response_then_blocked_before_model(self):
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query', side_effect=fixture_stream) as engine:
            self.assertEqual(self.query().status_code, 200)
            second = self.query('operation-fixture-0002')
            self.assertEqual(second.status_code, 429)
            self.assertEqual(second.json()['error'], 'guest_limit')
            self.assertIn('no requiere tarjeta', second.json()['response'])
        self.assertEqual(engine.call_count, 1)

    def test_refresh_navigation_other_tab_and_direct_api_share_guest_identity(self):
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query', side_effect=fixture_stream):
            self.query()
        for url in ['/chat/', '/about/', '/post/']:
            self.assertEqual(self.client.get(url).status_code, 200)
        other_tab = Client()
        other_tab.cookies[COOKIE] = self.client.cookies[COOKIE].value
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query') as engine:
            self.assertEqual(self.query('operation-another-tab-001', client=other_tab).status_code, 429)
        engine.assert_not_called()

    def test_transport_retry_replays_without_model_or_second_unit(self):
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query', side_effect=fixture_stream) as engine:
            first, repeat = self.query(), self.query()
        self.assertIn(b'Respuesta verificada', first.collected)
        self.assertIn(b'Respuesta verificada', repeat.collected)
        self.assertEqual(repeat['X-LitMate-Idempotent-Replay'], '1')
        self.assertEqual(engine.call_count, 1)
        self.assertEqual(UsageBucket.objects.get().used, 1)

    def test_same_operation_cannot_be_repurposed_for_another_question(self):
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query', side_effect=fixture_stream):
            self.query()
        self.assertEqual(self.query(message='Otra pregunta diferente').status_code, 409)

    def test_first_direct_post_requires_cookie_before_any_model(self):
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query') as engine:
            response = self.query(client=Client())
        self.assertEqual(response.status_code, 409)
        engine.assert_not_called()

    def test_technical_failure_refunds_but_same_id_does_not_restart_work(self):
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query', return_value=JsonResponse({}, status=503)) as engine:
            self.assertEqual(self.query().status_code, 503)
            self.assertEqual(self.query().status_code, 503)
        self.assertEqual(UsageBucket.objects.get().used, 0)
        self.assertEqual(engine.call_count, 1)

    def test_free_activation_is_post_only_has_no_card_and_cannot_activate_paid(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/cuenta/activar-gratis/').status_code, 405)
        self.assertEqual(self.client.post('/cuenta/activar-gratis/', {'plan': 'lector-pro', 'precio': '0'}).status_code, 404)
        self.assertFalse(SuscripcionUsuario.objects.filter(usuario=self.user).exists())
        response = self.client.post('/cuenta/activar-gratis/', {'plan': 'gratis'})
        self.assertEqual(response['Location'], '/chat/')
        sub = SuscripcionUsuario.objects.get(usuario=self.user)
        self.assertEqual(sub.plan, self.free)
        self.assertFalse(sub.auto_renovar)

    def test_registered_user_must_select_plan_and_limits_use_model_fields(self):
        self.client.force_login(self.user)
        self.assertEqual(self.query().status_code, 403)
        self.client.post('/cuenta/activar-gratis/', {'plan': 'gratis'})
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query', side_effect=fixture_stream):
            self.query('operation-user-query-001')
        data = self.client.get('/api/cuota-ia/').json()['cuota']
        self.assertEqual((data['limite'], data['usadas'], data['restantes']), (15, 1, 14))
        self.assertIn('no-store', self.client.get('/api/cuota-ia/')['Cache-Control'])
        self.client.post('/cuenta/activar-gratis/', {'plan': 'gratis'})
        self.assertEqual(self.client.get('/api/cuota-ia/').json()['cuota']['usadas'], 1)

    def test_registration_login_logout_and_redirect_to_plans(self):
        response = self.client.post('/registro/', {'username': 'nuevalectora', 'email': 'NUEVA@example.invalid',
            'password': 'Brisa-59-Nuevo-Portal!', 'password_confirm': 'Brisa-59-Nuevo-Portal!'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/suscripciones/planes/')
        user = User.objects.get(username='nuevalectora')
        self.assertTrue(user.check_password('Brisa-59-Nuevo-Portal!'))
        self.assertTrue(user.password.startswith('pbkdf2_sha256$'))
        self.assertFalse(user.is_staff)
        self.assertFalse(SuscripcionUsuario.objects.filter(usuario=user).exists())
        self.client.post('/logout/')
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        response = self.client.post('/login/?next=https://attacker.invalid/',
            {'username_or_email': 'nueva@example.invalid', 'password': 'Brisa-59-Nuevo-Portal!'})
        self.assertEqual(response['Location'], '/suscripciones/planes/')

    def test_common_password_is_rejected_and_duplicate_email_does_not_create_user(self):
        for username, email, password in [('nuevo', 'a@example.invalid', '123456789'),
                                           ('nuevo2', 'LECTORA@example.invalid', 'Brisa-59-Nuevo-Portal!')]:
            self.assertEqual(self.client.post('/registro/', {'username': username, 'email': email,
                'password': password, 'password_confirm': password}).status_code, 200)
            self.assertFalse(User.objects.filter(username=username).exists())

    def test_other_users_cannot_read_a_private_conversation(self):
        conv = ConversacionIA.objects.create(usuario=self.other, titulo='privado')
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(f'/cuenta/conversaciones/{conv.pk}/').status_code, 404)

    def test_chilean_day_changes_quota_and_plan_switch_does_not_reset_usage(self):
        SuscripcionUsuario.objects.create(usuario=self.user, plan=self.free)
        first = datetime.datetime(2026, 11, 3, 2, 59, tzinfo=datetime.timezone.utc)
        with patch('reader_accounts.usage.timezone.now', return_value=first):
            op, _ = reserve('u:' + str(self.user.pk), self.user, 'operation-day-boundary1', 'Consulta')
            finish(op.pk, {'response': 'Respuesta'})
            self.assertEqual(info('u:' + str(self.user.pk), self.user)['usadas'], 1)
            SuscripcionUsuario.objects.filter(usuario=self.user).update(plan=self.pro)
            verified_fixture(SuscripcionUsuario.objects.get(usuario=self.user))
            data = info('u:' + str(self.user.pk), self.user)
            self.assertEqual((data['limite'], data['usadas']), (100, 1))
        with patch('reader_accounts.usage.timezone.now', return_value=first + datetime.timedelta(minutes=2)):
            self.assertEqual(info('u:' + str(self.user.pk), self.user)['usadas'], 0)

    def test_pending_operation_duplicate_and_expiry_are_safe(self):
        op, _ = reserve('g:expiry', AnonymousUser(), 'operation-pending-0001', 'consulta')
        with self.assertRaises(UsageError) as error:
            reserve('g:expiry', AnonymousUser(), 'operation-pending-0001', 'consulta')
        self.assertEqual(error.exception.code, 'operation_pending')
        QueryOperation.objects.filter(pk=op.pk).update(expires_at=timezone.now()-datetime.timedelta(seconds=1))
        self.assertEqual(info('g:expiry', AnonymousUser())['usadas'], 0)
        self.assertFalse(finish(op.pk, {'response': 'too late'}))

    def test_plan_page_uses_exact_prices_and_paid_checkout_is_disabled(self):
        self.client.force_login(self.user)
        response = self.client.get('/suscripciones/planes/')
        self.assertContains(response, 'Activar gratis sin tarjeta')
        self.assertContains(response, 'Contratación no disponible', count=2)
        for path in ['/suscripciones/iniciar-pago/', '/suscripciones/webpay/commit/']:
            from .gateway import reader_methods
            self.assertEqual(reader_methods(path), set())
            self.assertEqual(self.client.post(path).status_code, 404)

    def test_csrf_remains_required(self):
        response = Client(enforce_csrf_checks=True).post('/registro/', {'username': 'fake'})
        self.assertEqual(response.status_code, 403)

    def test_authenticated_daily_exhaustion_across_two_sessions_and_logout(self):
        SuscripcionUsuario.objects.create(usuario=self.user, plan=self.free)
        self.client.force_login(self.user)
        UsageBucket.objects.create(actor='u:' + str(self.user.pk), period=timezone.now().astimezone(
            __import__('zoneinfo').ZoneInfo('America/Santiago')).date().isoformat(), used=15)
        second = Client()
        second.force_login(self.user)
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query') as engine:
            self.assertEqual(self.query(client=second).status_code, 429)
        engine.assert_not_called()
        self.client.post('/logout/')
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/api/cuota-ia/').json()['cuota']['usadas'], 15)

    def test_guest_lifetime_does_not_reset_on_new_day_or_cache_clear(self):
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query', side_effect=fixture_stream):
            self.query()
        from django.core.cache import cache
        cache.clear()
        future = timezone.now() + datetime.timedelta(days=2)
        with patch('reader_accounts.usage.timezone.now', return_value=future):
            self.assertEqual(self.client.get('/api/cuota-ia/').json()['cuota']['restantes'], 0)

    def test_expired_subscription_is_not_valid_even_if_state_says_active(self):
        SuscripcionUsuario.objects.create(usuario=self.user, plan=self.pro,
            fecha_fin=timezone.now() - datetime.timedelta(seconds=1))
        with self.assertRaises(UsageError) as error:
            reserve('u:' + str(self.user.pk), self.user, 'operation-expiredplan-1', 'consulta')
        self.assertEqual(error.exception.code, 'plan_required')

    def test_vip_zero_means_unlimited_without_resetting_account(self):
        verified_fixture(SuscripcionUsuario.objects.create(usuario=self.user, plan=self.vip))
        self.assertTrue(info('u:' + str(self.user.pk), self.user)['es_ilimitado'])
        op, _ = reserve('u:' + str(self.user.pk), self.user, 'operation-vip-fixture1', 'consulta')
        finish(op.pk, {'response': 'aceptada'})
        self.assertEqual(info('u:' + str(self.user.pk), self.user)['usadas'], 1)

    def test_browser_cannot_access_another_identity_ready_token(self):
        op, _ = reserve('u:' + str(self.other.pk), AnonymousUser(), 'operation-other-owner1', 'consulta')
        QueryOperation.objects.filter(pk=op.pk).update(stream_token='private-ready-token-fixture')
        self.client.force_login(self.user)
        with patch('reader_accounts.chat.literary_ai_views.chatbot_finalize') as engine:
            response = self.client.post('/chatbot_finalize/', json.dumps({'ready':'private-ready-token-fixture'}),
                                        content_type='application/json')
        self.assertEqual(response.status_code, 404)
        engine.assert_not_called()

    def test_profile_router_never_routes_account_writes_to_catalogue(self):
        from django.db import router
        from core.models import Libro
        self.assertEqual(router.db_for_write(User), 'accounts')
        self.assertEqual(router.db_for_write(ConversacionIA), 'accounts')
        self.assertEqual(router.db_for_read(Libro), 'default')
        self.assertFalse(router.allow_migrate('default', 'auth', model_name='user'))

    def test_conversation_messages_remain_private_and_persistent(self):
        from core.literary_ai import ChatResult
        from core.literary_ai_views import remember
        request = SimpleNamespace(user=self.user, session=self.client.session)
        state = {'owner': 'user:' + str(self.user.pk), 'turns': []}
        result = ChatResult('Una respuesta respaldada.', 'answered', remember=True)
        with override_settings(LITMATE_AUTO_ENRICHMENT=False):
            remember(request, state, 'Una consulta literaria', result, 10,
                     SimpleNamespace(usage={}, provider='fixture', calls=0))
        conv = ConversacionIA.objects.get(usuario=self.user)
        self.assertEqual(MensajeIA.objects.filter(conversacion=conv).count(), 2)
        self.client.force_login(self.user)
        response = self.client.get(f'/cuenta/conversaciones/{conv.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['mensajes']), 2)

    def test_ready_stream_reserves_once_and_finalize_retry_does_not_charge_again(self):
        def progressive(request):
            return StreamingHttpResponse(['data: {"stage":"search"}\n\n',
                'data: {"ready":"ready-fixture-valid-token"}\n\n', 'data: [DONE]\n\n'], content_type='text/event-stream')
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query', side_effect=progressive):
            self.query()
        self.assertEqual(QueryOperation.objects.get().status, 'pending')
        with patch('reader_accounts.chat.literary_ai_views.chatbot_finalize',
                   return_value=JsonResponse({'response': 'Respuesta final', 'status': 'answered', 'books': []})) as finalize:
            payload = json.dumps({'ready': 'ready-fixture-valid-token'})
            first = self.client.post('/chatbot_finalize/', payload, content_type='application/json')
            repeat = self.client.post('/chatbot_finalize/', payload, content_type='application/json')
        self.assertEqual(first.json(), repeat.json())
        self.assertEqual(finalize.call_count, 1)
        self.assertEqual(UsageBucket.objects.get().used, 1)

    def test_bad_visitor_signature_does_not_reuse_or_disclose_another_identity(self):
        self.client.cookies[COOKIE] = 'forged-cookie-signature'
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query') as engine:
            response = self.query()
        self.assertEqual(response.status_code, 409)
        engine.assert_not_called()

    def test_login_limit_ignores_forged_forwarded_headers(self):
        with patch('reader_accounts.auth_limits.rate_increment', return_value=9):
            response = self.client.post('/login/', {'username_or_email': 'lectora', 'password': 'bad'},
                                        HTTP_X_FORWARDED_FOR='203.0.113.22')
        self.assertEqual(response.status_code, 429)

    def test_dpapi_key_reopens_after_process_restart(self):
        from .signing_key import load_key
        import sqlite3
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'private.sqlite3'
            with closing(sqlite3.connect(path)) as db:
                for table in ['auth_user', 'django_session', 'reader_accounts_usagebucket', 'reader_accounts_queryoperation']:
                    db.execute('CREATE TABLE ' + table + '(id INTEGER PRIMARY KEY)')
                db.commit()
            first, second = load_key(path), load_key(path)
            self.assertEqual(first, second)
            self.assertNotIn(first.encode(), path.with_name(path.name + '.signing.dpapi').read_bytes())

    def test_missing_ledger_fails_closed_before_model(self):
        from django.db import OperationalError
        with patch('reader_accounts.chat.reserve', side_effect=OperationalError('private-db-fixture')), patch(
                'reader_accounts.chat.literary_ai_views.chatbot_query') as engine:
            response = self.query()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private-db-fixture', response.json()['response'])
        engine.assert_not_called()

    def test_free_selection_does_not_silently_replace_an_active_paid_contract(self):
        sub = SuscripcionUsuario.objects.create(usuario=self.user, plan=self.pro, id_suscripcion_externa='contract-fixture')
        self.client.force_login(self.user)
        response = self.client.post('/cuenta/activar-gratis/', {'plan':'gratis'})
        self.assertEqual(response.status_code, 409)
        sub.refresh_from_db()
        self.assertEqual(sub.plan_id, self.pro.pk)
        self.assertEqual(sub.id_suscripcion_externa, 'contract-fixture')

    def test_active_paid_flags_without_provider_proof_do_not_grant_quota(self):
        SuscripcionUsuario.objects.create(usuario=self.user, plan=self.pro, estado='activa',
                                         metadatos={'paid':True,'status':'COMPLETED'})
        with self.assertRaises(UsageError) as error:
            info('u:' + str(self.user.pk), self.user)
        self.assertEqual(error.exception.code, 'paid_confirmation_required')

    def test_legacy_duplicate_email_does_not_pick_an_arbitrary_account(self):
        User.objects.filter(pk=self.other.pk).update(email='LECTORA@example.invalid')
        response = self.client.post('/login/', {'username_or_email':'lectora@example.invalid', 'password':'Seguro-Portal-8Brisa!'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        response = self.client.post('/login/', {'username_or_email':'lectora', 'password':'Seguro-Portal-8Brisa!'})
        self.assertEqual(response['Location'], '/suscripciones/planes/')

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True,
                       SECURE_SSL_REDIRECT=True, SECURE_HSTS_SECONDS=3600)
    def test_https_cookies_and_origin_csrf_are_preserved(self):
        client = Client(enforce_csrf_checks=True)
        response = client.get('/login/', secure=True)
        self.assertTrue(response.cookies['csrftoken']['secure'])
        token = client.cookies['csrftoken'].value
        response = client.post('/login/', {'username_or_email':'lectora', 'password':'Seguro-Portal-8Brisa!'},
            secure=True, HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN='https://testserver')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.cookies['litmate_reader_sessionid']['secure'])
        self.assertTrue(response.cookies['litmate_reader_sessionid']['httponly'])
        self.assertEqual(response.cookies['litmate_reader_sessionid']['samesite'], 'Lax')
        self.assertIn('max-age=3600', response['Strict-Transport-Security'])

    def test_private_runtime_can_be_durable_without_changing_demo_workspace_rules(self):
        import iniciar_demo
        with TemporaryDirectory() as temp, patch.object(iniciar_demo, 'ROOT', Path(temp)):
            folder=Path(temp)/'data'/'accounts'/'runtime'
            cfg=SimpleNamespace(LITMATE_ACCOUNTS_ENABLED=True)
            result,_=iniciar_demo.prepare_workspace(folder,cfg)
            self.assertEqual(result,folder)
            self.assertTrue((folder/'demo-owner.json').is_file())
            with self.assertRaises(ValueError):
                iniciar_demo.prepare_workspace(Path(temp)/'data'/'another-folder',cfg)

    def test_two_visitors_on_same_proxy_ip_have_separate_resource_limits(self):
        from core.literary_ai_views import rate_allowed
        requests=[SimpleNamespace(user=AnonymousUser(),META={'REMOTE_ADDR':'127.0.0.1'},reader_actor=actor)
                  for actor in ['g:first-verified-fixture','g:second-verified-fixture']]
        with patch('core.literary_ai_views.rate_increment',return_value=1) as counter:
            self.assertTrue(all(rate_allowed(request) for request in requests))
        self.assertNotEqual(counter.call_args_list[0].args[0],counter.call_args_list[1].args[0])

    def test_retiring_plan_from_sales_does_not_revoke_an_existing_subscription(self):
        SuscripcionUsuario.objects.create(usuario=self.user,plan=self.free)
        PlanSuscripcion.objects.filter(pk=self.free.pk).update(activo=False)
        self.assertEqual(info('u:'+str(self.user.pk),self.user)['limite'],15)

    def test_finalization_storage_failure_rolls_back_history_then_replays_safely(self):
        from django.db import OperationalError
        from dataclasses import asdict
        from core.literary_ai import ChatResult
        from core.literary_ai_views import HISTORY_KEY, persist_turn_records
        import copy
        self.client.force_login(self.user)
        self.client.post('/cuenta/activar-gratis/',{'plan':'gratis'})
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query',side_effect=lambda request:
                   StreamingHttpResponse(['data: {"ready":"transactional-fixture-token"}\n\n','data: [DONE]\n\n'])):
            self.query()
        answer=ChatResult('Respuesta auditada de prueba.','answered',remember=True)
        client=SimpleNamespace(usage={},provider='fixture',calls=0)
        state={'owner':'user:'+str(self.user.pk),'turns':[]}
        body={'response':answer.text,'status':'answered','books':[]}
        def first(request):
            persist_turn_records(request,state,'Dime una trama',answer,10,client)
            request.session[HISTORY_KEY]=copy.deepcopy(state)
            return JsonResponse(body)
        def cached(request):
            request.session[HISTORY_KEY]=copy.deepcopy(state)
            return JsonResponse(body)
        payload=json.dumps({'ready':'transactional-fixture-token'})
        with patch('reader_accounts.chat.literary_ai_views.chatbot_finalize',side_effect=first), patch(
                'reader_accounts.chat.finish',side_effect=OperationalError('fixture storage failure')):
            response=self.client.post('/chatbot_finalize/',payload,content_type='application/json')
        self.assertEqual(response.status_code,409)
        self.assertEqual(MensajeIA.objects.count(),0)
        self.assertEqual(UsageBucket.objects.get().used,1)
        recovered_job={'result':{'result':asdict(answer),'client':vars(client)},'payload':{'message':'Dime una trama'}}
        with patch('reader_accounts.chat.literary_ai_views.chatbot_finalize',side_effect=cached), patch(
                'core.ai_stream_jobs.claim_finalization',return_value=recovered_job):
            response=self.client.post('/chatbot_finalize/',payload,content_type='application/json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(MensajeIA.objects.count(),2)
        self.assertEqual(UsageBucket.objects.get().used,1)
        self.assertEqual(QueryOperation.objects.get().status,'completed')
        self.assertEqual(self.client.post('/chatbot_finalize/',payload,content_type='application/json').status_code,200)
        self.assertEqual(MensajeIA.objects.count(),2)

    def test_client_cannot_turn_off_guarded_finalization(self):
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query',side_effect=fixture_stream) as engine:
            self.query()
        self.assertTrue(engine.call_args.args[0].reader_force_progress)

    def test_promoter_only_creates_new_destination_and_preserves_source(self):
        from scripts.accounts import promote_stage
        from .signing_key import load_key
        import sqlite3,hashlib
        with TemporaryDirectory() as temp:
            root=Path(temp)
            source=root/'.testtmp'/'copy'/'accounts.sqlite3'
            source.parent.mkdir(parents=True)
            with closing(sqlite3.connect(source)) as db:
                for table in ['auth_user','django_session','reader_accounts_usagebucket','reader_accounts_queryoperation']:
                    db.execute('CREATE TABLE '+table+'(id INTEGER PRIMARY KEY)')
                db.execute('INSERT INTO auth_user(id) VALUES (1)')
                db.commit()
            load_key(source)
            original_hash=hashlib.sha256(source.read_bytes()).hexdigest()
            receipt=root/'receipt.json'
            receipt.write_text(json.dumps({'source_read_only':True,'quick_check':'ok',
                'foreign_key_issues':0,'destination_file_sha256':original_hash}),encoding='utf-8')
            destination=root/'data/accounts/users.sqlite3'
            args=['promote_stage','--source',str(source),'--receipt',str(receipt),'--destination',str(destination),
                  '--deployment-authorized']
            with patch.object(promote_stage,'__file__',str(root/'scripts/accounts/promote_stage.py')), patch.object(sys,'argv',args):
                promote_stage.main()
                with self.assertRaises(SystemExit):promote_stage.main()
            self.assertEqual(promote_stage.inventory(source),promote_stage.inventory(destination))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),original_hash)

    def test_resource_limit_precedes_new_ledger_row_but_allows_idempotent_replay(self):
        with patch('reader_accounts.chat.literary_ai_views.chatbot_query',side_effect=fixture_stream):
            self.query()
        with patch('reader_accounts.chat.literary_ai_views.rate_allowed',return_value=False),patch(
                'reader_accounts.chat.literary_ai_views.chatbot_query') as engine:
            self.assertEqual(self.query('operation-resource-spam1').status_code,429)
            self.assertEqual(self.query().status_code,200)
        self.assertEqual(QueryOperation.objects.count(),1)
        engine.assert_not_called()


class ConcurrentUsageTests(TransactionTestCase):
    databases = {'accounts'}

    def test_two_simultaneous_guest_queries_only_reserve_one(self):
        def work(index):
            try:
                reserve('g:concurrent', AnonymousUser(), 'operation-concurrency-' + str(index), 'consulta')
                return 'accepted'
            except UsageError as error:
                return error.code
            finally:
                connections.close_all()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(work, range(2)))
        self.assertEqual(sorted(result), ['accepted', 'guest_limit'])
        self.assertEqual(UsageBucket.objects.get().used, 1)

    def test_new_python_process_reads_account_plan_and_existing_consumption(self):
        free = PlanSuscripcion.objects.create(nombre='Gratuito', slug='gratis', precio=0,
                                             limite_consultas_ia_diarias=15)
        user = User.objects.create_user('persistente', password='Seguro-Persistencia-7!')
        SuscripcionUsuario.objects.create(usuario=user, plan=free)
        operation, _ = reserve('u:' + str(user.pk), user, 'operation-restart-fixture1', 'consulta')
        finish(operation.pk, {'response': 'respuesta'})
        environment = dict(os.environ, LITMATE_ACCOUNTS_DB=str(connections['accounts'].settings_dict['NAME']))
        code = ('import django,json;django.setup();from django.contrib.auth.models import User;'
                'from reader_accounts.usage import info;u=User.objects.get(username="persistente");'
                'print(json.dumps({"password_ok":u.check_password("Seguro-Persistencia-7!"),'
                '"quota":info("u:"+str(u.pk),u)}))')
        result = subprocess.run([sys.executable, '-B', '-c', code], env=environment,
                                capture_output=True, text=True, check=True, timeout=20)
        data = json.loads(result.stdout)
        self.assertTrue(data['password_ok'])
        self.assertEqual((data['quota']['plan'], data['quota']['usadas']), ('Gratuito', 1))

    def test_two_authenticated_requests_compete_for_last_daily_unit(self):
        plan=PlanSuscripcion.objects.create(nombre='Gratuito',slug='gratis',precio=0,limite_consultas_ia_diarias=15)
        user=User.objects.create_user('concurrente')
        SuscripcionUsuario.objects.create(usuario=user,plan=plan)
        actor='u:'+str(user.pk)
        UsageBucket.objects.create(actor=actor,period='2026-10-31',used=14)
        def work(index):
            try:
                reserve(actor,user,'operation-last-unit-'+str(index),'consulta')
                return 'accepted'
            except UsageError as error:
                return error.code
            finally: connections.close_all()
        with patch('reader_accounts.usage.timezone.now',return_value=datetime.datetime(2026,10,31,14,tzinfo=datetime.timezone.utc)):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                result=list(pool.map(work,range(2)))
        self.assertEqual(sorted(result),['accepted','quota_exceeded'])
        self.assertEqual(UsageBucket.objects.get().used,15)
