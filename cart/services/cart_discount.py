"""Descuento por MONTO TOTAL del carrito (`Brand.cart_discount_config`) —
reemplaza al viejo combo por categoría (ver
`products/services/combo_pricing.py`). Se usa en los tres lugares que
resuelven el total de un carrito: `cart/serializers.py` (logueado),
`cart/views.py::CartQuoteAPIView` (invitado) y `payments/views.py`
(checkout real), para que el % que se muestra en el carrito sea
exactamente el que se cobra.
"""

from decimal import Decimal, ROUND_HALF_UP


def _sorted_tiers(tiers):
    return sorted(
        (tiers or []),
        key=lambda tier: Decimal(str(tier.get("min_amount", 0))),
    )


def cart_discount_percent_for_amount(brand, subtotal: Decimal) -> int:
    """% del tramo de mayor monto que `subtotal` todavía alcanza, según
    `brand.cart_discount_config`. Sin tramos configurados → 0."""
    tiers = _sorted_tiers(getattr(brand, "cart_discount_config", None))
    applicable = [
        int(tier.get("discount_percent", 0))
        for tier in tiers
        if subtotal >= Decimal(str(tier.get("min_amount", 0)))
    ]
    return max(applicable) if applicable else 0


def cart_discount_progress(brand, subtotal: Decimal) -> dict:
    """Info para la barra de progreso del carrito: tramo ya alcanzado y
    próximo tramo (si falta alguno), con cuánto falta en $ para
    desbloquearlo."""
    tiers = _sorted_tiers(getattr(brand, "cart_discount_config", None))
    current_percent = 0
    current_min_amount = None
    next_tier = None
    for tier in tiers:
        min_amount = Decimal(str(tier.get("min_amount", 0)))
        percent = int(tier.get("discount_percent", 0))
        if subtotal >= min_amount:
            if percent >= current_percent:
                current_percent = percent
                current_min_amount = tier.get("min_amount")
        elif next_tier is None:
            next_tier = tier

    amount_to_next_tier = None
    if next_tier is not None:
        amount_to_next_tier = (
            Decimal(str(next_tier["min_amount"])) - subtotal
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "tiers": tiers,
        "current_discount_percent": current_percent,
        "current_tier_min_amount": current_min_amount,
        "next_tier_min_amount": next_tier.get("min_amount") if next_tier else None,
        "next_tier_discount_percent": (
            next_tier.get("discount_percent") if next_tier else None
        ),
        "amount_to_next_tier": amount_to_next_tier,
    }


def compute_cart_pricing(brand, lines):
    """`lines`: lista de `(unit_price, quantity)` YA resueltos (precio de
    lista/socio, ver `products.services.combo_pricing.compute_unit_prices`),
    SIN ningún descuento aplicado todavía.

    Devuelve un dict con el desglose completo:
      - `raw_subtotal`: suma de `unit_price * quantity`, antes del
        descuento por monto.
      - `discount_percent` / `discount_amount`: resueltos sobre
        `raw_subtotal` vía `cart_discount_percent_for_amount`.
      - `discounted_unit_prices`: cada `unit_price` con el % ya aplicado
        (mismo % para todas las líneas, porque el descuento es por el
        monto TOTAL del carrito, no por línea) — en el MISMO orden que
        `lines`, listo para persistir/cobrar.
      - `total`: suma de `discounted_unit_prices * quantity`.
      - `progress`: ver `cart_discount_progress`.
    """
    raw_subtotal = sum((price * qty for price, qty in lines), Decimal("0"))
    percent = cart_discount_percent_for_amount(brand, raw_subtotal)
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
        "discount_percent": percent,
        "discount_amount": raw_subtotal - total,
        "discounted_unit_prices": discounted_unit_prices,
        "total": total,
        "progress": cart_discount_progress(brand, raw_subtotal),
    }
