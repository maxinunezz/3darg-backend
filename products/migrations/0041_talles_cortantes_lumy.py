"""Normaliza los talles de TODOS los cortantes de Lumy a la regla del dueño
(2026-11-16): Chico 4-6cm · Mediano 7-9cm · Grande 10-12cm, los tres en
todos los cortantes. Ver products/talles_lumy.py.

- Renombra los talles existentes por su palabra inicial (ej. "Chico 3cm",
  "Mediano 8cm", "Grande 8cm") y les fija el orden 0/1/2.
- Crea los talles que falten (ej. los Animales de Granja, cargados sin
  Mediano): mismo precio que sus hermanos, stock 0, disponible.
- No borra nada.

Autocontenida (modelos históricos), no importa products.talles_lumy a
propósito: si esa lógica cambia en el futuro, esta migración tiene que
seguir haciendo exactamente lo que hizo al correr.

Reversa: vuelve a los nombres anteriores en producción ("Chico 3cm" /
"Mediano 8cm" / "Grande 8cm"). Los talles CREADOS por esta migración no se
borran al revertir (no hay forma confiable de distinguirlos de los que se
carguen después) — quedan con el nombre viejo del talle.
"""

from django.db import migrations

TALLES = (
    ("chico", "Chico 4-6cm", 0, "-CH"),
    ("mediano", "Mediano 7-9cm", 1, "-MD"),
    ("grande", "Grande 10-12cm", 2, "-GR"),
)
NOMBRES_ANTERIORES = {"chico": "Chico 3cm", "mediano": "Mediano 8cm", "grande": "Grande 8cm"}
SUFIJOS = tuple(t[3] for t in TALLES)


def _clave(size):
    primera = (size or "").strip().split(" ", 1)[0].lower()
    return primera if primera in NOMBRES_ANTERIORES else None


def _cortantes_lumy(apps):
    Category = apps.get_model("products", "Category")
    Product = apps.get_model("products", "Product")
    raiz = Category.objects.filter(slug="cortantes", parent__isnull=True).first()
    if raiz is None:
        return Product.objects.none()
    cats = [raiz.pk, *Category.objects.filter(parent=raiz).values_list("pk", flat=True)]
    return Product.objects.filter(brand__slug="lumy", category_id__in=cats)


def aplicar(apps, schema_editor):
    ProductVariant = apps.get_model("products", "ProductVariant")
    renombradas = creadas = 0
    for product in _cortantes_lumy(apps).order_by("pk"):
        variantes = list(ProductVariant.objects.filter(product=product).order_by("order", "pk"))
        por_clave = {}
        for v in variantes:
            k = _clave(v.size)
            if k and k not in por_clave:
                por_clave[k] = v

        base = None
        for v in variantes:
            for suf in SUFIJOS:
                if (v.sku or "").endswith(suf):
                    base = v.sku[: -len(suf)]
                    break
            if base:
                break
        if not base:
            base = next((v.sku for v in variantes if v.sku), None) or product.sku or f"LUMY-{product.pk}"
        precio = next((v.price for v in variantes if v.price is not None), product.price)

        for clave, nombre, orden, sufijo in TALLES:
            v = por_clave.get(clave)
            if v is not None:
                if v.size != nombre or v.order != orden:
                    ProductVariant.objects.filter(pk=v.pk).update(size=nombre, order=orden)
                    renombradas += 1
                continue
            sku = f"{base}{sufijo}"
            n = 2
            while ProductVariant.objects.filter(sku=sku).exists():
                sku = f"{base}{sufijo}{n}"
                n += 1
            ProductVariant.objects.create(
                product=product, color="", size=nombre, order=orden, sku=sku,
                price=precio, stock=0, is_available=True,
            )
            creadas += 1
    print(f"\n  Talles cortantes Lumy: {renombradas} renombrados, {creadas} creados.")


def revertir(apps, schema_editor):
    ProductVariant = apps.get_model("products", "ProductVariant")
    for clave, nombre, _, _ in TALLES:
        ProductVariant.objects.filter(product__in=_cortantes_lumy(apps), size=nombre).update(
            size=NOMBRES_ANTERIORES[clave]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0040_talles_variantes_fase2"),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
