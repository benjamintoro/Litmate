"""Pruebas de contratación ficticia con cuotas y datos sintéticos."""
import datetime
import json
from unittest.mock import patch
from uuid import uuid4
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import PerfilUsuario, ListaLectura, ElementoListaLectura, ConversacionIA, LibroFavorito
from suscripciones.models import PlanSuscripcion, SuscripcionUsuario, HistorialPago
from .checkout_models import SimulatedOrder
from .models import SocialProfile, SocialPost, Follow, UsageBucket, PaymentEvent
from .payments import verified_payment
from . import simulated_checkout as service
from .usage import info, reserve, finish, UsageError


@override_settings(LITMATE_SIMULATED_CHECKOUT_ENABLED=True, LITMATE_CHECKOUT_TEST_SCENARIOS=True,
    LITMATE_COMMUNITY_ENABLED=True, ROOT_URLCONF='litmate_project.production_urls',
    ALLOWED_HOSTS=['testserver'], SECURE_SSL_REDIRECT=False, LITMATE_AI_LOCK_BACKEND='cache')
class CheckoutTests(TestCase):
    databases = {'accounts'}

    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user('checkout-a', 'a@example.invalid', 'Synthetic-Checkout-64-Only!')
        cls.b = User.objects.create_user('checkout-b', 'b@example.invalid', 'Synthetic-Checkout-64-Only!')
        cls.free = PlanSuscripcion.objects.create(nombre='Gratuito', slug='gratis', precio=0,
            limite_consultas_ia_diarias=15, limite_favoritos=20)
        cls.pro = PlanSuscripcion.objects.create(nombre='Lector Pro', slug='lector-pro', precio=4990,
            limite_consultas_ia_diarias=100, limite_favoritos=100)
        cls.vip = PlanSuscripcion.objects.create(nombre='Lector VIP', slug='lector-vip', precio=9990,
            limite_consultas_ia_diarias=0, limite_favoritos=0)
        SuscripcionUsuario.objects.create(usuario=cls.a, plan=cls.free, auto_renovar=False)
        cls.profile = SocialProfile.objects.create(user=cls.a, alias='lector-checkout', display_name='Lector de prueba', published=True)
        cls.post = SocialPost.objects.create(author=cls.profile, body='Publicación conservada', submission_id=uuid4(), visibility='public')
        other = SocialProfile.objects.create(user=cls.b, alias='lector-visitante', published=True)
        Follow.objects.create(follower=other, target=cls.profile)
        reading_list = ListaLectura.objects.create(usuario=cls.a, nombre='Lista conservada')
        cls.reading = ElementoListaLectura.objects.create(lista=reading_list, google_id='kept-book', titulo='Libro conservado',
                                                          nota_personal='Nota privada conservada')
        ConversacionIA.objects.create(usuario=cls.a, titulo='Conversación conservada')

    def setUp(self):
        cache.clear()
        self.client.force_login(self.a)

    def new_order(self, plan=None, **kwargs):
        return service.create_order(self.a, plan or self.pro, method=kwargs.pop('method', 'debit'),
                                     submission_id=kwargs.pop('submission_id', uuid4()), **kwargs)

    def approve(self, plan=None, **kwargs):
        order = self.new_order(plan, **kwargs)
        return service.process_order(self.a, order.pk)

    def path(self, name, *args):
        return reverse(name, args=args)

    def test_all_methods_activate_signed_pro_and_receipts(self):
        for method in dict(SimulatedOrder.METHODS):
            order = self.approve(method=method, renew=method != 'debit')
            self.assertEqual(order.state, 'approved')
            sub = service.subscription(self.a)
            self.assertEqual(sub.plan_id, self.pro.pk)
            self.assertTrue(verified_payment(sub))
            self.assertNotIn('provider_receipt', sub.metadatos)
            self.assertEqual(info('u:' + str(self.a.pk), self.a)['limite'], 100)
            page = self.client.get(self.path('sim_receipt', order.pk))
            self.assertContains(page, 'COMPROBANTE DE OPERACIÓN SIMULADA')
            self.assertContains(page, 'No acredita un pago real')
            self.assertContains(page, order.get_method_display())

    def test_vip_activates_unlimited_quota(self):
        self.approve(self.vip, method='credit')
        quota = info('u:' + str(self.a.pk), self.a)
        self.assertTrue(quota['es_ilimitado'])
        self.assertIsNone(quota['restantes'])
        self.assertEqual(service.subscription(self.a).plan.limite_favoritos, 0)

    def test_quota_consumption_preserved_and_chat_backend_reserves(self):
        actor = 'u:' + str(self.a.pk)
        period = timezone.localdate().isoformat()
        UsageBucket.objects.create(actor=actor, period=period, used=15)
        with self.assertRaises(UsageError):
            reserve(actor, self.a, 'before-upgrade-00001', 'Hola')
        self.approve()
        quota = info(actor, self.a)
        self.assertEqual((quota['usadas'], quota['restantes']), (15, 85))
        operation, replay = reserve(actor, self.a, 'after-upgrade-00001', 'Hola')
        self.assertFalse(replay)
        finish(operation.pk, {'response': 'Hola'})
        self.assertEqual(info(actor, self.a)['usadas'], 16)
        self.assertTrue(reserve(actor, self.a, 'after-upgrade-00001', 'Hola')[1])

    def test_rejected_and_cancelled_preserve_current_plan(self):
        rejected = self.new_order(scenario='rejected')
        self.assertEqual(service.process_order(self.a, rejected.pk).state, 'rejected')
        cancelled = self.new_order()
        self.assertEqual(service.process_order(self.a, cancelled.pk, cancel=True).state, 'cancelled')
        self.assertEqual(service.subscription(self.a).plan_id, self.free.pk)
        self.assertEqual(HistorialPago.objects.filter(estado='fallido').count(), 2)

    def test_temporary_error_retry_is_consistent(self):
        order = self.new_order(scenario='temporary')
        result = service.process_order(self.a, order.pk)
        self.assertEqual(result.state, 'temporary_error')
        self.assertEqual(service.subscription(self.a).plan_id, self.free.pk)
        result = service.process_order(self.a, order.pk)
        self.assertEqual((result.state, result.attempts), ('approved', 2))
        self.assertEqual(HistorialPago.objects.count(), 1)

    def test_double_prepare_and_confirmation_are_idempotent(self):
        token = uuid4()
        order = self.new_order(submission_id=token)
        self.assertEqual(self.new_order(submission_id=token).pk, order.pk)
        for _ in range(3):
            self.assertEqual(service.process_order(self.a, order.pk).state, 'approved')
        self.assertEqual(HistorialPago.objects.count(), 1)
        self.assertEqual(PaymentEvent.objects.count(), 2)

    def test_same_key_with_other_selection_is_rejected(self):
        token = uuid4()
        self.new_order(submission_id=token)
        with self.assertRaises(service.CheckoutError):
            self.new_order(self.vip, submission_id=token)
        self.assertEqual(HistorialPago.objects.count(), 1)

    def test_second_pending_order_cannot_replace_new_contract(self):
        one, two = self.new_order(), self.new_order(self.vip)
        service.process_order(self.a, one.pk)
        with self.assertRaises(service.CheckoutError):
            service.process_order(self.a, two.pk)
        self.assertEqual(service.subscription(self.a).plan_id, self.pro.pk)

    def test_public_success_get_cannot_activate_pending(self):
        order = self.new_order()
        response = self.client.get(self.path('sim_receipt', order.pk))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(service.subscription(self.a).plan_id, self.free.pk)
        self.assertEqual(self.client.get(self.path('sim_confirm', order.pk)).status_code, 405)

    def test_ownership_receipts_confirmation_and_cancellation(self):
        order = self.new_order()
        self.client.force_login(self.b)
        for name in ('sim_receipt', 'sim_order'):
            self.assertEqual(self.client.get(self.path(name, order.pk)).status_code, 404)
        for name in ('sim_confirm', 'sim_cancel_order'):
            self.assertEqual(self.client.post(self.path(name, order.pk), {'confirm': 'yes'} if 'cancel' in name else {}).status_code, 404)
        self.assertEqual(service.subscription(self.a).plan_id, self.free.pk)

    def test_tampered_fields_and_csrf_rejected(self):
        order = self.new_order()
        for data in ({'price': '1'}, {'state': 'approved'}, {'user': self.b.pk}, {'plan': self.vip.pk}, {'at':'2030-01-01'}):
            self.assertEqual(self.client.post(self.path('sim_confirm', order.pk), data).status_code, 409)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.a)
        self.assertEqual(client.post(self.path('sim_confirm', order.pk)).status_code, 403)

    def test_plan_repricing_rejects_old_order(self):
        order = self.new_order()
        self.pro.precio = 6000
        self.pro.save()
        with self.assertRaises(service.CheckoutError):
            service.process_order(self.a, order.pk)
        self.assertEqual(service.subscription(self.a).plan_id, self.free.pk)

    def test_paid_transitions_free_downgrade_preserve_all_data(self):
        for plan in (self.pro, self.vip, self.pro):
            self.approve(plan)
            self.assertEqual(service.subscription(self.a).plan_id, plan.pk)
        service.switch_to_free(self.a)
        self.assertEqual(service.subscription(self.a).plan_id, self.free.pk)
        self.reading.refresh_from_db()
        self.assertEqual(self.reading.nota_personal, 'Nota privada conservada')
        self.assertTrue(SocialPost.objects.filter(pk=self.post.pk).exists())
        self.assertEqual(Follow.objects.count(), 1)
        self.assertEqual(ConversacionIA.objects.count(), 1)

    def test_favorite_limits_change_without_deleting_saved_books(self):
        LibroFavorito.objects.bulk_create([LibroFavorito(usuario=self.a, google_id=str(n), titulo='Libro '+str(n), autores='Autora') for n in range(20)])
        data = json.dumps({'google_id':'extra', 'titulo':'Otro libro', 'autores':'Autora'})
        self.assertEqual(self.client.post('/favoritos/agregar/',data,content_type='application/json').status_code, 403)
        self.approve()
        self.assertEqual(self.client.post('/favoritos/agregar/',data,content_type='application/json').status_code, 200)
        service.switch_to_free(self.a)
        self.assertEqual(LibroFavorito.objects.filter(usuario=self.a).count(), 21)

    def test_same_active_plan_requires_explicit_renewal(self):
        self.approve()
        until = service.subscription(self.a).fecha_fin
        with self.assertRaises(service.CheckoutError):
            self.new_order()
        self.approve(renew=True)
        self.assertGreater(service.subscription(self.a).fecha_fin, until + datetime.timedelta(days=27))
        self.assertEqual(SimulatedOrder.objects.order_by('-created_at').first().kind, 'manual_renewal')

    def test_cancel_preserves_access_and_stops_scheduled_renewal(self):
        self.approve()
        end = service.subscription(self.a).fecha_fin
        first = service.cancel_subscription(self.a).fecha_cancelacion
        self.assertEqual(service.cancel_subscription(self.a).fecha_cancelacion, first)
        self.assertTrue(service.subscription(self.a).es_valida)
        self.assertIsNone(service.renew_due(self.a, at=end + datetime.timedelta(seconds=1)))

    def test_due_renewal_clock_and_duplicate_are_controlled(self):
        self.approve()
        end = service.subscription(self.a).fecha_fin
        at = end + datetime.timedelta(seconds=1)
        result = service.renew_due(self.a, at=at)
        self.assertEqual((result.state, result.kind), ('approved', 'scheduled_renewal'))
        self.assertGreater(service.subscription(self.a).fecha_fin, end + datetime.timedelta(days=27))
        self.assertIsNone(service.renew_due(self.a, at=at))
        self.assertEqual(SimulatedOrder.objects.count(), 2)

    def test_due_rejection_preserves_expired_contract(self):
        self.approve()
        end = service.subscription(self.a).fecha_fin
        at = end + datetime.timedelta(seconds=1)
        self.assertEqual(service.renew_due(self.a, at=at, scenario='rejected').state, 'rejected')
        self.assertEqual(service.subscription(self.a).fecha_fin, end)
        with patch('reader_accounts.usage.timezone.now', return_value=at):
            with self.assertRaises(UsageError):
                info('u:'+str(self.a.pk), self.a)

    def test_explicit_flag_and_scenario_protection(self):
        order = self.approve()
        with override_settings(LITMATE_SIMULATED_CHECKOUT_ENABLED=False):
            self.assertFalse(verified_payment(service.subscription(self.a)))
            self.assertEqual(self.client.get(self.path('sim_checkout', self.pro.slug)).status_code, 404)
            self.assertContains(self.client.get('/suscripciones/planes/'), 'Contratación no disponible')
        with override_settings(LITMATE_CHECKOUT_TEST_SCENARIOS=False):
            self.assertNotContains(self.client.get(self.path('sim_methods', self.vip.slug)), 'name="scenario"')
            with self.assertRaises(service.CheckoutError):
                self.new_order(self.vip, scenario='rejected')

    def test_plan_choice_resumes_after_login(self):
        self.client.logout()
        response = self.client.get(self.path('sim_checkout', self.pro.slug))
        self.assertEqual(response.status_code, 302)
        response = self.client.post('/login/', {'username_or_email': self.a.username, 'password':'Synthetic-Checkout-64-Only!'})
        self.assertRedirects(response, self.path('sim_checkout', self.pro.slug))

    def test_private_subscription_not_visible_in_public_profile(self):
        self.approve()
        self.client.force_login(self.b)
        response = self.client.get(reverse('social_public_profile', args=[self.profile.public_id]))
        for text in ('4990', 'Comprobante', 'Mi suscripción', 'Historial de operaciones', '100 consultas'):
            self.assertNotContains(response, text)

    def test_interruption_rolls_back_then_retry_activates_once(self):
        order = self.new_order()
        with patch('reader_accounts.simulated_checkout.apply_provider_event', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                service.process_order(self.a, order.pk)
        order.refresh_from_db()
        self.assertEqual((order.state, order.attempts), ('pending', 0))
        self.assertEqual(service.process_order(self.a, order.pk).state, 'approved')

    def test_normal_http_flow_and_history(self):
        response = self.client.post(self.path('sim_methods', self.pro.slug),
            {'method':'debit', 'submission_id':str(uuid4())})
        self.assertEqual(response.status_code, 302)
        order = SimulatedOrder.objects.get()
        self.assertContains(self.client.get(response.url), 'Confirmar contratación simulada')
        response = self.client.post(self.path('sim_confirm', order.pk))
        self.assertRedirects(response, self.path('sim_receipt', order.pk))
        self.assertContains(self.client.get('/suscripciones/mi-suscripcion/'), 'Lector Pro')
        self.assertContains(self.client.get('/cuenta/pagos/'), 'Débito simulado')
        self.assertEqual(self.client.post(self.path('sim_cancel_order', order.pk), {'confirm':'yes'}).status_code, 409)
        self.assertEqual(self.client.get('/api/cuota-ia/').json()['cuota']['limite'], 100)
        self.assertEqual(self.client.get('/perfil/').status_code, 200)

    def test_corrupt_simulation_reference_fails_closed(self):
        self.approve()
        sub = service.subscription(self.a)
        sub.metadatos['simulation_order'] = 'invalid-reference'
        sub.save()
        self.assertFalse(verified_payment(sub))

    def test_plan_choice_resumes_after_registration(self):
        self.client.logout()
        self.client.get(self.path('sim_checkout', self.vip.slug))
        response = self.client.post('/registro/', {
            'username': 'new-checkout-user', 'email': 'new-checkout@example.invalid',
            'password': 'Synthetic-New-Checkout-64-Only!', 'password_confirm': 'Synthetic-New-Checkout-64-Only!',
        })
        self.assertRedirects(response, self.path('sim_checkout', self.vip.slug))
