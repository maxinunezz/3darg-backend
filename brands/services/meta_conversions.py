"""Meta Conversions API (server-side).

Envía eventos de conversión a Meta usando el `pixel_id` +
`conversions_api_access_token` que cada `Brand` guarda en `meta_config`.
Mismo patrón que la integración de BamBuddy (`orders/signals.py`): si la
marca no tiene la config cargada, la función no hace nada — no rompe el
flujo de pago ni requiere feature flags.

No importar Django REST Framework acá: este módulo lo consume `orders`
(vía signal), no una vista.
"""
import hashlib
import logging
import time

import requests

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"
REQUEST_TIMEOUT = 10


def _hash(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def hash_user_data(email: str = "", phone: str = "") -> dict:
    """Arma el bloque `user_data` con PII hasheada SHA256, como exige Meta.

    `email` se normaliza a minúsculas/trim antes de hashear. `phone` se
    limpia a solo dígitos (Meta espera código de país + número, sin '+').
    """
    data = {}
    if email:
        data["em"] = [_hash(email)]
    if phone:
        digits = "".join(ch for ch in phone if ch.isdigit())
        if digits:
            data["ph"] = [_hash(digits)]
    return data


def send_event(
    brand,
    *,
    event_name: str,
    event_id: str,
    event_time: int | None = None,
    user_data: dict | None = None,
    custom_data: dict | None = None,
    event_source_url: str = "",
    action_source: str = "website",
) -> bool:
    """Envía un evento server-side a Meta Conversions API para `brand`.

    `event_id` debe coincidir con el que eventualmente dispare el Pixel
    client-side del mismo evento (deduplicación de Meta) — para `Purchase`
    usamos `order.external_reference`.

    Nunca levanta excepción: los errores se loguean para no romper el
    flujo que dispara el evento (confirmación de pago, webhook, etc.).
    Devuelve True/False según si se pudo enviar.
    """
    pixel_id = (brand.meta_config or {}).get("pixel_id")
    access_token = (brand.meta_config or {}).get("conversions_api_access_token")
    if not pixel_id or not access_token:
        logger.debug(
            "Meta CAPI no configurado para brand=%s — se omite evento %s",
            brand.slug, event_name,
        )
        return False

    payload = {
        "data": [{
            "event_name": event_name,
            "event_time": int(event_time or time.time()),
            "event_id": event_id,
            "action_source": action_source,
            "event_source_url": event_source_url,
            "user_data": user_data or {},
            "custom_data": custom_data or {},
        }],
    }

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{pixel_id}/events"
    try:
        response = requests.post(
            url,
            params={"access_token": access_token},
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        logger.info(
            "Meta CAPI: evento %s enviado — brand=%s event_id=%s response=%s",
            event_name, brand.slug, event_id, response.json(),
        )
        return True
    except requests.RequestException as e:
        body = getattr(e.response, "text", "")
        logger.error(
            "Meta CAPI error al enviar %s — brand=%s event_id=%s: %s %s",
            event_name, brand.slug, event_id, e, body,
        )
        return False
