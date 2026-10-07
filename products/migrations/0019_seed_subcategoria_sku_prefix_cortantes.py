from django.db import migrations


def seed_subcategoria_sku_prefix(apps, schema_editor):
    """Carga el código de subcategoría (ej: "04") para las subcategorías de
    Cortantes (Lumy), tomándolo del número que ya tienen en el slug
    (ej: "cortantes-04-animales-de-la-selva" -> "04"). Se usa como segmento
    extra del SKU (ver Product.generate_sku()): LUMY-COR-04-000037.
    """
    Category = apps.get_model("products", "Category")
    cortantes = Category.objects.filter(
        brand__slug="lumy", slug="cortantes", parent__isnull=True
    ).first()
    if not cortantes:
        return
    subcategorias = Category.objects.filter(parent=cortantes, sku_prefix="")
    for subcategoria in subcategorias:
        partes = subcategoria.slug.split("-")
        if len(partes) > 1 and partes[1].isdigit():
            subcategoria.sku_prefix = partes[1]
            subcategoria.save(update_fields=["sku_prefix"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0018_regenerar_skus"),
    ]

    operations = [
        migrations.RunPython(seed_subcategoria_sku_prefix, noop),
    ]
