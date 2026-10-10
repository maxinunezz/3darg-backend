from django.db import migrations

# Hardcodeado a propósito (no se importa desde products.models.Product.CutterSize):
# una migración de datos tiene que quedar congelada en el tiempo, no depender del
# estado futuro del modelo real (si mañana se agrega/saca un choice, esta migración
# vieja no debe cambiar de comportamiento).
CUTTER_SIZE_LABELS = {
    "mini": "Mini",
    "chico": "Chico",
    "mediano": "Mediano",
    "grande": "Grande",
    "a_medida": "A medida",
}


def crear_variantes_y_templates(apps, schema_editor):
    """Fase 1 del modelo de variantes: por cada Product existente, crea
    EXACTAMENTE un ProductVariant copiando 1:1 sus datos de venta (precio,
    stock, sku, medidas, color/tamaño, gtin, disponibilidad) — no cambia
    ningún comportamiento actual, nada lee ProductVariant todavía.

    Además crea un CostTemplate por cada valor de cutter_size en uso hoy
    (ver CUTTER_SIZE_LABELS), para no perder la agrupación histórica de
    costeo, y liga cada variante migrada al template que corresponde a su
    Product de origen. `sale_price` queda vacío en estos templates migrados
    a propósito: los productos de un mismo cutter_size pueden tener hoy
    precios distintos entre sí (cutter_size siempre fue solo una etiqueta
    de costeo, nunca forzó un precio único), así que no hay un valor
    correcto para completar acá sin inventarlo.
    """
    Product = apps.get_model("products", "Product")
    CostTemplate = apps.get_model("products", "CostTemplate")
    ProductVariant = apps.get_model("products", "ProductVariant")

    templates_por_cutter_size = {}
    for valor, etiqueta in CUTTER_SIZE_LABELS.items():
        if Product.objects.filter(cutter_size=valor).exists():
            templates_por_cutter_size[valor] = CostTemplate.objects.create(
                nombre=f"{etiqueta} (migrado automático)",
                legacy_cutter_size=valor,
            )

    variantes = [
        ProductVariant(
            product=product,
            color=product.color,
            size=product.size,
            sku=product.sku,
            price=product.price,
            stock=product.stock,
            cost_template=templates_por_cutter_size.get(product.cutter_size),
            weight_kg=product.weight_kg,
            length_cm=product.length_cm,
            width_cm=product.width_cm,
            height_cm=product.height_cm,
            gtin=product.gtin,
            is_available=product.is_available,
        )
        for product in Product.objects.all()
    ]
    ProductVariant.objects.bulk_create(variantes)


def eliminar_variantes_y_templates(apps, schema_editor):
    """Reversa de `crear_variantes_y_templates`: borra todo lo creado.

    Seguro porque, en Fase 1, nada más del sistema referencia todavía
    ProductVariant/CostTemplate (ni cart, ni orders, ni ML, ni el feed) —
    no hay FKs externas que se queden huérfanas al borrar estas filas.
    """
    ProductVariant = apps.get_model("products", "ProductVariant")
    CostTemplate = apps.get_model("products", "CostTemplate")
    ProductVariant.objects.all().delete()
    CostTemplate.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0034_crear_productvariant_y_costtemplate'),
    ]

    operations = [
        migrations.RunPython(crear_variantes_y_templates, eliminar_variantes_y_templates),
    ]
