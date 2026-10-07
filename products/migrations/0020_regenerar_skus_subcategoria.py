from django.db import migrations
from django.utils.text import slugify


def _root_sku_prefix(category, cache):
    if category.pk in cache:
        return cache[category.pk]
    node = category
    seen = {node.pk}
    while node.parent_id and node.parent_id not in seen:
        node = node.parent
        seen.add(node.pk)
    prefix = node.sku_prefix or (slugify(node.slug).replace("-", "").upper()[:3] or "CAT")
    cache[category.pk] = prefix
    return prefix


def regenerar_skus(apps, schema_editor):
    """Recalcula en lote los SKU afectados por el nuevo segmento de
    subcategoría (ver migración 0019): solo cambian los productos cuya
    categoría tiene ahora un sku_prefix propio (hoy, las subcategorías de
    Cortantes en Lumy) — el resto queda idéntico.
    """
    Product = apps.get_model("products", "Product")
    category_prefix_cache = {}
    productos = Product.objects.select_related("brand", "category").all()
    actualizados = []
    for producto in productos:
        if producto.brand_id and producto.brand.sku_prefix:
            brand_code = producto.brand.sku_prefix
        elif producto.brand_id:
            brand_code = slugify(producto.brand.slug).replace("-", "").upper()[:4] or "GEN"
        else:
            brand_code = "GEN"

        if producto.category_id:
            category_code = _root_sku_prefix(producto.category, category_prefix_cache)
        else:
            category_code = "GEN"

        base = f"{brand_code}-{category_code}"

        if producto.category_id and producto.category.parent_id and producto.category.sku_prefix:
            base += f"-{producto.category.sku_prefix}"

        base += f"-{producto.pk:06d}"

        variant_parts = []
        for value in (producto.color, producto.size):
            if value:
                code = slugify(value).replace("-", "").upper()
                if code:
                    variant_parts.append(code)
        if variant_parts:
            base += "-" + "-".join(variant_parts)

        if producto.sku != base:
            producto.sku = base
            actualizados.append(producto)

    if actualizados:
        Product.objects.bulk_update(actualizados, ["sku"], batch_size=200)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0019_seed_subcategoria_sku_prefix_cortantes"),
    ]

    operations = [
        migrations.RunPython(regenerar_skus, noop),
    ]
