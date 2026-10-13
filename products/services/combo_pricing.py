"""Pricing combo-aware: resuelve precios unitarios de una lista de líneas
(producto, cantidad) teniendo en cuenta no solo el descuento por volumen del
propio producto (`Product.bundle_discounts`), sino también el descuento por
combo de su subcategoría exacta (`Category.bundle_discounts`), que depende
de la cantidad SUMADA entre todas las líneas que comparten esa categoría
(mezclando productos distintos, o repitiendo el mismo).

Se usa en los dos lugares donde hace falta resolver precios de un carrito
completo de una sola vez (no línea por línea, porque el descuento de combo
necesita ver todas las líneas juntas): `cart/serializers.py` y
`payments/views.py` (checkout).
"""

from decimal import Decimal, ROUND_HALF_UP


def compute_unit_prices(user, items):
    """`items`: lista de `(product, quantity)`. Devuelve una lista de
    `Decimal` (precio unitario efectivo), en el MISMO orden que `items`.

    Para cada línea:
    1. Resuelve el precio base socio/anónimo + descuento por volumen del
       propio producto (`product.unit_price_for(user, quantity)` — ya
       existente, sin tocar).
    2. Si el producto tiene categoría y esa categoría tiene
       `bundle_discounts` configurado, calcula el % de combo según la
       cantidad TOTAL acumulada entre todas las líneas de esa misma
       categoría (no solo esta línea).
    3. Si ambos descuentos (bundle del producto y combo de la categoría)
       aplican, se usa el MAYOR porcentaje de los dos — no se suman, para
       no doble-descontar la misma cantidad comprada.

    No muta `items` ni asume que los `Product` ya estén guardados (no se
    usan como clave de dict en ningún momento, se referencia por posición
    e `id` de categoría para evitar problemas de hash/igualdad).
    """
    # Cantidad total por categoría, sumando todas las líneas (mezcladas o
    # repetidas) que caen en la misma subcategoría exacta.
    category_quantity = {}
    for product, quantity in items:
        category_id = product.category_id
        if category_id is None:
            continue
        category_quantity[category_id] = category_quantity.get(category_id, 0) + int(quantity)

    # % de combo por categoría, resuelto una sola vez por categoría presente.
    category_discount_percent = {}
    for category_id, total_qty in category_quantity.items():
        product = next(p for p, _ in items if p.category_id == category_id)
        category = product.category
        category_discount_percent[category_id] = category.bundle_discount_percent_for(total_qty)

    prices = []
    for product, quantity in items:
        own_price = product.unit_price_for(user, quantity)

        category_id = product.category_id
        combo_pct = category_discount_percent.get(category_id, 0) if category_id is not None else 0
        if combo_pct <= 0:
            prices.append(own_price)
            continue

        # Precio base (socio/anónimo, SIN el bundle propio) con el % de
        # combo de categoría, para comparar manzanas con manzanas contra
        # `own_price` (que ya incluye el bundle propio del producto) y
        # quedarnos con el MAYOR descuento de los dos, no la suma.
        base_price = product.price_for(user)
        factor = (Decimal(100) - Decimal(combo_pct)) / Decimal(100)
        combo_price = (base_price * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        prices.append(min(own_price, combo_price))

    return prices
