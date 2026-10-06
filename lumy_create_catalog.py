# -*- coding: utf-8 -*-
"""
Crea las subcategorías (Cortantes > tema, Rodillos Texturizadores > tema) y los 375
productos individuales de Lumy a partir del manifiesto en lumy_build_data.py.
Idempotente: usa get_or_create por slug, se puede correr de nuevo sin duplicar.
Correr con: python manage.py shell < create_catalog.py
"""
from django.utils.text import slugify
from products.models import Category, Product
from brands.models import Brand

from lumy_build_data import CORTANTES, RODILLOS

lumy = Brand.objects.get(slug="lumy")
cortantes = Category.objects.get(slug="cortantes", brand=lumy)
rodillos = Category.objects.get(slug="rodillos-texturizadores", brand=lumy)

created_cats = 0
created_products = 0
updated_products = 0

def slug_unique(base):
    """Devuelve un slug único agregando sufijo numérico si hace falta."""
    slug = base
    i = 2
    while Product.objects.filter(slug=slug).exists():
        slug = f"{base}-{i}"
        i += 1
    return slug


def process(groups, parent_cat, kind):
    global created_cats, created_products, updated_products
    for code, cat_name, items in groups:
        sub_slug = slugify(f"{parent_cat.slug}-{code}-{cat_name}")
        subcat, was_created = Category.objects.get_or_create(
            slug=sub_slug,
            defaults={"name": cat_name, "brand": lumy, "parent": parent_cat},
        )
        if was_created:
            created_cats += 1
        elif subcat.parent_id != parent_cat.id or subcat.brand_id != lumy.id:
            subcat.parent = parent_cat
            subcat.brand = lumy
            subcat.save(update_fields=["parent", "brand"])

        for item_code, item_name in items:
            if kind == "cortante":
                name = f"Cortante {item_name}"
                price = 1500
                desc = (
                    f"Cortante 3D de {item_name.lower()} — colección {cat_name}. "
                    f"Ideal para galletitas, fondant y masas. Tamaño a elección (4 a 12 cm). "
                    f"Código interno {item_code}."
                )
                base_slug = slugify(f"cortante-{item_code}")
            else:
                name = f"Rodillo Texturizador {item_name}"
                price = 2500
                desc = (
                    f"Rodillo texturizador 3D de {item_name.lower()} — colección {cat_name}. "
                    f"Para decorar fondant y masas con relieve. Código interno {item_code}."
                )
                base_slug = slugify(f"rodillo-{item_code}")

            existing = Product.objects.filter(slug=base_slug).first()
            if existing:
                # Ya existe (corrida previa) - no tocamos precio/nombre si el admin ya lo editó,
                # solo garantizamos que quede bien categorizado y con marca.
                changed = False
                if existing.category_id != subcat.id:
                    existing.category = subcat
                    changed = True
                if existing.brand_id != lumy.id:
                    existing.brand = lumy
                    changed = True
                if changed:
                    existing.save(update_fields=["category", "brand"])
                    updated_products += 1
                continue

            Product.objects.create(
                name=name,
                slug=base_slug,
                description=desc,
                price=price,
                stock=50,
                is_available=True,
                is_featured=False,
                category=subcat,
                brand=lumy,
            )
            created_products += 1


process(CORTANTES, cortantes, "cortante")
process(RODILLOS, rodillos, "rodillo")

print(f"Subcategorías creadas: {created_cats}")
print(f"Productos creados: {created_products}")
print(f"Productos existentes actualizados: {updated_products}")
print(f"Total productos Lumy en DB: {Product.objects.filter(brand=lumy).count()}")
