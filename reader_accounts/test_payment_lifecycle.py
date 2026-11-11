"""Contrato interno de pagos: datos sintéticos, ninguna pasarela externa."""
import datetime
import hashlib
import hmac
import json
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from suscripciones.models import PlanSuscripcion, HistorialPago, SuscripcionUsuario
from .payment_lifecycle import prepare_checkout, apply_provider_event, cancel_local_renewal, period_end, PaymentUnavailable
from .payments import verified_payment
from .models import PaymentEvent


class PaymentLifecycleTests(TestCase):
    databases = {'accounts'}
    secret = b'synthetic-fixture-secret-not-a-provider-credential'

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('payment-fixture')
        cls.plan = PlanSuscripcion.objects.create(nombre='Pro', slug='pro', precio=4990,
            moneda='CLP', periodo='mensual', limite_consultas_ia_diarias=100)

    def pending(self):
        return prepare_checkout(self.user, self.plan, provider='fixture', adapter_authorized=True)

    def event(self, payment, *, event_id='evt-fixture-1', state='confirmed', **changes):
        data = {'event_id': event_id, 'timestamp': timezone.now().timestamp(), 'payment_id': payment.pk,
                'reference': payment.referencia_transaccion, 'amount': '4990.00', 'currency': 'CLP', 'state': state,
                'user_id': payment.usuario_id, 'plan_id': payment.plan_id, 'period': payment.plan.periodo, **changes}
        raw = json.dumps(data, sort_keys=True).encode()
        return raw, hmac.new(self.secret, raw, hashlib.sha256).hexdigest()

    def apply(self, event):
        return apply_provider_event(*event, provider='fixture', secret=self.secret)

    def test_checkout_is_disabled_by_default_and_pending_has_no_benefits(self):
        with self.assertRaises(PaymentUnavailable):
            prepare_checkout(self.user, self.plan, provider='fixture')
        payment = self.pending()
        self.assertEqual(payment.estado, 'pendiente')
        self.assertFalse(SuscripcionUsuario.objects.filter(usuario=self.user).exists())

    def test_confirmed_payment_is_verified_and_duplicate_event_is_idempotent(self):
        payment = self.pending()
        event = self.event(payment)
        self.apply(event)
        self.apply(event)
        self.assertTrue(verified_payment(SuscripcionUsuario.objects.get(usuario=self.user)))
        self.assertEqual(PaymentEvent.objects.count(), 1)
        self.assertEqual(HistorialPago.objects.count(), 1)

    def test_forged_signature_cannot_activate(self):
        raw, signature = self.event(self.pending())
        with self.assertRaises(ValueError):
            self.apply((raw, '0' * 64))
        self.assertFalse(SuscripcionUsuario.objects.exists())

    def test_verified_envelope_cannot_change_owner_plan_or_billing_period(self):
        payment = self.pending()
        for changes in ({'user_id': self.user.pk + 1}, {'plan_id': self.plan.pk + 1},
                        {'period': 'anual'}):
            with self.assertRaises(ValueError):
                self.apply(self.event(payment, **changes))
        self.assertFalse(SuscripcionUsuario.objects.exists())

    def test_verified_envelope_requires_explicit_identity_and_period(self):
        payment = self.pending()
        for changes in ({'user_id': None}, {'plan_id': None}, {'period': None}):
            with self.assertRaises(ValueError):
                self.apply(self.event(payment, **changes))
        self.assertFalse(SuscripcionUsuario.objects.exists())

    def test_amount_currency_provider_reference_and_stale_events_are_rejected(self):
        payment = self.pending()
        for changes in ({'amount': '1'}, {'currency': 'USD'}, {'reference': 'forged'},
                        {'timestamp': timezone.now().timestamp() - 600}, {'timestamp': float('nan')}):
            with self.assertRaises(ValueError):
                self.apply(self.event(payment, **changes))
        event = self.event(payment)
        with self.assertRaises(ValueError):
            apply_provider_event(*event, provider='wrong', secret=self.secret)
        self.assertFalse(PaymentEvent.objects.exists())

    def test_same_event_id_with_changed_content_and_second_confirmation_are_rejected(self):
        payment = self.pending()
        self.apply(self.event(payment))
        for event in (self.event(payment, state='failed'), self.event(payment, event_id='different')):
            with self.assertRaises(ValueError):
                self.apply(event)
        self.assertEqual(PaymentEvent.objects.count(), 1)

    def test_failed_and_cancelled_payments_do_not_activate_subscription(self):
        for state in ('failed', 'cancelled'):
            payment = self.pending()
            self.apply(self.event(payment, event_id=state, state=state))
            payment.refresh_from_db()
            self.assertEqual(payment.estado, 'fallido')
        self.assertFalse(SuscripcionUsuario.objects.exists())

    def test_renewal_extends_valid_period_and_failure_preserves_current_plan(self):
        self.apply(self.event(self.pending()))
        sub = SuscripcionUsuario.objects.get(usuario=self.user)
        first_end = sub.fecha_fin
        self.apply(self.event(self.pending(), event_id='evt-renewal'))
        sub.refresh_from_db()
        self.assertGreater(sub.fecha_fin, first_end + datetime.timedelta(days=27))
        self.apply(self.event(self.pending(), event_id='evt-failed-renewal', state='failed'))
        sub.refresh_from_db()
        self.assertTrue(verified_payment(sub))
        self.assertTrue(sub.es_valida)

    def test_cancel_local_renewal_preserves_already_paid_access(self):
        self.apply(self.event(self.pending()))
        sub = cancel_local_renewal(self.user)
        self.assertFalse(sub.auto_renovar)
        self.assertIsNotNone(sub.fecha_cancelacion)
        self.assertTrue(sub.es_valida)
        self.assertTrue(verified_payment(sub))

    def test_end_of_month_and_leap_year_periods(self):
        start = datetime.datetime(2028, 1, 31, tzinfo=datetime.timezone.utc)
        self.assertEqual(period_end(start, 'mensual').date(), datetime.date(2028, 2, 29))
        self.assertEqual(period_end(start.replace(month=2, day=29), 'anual').date(), datetime.date(2029, 2, 28))

    def test_expired_paid_subscription_cannot_keep_paid_entitlement(self):
        from .usage import entitlement, UsageError
        PlanSuscripcion.objects.create(nombre='Gratuito', slug='gratis', precio=0,
                                        moneda='CLP', limite_consultas_ia_diarias=15)
        self.apply(self.event(self.pending()))
        sub = SuscripcionUsuario.objects.get(usuario=self.user)
        sub.fecha_fin = timezone.now() - datetime.timedelta(seconds=1)
        sub.save(update_fields=['fecha_fin'])
        # Se conserva el flujo actual: elegir Gratuito; no renovar ni dar VIP
        # automáticamente sólo porque el pago anterior figure completado.
        with self.assertRaises(UsageError) as caught:
            entitlement(self.user)
        self.assertEqual(caught.exception.code, 'plan_required')

    def test_plan_change_requires_new_verified_payment(self):
        vip = PlanSuscripcion.objects.create(nombre='VIP', slug='vip', precio=9990,
            moneda='CLP', periodo='mensual', limite_consultas_ia_diarias=0)
        self.apply(self.event(self.pending()))
        old = SuscripcionUsuario.objects.get(usuario=self.user)
        payment = prepare_checkout(self.user, vip, provider='fixture', adapter_authorized=True)
        self.assertEqual(SuscripcionUsuario.objects.get(pk=old.pk).plan_id, self.plan.pk)
        self.apply(self.event(payment, event_id='evt-upgrade', amount='9990.00'))
        old.refresh_from_db()
        self.assertEqual(old.plan_id, vip.pk)
        self.assertTrue(verified_payment(old))

    def test_interruption_rolls_back_activation_and_authenticated_retry_recovers(self):
        payment = self.pending()
        event = self.event(payment)
        with patch.object(PaymentEvent.objects, 'create', side_effect=RuntimeError('synthetic interruption')):
            with self.assertRaises(RuntimeError):
                self.apply(event)
        payment.refresh_from_db()
        self.assertEqual(payment.estado, 'pendiente')
        self.assertFalse(SuscripcionUsuario.objects.filter(usuario=self.user).exists())
        self.apply(event)
        self.assertTrue(verified_payment(SuscripcionUsuario.objects.get(usuario=self.user)))

    def test_applied_event_retry_remains_idempotent_after_timestamp_window(self):
        payment = self.pending()
        event = self.event(payment)
        self.apply(event)
        with patch('reader_accounts.payment_lifecycle.timezone.now',
                   return_value=timezone.now() + datetime.timedelta(minutes=10)):
            self.apply(event)
        self.assertEqual(PaymentEvent.objects.count(), 1)

    def test_paid_public_urls_remain_unavailable(self):
        self.client.force_login(self.user)
        for path in ('/suscripciones/iniciar-pago/', '/suscripciones/mercadopago/callback/',
                     '/suscripciones/paypal/callback/', '/suscripciones/webpay/commit/'):
            self.assertEqual(self.client.post(path, {}, secure=True,
                                             HTTP_HOST=settings.ALLOWED_HOSTS[0]).status_code, 404)
