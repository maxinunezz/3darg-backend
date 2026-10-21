"""Cancela automáticamente los pedidos por transferencia bancaria que
quedaron `PENDING` más de `TRANSFER_PENDING_EXPIRATION_HOURS` (default 48,
ver `config/settings.py`) sin que el dueño confirme el ingreso del pago
("Confirmar transferencia recibida" en el admin, ver `orders/admin.py`).

¿Por qué existe? A diferencia de MercadoPago (que avisa solo vía webhook si
el pago se rechaza/expira), el canal transferencia depende 100% de que el
dueño revise el banco a mano — si nunca transfieren, el pedido se quedaría
`PENDING` para siempre, con el stock nunca liberado para otros compradores
(en este canal el stock NUNCA se descuenta mientras está `PENDING`, así que
"liberar" acá es un no-op real, pero el pedido igual queda cancelado para
no ensuciar el panel/reportes con pedidos zombies).

Mismo patrón que `payments/management/commands/reconcile_pending_payments.py`
(pensado para correr por cron), pero sin llamar a ninguna API externa — es
una comparación de fechas pura contra la propia DB.

Uso:
    python manage.py expire_pending_transfers
    python manage.py expire_pending_transfers --hours 48   # override puntual
    python manage.py expire_pending_transfers --dry-run

Cron sugerido (cada hora):
    0 * * * * docker compose exec -T web python manage.py expire_pending_transfers
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from orders.models import Order

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Cancela pedidos PENDING de transferencia bancaria vencidos (sin confirmar a tiempo)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=None,
            help="Horas de gracia antes de cancelar (default: "
                 "settings.TRANSFER_PENDING_EXPIRATION_HOURS).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra qué pedidos cancelaría sin tocar la DB.",
        )

    def handle(self, *args, **options):
        hours = options["hours"] if options["hours"] is not None else settings.TRANSFER_PENDING_EXPIRATION_HOURS
        dry_run = options["dry_run"]

        cutoff = timezone.now() - timedelta(hours=hours)
        vencidos = Order.objects.filter(
            status=Order.Status.PENDING,
            payment_channel=Order.PaymentChannel.TRANSFER,
            created_at__lte=cutoff,
        ).order_by("created_at")

        total = vencidos.count()
        self.stdout.write(
            f"Pedidos PENDING de transferencia vencidos (creados antes de "
            f"{cutoff:%Y-%m-%d %H:%M}, gracia={hours}h): {total}"
        )

        if dry_run:
            for order in vencidos:
                self.stdout.write(
                    f"  [dry-run] {order.id} ref={order.external_reference} "
                    f"creada={order.created_at:%Y-%m-%d %H:%M}"
                )
            self.stdout.write(self.style.WARNING("Dry-run: no se canceló nada."))
            return

        cancelados = 0
        errores = 0
        for order in vencidos:
            try:
                order.status = Order.Status.CANCELLED
                order.save()
                cancelados += 1
                self.stdout.write(self.style.SUCCESS(f"  {order.id}: PENDING → CANCELLED (vencido)"))
            except Exception as e:
                errores += 1
                logger.error("Error cancelando orden %s por vencimiento de transferencia: %s", order.id, e)
                self.stderr.write(self.style.ERROR(f"  {order.id}: error → {e}"))

        self.stdout.write(
            self.style.SUCCESS(f"Listo. Revisados={total} cancelados={cancelados} errores={errores}")
        )
