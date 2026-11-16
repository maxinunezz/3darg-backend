"""Regla de talles de los cortantes de Lumy.

Regla del dueño (2026-11-16): TODOS los cortantes de Lumy (categoría raíz
"Cortantes" y todas sus subcategorías) se venden en exactamente tres talles,
siempre los mismos y con estos nombres:

    Chico 4-6cm · Mediano 7-9cm · Grande 10-12cm

Además se produce bajo pedido: el stock no importa, siempre están los tres
talles disponibles. Por eso, cuando un cortante no tiene alguno de los tres,
se crea solo (mismo precio que sus hermanos, stock 0 — el stock es
informativo, nunca bloquea la compra).

Dónde se aplica (para que nadie tenga que acordarse de cargarlo a mano):
- `ProductVariant.save()` fuerza el nombre canónico del talle, incluso si un
  `CostTemplate` vinculado trae otro `size_label` (ej. "Mediano 8cm"), y lo
  deja siempre disponible (no se puede apagar un talle desde el admin).
- Señal `post_save` de `Product` (`products/signals.py`): completa los talles
  que falten al crear o guardar un cortante de Lumy.
- Migración `0041_talles_cortantes_lumy`: normalizó el catálogo existente.
- Migración `0042_talles_cortantes_lumy_activos`: prendió los talles que
  habían quedado apagados a mano.
- `python manage.py normalizar_talles_cortantes_lumy`: re-aplica la regla a
  mano sobre todo el catálogo (por si algo quedó cargado por otro camino).

Para cambiar los rangos de medida a futuro alcanza con editar `TALLES` y
correr el comando de arriba — no hay que tocar nada más.
"""

from django.db import transaction

BRAND_SLUG = "lumy"
CATEGORY_ROOT_SLUG = "cortantes"

# (clave, nombre canónico, orden, sufijo de SKU). La clave es la palabra con
# la que arranca el nombre del talle, sin importar la medida que tenga
# cargada hoy ("Chico 3cm", "chico", "Chico 4-6cm" → "chico").
TALLES = (
    ("chico", "Chico 4-6cm", 0, "-CH"),
    ("mediano", "Mediano 7-9cm", 1, "-MD"),
    ("grande", "Grande 10-12cm", 2, "-GR"),
)

_SUFIJOS_SKU = tuple(sufijo for *_, sufijo in TALLES)


def clave_talle(size: str) -> str | None:
    """'Mediano 8cm' → 'mediano'. None si no es uno de los tres talles."""
    primera = (size or "").strip().split(" ", 1)[0].lower()
    for clave, *_ in TALLES:
        if primera == clave:
            return clave
    return None


def talle_canonico(size: str) -> tuple[str, int] | None:
    """Nombre y orden canónicos para un talle, o None si no es reconocible."""
    clave = clave_talle(size)
    for k, nombre, orden, _ in TALLES:
        if k == clave:
            return nombre, orden
    return None


def categorias_cortantes_ids():
    """IDs de la categoría raíz "Cortantes" + todas sus subcategorías."""
    from products.models import Category

    raiz = Category.objects.filter(slug=CATEGORY_ROOT_SLUG, parent__isnull=True).first()
    if raiz is None:
        return []
    return [raiz.pk, *Category.objects.filter(parent=raiz).values_list("pk", flat=True)]


def es_cortante_lumy(product) -> bool:
    if not product.brand_id or not product.category_id:
        return False
    if getattr(product.brand, "slug", None) != BRAND_SLUG:
        return False
    return product.category_id in categorias_cortantes_ids()


def _sku_base(product, variantes) -> str:
    """SKU base del diseño: el de alguna variante sin el sufijo de talle, o el
    del producto. Mismo criterio que `seed_talle_variants` (los sufijos se
    derivan del SKU real, nunca se inventan de cero)."""
    for v in variantes:
        sku = v.sku or ""
        for sufijo in _SUFIJOS_SKU:
            if sku.endswith(sufijo):
                return sku[: -len(sufijo)]
    for v in variantes:
        if v.sku:
            return v.sku
    return product.sku or f"LUMY-{product.pk}"


def _sku_libre(base: str, sufijo: str) -> str:
    from products.models import ProductVariant

    candidato = f"{base}{sufijo}"
    n = 2
    while ProductVariant.objects.filter(sku=candidato).exists():
        candidato = f"{base}{sufijo}{n}"
        n += 1
    return candidato


@transaction.atomic
def normalizar_talles(product) -> dict:
    """Deja a `product` con exactamente los tres talles canónicos.

    - Renombra/reordena los talles existentes (por la palabra inicial) y los
      deja disponibles (`is_available=True`).
    - Crea los que falten: mismo precio que sus hermanos, stock 0, disponible.
    - No borra nada: una variante que no sea Chico/Mediano/Grande se deja
      como está y se informa en el resultado.

    Usa `.update()` para renombrar (no `.save()`), así no dispara la
    propagación de precio/medidas del `CostTemplate`. Idempotente.
    """
    from products.models import ProductVariant

    resultado = {"renombradas": 0, "creadas": 0, "no_reconocidas": []}
    variantes = list(ProductVariant.objects.filter(product=product).order_by("order", "pk"))
    por_clave = {}
    for v in variantes:
        clave = clave_talle(v.size)
        if clave is None:
            resultado["no_reconocidas"].append(v.size)
            continue
        if clave in por_clave:
            # Duplicado del mismo talle: se deja quieto, no se adivina cuál vale.
            resultado["no_reconocidas"].append(v.size)
            continue
        por_clave[clave] = v

    precio = next((v.price for v in variantes if v.price is not None), product.price)
    base = _sku_base(product, variantes)

    for clave, nombre, orden, sufijo in TALLES:
        v = por_clave.get(clave)
        if v is not None:
            # Además, el talle queda siempre disponible: se produce bajo
            # pedido, así que un talle apagado a mano en el admin (pasó con
            # los Mediano de Animales de Granja) no puede ocultarse de la ficha.
            if v.size != nombre or v.order != orden or not v.is_available:
                ProductVariant.objects.filter(pk=v.pk).update(size=nombre, order=orden, is_available=True)
                resultado["renombradas"] += 1
            continue
        ProductVariant.objects.create(
            product=product,
            color="",
            size=nombre,
            order=orden,
            sku=_sku_libre(base, sufijo),
            price=precio,
            stock=0,
            is_available=True,
        )
        resultado["creadas"] += 1
    return resultado
