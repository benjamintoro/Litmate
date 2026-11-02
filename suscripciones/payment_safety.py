"""Reglas compartidas para no activar pagos simulados en producción."""
from django.conf import settings


def simulation_allowed():
    """El sandbox local sólo existe en desarrollo o con permiso explícito.

    Las credenciales de prueba del repositorio no deben convertir una caída de
    la pasarela en una suscripción gratuita en producción.
    """
    return bool(getattr(settings, 'DEBUG', False)
                or getattr(settings, 'LITMATE_PAYMENT_SANDBOX', False))
