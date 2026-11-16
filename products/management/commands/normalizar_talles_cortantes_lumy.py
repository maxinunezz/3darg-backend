from django.core.management.base import BaseCommand
from django.db import transaction

from products.models import Product
from products.talles_lumy import BRAND_SLUG, TALLES, categorias_cortantes_ids, normalizar_talles


class Command(BaseCommand):
    help = (
        "Aplica la regla de talles a TODOS los cortantes de Lumy: exactamente "
        + " / ".join(nombre for _, nombre, _, _ in TALLES)
        + ". Renombra los talles existentes y crea los que falten (stock 0, "
        "mismo precio). No borra nada. Re-ejecutable."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Muestra qué haría, sin guardar.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        productos = Product.objects.filter(
            brand__slug=BRAND_SLUG, category_id__in=categorias_cortantes_ids()
        ).order_by("pk")

        totales = {"productos": 0, "renombradas": 0, "creadas": 0}
        with transaction.atomic():
            for product in productos:
                r = normalizar_talles(product)
                totales["productos"] += 1
                totales["renombradas"] += r["renombradas"]
                totales["creadas"] += r["creadas"]
                if r["creadas"] or r["no_reconocidas"]:
                    extra = f", talles sin tocar: {r['no_reconocidas']}" if r["no_reconocidas"] else ""
                    self.stdout.write(f"  {product.name} (pk={product.pk}): creadas {r['creadas']}{extra}")
            if dry_run:
                transaction.set_rollback(True)

        prefijo = "[dry-run] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefijo}Cortantes de Lumy: {totales['productos']}. "
                f"Talles renombrados: {totales['renombradas']}. Talles creados: {totales['creadas']}."
            )
        )
