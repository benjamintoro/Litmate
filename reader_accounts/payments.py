"""Valida recibos del ciclo comercial y del checkout ficticio.

Los recibos simulados requieren el modo de demostración habilitado y un pedido
aprobado persistente. Los estados históricos por sí solos no conceden acceso.
"""
from uuid import UUID
from django.core import signing
from django.conf import settings
from suscripciones.models import HistorialPago

SALT = 'litmate-provider-payment-receipt-v1'


def verified_payment(sub):
    metadata = sub.metadatos if isinstance(sub.metadatos, dict) else {}
    receipt = metadata.get('provider_receipt')
    salt = SALT
    if metadata.get('simulation_receipt'):
        if not getattr(settings, 'LITMATE_SIMULATED_CHECKOUT_ENABLED', False):
            return False
        from .checkout_models import SimulatedOrder
        try:
            order_id = UUID(str(metadata.get('simulation_order')))
        except (ValueError, TypeError, AttributeError):
            return False
        if not SimulatedOrder.objects.filter(user_id=sub.usuario_id, state='approved',
                payment__referencia_transaccion=sub.id_suscripcion_externa,
                id=order_id).exists():
            return False
        receipt = metadata['simulation_receipt']
        salt = SALT + '.simulation'
    if not isinstance(receipt, str) or len(receipt) > 4096 or not sub.id_suscripcion_externa:
        return False
    try:
        claims = signing.loads(receipt, salt=salt)
    except (signing.BadSignature, ValueError, TypeError):
        return False
    expected = {'user': sub.usuario_id, 'plan': sub.plan_id,
                'amount': format(sub.plan.precio, '.2f'), 'currency': sub.plan.moneda,
                'reference': sub.id_suscripcion_externa}
    return claims == expected and HistorialPago.objects.filter(
        usuario_id=sub.usuario_id, suscripcion_id=sub.pk, plan_id=sub.plan_id,
        referencia_transaccion=sub.id_suscripcion_externa, estado='completado',
        monto=sub.plan.precio, moneda=sub.plan.moneda).exists()
