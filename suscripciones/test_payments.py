"""Los callbacks no pueden activar planes con un estado de la URL."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import HistorialPago, PlanSuscripcion, SuscripcionUsuario
from .services import MercadoPagoService, PayPalService, TransbankService
from .views import _completar_suscripcion_usuario


@override_settings(DEBUG=False, LITMATE_PAYMENT_SANDBOX=False)
class PaymentCallbackSecurityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('comprador', password='test-pass')
        self.plan = PlanSuscripcion.objects.create(
            nombre='Plan de prueba', slug='plan-prueba', precio=9990, periodo='mensual')
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['checkout_plan_id'] = self.plan.id
        session.save()

    def test_callbacks_require_an_authenticated_user(self):
        anon = Client()
        for url in (reverse('suscripciones:mercadopago_callback'),
                    reverse('suscripciones:paypal_callback')):
            with self.subTest(url=url):
                response = anon.get(url, {'payment_id': '123', 'token': 'order'})
                self.assertEqual(response.status_code, 302)
                self.assertIn('/login/', response['Location'])
        response = anon.get(reverse('suscripciones:webpay_commit'), {'token_ws': 'token'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])
        self.assertEqual(HistorialPago.objects.count(), 0)

    def test_mercadopago_does_not_trust_the_query_status(self):
        with patch.object(MercadoPagoService, 'verificar_pago',
                          return_value={'success': False, 'status': 'rejected'}):
            response = self.client.get(reverse('suscripciones:mercadopago_callback'),
                {'payment_id': '123', 'status': 'approved'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('pago-cancelado', response['Location'])
        self.assertEqual(HistorialPago.objects.count(), 0)

    def test_mercadopago_rejects_a_payment_from_another_reference(self):
        with patch.object(MercadoPagoService, 'verificar_pago', return_value={
                'success': True, 'status': 'approved', 'payment_id': '123',
                'transaction_amount': str(self.plan.precio),
                'external_reference': 'MP-999-999-000',
                'raw_data': {'external_reference': 'MP-999-999-000'}}):
            response = self.client.get(reverse('suscripciones:mercadopago_callback'),
                {'payment_id': '123', 'status': 'approved'})
        self.assertIn('pago-cancelado', response['Location'])
        self.assertEqual(HistorialPago.objects.count(), 0)

    def test_mercadopago_activates_a_verified_matching_payment(self):
        reference = f'MP-{self.user.id}-{self.plan.id}-abc'
        with patch.object(MercadoPagoService, 'verificar_pago', return_value={
                'success': True, 'status': 'approved', 'payment_id': '123',
                'transaction_amount': str(self.plan.precio),
                'external_reference': reference,
                'raw_data': {'external_reference': reference}}):
            response = self.client.get(reverse('suscripciones:mercadopago_callback'),
                {'payment_id': '123', 'status': 'approved'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('pago-exitoso', response['Location'])
        self.assertEqual(HistorialPago.objects.count(), 1)
        self.assertEqual(SuscripcionUsuario.objects.get(usuario=self.user).plan, self.plan)

    def test_webpay_rejects_a_mismatched_amount(self):
        with patch.object(TransbankService, 'confirmar_transaccion', return_value={
                'success': True, 'amount': '1', 'authorization_code': 'AUT-1',
                'is_simulated': False}):
            response = self.client.post(reverse('suscripciones:webpay_commit'),
                {'token_ws': 'real-token'})
        self.assertIn('pago-cancelado', response['Location'])
        self.assertEqual(HistorialPago.objects.count(), 0)

    def test_paypal_rejects_an_order_for_another_user(self):
        with patch.object(PayPalService, 'capturar_orden', return_value={
                'success': True, 'status': 'COMPLETED', 'is_simulated': False,
                'raw_data': {'purchase_units': [{'custom_id': 'LITMATE-999-999'}]}}):
            response = self.client.get(reverse('suscripciones:paypal_callback'),
                {'token': 'PP-ORDER-1'})
        self.assertIn('pago-cancelado', response['Location'])
        self.assertEqual(HistorialPago.objects.count(), 0)

    def _set_paypal_expected_amount(self, amount='10.52'):
        session = self.client.session
        session['checkout_amount_usd'] = amount
        session.save()

    def _paypal_order(self, value):
        return {
            'success': True, 'status': 'COMPLETED', 'is_simulated': False,
            'raw_data': {'purchase_units': [{
                'custom_id': f'LITMATE-{self.user.id}-{self.plan.id}',
                'amount': {'currency_code': 'USD', 'value': value},
            }]},
        }

    def test_paypal_rejects_a_mismatched_amount(self):
        self._set_paypal_expected_amount()
        with patch.object(PayPalService, 'capturar_orden',
                          return_value=self._paypal_order('0.01')):
            response = self.client.get(reverse('suscripciones:paypal_callback'),
                {'token': 'PP-ORDER-2'})
        self.assertIn('pago-cancelado', response['Location'])
        self.assertEqual(HistorialPago.objects.count(), 0)

    def test_paypal_activates_a_verified_order_with_the_expected_amount(self):
        self._set_paypal_expected_amount()
        with patch.object(PayPalService, 'capturar_orden',
                          return_value=self._paypal_order('10.52')):
            response = self.client.get(reverse('suscripciones:paypal_callback'),
                {'token': 'PP-ORDER-3'})
        self.assertIn('pago-exitoso', response['Location'])
        self.assertEqual(HistorialPago.objects.count(), 1)

    def _call_complete(self, reference='REF-1'):
        return _completar_suscripcion_usuario(
            self.user, self.plan, 'test', self.plan.precio, reference, {'ok': True})

    def test_completion_is_idempotent_for_the_same_user(self):
        first = self._call_complete()
        second = self._call_complete()
        self.assertEqual(first[0].pk, second[0].pk)
        self.assertEqual(HistorialPago.objects.count(), 1)

    def test_completion_rejects_anonymous_users(self):
        from django.contrib.auth.models import AnonymousUser
        with self.assertRaises(ValueError):
            _completar_suscripcion_usuario(AnonymousUser(), self.plan, 'test',
                                           self.plan.precio, 'REF-ANON')

    def test_simulator_is_not_public_in_production(self):
        response = Client().get(reverse('suscripciones:simulador_gateway'))
        self.assertEqual(response.status_code, 404)


@override_settings(DEBUG=False, LITMATE_PAYMENT_SANDBOX=False)
class PaymentSimulationTests(TestCase):
    def test_mock_tokens_are_rejected_when_sandbox_is_disabled(self):
        self.assertFalse(TransbankService().confirmar_transaccion('TBK_MOCK_123')['success'])
        self.assertFalse(MercadoPagoService().verificar_pago('MP_MOCK_123')['success'])
        self.assertFalse(PayPalService().capturar_orden('PP_ORD_123')['success'])

    @override_settings(DEBUG=True)
    def test_mock_tokens_remain_available_for_development(self):
        self.assertTrue(TransbankService().confirmar_transaccion('TBK_MOCK_123')['success'])
        self.assertTrue(MercadoPagoService().verificar_pago('MP_MOCK_123')['success'])
        self.assertTrue(PayPalService().capturar_orden('PP_ORD_123')['success'])
