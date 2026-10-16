"""Descuento por CANTIDAD TOTAL de unidades del carrito (`Brand.cart_discount_config`)
— reemplaza por completo al mecanismo anterior por MONTO TOTAL del carrito
(decisión del dueño: un solo mecanismo, no conviven los dos) y al viejo combo
por categoría (ver `products/services/combo_pricing.py`). Se usa en los tres
lugares que resuelven el total de un carrito: `cart/serializers.py`
(logueado), `cart/views.py::CartQuoteAPIView` (invitado) y `payments/views.py`
(checkout real), para que el % que se muestra en el carrito sea exactamente
el que se cobra.

El descuento sigue siendo un % sobre el MONTO del pedido (se sigue cobrando
por plata, no se regala una unidad gratis) — lo único que cambió respecto al
mecanismo anterior es qué dispara el %: la CANTIDAD TOTAL de unidades en el
carrito (sumando TODOS los productos, sin importar cuál), no el subtotal en
pesos. Tramos: `[{"min_quantity": 5, "discount_percent": 5}, ...]`.
"""

from decimal import Decimal, ROUND_HALF_UP


def _sorted_tiers(tiers):
    return sorted(
        (tiers or []),
        key=lambda tier: int(tier.get("min_quantity", 0)),
    )


def cart_discount_percent_for_quantity(brand, total_quantity: int) -> int:
    """% del tramo de mayor `min_quantity` que `total_quantity` todavía
    alcanza, según `brand.cart_discount_config`. Sin tramos configurados → 0."""
    tiers = _sorted_tiers(getattr(brand, "cart_discount_config", None))
    applicable = [
        int(tier.get("discount_percent", 0))
        for tier in tiers
        if total_quantity >= int(tier.get("min_quantity", 0))
    ]
    return max(applicable) if applicable else 0


def cart_discount_progress(brand, total_quantity: int) -> dict:
    """Info para la barra de progreso del carrito: tramo ya alcanzado y
    próximo tramo (si falta alguno), con cuántas unidades faltan para
    desbloquearlo."""
    tiers = _sorted_tiers(getattr(brand, "cart_discount_config", None))
    current_percent = 0
    current_min_quantity = None
    next_tier = None
    for tier in tiers:
        min_quantity = int(tier.get("min_quantity", 0))
        percent = int(tier.get("discount_percent", 0))
        if total_quantity >= min_quantity:
            if percent >= current_percent:
                current_percent = percent
                current_min_quantity = tier.get("min_quantity")
        elif next_tier is None:
            next_tier = tier

    quantity_to_next_tier = None
    if next_tier is not None:
        quantity_to_next_tier = max(0, int(next_tier["min_quantity"]) - total_quantity)

    return {
        "tiers": tiers,
        "current_discount_percent": current_percent,
        "current_tier_min_quantity": current_min_quantity,
        "next_tier_min_quantity": next_tier.get("min_quantity") if next_tier else None,
        "next_tier_discount_percent": (
            next_tier.get("discount_percent") if next_tier else None
        ),
        "quantity_to_next_tier": quantity_to_next_tier,
    }


def compute_cart_pricing(brand, lines):
    """`lines`: lista de `(unit_price, quantity)` YA resueltos (precio de
    lista/socio, ver `products.services.combo_pricing.compute_unit_prices`),
    SIN ningún descuento aplicado todavía.

    Devuelve un dict con el desglose completo:
      - `raw_subtotal`: suma de `unit_price * quantity`, antes del
        descuento por cantidad.
      - `total_quantity`: suma de `quantity` de todas las líneas — es lo
        que dispara el % (no el monto en $).
      - `discount_percent` / `discount_amount`: resueltos sobre
        `total_quantity` vía `cart_discount_percent_for_quantity`.
      - `discounted_unit_prices`: cada `unit_price` con el % ya aplicado
        (mismo % para todas las líneas, porque el descuento es por la
        CANTIDAD TOTAL del carrito, no por línea ni por producto) — en el
        MISMO orden que `lines`, listo para persistir/cobrar.
      - `total`: suma de `discounted_unit_prices * quantity`.
      - `progress`: ver `cart_discount_progress`.
    """
    raw_subtotal = sum((price * qty for price, qty in lines), Decimal("0"))
    total_quantity = sum(qty for _price, qty in lines)
    percent = cart_discount_percent_for_quantity(brand, total_quantity)
    factor = (Decimal(100) - Decimal(percent)) / Decimal(100)
    discounted_unit_prices = [
        (price * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        for price, _qty in lines
    ]
    total = sum(
        (dp * qty for dp, (_price, qty) in zip(discounted_unit_prices, lines)),
        Decimal("0"),
    )
    return {
        "raw_subtotal": raw_subtotal,
        "total_quantity": total_quantity,
        "discount_percent": percent,
        "discount_amount": raw_subtotal - total,
        "discounted_unit_prices": discounted_unit_prices,
        "total": total,
        "progress": cart_discount_progress(brand, total_quantity),
    }
