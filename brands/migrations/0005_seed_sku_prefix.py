# Carga los códigos cortos de SKU acordados para las marcas que ya existen.
# Nuevas marcas (ej: MiniSlam/CyberWeed cuando carguen catálogo) ya nacen con
# brand_type definido a mano en el admin — este mismo criterio aplica para
# sku_prefix: se carga ahí, esta migración solo resuelve el backfill inicial.
from django.db import migrations

# slug -> código. Elegidos para que no colisionen entre sí y sean legibles.
SKU_PREFIXES = {
    "3darg": "DRG",
    "lumy": "LUMY",
    "printgym": "PYG",
    "minislam": "MSL",
    "cyberweed": "CYW",
}


def seed_sku_prefix(apps, schema_editor):
    Brand = apps.get_model("brands", "Brand")
    for slug, prefix in SKU_PREFIXES.items():
        Brand.objects.filter(slug=slug, sku_prefix="").update(sku_prefix=prefix)


def noop(apps, schema_editor):
    # No hace falta revertir: dejar el sku_prefix cargado no rompe nada.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('brands', '0004_brand_sku_prefix'),
    ]

    operations = [
        migrations.RunPython(seed_sku_prefix, noop),
    ]
