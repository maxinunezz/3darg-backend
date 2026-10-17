import json
import logging
import os
import urllib.error
import urllib.request

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from brands.services.meta_conversions import hash_user_data, send_event as send_meta_event
from products.models import Product, ProductVariant
from shipping.services import correo_argentino
from shipping.services.correo_argentino import CorreoArgentinoConfigError, CorreoArgentinoError
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
        _create_correo_argentino_shipment(instance)
    elif paid_undone:
        _restore_stock(instance)
        _cancel_correo_argentino_shipment(instance)


def _decrement_stock(order):
    # Talles/variantes (Fase 2 de ProductVariant): si el item se compró con
    # una variante puntual, el stock que se mueve es el de ESA variante, no
    # el del Product (que puede tener otras variantes con su propio stock
    # intacto). Sin variante (producto sin talles), comportamiento histórico.
    with transaction.atomic():
        for item in order.order_items.all():
            if item.variant_id:
                variant = ProductVariant.objects.select_for_update().get(pk=item.variant_id)
                new_stock = max(variant.stock - item.quantity, 0)
                variant.stock = new_stock
                variant.save(update_fields=["stock"])
                logger.info(
                    "Stock descontado: variant=%s qty=-%s stock_actual=%s",
                    variant.sku or variant.pk, item.quantity, new_stock,
                )
                continue
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
            if item.variant_id:
                variant = ProductVariant.objects.select_for_update().get(pk=item.variant_id)
                variant.stock = variant.stock + item.quantity
                variant.save(update_fields=["stock"])
                logger.info(
                    "Stock restituido: variant=%s qty=+%s stock_actual=%s",
                    variant.sku or variant.pk, item.quantity, variant.stock,
                )
                continue
            if not item.product_id:
                continue
            product = Product.objects.select_for_update().get(pk=item.product_id)
            product.stock = product.stock + item.quantity
            product.save(update_fields=["stock"])
            logger.info(
                "Stock restituido: product=%s qty=+%s stock_actual=%s",
                product.slug, item.quantity, product.stock,
            )


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


