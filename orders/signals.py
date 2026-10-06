import json
import logging
import os
import urllib.error
import urllib.request

import requests
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from brands.services.meta_conversions import hash_user_data, send_event as send_meta_event
from products.models import Product
from .models import Order

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Order)
def cache_old_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._old_status = None
        return
    try:
        instance._old_status = sender.objects.only("status").get(pk=instance.pk).status
    except sender.DoesNotExist:
        instance._old_status = None


@receiver(post_save, sender=Order)
def handle_order_status_change(sender, instance, created, **kwargs):
    old_status = getattr(instance, "_old_status", None)
    new_status = instance.status

    if old_status == new_status:
        return

    paid_now = (
        new_status == Order.Status.PAID
        and old_status is not None
        and old_status != Order.Status.PAID
    )
    paid_undone = (
        old_status == Order.Status.PAID
        and new_status in (Order.Status.REJECTED, Order.Status.CANCELLED)
    )

    if paid_now:
        _decrement_stock(instance)
        _send_payment_email(instance)
        _send_owner_notification_email(instance)
        _trigger_bambuddy_print(instance)
        _send_meta_purchase_event(instance)
        _notify_presupuestos3d(instance)
    elif paid_undone:
        _restore_stock(instance)


def _decrement_stock(order):
    with transaction.atomic():
        for item in order.order_items.all():
            if not item.product_id:
                continue
            product = Product.objects.select_for_update().get(pk=item.product_id)
            new_stock = max(product.stock - item.quantity, 0)
            product.stock = new_stock
            product.save(update_fields=["stock"])
            logger.info(
                "Stock descontado: product=%s qty=-%s stock_actual=%s",
                product.slug, item.quantity, new_stock,
            )


def _restore_stock(order):
    with transaction.atomic():
        for item in order.order_items.all():
            if not item.product_id:
                continue
            product = Product.objects.select_for_update().get(pk=item.product_id)
            product.stock = product.stock + item.quantity
            product.save(update_fields=["stock"])
            logger.info(
                "Stock restituido: product=%s qty=+%s stock_actual=%s",
                product.slug, item.quantity, product.stock,
            )


def _notify_presupuestos3d(order):
    """Aviso de solo lectura hacia presupuestos3d. No descuenta stock ni crea nada
    de este lado; no-op silencioso si faltan las env vars (ver settings.py)."""
    api_url = settings.PRESUPUESTOS3D_API_URL
    api_token = settings.PRESUPUESTOS3D_API_TOKEN
    if not api_url or not api_token:
        return

    payload = {
        "external_reference": order.external_reference,
        "brand_slug": order.brand.slug,
        "brand_name": order.brand.name,
        "customer_email": order.customer_email,
        "items": order.items,
        "total_amount": str(order.total_amount),
        "currency": order.currency,
        "order_created_at": order.created_at.isoformat(),
        "raw_payload": {
            "order_id": str(order.id),
            "status": order.status,
        },
    }

    try:
        response = requests.post(
            api_url.rstrip("/") + "/api/pedidos-online/",
            json=payload,
            headers={"Authorization": f"Token {api_token}"},
            timeout=5,
        )
        response.raise_for_status()
        logger.info("Aviso enviado a presupuestos3d para orden %s", order.id)
    except requests.RequestException as e:
        logger.error("Error avisando a presupuestos3d para orden %s: %s", order.id, e)


