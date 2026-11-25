"""Aceptación de reseñas y del adaptador Webpay con cuentas sintéticas."""
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from . import simulated_checkout, webpay
from .checkout_models import WebpayTransaction
from .content_policy import validate_reader_text
from .models import SocialPost, SocialProfile, SocialReport
from .payments import verified_payment
from .social_forms import PostForm
from .test_checkout import CheckoutTests
from .usage import info


@override_settings(LITMATE_COMMUNITY_ENABLED=True, ROOT_URLCONF='litmate_project.production_urls',
                   ALLOWED_HOSTS=['testserver'], SECURE_SSL_REDIRECT=False, LITMATE_AI_LOCK_BACKEND='cache')
class ReviewTests(TestCase):
    databases = {'accounts'}

    def setUp(self):
        cache.clear()
        self.a = User.objects.create_user('review-a', password='Synthetic-Review-74!')
        self.b = User.objects.create_user('review-b', password='Synthetic-Review-74!')
        self.profile = SocialProfile.objects.create(user=self.a, published=True, alias='review-a')
        self.client.force_login(self.a)
        self.book = SimpleNamespace(pk=41, titulo='Frankenstein', autor=SimpleNamespace(nombre='Mary Shelley'))
        self.lookup = patch('reader_accounts.social_forms.PostForm.clean_catalogue_id', return_value=41)
        self.lookup.start()
        self.addCleanup(self.lookup.stop)

    def data(self, **extra):
        return {'submission_id': str(uuid4()), 'catalogue_id': 41, 'rating': '4',
                'body': 'Una novela que invita a pensar en la responsabilidad.', 'visibility': 'public', **extra}

    def test_rating_required_and_bounded(self):
        for value in ('', '0', '6', '3.5', 'texto'):
            form = PostForm(self.data(rating=value), profile=self.profile)
            self.assertFalse(form.is_valid())
        for number in range(1, 6):
            self.assertTrue(PostForm(self.data(rating=str(number)), profile=self.profile).is_valid())

    def test_book_required_and_missing_catalogue_rejected(self):
        self.lookup.stop()
        with patch('core.models.Libro.objects') as books:
            books.select_related.return_value.filter.return_value.first.return_value = None
            for value in ('', '999999'):
                self.assertFalse(PostForm(self.data(catalogue_id=value), profile=self.profile).is_valid())
        self.lookup.start()

    def test_offensive_text_and_simple_evasion_blocked(self):
        for body in ('Esta mierda', 'Eres un ctm', 'P U T O', 'p.u.t.a', 'pUt0'):
            with self.subTest(body=body):
                self.assertFalse(PostForm(self.data(body=body), profile=self.profile).is_valid())
        validate_reader_text('La diputada analiza una disputa en la novela.')

    def test_create_edit_idempotent_and_owner_enforced(self):
        data = self.data()
        route = reverse('social_new_post')
        self.assertEqual(self.client.post(route, data).status_code, 302)
        self.assertEqual(self.client.post(route, data).status_code, 302)
        post = SocialPost.objects.get(author=self.profile)
        self.assertTrue(post.is_review)
        self.assertEqual(post.rating, 4)
        self.client.force_login(self.b)
        self.assertEqual(self.client.post(reverse('social_edit_post', args=[post.pk]), data).status_code, 404)
        self.client.force_login(self.a)
        self.assertEqual(self.client.post(reverse('social_edit_post', args=[post.pk]), self.data(rating='5')).status_code, 302)
        post.refresh_from_db()
        self.assertEqual(post.rating, 5)

    def test_private_review_hidden_and_reports_preserved(self):
        self.client.post(reverse('social_new_post'), self.data(visibility='private'))
        post = SocialPost.objects.get(author=self.profile)
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(reverse('social_post', args=[post.pk])).status_code, 404)
        post.visibility = 'public'
        post.save()
        response = self.client.post(reverse('social_report_post', args=[post.pk]), {'reason': 'Revisar contenido'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SocialReport.objects.get().reporter, self.b)

    def test_sql_constraints_and_multiple_empty_aliases(self):
        SocialProfile.objects.create(user=self.b)
        for fields in ({'rating': 6}, {'rating': 3, 'catalogue_id': None}):
            with self.assertRaises(IntegrityError), transaction.atomic(using='accounts'):
                SocialPost.objects.create(author=self.profile, submission_id=uuid4(), body='Reseña',
                                          is_review=True, **fields)

    def test_archived_content_not_shown_as_review(self):
        post = SocialPost.objects.create(author=self.profile, submission_id=uuid4(), body='ARCHIVO ANTERIOR', visibility='public')
        response = self.client.get(reverse('social_feed'))
        self.assertContains(response, 'Reseñas LitMate')
        self.assertNotContains(response, 'ARCHIVO ANTERIOR')
        self.assertEqual(self.client.get(reverse('social_post', args=[post.pk])).status_code, 200)
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(reverse('social_post', args=[post.pk])).status_code, 404)


