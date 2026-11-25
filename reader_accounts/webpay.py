"""Webpay Plus REST en integración, fijado al host oficial sin cobros reales."""
import hashlib
import hmac
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from .checkout_models import SimulatedOrder, WebpayTransaction
from .payment_lifecycle import apply_provider_event
from .simulated_checkout import CheckoutError, subscription
from .locking import reader_lock

# Credenciales públicas de integración publicadas por Transbank.
HOST = 'https://webpay3gint.transbank.cl'
COMMERCE_CODE = '597055555532'
INTEGRATION_KEY = '579B532A7440BB0C9079DED94D31EA1615BACEB56610332264630D42D0A36B1C'
ENDPOINT = HOST + '/rswebpaytransaction/api/webpay/v1.2/transactions'


def enabled():
    return getattr(settings, 'LITMATE_WEBPAY_INTEGRATION_ENABLED', False)


def api(method, *, token='', payload=None):
    if not enabled():
        raise CheckoutError('Webpay de integración está desactivado.')
    if token and not re.fullmatch(r'[A-Za-z0-9_-]{20,128}', token):
        raise CheckoutError('La referencia de Webpay no es válida.')
    url = ENDPOINT + ('/' + token if token else '')
    data = json.dumps(payload or {}).encode('utf8') if method != 'GET' else None
    request = Request(url, data=data, method=method, headers={
        'Tbk-Api-Key-Id': COMMERCE_CODE, 'Tbk-Api-Key-Secret': INTEGRATION_KEY,
        'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read(16384))
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as error:
        raise CheckoutError('Webpay no confirmó la operación. Revisa el mismo pedido antes de reintentar.') from error
    if not isinstance(result, dict):
        raise CheckoutError('Webpay devolvió una respuesta inesperada.')
    return result


def start(user, order_id):
    with reader_lock('u:' + str(user.pk)), transaction.atomic(using='accounts'):
        order = SimulatedOrder.objects.select_for_update().select_related('payment__plan').get(pk=order_id, user=user)
        if order.method != 'webpay' or order.state not in ('pending', 'temporary_error'):
            raise CheckoutError('Este pedido no admite iniciar Webpay.')
        existing = WebpayTransaction.objects.filter(order=order).first()
        if existing:
            return existing
        origin = getattr(settings, 'LITMATE_PUBLIC_ORIGIN', '').rstrip('/')
        parsed = urlsplit(origin)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise CheckoutError('Configura el origen HTTPS de retorno antes de usar Webpay.')
        plan = order.payment.plan
        if not plan or not plan.activo or plan.precio != order.payment.monto:
            raise CheckoutError('El plan cambió. Revisa una nueva contratación.')
        buy_order = 'LM' + order.pk.hex[:24]
        session_id = order.pk.hex
        result = api('POST', payload={'buy_order': buy_order, 'session_id': session_id,
            'amount': int(order.payment.monto), 'return_url': origin + '/suscripciones/webpay/retorno/'})
        # La URL suministrada por el proveedor nunca permite redirigir a otro host.
        address = urlsplit(result.get('url', ''))
        token = result.get('token', '')
        if (address.scheme != 'https' or address.hostname != 'webpay3gint.transbank.cl'
                or address.username or address.password or address.port not in (None, 443)
                or not re.fullmatch(r'[A-Za-z0-9_-]{20,128}', token)):
            raise CheckoutError('Webpay devolvió un destino de pago inesperado.')
        return WebpayTransaction.objects.create(order=order, token=token, buy_order=buy_order, session_id=session_id)


def complete(token, *, aborted=False):
    if not enabled() or not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,128}', token):
        raise CheckoutError('La referencia de retorno no es válida.')
    user_id = WebpayTransaction.objects.values_list('order__user_id', flat=True).get(token=token)
    with reader_lock('u:' + str(user_id)), transaction.atomic(using='accounts'):
        entry = WebpayTransaction.objects.select_for_update().select_related('order__payment__plan').get(token=token)
        order = SimulatedOrder.objects.select_for_update().get(pk=entry.order_id)
        if order.state in ('approved', 'rejected', 'cancelled'):
            return order
        # Consultar primero recupera un commit confirmado cuya respuesta se perdió.
        result = api('GET', token=token)
        if result.get('status') == 'INITIALIZED' and not aborted:
            try:
                result = api('PUT', token=token)
            except CheckoutError:
                result = api('GET', token=token)
        payment = entry.order.payment
        try:
            amount = Decimal(str(result.get('amount')))
        except InvalidOperation as error:
            raise CheckoutError('Webpay devolvió un importe inválido.') from error
        if (not amount.is_finite() or amount != payment.monto or result.get('buy_order') != entry.buy_order
                or result.get('session_id') != entry.session_id):
            raise CheckoutError('La respuesta no corresponde al pedido registrado.')
        status = result.get('status')
        approved = status == 'AUTHORIZED' and type(result.get('response_code')) is int and result['response_code'] == 0
        if status in ('INITIALIZED', 'FAILED') and not aborted and status != 'FAILED':
            raise CheckoutError('La operación sigue pendiente en Webpay. Revisa este pedido nuevamente.')
        if status not in ('AUTHORIZED', 'FAILED', 'REVERSED', 'NULLIFIED', 'PARTIALLY_NULLIFIED', 'INITIALIZED'):
            raise CheckoutError('Webpay todavía no entregó un resultado final reconocible.')
        current = subscription(order.user)
        reference = (current.id_suscripcion_externa or '') if current else ''
        if approved and reference != order.source_reference:
            raise CheckoutError('La cuenta cambió de plan durante el pago. El equipo debe conciliar esta operación de prueba.')
        state = 'confirmed' if approved else ('cancelled' if aborted else 'failed')
        now = timezone.now()
        payload = {'event_id': 'webpay-' + order.pk.hex, 'timestamp': now.timestamp(),
            'payment_id': payment.pk, 'reference': payment.referencia_transaccion,
            'amount': format(payment.monto, '.2f'), 'currency': payment.moneda,
            'state': state, 'user_id': order.user_id, 'plan_id': payment.plan_id, 'period': order.period}
        raw = json.dumps(payload, sort_keys=True).encode()
        secret = hashlib.sha256(signing.Signer(salt='webpay-integration').signature(order.pk.hex).encode()).digest()
        apply_provider_event(raw, hmac.new(secret, raw, hashlib.sha256).hexdigest(),
                             provider=payment.metodo_pago, secret=secret)
        order.state = 'approved' if approved else ('cancelled' if aborted else 'rejected')
        order.attempts += 1
        if approved:
            from .payments import SALT
            sub = subscription(order.user)
            claims = signing.loads(sub.metadatos['provider_receipt'], salt=SALT)
            sub.metadatos = {'simulation_receipt': signing.dumps(claims, salt=SALT + '.simulation'),
                             'simulation_order': str(order.pk), 'integration_provider': 'webpay-plus'}
            sub.save(update_fields=['metadatos'])
            order.activated_at, order.access_until = sub.fecha_inicio, sub.fecha_fin
        order.save(update_fields=['state', 'attempts', 'activated_at', 'access_until'])
        entry.provider_status = status
        entry.response_code = result.get('response_code') if type(result.get('response_code')) is int else None
        entry.authorization_code = str(result.get('authorization_code') or '')[:20]
        entry.save(update_fields=['provider_status', 'response_code', 'authorization_code'])
        return order