def _notify_presupuestos3d(order):
    """Avisa a presupuestos3d (sistema interno de gestión) que entró una venta
    online, para que el dueño la revise y la cargue a mano como Presupuesto
    si corresponde poner a producir.

    A propósito NO dispara nada automático del lado de presupuestos3d (ni
    Presupuesto, ni costeo, ni cola de impresión) — solo crea el aviso en su
    admin (modelo `PedidoOnline`) con los datos necesarios para cargarlo. La
    decisión de aprobar/producir la toma el dueño a mano.

    Solo actúa si PRESUPUESTOS3D_API_URL y PRESUPUESTOS3D_API_TOKEN están
    configurados en .env. Los errores se loguean pero nunca rompen el flujo
    de pago (mismo criterio que `_trigger_bambuddy_print`).
    """
    api_url = getattr(settings, "PRESUPUESTOS3D_API_URL", "").rstrip("/")
    api_token = getattr(settings, "PRESUPUESTOS3D_API_TOKEN", "")

    if not api_url or not api_token:
        logger.debug(
            "presupuestos3d no configurado — se omite aviso de venta para orden %s", order.id
        )
        return

    items = [
        {
            "product_name": item.product_name,
            "quantity": item.quantity,
            "unit_price": float(item.unit_price),
        }
        for item in order.order_items.all()
    ]
    payload = json.dumps({
        "external_reference": order.external_reference,
        "brand_slug": order.brand.slug if order.brand_id else "",
        "brand_name": order.brand.name if order.brand_id else "",
        "customer_email": order.customer_email,
        "items": items,
        "total_amount": float(order.total_amount),
        "currency": order.currency,
        "order_created_at": order.created_at.isoformat() if order.created_at else None,
        "raw_payload": {
            "order_id": str(order.id),
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{api_url}/api/pedidos-online/",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Token {api_token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            logger.info(
                "presupuestos3d: aviso de venta creado #%s — orden=%s",
                result.get("id"), order.id,
            )
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error(
            "presupuestos3d HTTP %s al avisar venta orden=%s: %s",
            e.code, order.id, body,
        )
    except Exception as e:
        logger.error(
            "presupuestos3d error inesperado al avisar venta orden=%s: %s",
            order.id, e,
        )


def _create_correo_argentino_shipment(order):
    """Da de alta el envío real en Correo Argentino (API MiCorreo,
    `POST /shipping/import`) cuando el pedido se paga, para cualquiera de
    las dos modalidades (sucursal/domicilio).

    Mismo patrón no-bloqueante que `_notify_presupuestos3d`/`_trigger_bambuddy_print`:
    un fallo (sin credenciales, o la API rechazando el alta) se guarda en
    `correo_argentino_sync_error` y se loguea, pero nunca rompe la
    confirmación del pago. El dueño puede reintentar desde el admin
    (acción "Reintentar alta en Correo Argentino").

    La API real **no devuelve tracking number** en la respuesta (solo
    `{"createdAt": ...}`) — el identificador del envío de cara a Correo
    Argentino es nuestro propio `extOrderId`, que es `order.external_reference`.
    Por eso `correo_argentino_tracking_number` se completa con ese mismo
    valor en éxito, no con algo que devuelva la API.
    """
    if order.shipping_method != "correoargentino":
        return

    try:
        correo_argentino.create_shipment(order)
    except CorreoArgentinoConfigError as e:
        logger.info(
            "Correo Argentino no configurado — no se da de alta el envío de la orden %s: %s",
            order.id, e,
        )
        order.correo_argentino_sync_error = str(e)
        order.save(update_fields=["correo_argentino_sync_error"])
        return
    except CorreoArgentinoError as e:
        logger.error("Correo Argentino: no se pudo dar de alta el envío de la orden %s: %s", order.id, e)
        order.correo_argentino_sync_error = str(e)
        order.save(update_fields=["correo_argentino_sync_error"])
        return
    except Exception as e:
        logger.error("Correo Argentino: error inesperado al dar de alta el envío de la orden %s: %s", order.id, e)
        order.correo_argentino_sync_error = str(e)
        order.save(update_fields=["correo_argentino_sync_error"])
        return

    order.correo_argentino_tracking_number = order.external_reference
    order.correo_argentino_sync_error = ""
    order.save(update_fields=["correo_argentino_tracking_number", "correo_argentino_sync_error"])
    logger.info(
        "Correo Argentino: envío dado de alta — orden=%s extOrderId=%s",
        order.id, order.external_reference,
    )


def _cancel_correo_argentino_shipment(order):
    """La API real de Correo Argentino (MiCorreo) **no tiene endpoint de
    cancelación** — a diferencia de lo asumido en una iteración anterior de
    esta integración. Si el pedido ya tenía un envío dado de alta
    (`correo_argentino_tracking_number`) y el pago se cae
    (`PAID → REJECTED/CANCELLED`), solo se loguea para que el dueño lo
    cancele a mano desde el panel de MiCorreo — no hay nada que llamar acá.
    Nunca rompe la restitución de stock."""
    if not order.correo_argentino_tracking_number:
        return

    logger.warning(
        "Correo Argentino: la orden %s (extOrderId=%s) pasó a %s después de tener un envío "
        "dado de alta — la API no tiene endpoint de cancelación, hay que cancelarlo a mano "
        "desde el panel de MiCorreo.",
        order.id, order.correo_argentino_tracking_number, order.status,
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
    presupuestos3d_note = (
        "\nYa debería estar como aviso pendiente en el admin de presupuestos3d "
        "para que lo cargues y pongas a producir.\n"
        if getattr(settings, "PRESUPUESTOS3D_API_URL", "") and getattr(settings, "PRESUPUESTOS3D_API_TOKEN", "")
        else ""
    )
    subject = f"Nueva venta — {order.brand.name} — {order.currency} {order.total_amount}"
    message = (
        f"Nueva venta confirmada en {order.brand.name}.\n\n"
        f"Orden: {order.id}\n"
        f"Cliente: {order.customer_email or '(sin email, compra de invitado)'}\n"
        f"{presupuestos3d_note}\n"
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
