"""Resuelve el precio de lista/socio de cada línea de un carrito.

Históricamente este módulo combinaba el descuento por volumen del propio
producto (`Product.bundle_discounts`) con el combo por categoría
(`Category.bundle_discounts`, entre productos DISTINTOS de una misma
subcategoría). Ambos mecanismos quedaron reemplazados por el descuento por
MONTO TOTAL del carrito (`Brand.cart_discount_config`, ver
`cart/services/cart_discount.py`), que es el único que hoy incentiva
comprar más desde el carrito (antes se elegía desde la ficha de producto).

`compute_unit_prices()` ahora solo resuelve `price_for(user)` por línea
(precio de lista o de socio, sin ningún descuento por volumen) — se
mantiene como punto único de entrada para no tocar los tres lugares que la
importan (`cart/serializers.py`, `cart/views.py::CartQuoteAPIView`,
`payments/views.py`).
"""


def compute_unit_prices(user, items):
    """`items`: lista de `(product, quantity)`. Devuelve una lista de
    `Decimal` (precio de lista/socio, sin descuento por volumen — ver
    docstring del módulo), en el MISMO orden que `items`.
    """
    return [product.price_for(user) for product, _quantity in items]
