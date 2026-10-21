"""Descuento por pagar por transferencia bancaria (`Brand.transfer_discount_percent`).

Se aplica SOLO cuando el comprador elige el canal `Order.PaymentChannel.TRANSFER`
en el checkout (ver `payments/views.py::TransferCheckoutCreateAPIView`) — el
canal MercadoPago nunca lo usa. Se aplica sobre el `total` que ya salió de
`cart.services.cart_discount.compute_cart_pricing()` (es decir, DESPUÉS del
descuento por cantidad del carrito, si corresponde) y ANTES de sumar el costo
de envío, mismo orden de operaciones que el resto del checkout:

    precio de lista/socio -> descuento por cantidad (cart_discount) ->
    descuento por transferencia (este módulo) -> + envío = total a cobrar

Ojo: el umbral de envío gratis (`Brand.shipping_config`) se evalúa contra el
subtotal ANTES de este descuento (ver `payments/views.py`) — una decisión de
producto explícita, no un olvido: así un pedido no pierde el envío gratis
solo por elegir transferencia.
"""

from decimal import Decimal, ROUND_HALF_UP


def transfer_discount_percent_for_brand(brand) -> int:
    """`Brand.transfer_discount_percent` tal cual está cargado, 0 si no tiene."""
    return int(getattr(brand, "transfer_discount_percent", 0) or 0)


def apply_transfer_discount(brand, pricing: dict) -> dict:
    """Aplica el % de transferencia de `brand` sobre el resultado de
    `compute_cart_pricing()` (`pricing`). Devuelve un dict nuevo (no muta
    `pricing`) con las mismas claves más el desglose del descuento:

      - `transfer_discount_percent`: el % aplicado (0 si la marca no tiene).
      - `transfer_discount_amount`: cuánto se restó, en $.
      - `total`: el `pricing["total"]` original, con este descuento ya
        aplicado (pisa la clave, para que el resto del checkout lo use tal
        cual sin tener que saber de este módulo).
      - `discounted_unit_prices`: idem, cada precio unitario con el %
        de transferencia ya aplicado además del de cantidad — es lo que se
        persiste en `OrderItem.unit_price` para que el historial del pedido
        refleje el precio real pagado por unidad.

    Si la marca no tiene `transfer_discount_percent` cargado (0), devuelve
    `pricing` sin tocar (salvo agregar las claves nuevas en 0/sin cambios),
    para que sea seguro llamar siempre, incluso sin descuento configurado.
    """
    percent = transfer_discount_percent_for_brand(brand)
    factor = (Decimal(100) - Decimal(percent)) / Decimal(100)

    discounted_unit_prices = [
        (price * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        for price in pricing["discounted_unit_prices"]
    ]
    total = (pricing["total"] * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        **pricing,
        "discounted_unit_prices": discounted_unit_prices,
        "total": total,
        "transfer_discount_percent": percent,
        "transfer_discount_amount": pricing["total"] - total,
    }
