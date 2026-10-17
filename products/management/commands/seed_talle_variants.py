from django.core.management.base import BaseCommand
from django.db import transaction

from products.models import Product, ProductVariant

# Las tres "tallas" que debe poder mostrar el selector del frontend en TODOS
# los productos — pedido explícito del dueño: "quiero que todos los
# productos soporten talles [...] y los que no tengan un producto de esa
# variante ponele como agotado en el frontend". `order` fija el orden de
# aparición (Chico -> Mediano -> Grande), no el alfabético.
SIZE_CHICO = "Chico 3cm"
SIZE_MEDIANO = "Mediano 5cm"
SIZE_GRANDE = "Grande 8cm"

TARGET_SIZES = {SIZE_CHICO: 0, SIZE_MEDIANO: 1, SIZE_GRANDE: 2}

# Sufijos de SKU para las variantes placeholder nuevas (`sku` es único en
# todo `ProductVariant`, ver products/models.py) — se derivan del SKU real
# de la variante que se promueve a "Mediano 5cm", nunca se inventan de cero.
SKU_SUFFIXES = {SIZE_CHICO: "-CH", SIZE_GRANDE: "-GR"}


class Command(BaseCommand):
    help = (
        "Siembra la estructura de talles Chico 3cm / Mediano 5cm / Grande 8cm "
        "en TODOS los productos del catálogo, para que el selector de Talle "
        "del frontend (que hoy no se muestra en ningún lado porque cada "
        "Product tiene exactamente una ProductVariant) aparezca en todas las "
        "fichas. La variante real existente de cada producto se promueve a "
        "'Mediano 5cm' (conserva su precio/stock/SKU/cost_template real); las "
        "dos variantes nuevas ('Chico 3cm'/'Grande 8cm') se crean como "
        "placeholder sin stock (stock=0, is_available=True) para que el "
        "frontend las muestre deshabilitadas como 'Agotado' en vez de "
        "ocultarlas (el serializer solo esconde variantes is_available=False). "
        "Re-ejecutable: no duplica nada, solo completa lo que falte."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="No escribe nada, solo lista qué haría."
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        promoted = 0
        created_chico = 0
        created_grande = 0
        already_ok = 0
        skipped_no_base = []
        skipped_ambiguous = []

        for product in Product.objects.prefetch_related("variants").order_by("pk"):
            variants = list(product.variants.all())
            by_size = {v.size: v for v in variants}

            mediano = by_size.get(SIZE_MEDIANO)

            if mediano is None:
                # Candidata a promover: la variante "base" que no sea ya uno
                # de los dos placeholders de los extremos (Chico/Grande).
                candidates = [v for v in variants if v.size not in (SIZE_CHICO, SIZE_GRANDE)]
                if len(candidates) == 0:
                    skipped_no_base.append(product)
                    continue
                if len(candidates) > 1:
                    skipped_ambiguous.append(product)
                    continue
                mediano = candidates[0]
                self.stdout.write(
                    f"  {'[dry-run] ' if dry_run else ''}promover variante #{mediano.pk} "
                    f"de '{product.name}' (pk={product.pk}): size={mediano.size!r} -> {SIZE_MEDIANO!r}"
                )
                if not dry_run:
                    # OJO: .save() en ProductVariant pisa `size` con el
                    # size_label del cost_template vinculado (ver save() en
                    # products/models.py) — por eso se renombra con .update()
                    # a nivel QuerySet, el mismo criterio que ya usan
                    # CosteoSyncAPIView y la acción de bulk del admin.
                    ProductVariant.objects.filter(pk=mediano.pk).update(
                        size=SIZE_MEDIANO, order=TARGET_SIZES[SIZE_MEDIANO]
                    )
                promoted += 1
            elif mediano.order != TARGET_SIZES[SIZE_MEDIANO] and not dry_run:
                ProductVariant.objects.filter(pk=mediano.pk).update(
                    order=TARGET_SIZES[SIZE_MEDIANO]
                )

            base_sku = mediano.sku
            base_price = mediano.price

            for size_label in (SIZE_CHICO, SIZE_GRANDE):
                if size_label in by_size:
                    already_ok += 1
                    continue
                sku = f"{base_sku}{SKU_SUFFIXES[size_label]}" if base_sku else ""
                self.stdout.write(
                    f"  {'[dry-run] ' if dry_run else ''}crear variante '{size_label}' "
                    f"para '{product.name}' (pk={product.pk}), sku={sku!r}, agotado"
                )
                if not dry_run:
                    with transaction.atomic():
                        ProductVariant.objects.get_or_create(
                            product=product,
                            color="",
                            size=size_label,
                            defaults=dict(
                                order=TARGET_SIZES[size_label],
                                sku=sku,
                                price=base_price,
                                stock=0,
                                is_available=True,
                            ),
                        )
                if size_label == SIZE_CHICO:
                    created_chico += 1
                else:
                    created_grande += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"{'[dry-run] ' if dry_run else ''}Variantes 'Mediano 5cm' promovidas: {promoted}. "
                f"'Chico 3cm' creadas: {created_chico}. 'Grande 8cm' creadas: {created_grande}. "
                f"Ya estaban completas: {already_ok}."
            )
        )
        if skipped_no_base:
            self.stdout.write(
                self.style.WARNING(
                    f"Productos sin ninguna variante (no se les pudo asignar 'Mediano 5cm'): "
                    f"{len(skipped_no_base)}"
                )
            )
            for p in skipped_no_base:
                self.stdout.write(f"   - pk={p.pk}: {p.name}")
        if skipped_ambiguous:
            self.stdout.write(
                self.style.WARNING(
                    f"Productos con más de una variante candidata a 'Mediano 5cm' "
                    f"(revisar a mano): {len(skipped_ambiguous)}"
                )
            )
            for p in skipped_ambiguous:
                self.stdout.write(f"   - pk={p.pk}: {p.name}")
