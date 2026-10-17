"""Resuelve el precio de lista/socio de cada línea de un carrito.

Históricamente este módulo combinaba el descuento por volumen del propio
producto (`Product.bundle_discounts`) con el combo por categoría
(`Category.bundle_discounts`, entre productos DISTINTOS de una misma
subcategoría). Ambos mecanismos quedaron reemplazados por el descuento por
CANTIDAD TOTAL de unidades del carrito (`Brand.cart_discount_config`, ver
`cart/services/cart_discount.py` — a su vez reemplazo de un primer mecanismo
por MONTO total que tuvo este campo antes), que es el único que hoy incentiva
comprar más desde el carrito (antes se elegía desde la ficha de producto).

`compute_unit_prices()` ahora solo resuelve `price_for(user)` por línea
(precio de lista o de socio, sin ningún descuento por volumen) — se
mantiene como punto único de entrada para no tocar los tres lugares que la
importan (`cart/serializers.py`, `cart/views.py::CartQuoteAPIView`,
`payments/views.py`).

**Variantes (Fase 2 de `ProductVariant`)**: cada línea puede venir como
`(product, quantity)` (sin variante, comportamiento histórico) o
`(product, quantity, variant)`, donde `variant` es una `ProductVariant` ya
cargada o `None`. Si hay variante, el precio es el de la variante
(`variant.price_for(user)`, que aplica el mismo `member_discount_percent`
del producto pero sobre el precio PROPIO de la variante) — si no, cae al
precio del producto como siempre.
"""


def compute_unit_prices(user, items):
    """`items`: lista de `(product, quantity)` o `(product, quantity,
    variant)` (`variant` puede ser `None`). Devuelve una lista de `Decimal`
    (precio de lista/socio, sin descuento por volumen — ver docstring del
    módulo), en el MISMO orden que `items`.
    """
    prices = []
    for item in items:
        if len(item) == 3:
            product, _quantity, variant = item
        else:
            product, _quantity = item
            variant = None
        if variant is not None:
            prices.append(variant.price_for(user))
        else:
            prices.append(product.price_for(user))
    return prices