@override_settings(LITMATE_SIMULATED_CHECKOUT_ENABLED=True, LITMATE_WEBPAY_INTEGRATION_ENABLED=True,
    LITMATE_PUBLIC_ORIGIN='https://litmate.example.test', LITMATE_COMMUNITY_ENABLED=True,
    ROOT_URLCONF='litmate_project.production_urls', ALLOWED_HOSTS=['testserver'],
    SECURE_SSL_REDIRECT=False, LITMATE_AI_LOCK_BACKEND='cache')
class WebpayTests(TestCase):
    databases = {'accounts'}

    @classmethod
    def setUpTestData(cls):
        CheckoutTests.setUpTestData.__func__(cls)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.a)
        self.order = simulated_checkout.create_order(self.a, self.pro, method='webpay', submission_id=uuid4())
        self.entry = WebpayTransaction.objects.create(order=self.order, token='f' * 64,
            buy_order='LM' + self.order.pk.hex[:24], session_id=self.order.pk.hex)

    def result(self, **extra):
        return {'buy_order': self.entry.buy_order, 'session_id': self.entry.session_id,
                'amount': 4990, 'status': 'AUTHORIZED', 'response_code': 0,
                'authorization_code': '123456', **extra}

    def test_approval_activates_quota_and_idempotent_receipt(self):
        with patch.object(webpay, 'api', return_value=self.result()) as api:
            result = webpay.complete(self.entry.token)
            self.assertEqual(result.state, 'approved')
            webpay.complete(self.entry.token)
            self.assertEqual(api.call_count, 1)
        self.assertTrue(verified_payment(simulated_checkout.subscription(self.a)))
        self.assertEqual(info('u:' + str(self.a.pk), self.a)['limite'], 100)

    def test_decline_and_abort_preserve_free_plan(self):
        with patch.object(webpay, 'api', return_value=self.result(status='FAILED', response_code=-1)):
            result = webpay.complete(self.entry.token)
        self.assertEqual(result.state, 'rejected')
        self.assertEqual(simulated_checkout.subscription(self.a).plan_id, self.free.pk)

    def test_abort_uninitialized_records_cancellation(self):
        with patch.object(webpay, 'api', return_value=self.result(status='INITIALIZED', response_code=None)):
            result = webpay.complete(self.entry.token, aborted=True)
        self.assertEqual(result.state, 'cancelled')

    def test_tampered_amount_and_identity_rejected(self):
        for changes in ({'amount': 1}, {'buy_order': 'other'}, {'session_id': 'other'}, {'amount': 'NaN'}):
            with patch.object(webpay, 'api', return_value=self.result(**changes)):
                with self.assertRaises(webpay.CheckoutError):
                    webpay.complete(self.entry.token)
        self.order.refresh_from_db()
        self.assertEqual(self.order.state, 'pending')

    def test_timeout_recovery_uses_provider_status(self):
        with patch.object(webpay, 'api', side_effect=[self.result(status='INITIALIZED'),
                         webpay.CheckoutError('Temporal'), self.result()]):
            self.assertEqual(webpay.complete(self.entry.token).state, 'approved')

    def test_direct_simulation_cannot_approve_webpay(self):
        with self.assertRaises(webpay.CheckoutError):
            simulated_checkout.process_order(self.a, self.order.pk)

    def test_callback_works_without_session_and_receipt_is_private(self):
        self.client.logout()
        with patch.object(webpay, 'api', return_value=self.result()):
            response = self.client.post(reverse('webpay_return'), {'token_ws': self.entry.token})
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(response.url).status_code, 404)

    def test_return_rejects_duplicated_and_unexpected_parameters(self):
        with patch.object(webpay, 'api') as api:
            self.assertEqual(self.client.post(reverse('webpay_return'), {'token_ws': self.entry.token, 'state': 'approved'}).status_code, 400)
            self.assertEqual(self.client.post(reverse('webpay_return'), {'token_ws': [self.entry.token, 'bad']}).status_code, 400)
            api.assert_not_called()

    def test_legacy_paid_record_does_not_claim_verified_benefits(self):
        sub = simulated_checkout.subscription(self.a)
        sub.plan = self.pro
        sub.metadatos = {}
        sub.save()
        response = self.client.get(reverse('sim_subscription'))
        self.assertContains(response, 'Pendiente de verificación del pago')