def _trigger_bambuddy_print(order):
    """Encola en BamBuddy cada item de la orden para impresión automática.

    Solo actúa si BAMBUDDY_URL y BAMBUDDY_API_KEY están configurados en .env.
    Los errores se loguean pero nunca rompen el flujo de pago.
    Requiere que cada Product tenga `bambuddy_file_id` seteado.
    """
    bambuddy_url = getattr(settings, "BAMBUDDY_URL", "").rstrip("/")
    api_key = getattr(settings, "BAMBUDDY_API_KEY", "")
    printer_id = getattr(settings, "BAMBUDDY_PRINTER_ID", 1)

    if not bambuddy_url or not api_key:
        logger.debug("BamBuddy no configurado — se omite encolado automático para orden %s", order.id)
        return

    items = order.order_items.select_related("product").all()
    for item in items:
        if not item.product_id:
            continue

        file_id = getattr(item.product, "bambuddy_file_id", None)
        if not file_id:
            logger.warning(
                "Producto '%s' (orden %s) sin bambuddy_file_id — no se encola",
                item.product_name, order.id,
            )
            continue

        payload = json.dumps({
            "library_file_id": file_id,
            "printer_id": printer_id,
            "quantity": item.quantity,
            "bed_levelling": "auto",
            "flow_cali": "auto",
            "vibration_cali": True,
            "layer_inspect": False,
            "timelapse": False,
            "use_ams": True,
            "manual_start": False,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{bambuddy_url}/api/v1/queue/",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                logger.info(
                    "BamBuddy: encolado trabajo #%s — orden=%s producto='%s' file_id=%s cantidad=%s",
                    result.get("id"), order.id, item.product_name, file_id, item.quantity,
                )
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            logger.error(
                "BamBuddy HTTP %s al encolar orden=%s producto='%s': %s",
                e.code, order.id, item.product_name, body,
            )
        except Exception as e:
            logger.error(
                "BamBuddy error inesperado al encolar orden=%s producto='%s': %s",
                order.id, item.product_name, e,
            )


def _send_meta_purchase_event(order):
    """Dispara el evento `Purchase` a Meta Conversions API para la marca de la orden.

    `event_id = order.external_reference` — si en el futuro se agrega el
    Pixel client-side en la página de éxito, debe usar el mismo `event_id`
    para que Meta deduplique el evento client-side y el server-side en vez
    de contarlo dos veces.

    Se omite en silencio si la marca no tiene `meta_config` cargado
    (`send_event` ya loguea y no rompe el flujo de pago).
    """
    frontend_base = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")
    contents = [
        {
            "id": item.product.sku if item.product_id and item.product else "",
            "quantity": item.quantity,
            "item_price": float(item.unit_price),
        }
        for item in order.order_items.select_related("product").all()
    ]
    send_meta_event(
        order.brand,
        event_name="Purchase",
        event_id=order.external_reference,
        user_data=hash_user_data(email=order.customer_email),
        custom_data={
            "currency": order.currency,
            "value": float(order.total_amount),
            "contents": contents,
            "content_type": "product",
        },
        event_source_url=f"{frontend_base}/checkout/success/?order_id={order.id}",
    )


def _send_payment_email(order):
    if not order.customer_email:
        return
    subject = f"Tu pedido está confirmado — {order.brand.name}"
    message = (
        f"Hola!\n\n"
        f"Tu pago fue aprobado. Tu número de orden es:\n"
        f"{order.id}\n\n"
        f"Total: {order.currency} {order.total_amount}\n\n"
        f"Gracias por tu compra en {order.brand.name}.\n"
    )
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [order.customer_email],
            fail_silently=False,
        )
        logger.info("Email de confirmación enviado a %s (orden %s)", order.customer_email, order.id)
    except Exception as e:
        logger.error("Error enviando email para orden %s: %s", order.id, e)


def _resolve_owner_email(brand_slug: str) -> str:
    """Destinatario del aviso interno de venta. Mismo patrón que
    contact/views.py::_resolve_contact_email — cada marca puede tener su
    propio destinatario vía <SLUG>_CONTACT_EMAIL (ej: LUMY_CONTACT_EMAIL)
    en el .env; si no está seteada, cae al CONTACT_EMAIL global."""
    if brand_slug:
        env_key = f"{brand_slug.upper().replace('-', '_')}_CONTACT_EMAIL"
        brand_email = os.getenv(env_key)
        if brand_email:
            return brand_email
    return getattr(settings, "CONTACT_EMAIL", "3darg1@gmail.com")


def _send_owner_notification_email(order):
    """Avisa al dueño del negocio que entró una venta — hoy la única
    confirmación que se mandaba era al cliente, el dueño no se enteraba
    de nada salvo que entrara al admin a revisar."""
    owner_email = _resolve_owner_email(order.brand.slug if order.brand_id else "")
    if not owner_email:
        return

    items_lines = "\n".join(
        f"  - {item.product_name} x{item.quantity} — {order.currency} {item.unit_price} c/u"
        for item in order.order_items.all()
    )
    subject = f"Nueva venta — {order.brand.name} — {order.currency} {order.total_amount}"
    message = (
        f"Nueva venta confirmada en {order.brand.name}.\n\n"
        f"Orden: {order.id}\n"
        f"Cliente: {order.customer_email or '(sin email, compra de invitado)'}\n\n"
        f"Productos:\n{items_lines}\n\n"
        f"Total: {order.currency} {order.total_amount}\n"
    )
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [owner_email],
            fail_silently=False,
        )
        logger.info("Aviso de venta enviado a %s (orden %s)", owner_email, order.id)
    except Exception as e:
        logger.error("Error enviando aviso de venta para orden %s: %s", order.id, e)
