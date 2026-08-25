"""Red de seguridad: reconcilia órdenes PENDING contra MercadoPago.

¿Por qué existe? En Argentina buena parte de los pagos son offline
(efectivo/Rapipago/Pago Fácil/transferencia). Esos se aprueban HORAS o DÍAS
después de generar la preferencia, y el cliente casi nunca vuelve a la página
de éxito. Si el webhook falla o llega tarde, la orden quedaría PENDING para
siempre y el stock nunca se descontaría.

Este comando barre las órdenes PENDING y le pregunta a MP por cada una
(search_payments por external_reference). Está pensado para correr por cron.

Uso:
    python manage.py reconcile_pending_payments
    python manage.py reconcile_pending_payments --older-than 10   # minutos
    python manage.py reconcile_pending_payments --max-age-days 7
    python manage.py reconcile_pending_payments --dry-run

Cron sugerido (cada 15 min):
    */15 * * * * docker compose exec -T web python manage.py reconcile_pending_payments
"""
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from orders.models import Order
from payments.services.reconciliation import reconcile_order

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Reconcilia órdenes PENDING contra MercadoPago (red de seguridad sin webhook)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than",
            type=int,
            default=5,
            help="Solo órdenes creadas hace más de N minutos (default: 5). "
                 "Evita pisar checkouts recién iniciados.",
        )
        parser.add_argument(
            "--max-age-days",
            type=int,
            default=30,
            help="Ignora órdenes más viejas que N días (default: 30). "
                 "Pasado ese plazo el pago ya no se va a concretar.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra qué haría sin tocar la DB ni consultar MP.",
        )

    def handle(self, *args, **options):
        older_than = options["older_than"]
        max_age_days = options["max_age_days"]
        dry_run = options["dry_run"]

        now = timezone.now()
        upper = now - timedelta(minutes=older_than)
        lower = now - timedelta(days=max_age_days)

        pending = (
            Order.objects.filter(
                status=Order.Status.PENDING,
                created_at__lte=upper,
                created_at__gte=lower,
            )
            .order_by("created_at")
        )

        total = pending.count()
        self.stdout.write(
            f"Órdenes PENDING a revisar: {total} "
            f"(creadas entre {lower:%Y-%m-%d %H:%M} y {upper:%Y-%m-%d %H:%M})"
        )

        if dry_run:
            for order in pending:
                self.stdout.write(
                    f"  [dry-run] {order.id} ref={order.external_reference} "
                    f"creada={order.created_at:%Y-%m-%d %H:%M}"
                )
            self.stdout.write(self.style.WARNING("Dry-run: no se tocó nada."))
            return

        changed = 0
        errors = 0
        for order in pending:
            try:
                before = order.status
                after = reconcile_order(order)
                if after != before:
                    changed += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  {order.id}: {before} → {after}"
                        )
                    )
            except Exception as e:
                errors += 1
                logger.error("Error reconciliando orden %s: %s", order.id, e)
                self.stderr.write(self.style.ERROR(f"  {order.id}: error → {e}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Listo. Revisadas={total} actualizadas={changed} errores={errors}"
            )
        )
