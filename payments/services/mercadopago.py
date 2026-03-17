import os
import requests

MP_API_BASE = "https://api.mercadopago.com"


def mp_headers():
    token = os.getenv("MP_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("MP_ACCESS_TOKEN no está configurado")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def create_preference(*, items, external_reference, notification_url, back_urls):
    payload = {
        "items": items,
        "external_reference": external_reference,
        "notification_url": notification_url,
        "back_urls": back_urls,
        "auto_return": "approved",
    }

    r = requests.post(
        f"{MP_API_BASE}/checkout/preferences",
        headers=mp_headers(),
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_payment(payment_id: str):
    r = requests.get(
        f"{MP_API_BASE}/v1/payments/{payment_id}",
        headers=mp_headers(),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()