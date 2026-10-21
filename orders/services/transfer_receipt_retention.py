"""Borrado de comprobantes de transferencia viejos — ya cumplieron su
función (que el dueño pudiera verificar el pago antes de confirmarlo) y no
hace falta guardarlos para siempre, a diferencia de las fotos de producto
que comparten el mismo pool de storage de Cloudinary (ver nota de storage
en `config/settings.py` y `3darg-backend/CLAUDE.md`).

Reusada por dos caminos, para no duplicar la lógica:
  - `orders/management/commands/cleanup_old_transfer_receipts.py` (pensado
    para correr por un Cron Job de Railway, ver CLAUDE.md → "Deploy en
    producción").
  - La acción de admin "Eliminar comprobantes de pedidos confirmados..."
    (`orders/admin.py`), como respaldo manual mientras no esté cargado el
    Cron Job (o para un caso puntual sin esperar al próximo disparo).
"""
import logging
from datetime import timedelta

from django.utils import timezone

from orders.models import Order

logger = logging.getLogger(__name__)


def delete_old_transfer_receipts(days: int, dry_run: bool = False, queryset=None):
    """Devuelve la lista de `Order` TRANSFER/PAID con comprobante,
    confirmados hace más de `days` días — y, si `dry_run=False`, borra el
    archivo de cada una (storage-agnóstico: funciona igual contra Cloudinary
    o `FileSystemStorage`, ver `Order.transfer_receipt`).

    Usa `Order.updated_at` como aproximación de "fecha de confirmación" (se
    actualiza cuando `orders/signals.py` pasa el pedido a PAID) — no hace
    falta un campo `confirmed_at` dedicado para este alcance: un pedido ya
    `PAID` casi no se vuelve a guardar por otro motivo.

    `days <= 0` = retención desactivada (mismo criterio "0 = apagado" de
    siempre): no hace nada, devuelve `[]`.

    `queryset`: opcional, para que la acción de admin pueda acotar el
    borrado a la selección manual del dueño en vez de TODOS los pedidos
    vencidos — si no se pasa, se usa `Order.objects.all()`.
    """
    if days <= 0:
        return []

    cutoff = timezone.now() - timedelta(days=days)
    base_qs = queryset if queryset is not None else Order.objects.all()
    candidates = base_qs.filter(
        payment_channel=Order.PaymentChannel.TRANSFER,
        status=Order.Status.PAID,
        updated_at__lte=cutoff,
    ).exclude(transfer_receipt="")

    orders = list(candidates)

    if dry_run:
        logger.info(
            "[dry-run] %d comprobante(s) de transferencia a borrar (confirmados antes de %s)",
            len(orders), cutoff,
        )
        return orders

    for order in orders:
        try:
            # `transfer_receipt_uploaded_at` queda como rastro histórico de
            # que *hubo* un comprobante, aunque el archivo ya no exista.
            order.transfer_receipt.delete(save=False)
            order.save(update_fields=["transfer_receipt"])
        except Exception as e:
            logger.error("Error borrando comprobante de transferencia de la orden %s: %s", order.id, e)

    logger.info(
        "%d comprobante(s) de transferencia borrados (confirmados antes de %s)",
        len(orders), cutoff,
    )
    return orders
