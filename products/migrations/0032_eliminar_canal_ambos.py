# Generated manually (migración de datos antes de borrar ml_order/choice "both")

from django.db import migrations
from django.db.models import F


def dividir_canal_ambos(apps, schema_editor):
    """Cada ProductImage pasa a pertenecer a UN solo canal (web o ml) — se
    elimina el choice "both" (`ProductImage.Channel.BOTH`) y el campo
    `ml_order` (ver migración siguiente, que ya borra la columna).

    Antes de borrar `ml_order`, cada fila con `channel="both"`:
    - se convierte en la fila "web" (conserva `order` tal cual, ya era el
      orden de la web).
    - se duplica en una fila nueva "ml" (mismo `image`/`alt`), con
      `order = ml_order` si estaba cargado, sino el mismo `order` de la web
      — así no se pierde ninguna foto ML-elegible (ver
      `mercadolibre/services.py::MIN_ML_PICTURES`).

    Además, las filas que ya eran `channel="ml"` (sin pasar por "both") y
    tenían `ml_order` cargado, vuelcan ese valor a `order` — a partir de
    ahora `order` es el único campo de orden, por canal.
    """
    ProductImage = apps.get_model("products", "ProductImage")

    for img in ProductImage.objects.filter(channel="both"):
        ml_order = img.ml_order if img.ml_order is not None else img.order
        ProductImage.objects.create(
            product_id=img.product_id,
            image=img.image,
            alt=img.alt,
            channel="ml",
            order=ml_order,
        )
        img.channel = "web"
        img.save(update_fields=["channel"])

    ProductImage.objects.filter(channel="ml", ml_order__isnull=False).update(
        order=F("ml_order")
    )


def revertir(apps, schema_editor):
    # No reversible de forma segura: no hay manera de distinguir, entre las
    # filas "web"/"ml" resultantes, cuáles vinieron de un "both" original y
    # cuáles ya eran así — no-op a propósito (mismo criterio que
    # 0028_apagar_ml_sin_fotos_suficientes.py).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0031_agregar_shape_dishwasher_safe"),
    ]

    operations = [
        migrations.RunPython(dividir_canal_ambos, revertir),
    ]
