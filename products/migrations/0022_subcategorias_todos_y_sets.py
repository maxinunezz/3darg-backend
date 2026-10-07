from django.db import migrations


def crear_todos_y_sets(apps, schema_editor):
    """Reorganiza las categorías de nivel superior de Lumy (Cortantes,
    Rodillos Texturizadores) para que tengan dos subcategorías fijas además
    de los temas existentes (Halloween, Disney, etc.):

    - "Todos": para productos que no encajan en ningún tema puntual.
    - "Sets": para productos vendidos en combo/set.

    "Set de cortantes" (categoría de nivel superior, suelta, con 3
    productos) se reutiliza como "Sets" de Cortantes en vez de crear una
    categoría nueva — se le cambia el nombre y se la reparenta, el `pk` y
    el `slug` quedan iguales así no se pierden/rompen referencias (FK de
    los productos ya cargados, ni la URL `?category=set-de-cortantes` si
    quedó compartida en algún lado).

    Ver `products/admin.py::_GroupedCategoryIterator` (dropdown de
    categoría agrupado en el admin) y el sidebar de categorías de la
    tienda (`[brand]/shop/page.tsx`), que ya soportan subcategorías sin
    tocar código — esta migración solo toca datos.
    """
    Category = apps.get_model("products", "Category")

    cortantes = Category.objects.filter(
        brand__slug="lumy", slug="cortantes", parent__isnull=True
    ).first()
    rodillos = Category.objects.filter(
        brand__slug="lumy", slug="rodillos-texturizadores", parent__isnull=True
    ).first()
    if not cortantes or not rodillos:
        return

    set_cortantes = Category.objects.filter(
        brand__slug="lumy", slug="set-de-cortantes", parent__isnull=True
    ).first()
    if set_cortantes:
        set_cortantes.name = "Sets"
        set_cortantes.parent = cortantes
        set_cortantes.save(update_fields=["name", "parent"])

    Category.objects.get_or_create(
        brand=cortantes.brand,
        slug="cortantes-00-todos",
        defaults={"name": "Todos", "parent": cortantes, "sku_prefix": "00"},
    )
    Category.objects.get_or_create(
        brand=rodillos.brand,
        slug="rodillos-texturizadores-00-todos",
        defaults={"name": "Todos", "parent": rodillos, "sku_prefix": "00"},
    )
    Category.objects.get_or_create(
        brand=rodillos.brand,
        slug="rodillos-texturizadores-sets",
        defaults={"name": "Sets", "parent": rodillos, "sku_prefix": "SET"},
    )


def revertir(apps, schema_editor):
    Category = apps.get_model("products", "Category")

    Category.objects.filter(
        brand__slug="lumy",
        slug__in=[
            "cortantes-00-todos",
            "rodillos-texturizadores-00-todos",
            "rodillos-texturizadores-sets",
        ],
    ).delete()

    set_cortantes = Category.objects.filter(
        brand__slug="lumy", slug="set-de-cortantes"
    ).first()
    if set_cortantes:
        set_cortantes.name = "Set de cortantes"
        set_cortantes.parent = None
        set_cortantes.save(update_fields=["name", "parent"])


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0021_canales_disponibilidad"),
    ]

    operations = [
        migrations.RunPython(crear_todos_y_sets, revertir),
    ]
