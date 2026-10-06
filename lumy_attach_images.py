# -*- coding: utf-8 -*-
"""
Adjunta a cada producto de Lumy la imagen placeholder (hoja de catálogo completa)
de su subcategoría, usando el mapeo categoria->pagina relevado en Canva.
Idempotente: si el producto ya tiene una ProductImage, no duplica.
Correr con: python manage.py shell < attach_images.py
"""
import os
from django.core.files import File
from django.utils.text import slugify
from products.models import Category, Product, ProductImage
from brands.models import Brand

from lumy_build_data import CORTANTES, RODILLOS

lumy = Brand.objects.get(slug="lumy")
cortantes = Category.objects.get(slug="cortantes", brand=lumy)
rodillos = Category.objects.get(slug="rodillos-texturizadores", brand=lumy)

MEDIA_DIR = "/app/media/products/images/lumy_catalog_pages"

# codigo_categoria -> numero de pagina (primera pagina si ocupa mas de una)
CORTANTES_PAGE = {
    "01": 5, "02": 7, "03": 7, "04": 8, "05": 8, "06": 9, "07": 9, "08": 10, "09": 10,
    "10": 11, "11": 11, "12": 12, "13": 12, "14": 13, "15": 13, "16": 14, "17": 14,
    "18": 15, "19": 16, "20": 16, "21": 17, "22": 17, "23": 18, "24": 18, "25": 19,
    "26": 19, "27": 20, "28": 20, "29": 21, "30": 21, "31": 22, "32": 22, "33": 23,
    "34": 23, "35": 24, "36": 24, "37": 25, "38": 25, "39": 26, "40": 26, "41": 27,
    "42": 27, "43": 28, "44": 28,
}
RODILLOS_PAGE = {
    "1": 31, "2": 33, "3": 34, "4": 35, "5": 38, "6": 41, "7": 43, "8": 46,
}

attached = 0
skipped_existing = 0
missing_file = 0
missing_category = 0


def attach_for(groups, parent_cat, page_map, prefix):
    global attached, skipped_existing, missing_file, missing_category
    for code, cat_name, items in groups:
        sub_slug = slugify(f"{parent_cat.slug}-{code}-{cat_name}")
        subcat = Category.objects.filter(slug=sub_slug, parent=parent_cat).first()
        if not subcat:
            print(f"[WARN] no encontre categoria {sub_slug}")
            missing_category += 1
            continue

        page = page_map.get(code)
        image_path = os.path.join(MEDIA_DIR, f"pagina_{page:04d}.png") if page else None
        if not image_path or not os.path.exists(image_path):
            print(f"[WARN] falta imagen para categoria {cat_name} (pagina {page})")
            missing_file += len(items)
            continue

        products = Product.objects.filter(category=subcat, brand=lumy)
        for product in products:
            if product.images.exists():
                skipped_existing += 1
                continue
            with open(image_path, "rb") as f:
                django_file = File(f, name=f"catalogo_{prefix}_{code}.png")
                ProductImage.objects.create(
                    product=product,
                    image=django_file,
                    order=0,
                    alt=f"Hoja de catálogo — {cat_name} (placeholder, foto real pendiente)",
                )
            attached += 1


attach_for(CORTANTES, cortantes, CORTANTES_PAGE, "cortante")
attach_for(RODILLOS, rodillos, RODILLOS_PAGE, "rodillo")

print(f"Imagenes adjuntadas: {attached}")
print(f"Productos que ya tenian imagen (sin tocar): {skipped_existing}")
print(f"Items sin archivo de imagen disponible: {missing_file}")
print(f"Categorias no encontradas: {missing_category}")
