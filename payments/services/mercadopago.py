import os
import hmac
import hashlib
import logging
import mercadopago

logger = logging.getLogger(__name__)


def get_mp_sdk():
    token = os.getenv("MP_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("MP_ACCESS_TOKEN no configurado en el archivo .env")
    return mercadopago.SDK(token)


def create_preference(*, items, external_reference, notification_url, back_urls):
    sdk = get_mp_sdk()

    preference_data = {
        "items": items,
        "external_reference": str(external_reference).strip(),
        "notification_url": notification_url.strip(),
        "back_urls": {
            "success": back_urls.get("success").strip(),
            "failure": back_urls.get("failure").strip(),
            "pending": back_urls.get("pending").strip(),
        },
        "auto_return": "approved",
    }

    result = sdk.preference().create(preference_data)

    if result["status"] not in [200, 201]:
        logger.error("MP SDK error al crear preferencia: %s", result)
        raise Exception(f"MP Error: {result['response']}")

    return result["response"]


def get_payment(payment_id: str):
    sdk = get_mp_sdk()
    result = sdk.payment().get(str(payment_id))

    if result["status"] == 200:
        return result["response"]

    logger.error("MP SDK error al buscar pago %s: %s", payment_id, result.get("response"))
    raise Exception("No se pudo obtener el pago de MP")


def is_valid_webhook_signature(request) -> bool:
    secret = os.getenv("MP_WEBHOOK_SECRET")
    x_signature = request.headers.get("x-signature")
    x_request_id = request.headers.get("x-request-id")
    resource_id = request.GET.get("data.id") or request.GET.get("id")

    if not all([secret, x_signature, x_request_id, resource_id]):
        return False

    try:
        parts = {p.split("=")[0]: p.split("=")[1] for p in x_signature.split(",")}
        ts, v1 = parts.get("ts"), parts.get("v1")

        manifests = [
            f"id:{resource_id};request-id:{x_request_id};ts:{ts};",
            f"id:{resource_id};request-id:{x_request_id};ts:{ts}",
        ]

        for m in manifests:
            h = hmac.new(secret.encode(), msg=m.encode(), digestmod=hashlib.sha256).hexdigest()
            if hmac.compare_digest(h, v1):
                return True

        return False
    except Exception as e:
        logger.warning("Error en validación de firma webhook: %s", e)
        return False
