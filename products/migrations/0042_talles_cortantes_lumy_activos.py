"""Prende (`is_available=True`) los talles Chico/Mediano/Grande de todos los
cortantes de Lumy. Regla del dueño (2026-11-16): se produce bajo pedido, los
tres talles siempre están a la venta. En producción había 7 Mediano de
Animales de Granja apagados a mano, que la tienda ocultaba.

Autocontenida (modelos históricos), igual que 0041. Reversa: no-op — no hay
forma confiable de saber cuáles estaban apagados antes (quedan en el backup
tomado antes del deploy).
"""

from django.db import migrations

NOMBRES = ("Chico 4-6cm", "Mediano 7-9cm", "Grande 10-12cm")


def aplicar(apps, schema_editor):
    Category = apps.get_model("products", "Category")
    ProductVariant = apps.get_model("products", "ProductVariant")
    raiz = Category.objects.filter(slug="cortantes", parent__isnull=True).first()
    if raiz is None:
        return
    cats = [raiz.pk, *Category.objects.filter(parent=raiz).values_list("pk", flat=True)]
    n = ProductVariant.objects.filter(
        product__brand__slug="lumy",
        product__category_id__in=cats,
        size__in=NOMBRES,
        is_available=False,
    ).update(is_available=True)
    print(f"\n  Talles cortantes Lumy prendidos: {n}.")


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0041_talles_cortantes_lumy"),
    ]

    operations = [
        migrations.RunPython(aplicar, migrations.RunPython.noop),
    ]
