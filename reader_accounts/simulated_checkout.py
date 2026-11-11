"""Adaptador ficticio del ciclo comercial. No contacta servicios de pago."""
import hashlib
import hmac
import json
from pathlib import Path
from uuid import UUID, uuid5, NAMESPACE_URL

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from suscripciones.models import PlanSuscripcion, SuscripcionUsuario
from .checkout_models import SimulatedOrder
from .payment_lifecycle import prepare_checkout, apply_provider_event, cancel_local_renewal
from .payments import SALT, verified_payment

PROVIDER = 'litmate-simulation'
SIMULATION_SALT = SALT + '.simulation'
SCENARIOS = [('approved', 'Aprobar'), ('rejected', 'Rechazar'), ('temporary', 'Error temporal en el primer intento')]


class CheckoutError(ValueError):
    pass


def enabled():
    return getattr(settings, 'LITMATE_SIMULATED_CHECKOUT_ENABLED', False)


def scenarios_allowed():
    path = Path(settings.DATABASES['accounts']['NAME']).resolve()
    return (enabled() and getattr(settings, 'LITMATE_CHECKOUT_TEST_SCENARIOS', False)
            and path.is_relative_to(Path(settings.BASE_DIR) / '.testtmp'))


def paid_plan(slug):
    return PlanSuscripcion.objects.filter(slug=slug, activo=True, precio__gt=0, moneda='CLP', periodo='mensual').first()


def subscription(user):
    return SuscripcionUsuario.objects.select_related('plan').filter(usuario=user).first()


def is_simulated(sub):
    return bool(sub and isinstance(sub.metadatos, dict) and sub.metadatos.get('simulation_receipt'))


def create_order(user, plan, *, method, submission_id, scenario='approved', renew=False,
                 kind=None, at=None):
    if not enabled():
        raise CheckoutError('La contratación simulada está desactivada.')
    if method not in dict(SimulatedOrder.METHODS) or scenario not in dict(SCENARIOS):
        raise CheckoutError('Método o escenario inválido.')
    if scenario != 'approved' and not scenarios_allowed():
        raise CheckoutError('El escenario requiere el entorno de pruebas protegido.')
    submission_id = UUID(str(submission_id))
    with transaction.atomic(using='accounts'):
        previous = SimulatedOrder.objects.select_related('payment').filter(user=user, submission_id=submission_id).first()
        if previous:
            if previous.payment.plan_id != plan.pk or previous.method != method or previous.scenario != scenario:
                raise CheckoutError('El identificador corresponde a otra selección.')
            return previous
        current = subscription(user)
        now = at or timezone.now()
        same_active = (current and current.plan_id == plan.pk and current.estado == 'activa'
                       and (current.fecha_fin is None or current.fecha_fin > now) and verified_payment(current))
        if same_active and not renew:
            raise CheckoutError('Ya tienes este plan. Confirma expresamente una renovación voluntaria.')
        if not paid_plan(plan.slug):
            raise CheckoutError('Selecciona un plan mensual disponible.')
        payment = prepare_checkout(user, plan, provider=PROVIDER, adapter_authorized=True,
                                   idempotency_key='sim-' + submission_id.hex)
        return SimulatedOrder.objects.create(user=user, payment=payment, submission_id=submission_id,
            method=method, scenario=scenario, plan_name=plan.nombre, period=plan.periodo,
            kind=kind or ('manual_renewal' if same_active else 'purchase'),
            source_reference=(current.id_suscripcion_externa or '') if current else '')


