# Regenera el SKU de TODOS los productos existentes al nuevo formato
# MARCA-CATEGORIA-NNNNNN[-VARIANTE] (ver Product.generate_sku()).
#
# Se corre una sola vez, a pedido: hasta este momento el SKU era puramente
# secuencial ("3DARG-000037") sin ningún significado, no se usa en ningún
# lado del frontend, y de ~380 productos solo 1 estaba publicado en Mercado
# Libre — ventana de bajo riesgo para resetear el formato antes de que el
# catálogo/las publicaciones crezcan más.
#
# Después de esta migración, el SKU vuelve a quedar "congelado": no se
# recalcula solo si cambiás marca/categoría/color más adelante.
from django.db import migrations
from django.utils.text import slugify


def _root_sku_prefix(category, cache):
    """Replica Category.root_sku_prefix() con el modelo histórico (sin
    métodos custom): sube por `parent` hasta la raíz y devuelve su
    sku_prefix, con el mismo fallback basado en el slug."""
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

        base = f"{brand_code}-{category_code}-{producto.pk:06d}"

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
    # No hay vuelta atrás automática: el SKU viejo era puramente secuencial
    # y no se guarda en ningún lado para reconstruirlo.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0017_seed_category_sku_prefix'),
        ('brands', '0005_seed_sku_prefix'),
    ]

    operations = [
        migrations.RunPython(regenerar_skus, noop),
    ]
