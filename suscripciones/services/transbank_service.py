import requests
import logging
import uuid
from django.conf import settings

from ..payment_safety import simulation_allowed

logger = logging.getLogger('litmate')


class TransbankService:
    """
    Servicio de integración para Transbank Webpay Plus REST API v1.2.
    Soporta entorno de Integración oficial (Sandbox Transbank) y simulación interactiva para desarrollo.
    """

    INTEGRATION_URL = "https://webpay3gint.transbank.cl/rswebpaytransaction/api/webpay/v1.2/transactions"
    PRODUCTION_URL = "https://webpay3g.transbank.cl/rswebpaytransaction/api/webpay/v1.2/transactions"

    def __init__(self):
        self.commerce_code = getattr(settings, 'TRANSBANK_COMMERCE_CODE', '597055555532')
        self.api_key = getattr(settings, 'TRANSBANK_API_KEY', '579B532A7440BB0C9079DED94D31EA1615BACEB56610332264630D42D0A36B1C')
        self.environment = getattr(settings, 'TRANSBANK_ENVIRONMENT', 'integration')
        self.base_url = self.PRODUCTION_URL if self.environment == 'production' else self.INTEGRATION_URL

    def _get_headers(self):
        return {
            "Tbk-Api-Key-Id": self.commerce_code,
            "Tbk-Api-Key-Secret": self.api_key,
            "Content-Type": "application/json"
        }

    def crear_transaccion(self, buy_order, session_id, amount, return_url):
        """
        Crea una transacción en Webpay Plus.
        Retorna dict con 'token' y 'url' para redirección.
        """
        payload = {
            "buy_order": str(buy_order),
            "session_id": str(session_id),
            "amount": int(amount),
            "return_url": return_url
        }

        try:
            response = requests.post(
                self.base_url,
                json=payload,
                headers=self._get_headers(),
                timeout=8
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"[Webpay Plus] Transacción creada con éxito. Token: {data.get('token')}")
                return {
                    "success": True,
                    "token": data.get("token"),
                    "url": data.get("url"),
                    "is_simulated": False
                }
            else:
                logger.warning(f"[Webpay Plus] Error de API Transbank ({response.status_code}): {response.text}")
        except Exception as e:
            logger.warning(f"[Webpay Plus] Conexión directa a Transbank falló: {e}.")

        if not simulation_allowed():
            logger.error("[Webpay Plus] Pasarela no disponible y el sandbox local está desactivado.")
            return {"success": False, "error": "provider_unavailable"}

        # Fallback de desarrollo. Nunca se usa para activar pagos reales.
        mock_token = f"TBK_MOCK_{uuid.uuid4().hex[:16].upper()}"
        return {
            "success": True,
            "token": mock_token,
            "url": f"/suscripciones/simulador-gateway/?provider=webpay&token={mock_token}&amount={int(amount)}&buy_order={buy_order}",
            "is_simulated": True
        }

    def confirmar_transaccion(self, token_ws):
        """
        Confirma (Commit) una transacción con Transbank usando token_ws.
        """
        # Un token local nunca activa una suscripción fuera del sandbox.
        if str(token_ws).startswith("TBK_MOCK_"):
            if not simulation_allowed():
                logger.warning("[Webpay Plus] Token simulado rechazado fuera del sandbox.")
                return {"success": False, "error": "simulation_disabled"}
            return {
                "success": True,
                "status": "AUTHORIZED",
                "response_code": 0,
                "amount": 0,
                "authorization_code": f"AUT-{uuid.uuid4().hex[:6].upper()}",
                "payment_type_code": "VN",
                "shares_number": 0,
                "card_detail": {"card_number": "6623"},
                "accounting_date": "0825",
                "transaction_date": "2026-08-25T20:00:00.000Z",
                "is_simulated": True
            }

        try:
            url = f"{self.base_url}/{token_ws}"
            response = requests.put(
                url,
                headers=self._get_headers(),
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                is_authorized = data.get("response_code") == 0 and data.get("status") == "AUTHORIZED"
                logger.info(f"[Webpay Plus] Transacción confirmada. Estado: {data.get('status')}, Código: {data.get('response_code')}")
                return {
                    "success": is_authorized,
                    "status": data.get("status"),
                    "response_code": data.get("response_code"),
                    "amount": data.get("amount"),
                    "authorization_code": data.get("authorization_code"),
                    "payment_type_code": data.get("payment_type_code"),
                    "card_detail": data.get("card_detail", {}),
                    "raw_data": data,
                    "is_simulated": False
                }
            else:
                logger.error(f"[Webpay Plus] Error confirmando transacción ({response.status_code}): {response.text}")
                return {"success": False, "error": response.text}
        except Exception as e:
            logger.error(f"[Webpay Plus] Excepción confirmando transacción: {e}")
            return {"success": False, "error": str(e)}
