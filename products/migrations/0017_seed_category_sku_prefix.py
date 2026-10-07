# Carga los códigos cortos de SKU para las categorías raíz que ya existen.
# Solo aplica a categorías de nivel superior (parent=None) — las
# subcategorías heredan el código de su raíz vía Category.root_sku_prefix(),
# no necesitan sku_prefix propio.
from django.db import migrations

# (brand_slug, category_slug) -> código.
SKU_PREFIXES = {
    ("3darg", "diseno-3d"): "D3D",
    ("3darg", "diseno-de-autor"): "DAU",
    ("3darg", "impresion-3d"): "IMP",
    ("3darg", "miniaturas"): "MIN",
    ("3darg", "prototipado"): "PRO",
    ("lumy", "cortantes"): "COR",
    ("lumy", "rodillos-texturizadores"): "ROD",
    ("lumy", "set-de-cortantes"): "SET",
    ("printgym", "llaveros"): "LLA",
    ("printgym", "shaker"): "SHK",
}


def seed_category_sku_prefix(apps, schema_editor):
    Category = apps.get_model("products", "Category")
    for (brand_slug, category_slug), prefix in SKU_PREFIXES.items():
        Category.objects.filter(
            brand__slug=brand_slug,
            slug=category_slug,
            parent__isnull=True,
            sku_prefix="",
        ).update(sku_prefix=prefix)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0016_category_sku_prefix_product_color_product_size_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_category_sku_prefix, noop),
    ]
