"""Emails del checkout por transferencia bancaria — se disparan al CREAR el
pedido (todavía `PENDING`), no en la confirmación de pago. Por eso viven
acá y no en `orders/signals.py::handle_order_status_change`, que solo
reacciona a la transición `-> PAID` (que para este canal la dispara a mano
el dueño desde el admin, ver `orders/admin.py::confirmar_transferencia_recibida`
— ese flip de status sí reusa el signal existente, sin lógica nueva).

Mismo patrón defensivo que `orders/signals.py::_send_payment_email`/
`_send_owner_notification_email`: `send_mail()` envuelto en try/except, un
fallo de email nunca rompe el checkout.
"""

import logging
import os

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _resolve_owner_email(brand_slug: str) -> str:
    """Duplicado a propósito de `orders/signals.py::_resolve_owner_email`
    (mismo criterio: <SLUG>_CONTACT_EMAIL con fallback a CONTACT_EMAIL) — se
    prefiere este pequeño duplicado a importar una función privada de otra
    app."""
    if brand_slug:
        env_key = f"{brand_slug.upper().replace('-', '_')}_CONTACT_EMAIL"
        brand_email = os.getenv(env_key)
        if brand_email:
            return brand_email
    return getattr(settings, "CONTACT_EMAIL", "3darg1@gmail.com")


def reference_code(order) -> str:
    """Código corto que el comprador pone como "concepto" al transferir —
    se reusa `external_reference` (ya único, ya se usaba para MP) en vez de
    sumar un campo nuevo, mostrado acortado/en mayúsculas para que sea fácil
    de tipear/leer en el comprobante del banco."""
    return (order.external_reference or str(order.id))[:8].upper()


def send_transfer_instructions_email(order):
    """Al comprador: alias/CBU, monto exacto, código de referencia y el
    aviso de las 48hs de gracia antes de que el pedido se cancele solo."""
    if not order.customer_email:
        return

    hours = getattr(settings, "TRANSFER_PENDING_EXPIRATION_HOURS", 48)
    message = (
        f"Hola!\n\n"
        f"Registramos tu pedido en {order.brand.name}, pendiente de pago por "
        f"transferencia bancaria.\n\n"
        f"Datos para transferir:\n"
        f"  Alias: {settings.TRANSFER_BANK_ALIAS}\n"
        f"  CBU: {settings.TRANSFER_BANK_CBU}\n"
        f"  Titular: {settings.TRANSFER_BANK_HOLDER_NAME}\n"
        f"  CUIT/CUIL: {settings.TRANSFER_BANK_CUIT}\n\n"
        f"Monto exacto a transferir: {order.currency} {order.total_amount}\n"
        f"Código de referencia (poné esto en el concepto/motivo de la "
        f"transferencia): {reference_code(order)}\n\n"
        f"Tu número de orden es {order.id}.\n\n"
        f"Importante: una vez que transfieras, vas a recibir la confirmación "
        f"por este mismo medio en cuanto verifiquemos el ingreso a mano — "
        f"puede demorar unas horas. Si no transferís dentro de las "
        f"{hours} horas, el pedido se cancela automáticamente y el stock se "
        f"libera.\n\n"
        f"Gracias por tu compra en {order.brand.name}.\n"
    )
    try:
        send_mail(
            f"Instrucciones para tu transferencia — {order.brand.name}",
            message,
            settings.DEFAULT_FROM_EMAIL,
            [order.customer_email],
            fail_silently=False,
        )
        logger.info(
            "Email de instrucciones de transferencia enviado a %s (orden %s)",
            order.customer_email, order.id,
        )
    except Exception as e:
        logger.error(
            "Error enviando instrucciones de transferencia para orden %s: %s", order.id, e
        )


def send_transfer_pending_owner_email(order):
    """Al dueño: aviso de que hay un pedido nuevo esperando que confirme la
    transferencia a mano (vía admin) una vez que vea el ingreso en el banco."""
    owner_email = _resolve_owner_email(order.brand.slug if order.brand_id else "")
    if not owner_email:
        return

    items_lines = "\n".join(
        f"  - {item.product_name} x{item.quantity} — {order.currency} {item.unit_price} c/u"
        for item in order.order_items.all()
    )
    hours = getattr(settings, "TRANSFER_PENDING_EXPIRATION_HOURS", 48)
    message = (
        f"Nuevo pedido pendiente de transferencia en {order.brand.name}.\n\n"
        f"Orden: {order.id}\n"
        f"Código de referencia: {reference_code(order)}\n"
        f"Cliente: {order.customer_email or '(sin email, compra de invitado)'}\n\n"
        f"Productos:\n{items_lines}\n\n"
        f"Total a recibir: {order.currency} {order.total_amount}\n\n"
        f"Revisá el banco y, cuando veas el ingreso con este código de "
        f"referencia, confirmalo desde el admin (acción 'Confirmar "
        f"transferencia recibida' sobre esta orden) — eso descuenta el "
        f"stock y manda la confirmación al cliente.\n\n"
        f"Si no se confirma dentro de las {hours} horas, el pedido se "
        f"cancela solo.\n"
    )
    try:
        send_mail(
            f"Pedido pendiente de transferencia — {order.brand.name} — "
            f"{order.currency} {order.total_amount}",
            message,
            settings.DEFAULT_FROM_EMAIL,
            [owner_email],
            fail_silently=False,
        )
        logger.info(
            "Aviso de pedido pendiente de transferencia enviado a %s (orden %s)",
            owner_email, order.id,
        )
    except Exception as e:
        logger.error(
            "Error enviando aviso de pedido pendiente de transferencia para orden %s: %s",
            order.id, e,
        )
