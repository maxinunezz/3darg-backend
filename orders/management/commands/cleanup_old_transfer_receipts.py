"""Borra los comprobantes de transferencia de pedidos ya `PAID` hace más de
`TRANSFER_RECEIPT_RETENTION_DAYS` días (default 90, ver `config/settings.py`)
— un comprobante solo existe para que el dueño confirme el pago; una vez
confirmado y pasado un margen prudencial, ya no aporta nada guardado para
siempre, y compite por el mismo cupo de storage de Cloudinary que las fotos
de producto/marca/CMS (ver nota de storage en CLAUDE.md).

Storage-agnóstico: llama `order.transfer_receipt.delete(save=...)`, que el
backend de storage activo resuelve solo (Cloudinary en producción, disco en
dev) — no hay nada específico de Cloudinary en este comando.

Pensado para correr por un **Railway Cron Job** (recomendado, ver CLAUDE.md
→ "Deploy en producción" — no hay Celery/scheduler en este proyecto, un
cron diario no justifica sumar esa infraestructura). Mientras no esté
cargado, se puede correr a mano o usar la acción de admin equivalente
("Eliminar comprobantes de pedidos confirmados...", `orders/admin.py`).

Uso:
    python manage.py cleanup_old_transfer_receipts
    python manage.py cleanup_old_transfer_receipts --days 30   # override puntual
    python manage.py cleanup_old_transfer_receipts --dry-run   # solo lista, no borra

Cron Job sugerido en Railway (diario, 6am):
    0 6 * * *   →  Start Command: python manage.py cleanup_old_transfer_receipts
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from orders.services.transfer_receipt_retention import delete_old_transfer_receipts


class Command(BaseCommand):
    help = "Borra comprobantes de transferencia de pedidos PAID confirmados hace más de N días."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Días desde la confirmación (default: settings.TRANSFER_RECEIPT_RETENTION_DAYS).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra qué comprobantes borraría sin tocar nada.",
        )

    def handle(self, *args, **options):
        days = options["days"] if options["days"] is not None else settings.TRANSFER_RECEIPT_RETENTION_DAYS
        dry_run = options["dry_run"]

        if days <= 0:
            self.stdout.write(self.style.WARNING(
                "Retención desactivada (días <= 0) — no se borra nada."
            ))
            return

        orders = delete_old_transfer_receipts(days=days, dry_run=dry_run)

        if not orders:
            self.stdout.write("No hay comprobantes para borrar.")
            return

        refs = ", ".join(order.external_reference or str(order.id) for order in orders)
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"[dry-run] {len(orders)} comprobante(s) se borrarían (pedidos: {refs})."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"{len(orders)} comprobante(s) borrados (pedidos: {refs})."
            ))
