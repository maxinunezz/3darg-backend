from django.db import migrations

PREFIJO = "Cortante "


def sacar_prefijo(apps, schema_editor):
    """Saca el prefijo redundante "Cortante " del `name` de los productos
    de la categoría raíz "Cortantes" (hoy, todos los productos de Lumy) —
    la categoría ya dice "Cortante", repetirlo en el nombre es ruido (ej:
    "Cortante Cebra" -> "Cebra").

    Solo toca productos cuya categoría (raíz, subiendo por `parent`) sea
    "Cortantes" y cuyo `name` arranque con el prefijo exacto — no toca
    productos de otras categorías/marcas que puedan llamarse "Cortante X"
    por coincidencia.
    """
    Product = apps.get_model("products", "Product")

    for product in Product.objects.select_related("category", "category__parent").filter(
        name__startswith=PREFIJO
    ):
        category = product.category
        if category is None:
            continue
        root = category.parent if category.parent_id else category
        if root.slug != "cortantes":
            continue
        nuevo_nombre = product.name[len(PREFIJO):].strip()
        if nuevo_nombre:
            product.name = nuevo_nombre
            product.save(update_fields=["name"])


def revertir(apps, schema_editor):
    """Vuelve a anteponer "Cortante " a los productos de la categoría
    "Cortantes" que no lo tengan ya.

    Es un revert "best effort" para el dataset de producción al momento de
    escribir esta migración (ahí, todos los productos de Cortantes tenían
    el prefijo) — no hay forma de distinguir "nunca tuvo el prefijo" de
    "se lo sacamos" sin guardar estado extra, así que un producto nuevo
    cargado ya sin el prefijo (el comportamiento deseado de acá en más)
    también lo recibiría si se corre este revert más adelante.
    """
    Product = apps.get_model("products", "Product")

    for product in Product.objects.select_related("category", "category__parent"):
        category = product.category
        if category is None:
            continue
        root = category.parent if category.parent_id else category
        if root.slug != "cortantes":
            continue
        if not product.name.startswith(PREFIJO):
            product.name = f"{PREFIJO}{product.name}"
            product.save(update_fields=["name"])


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0025_cutter_size_a_medida"),
    ]

    operations = [
        migrations.RunPython(sacar_prefijo, revertir),
    ]
