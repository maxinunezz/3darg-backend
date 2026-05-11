import logging
from django.db import transaction
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.conf import settings

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
