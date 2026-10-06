"""Servicio de reconciliación de pagos MercadoPago.

Fuente de verdad ÚNICA para pasar una orden de PENDING a su estado real.
La usan tres consumidores:
  1. El webhook (payments/views.py) → cuando MP nos avisa.
  2. La página de éxito (OrderReconcileAPIView) → cuando el cliente vuelve del checkout.
  3. El comando de cron (reconcile_pending_payments) → red de seguridad para
     pagos offline (efectivo/Rapipago/transferencia) que se aprueban horas o
     días después y sin que el cliente vuelva a la página de éxito.

Todo pasa por acá para que la lógica de mapeo de estado, idempotencia y
disparo del signal de stock/email viva en un solo lugar.
"""
import logging

from django.db import transaction

from orders.models import Order
from ..models import MercadoPagoPayment
from .mercadopago import search_payments

logger = logging.getLogger(__name__)


def _map_status(status_mp):
    """Traduce el estado de MP a (estado de orden, estado de pago MP).

    Devuelve new_order_status=None cuando el estado de MP no debe cambiar la
    orden (ej: 'in_process', 'pending') para que el llamador conserve el actual.
    """
    if status_mp == "approved":
        return Order.Status.PAID, MercadoPagoPayment.Status.APPROVED
    if status_mp in ("rejected", "cancelled"):
        return Order.Status.REJECTED, MercadoPagoPayment.Status.REJECTED
    return None, MercadoPagoPayment.Status.PENDING


@transaction.atomic
def apply_payment_status(order_id, payment_info) -> bool:
    """Aplica el estado de un pago de MP sobre la orden. Idempotente.

    - Usa select_for_update para evitar carreras (webhook + cron + success page
      pueden dispararse casi simultáneamente sobre la misma orden).
    - Nunca "degrada" una orden ya PAID (el signal de stock ya corrió).
    - order.save() con cambio de status dispara el signal de orders que
      descuenta/repone stock y manda el email. No duplicamos esa lógica acá.

    Devuelve True si hubo algún cambio, False si no (duplicado / sin novedad).
    """
    order = Order.objects.select_for_update().get(pk=order_id)
    payment_id = str(payment_info.get("id", ""))
    status_mp = payment_info.get("status")

    new_order_status, new_mp_status = _map_status(status_mp)
    if new_order_status is None:
        new_order_status = order.status

    # Una orden ya pagada no vuelve atrás por un pago posterior rechazado.
    if order.status == Order.Status.PAID and new_order_status != Order.Status.PAID:
        new_order_status = Order.Status.PAID

    mp_payment = MercadoPagoPayment.objects.filter(order=order).first()

    # Idempotencia: mismo pago + mismo estado ya procesado → no hacemos nada.
    if (
        mp_payment
        and mp_payment.mp_payment_id == payment_id
        and mp_payment.status == new_mp_status
    ):
        logger.info(
            "Reconciliación sin novedad: order=%s payment=%s status=%s",
            order_id, payment_id, new_mp_status,
        )
        return False

    changed = False

    if order.status != new_order_status:
        order.status = new_order_status
        order.save()  # dispara el signal (stock + email)
        changed = True

    if mp_payment and (
        mp_payment.status != new_mp_status or mp_payment.mp_payment_id != payment_id
    ):
        mp_payment.status = new_mp_status
        mp_payment.mp_payment_id = payment_id
        raw = mp_payment.raw or {}
        raw["last_api_check"] = payment_info
        mp_payment.raw = raw
        mp_payment.save()
        changed = True

    if changed:
        logger.info(
            "Orden %s reconciliada: order_status=%s mp_status=%s payment=%s",
            order_id, new_order_status, new_mp_status, payment_id,
        )

    return changed


def _pick_relevant_payment(payments):
    """Elige el pago que representa el estado real de la orden.

    Un external_reference puede tener varios intentos de pago (el cliente
    reintentó). Priorizamos un pago aprobado; si no hay, el más reciente.
    """
    if not payments:
        return None
    approved = [p for p in payments if p.get("status") == "approved"]
    candidates = approved or payments
    return sorted(candidates, key=lambda p: p.get("date_created", "") or "")[-1]


def reconcile_order(order) -> str:
    """Consulta MP por external_reference y sincroniza la orden. Sin webhook.

    Devuelve el estado final de la orden (Order.Status.*).
    """
    if order.status == Order.Status.PAID:
        return order.status

    payments = search_payments(order.external_reference)
    payment = _pick_relevant_payment(payments)
    if not payment:
        logger.info(
            "Reconciliación: orden %s sin pagos en MP (ref=%s)",
            order.id, order.external_reference,
        )
        return order.status

    apply_payment_status(order.id, payment)
    order.refresh_from_db()
    return order.status