def process_order(user, order_id, *, cancel=False, at=None):
    if not enabled():
        raise CheckoutError('La contratación simulada está desactivada.')
    now = at or timezone.now()
    with transaction.atomic(using='accounts'):
        order = SimulatedOrder.objects.select_related('payment__plan').get(pk=order_id, user=user)
        if order.state in ('approved', 'rejected', 'cancelled'):
            return order
        payment = order.payment
        plan = payment.plan
        if not plan or (not cancel and (not plan.activo or payment.monto != plan.precio
                or payment.moneda != plan.moneda or order.period != plan.periodo)):
            raise CheckoutError('El plan cambió. Cancela este pedido y revisa una nueva contratación.')
        current = subscription(user)
        reference = current.id_suscripcion_externa or '' if current else ''
        if not cancel and reference != order.source_reference:
            raise CheckoutError('Tu suscripción cambió desde que abriste el pedido. Revisa una nueva contratación.')
        order.attempts += 1
        if not cancel and order.scenario == 'temporary' and order.attempts == 1:
            order.state = 'temporary_error'
            order.save(update_fields=['state', 'attempts'])
            return order
        state = 'cancelled' if cancel else ('failed' if order.scenario == 'rejected' else 'confirmed')
        payload = {'event_id': 'sim-result-' + order.pk.hex, 'timestamp': now.timestamp(),
            'payment_id': payment.pk, 'reference': payment.referencia_transaccion,
            'amount': format(payment.monto, '.2f'), 'currency': payment.moneda,
            'state': state, 'user_id': user.pk, 'plan_id': plan.pk, 'period': order.period}
        raw = json.dumps(payload, sort_keys=True).encode()
        secret = signing.Signer(salt='litmate-simulation-adapter').signature(order.pk.hex).encode()
        # La clave derivada permanece en servidor. Se usa el contrato interno existente.
        secret = hashlib.sha256(secret).digest()
        signature = hmac.new(secret, raw, hashlib.sha256).hexdigest()
        applied = apply_provider_event(raw, signature, provider=PROVIDER, secret=secret, at=at)
        order.state = 'cancelled' if cancel else ('rejected' if state == 'failed' else 'approved')
        if order.state == 'approved':
            sub = subscription(user)
            claims = signing.loads(sub.metadatos['provider_receipt'], salt=SALT)
            sub.metadatos = {'simulation_receipt': signing.dumps(claims, salt=SIMULATION_SALT),
                             'simulation_order': str(order.pk)}
            sub.save(update_fields=['metadatos'])
            order.activated_at = sub.fecha_inicio
            order.access_until = sub.fecha_fin
        order.save(update_fields=['state', 'attempts', 'activated_at', 'access_until'])
        return order


def cancel_subscription(user):
    with transaction.atomic(using='accounts'):
        sub = subscription(user)
        if not enabled() or not is_simulated(sub) or not verified_payment(sub):
            raise CheckoutError('No se encontró una suscripción simulada verificable.')
        return sub if sub.fecha_cancelacion else cancel_local_renewal(user)


def switch_to_free(user):
    with transaction.atomic(using='accounts'):
        sub = subscription(user)
        if not enabled() or not is_simulated(sub) or not verified_payment(sub):
            raise CheckoutError('El cambio requiere una suscripción simulada verificable.')
        plan = PlanSuscripcion.objects.filter(activo=True, precio=0).order_by('orden', 'pk').first()
        if plan is None:
            raise CheckoutError('El plan gratuito no está disponible.')
        sub.plan = plan
        sub.estado = 'activa'
        sub.fecha_inicio = timezone.now()
        sub.fecha_fin = None
        sub.auto_renovar = False
        sub.fecha_cancelacion = None
        sub.id_suscripcion_externa = None
        sub.metadatos = {}
        sub.save()
        return sub


def renew_due(user, *, at, scenario='approved'):
    """Sólo lo invoca el comando de pruebas con almacenamiento sintético."""
    with transaction.atomic(using='accounts'):
        sub = subscription(user)
        if (not sub or not is_simulated(sub) or sub.fecha_cancelacion or not sub.fecha_fin
                or sub.fecha_fin > at or not verified_payment(sub)):
            return None
        source = SimulatedOrder.objects.get(pk=sub.metadatos['simulation_order'], user=user)
        token = uuid5(NAMESPACE_URL, 'litmate-renew:' + sub.id_suscripcion_externa + ':' + sub.fecha_fin.isoformat())
        order = create_order(user, sub.plan, method=source.method, submission_id=token, scenario=scenario,
                             kind='scheduled_renewal', at=at)
        return process_order(user, order.pk, at=at)
