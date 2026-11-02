"""Validación defensiva de acceso pagado; no crea pagos ni recibos.

Los estados históricos 'activa/completado' por sí solos no prueban un cobro.
No existe todavía una ruta pública que emita el recibo firmado: los pagos
siguen desactivados hasta integrar y probar la confirmación real del proveedor.
"""
from django.core import signing
from suscripciones.models import HistorialPago

SALT = 'litmate-provider-payment-receipt-v1'


def verified_payment(sub):
    metadata = sub.metadatos if isinstance(sub.metadatos, dict) else {}
    receipt = metadata.get('provider_receipt')
    if not isinstance(receipt, str) or len(receipt) > 4096 or not sub.id_suscripcion_externa:
        return False
    try:
        claims = signing.loads(receipt, salt=SALT)
    except (signing.BadSignature, ValueError, TypeError):
        return False
    expected = {'user': sub.usuario_id, 'plan': sub.plan_id,
                'amount': format(sub.plan.precio, '.2f'), 'currency': sub.plan.moneda,
                'reference': sub.id_suscripcion_externa}
    return claims == expected and HistorialPago.objects.filter(
        usuario_id=sub.usuario_id, suscripcion_id=sub.pk, plan_id=sub.plan_id,
        referencia_transaccion=sub.id_suscripcion_externa, estado='completado',
        monto=sub.plan.precio, moneda=sub.plan.moneda).exists()
