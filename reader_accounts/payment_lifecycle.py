"""Núcleo de contratación sin rutas públicas ni conexión a pasarelas.

El sobre HMAC es un contrato INTERNO para un futuro adaptador autorizado, no
implementa ni reemplaza la firma propia de Transbank/MercadoPago/PayPal.
Se prueba sólo con eventos sintéticos. No hay adaptador habilitado en producción.
"""
import calendar
import hashlib
import hmac
import json
import math
import re
import secrets
from decimal import Decimal, InvalidOperation
from django.core import signing
from django.db import transaction
from django.utils import timezone
from suscripciones.models import HistorialPago, SuscripcionUsuario
from .models import PaymentEvent
from .payments import SALT


class PaymentUnavailable(ValueError):
    pass


def prepare_checkout(user, plan, *, provider, adapter_authorized=False, idempotency_key=None):
    if not adapter_authorized:
        raise PaymentUnavailable('La contratación de pago sigue deshabilitada.')
    if not plan.activo or plan.precio <= 0 or not re.fullmatch(r'[a-z0-9_-]{1,50}', provider):
        raise ValueError('Plan o proveedor no válido.')
    if idempotency_key is not None and (not isinstance(idempotency_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', idempotency_key)):
        raise ValueError('Identificador de operación no válido.')
    with transaction.atomic(using='accounts'):
        event_id = None
        if idempotency_key is not None:
            event_id = 'checkout-' + hashlib.sha256((str(user.pk)+':'+idempotency_key).encode()).hexdigest()
            digest = hashlib.sha256(json.dumps([user.pk, plan.pk, format(plan.precio, '.2f'), plan.moneda,
                                               plan.periodo], separators=(',', ':')).encode()).hexdigest()
            previous = PaymentEvent.objects.filter(provider=provider, event_id=event_id).first()
            if previous:
                if not hmac.compare_digest(previous.digest, digest):
                    raise ValueError('El identificador corresponde a otra contratación.')
                return previous.payment
        payment = HistorialPago.objects.create(usuario=user, plan=plan, monto=plan.precio,
            moneda=plan.moneda, metodo_pago=provider, estado='pendiente',
            referencia_transaccion='lm-' + secrets.token_hex(20))
        if event_id:
            PaymentEvent.objects.create(provider=provider, event_id=event_id, digest=digest, payment=payment)
        return payment


def period_end(start, period):
    months = {'mensual': 1, 'semestral': 6, 'anual': 12}.get(period)
    if period == 'vitalicio':
        return None
    if months is None:
        raise ValueError('Periodicidad no reconocida.')
    month = start.month - 1 + months
    year = start.year + month // 12
    month = month % 12 + 1
    return start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))


def apply_provider_event(raw, signature, *, provider, secret, at=None):
    """Sólo debe invocarlo un adaptador tras verificar la respuesta del proveedor."""
    if not isinstance(secret, bytes) or len(secret) < 32 or not isinstance(raw, bytes) or len(raw) > 8192:
        raise ValueError('Sobre de confirmación no válido.')
    expected = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(expected, signature):
        raise ValueError('Confirmación no autenticada.')
    data = json.loads(raw)
    if not isinstance(data, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', str(data.get('event_id', ''))):
        raise ValueError('Evento no válido.')
    digest = hashlib.sha256(raw).hexdigest()
    with transaction.atomic(using='accounts'):
        previous = PaymentEvent.objects.filter(provider=provider, event_id=data['event_id']).first()
        if previous:
            if not hmac.compare_digest(previous.digest, digest):
                raise ValueError('El evento repetido tiene otro contenido.')
            return previous.payment
        # La repetición autenticada ya aplicada es idempotente incluso después
        # de vencer esta ventana. Un evento nuevo sí debe ser reciente.
        stamp = data.get('timestamp')
        if not isinstance(stamp, (float, int)) or not math.isfinite(stamp) or abs((at or timezone.now()).timestamp() - stamp) > 300:
            raise ValueError('Confirmación caducada.')
        payment = HistorialPago.objects.select_related('plan').get(pk=data.get('payment_id'))
        if payment.metodo_pago != provider or payment.referencia_transaccion != data.get('reference'):
            raise ValueError('Referencia incorrecta.')
        if (type(data.get('user_id')) is not int or data['user_id'] != payment.usuario_id
                or type(data.get('plan_id')) is not int or data['plan_id'] != payment.plan_id
                or not payment.plan or data.get('period') != payment.plan.periodo):
            raise ValueError('Identidad o periodicidad de contratación incorrectas.')
        try:
            amount = Decimal(str(data.get('amount')))
        except InvalidOperation as error:
            raise ValueError('Importe incorrecto.') from error
        if not amount.is_finite() or amount != payment.monto or data.get('currency') != payment.moneda:
            raise ValueError('Importe o moneda incorrectos.')
        state = data.get('state')
        if state not in ('confirmed', 'failed', 'cancelled') or payment.estado != 'pendiente':
            raise ValueError('Transición de pago no válida.')
        if state != 'confirmed':
            payment.estado = 'fallido'
            payment.save(update_fields=['estado'])
        else:
            plan = payment.plan
            if not plan or not plan.activo or payment.monto != plan.precio or payment.moneda != plan.moneda:
                raise ValueError('El plan requiere revisión.')
            now = at or timezone.now()
            sub = SuscripcionUsuario.objects.filter(usuario_id=payment.usuario_id).first()
            start = now
            from .payments import verified_payment
            if sub and sub.plan_id == plan.pk and sub.estado == 'activa' and (sub.fecha_fin is None or sub.fecha_fin > now) and verified_payment(sub):
                if sub.fecha_fin is None and sub.plan.precio > 0:
                    raise ValueError('Suscripción sin vencimiento; requiere revisión.')
                if sub.fecha_fin:
                    start = max(now, sub.fecha_fin)
            sub, _ = SuscripcionUsuario.objects.update_or_create(usuario_id=payment.usuario_id, defaults={
                'plan': plan, 'estado': 'activa', 'fecha_inicio': now,
                'fecha_fin': period_end(start, plan.periodo), 'auto_renovar': False,
                'fecha_cancelacion': None, 'motivo_cancelacion': None,
                'id_suscripcion_externa': payment.referencia_transaccion,
                'metadatos': {'provider_receipt': signing.dumps({
                    'user': payment.usuario_id, 'plan': plan.pk, 'amount': format(plan.precio, '.2f'),
                    'currency': plan.moneda, 'reference': payment.referencia_transaccion}, salt=SALT)},
            })
            payment.suscripcion = sub
            payment.estado = 'completado'
            payment.save(update_fields=['suscripcion', 'estado'])
        PaymentEvent.objects.create(provider=provider, event_id=data['event_id'], digest=digest, payment=payment)
        return payment


def cancel_local_renewal(user):
    """Estado local; no promete cancelar un contrato externo sin adaptador."""
    with transaction.atomic(using='accounts'):
        sub = SuscripcionUsuario.objects.get(usuario=user)
        sub.auto_renovar = False
        sub.fecha_cancelacion = timezone.now()
        sub.save(update_fields=['auto_renovar', 'fecha_cancelacion'])
        return sub
