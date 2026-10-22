import requests
import logging
import uuid
from django.conf import settings

from ..payment_safety import simulation_allowed

logger = logging.getLogger('litmate')


class MercadoPagoService:
    """
    Servicio de integración para Mercado Pago Checkout Pro API.
    Permite generar preferencias de pago en CLP y verificar el estado de los pagos.
    """

    PREFERENCE_URL = "https://api.mercadopago.com/checkout/preferences"
    PAYMENTS_URL = "https://api.mercadopago.com/v1/payments"

    def __init__(self):
        self.access_token = getattr(settings, 'MERCADOPAGO_ACCESS_TOKEN', '')
        self.public_key = getattr(settings, 'MERCADOPAGO_PUBLIC_KEY', '')

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def crear_preferencia(self, plan, usuario, external_reference, back_urls):
        """
        Crea una preferencia de pago para el plan en Mercado Pago.
        """
        payload = {
            "items": [
                {
                    "title": f"Suscripción LitMate {plan.nombre}",
                    "description": f"Membresía {plan.periodo} en plataforma LitMate",
                    "quantity": 1,
                    "currency_id": "CLP",
                    "unit_price": float(plan.precio)
                }
            ],
            "payer": {
                "name": usuario.first_name or usuario.username,
                "email": usuario.email or "usuario@litmate.com"
            },
            "back_urls": {
                "success": back_urls.get("success"),
                "failure": back_urls.get("failure"),
                "pending": back_urls.get("pending")
            },
            "external_reference": str(external_reference),
            "statement_descriptor": "LITMATE"
        }

        success_url = back_urls.get("success", "")
        if success_url and "127.0.0.1" not in success_url and "localhost" not in success_url:
            payload["auto_return"] = "approved"

        # Si el token es real y no de prueba inicial
        if self.access_token and not self.access_token.startswith("TEST-litmate"):
            try:
                response = requests.post(
                    self.PREFERENCE_URL,
                    json=payload,
                    headers=self._get_headers(),
                    timeout=8
                )
                if response.status_code in [200, 201]:
                    data = response.json()
                    if self.access_token.startswith("APP_USR-"):
                        init_point = data.get("init_point") or data.get("sandbox_init_point")
                    else:
                        init_point = data.get("sandbox_init_point") or data.get("init_point")
                    logger.info(f"[Mercado Pago] Preferencia creada exitosamente: {data.get('id')}")
                    return {
                        "success": True,
                        "preference_id": data.get("id"),
                        "init_point": init_point,
                        "is_simulated": False
                    }
                else:
                    logger.warning(f"[Mercado Pago] Error API ({response.status_code}): {response.text}")
            except Exception as e:
                logger.warning(f"[Mercado Pago] Conexión falló: {e}.")

        if not simulation_allowed():
            logger.error("[Mercado Pago] Pasarela no disponible y el sandbox local está desactivado.")
            return {"success": False, "error": "provider_unavailable"}

        # Modo Sandbox / Simulación Local para Desarrollo
        mock_pref_id = f"MP_MOCK_{uuid.uuid4().hex[:12].upper()}"
        return {
            "success": True,
            "preference_id": mock_pref_id,
            "init_point": f"/suscripciones/simulador-gateway/?provider=mercadopago&token={mock_pref_id}&amount={int(plan.precio)}&ref={external_reference}",
            "is_simulated": True
        }

    def verificar_pago(self, payment_id):
        """
        Verifica el estado de un pago en Mercado Pago mediante su ID.
        """
        if str(payment_id).startswith("MP_MOCK_"):
            if not simulation_allowed():
                logger.warning("[Mercado Pago] Pago simulado rechazado fuera del sandbox.")
                return {"success": False, "status": "simulation_disabled"}
            return {
                "success": True,
                "status": "approved",
                "status_detail": "accredited",
                "payment_id": payment_id,
                "is_simulated": True,
                "raw_data": {},
            }

        try:
            url = f"{self.PAYMENTS_URL}/{payment_id}"
            response = requests.get(
                url,
                headers=self._get_headers(),
                timeout=8
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": data.get("status") == "approved",
                    "status": data.get("status"),
                    "status_detail": data.get("status_detail"),
                    "payment_id": data.get("id"),
                    "transaction_amount": data.get("transaction_amount"),
                    "currency_id": data.get("currency_id"),
                    "external_reference": data.get("external_reference"),
                    "raw_data": data,
                    "is_simulated": False
                }
        except Exception as e:
            logger.error(f"[Mercado Pago] Error verificando pago {payment_id}: {e}")

        return {"success": False, "status": "unknown"}
