"""Cálculo de peso facturable (real vs. volumétrico) para cotizar envíos.

Los cortantes 3D son extremadamente livianos para el volumen que ocupan
(packaging relativamente grande, peso real mínimo) — por eso los couriers
cobran por el MAYOR entre el peso real y el peso volumétrico, no solo por
el real. Esta función es pura (sin acceso a DB/red) para que sea fácil de
testear y de reusar tanto en el llamado a Envíopack como en el fallback.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings


@dataclass
class ShipmentItem:
    """Ítem normalizado para el cálculo, desacoplado de `products.Product`
    a propósito (así esta función no depende de Django ORM)."""

    quantity: int
    weight_kg: Decimal | None = None
    length_cm: Decimal | None = None
    width_cm: Decimal | None = None
    height_cm: Decimal | None = None


def _item_dimensions_cm(item: ShipmentItem) -> tuple[Decimal, Decimal, Decimal]:
    if item.length_cm and item.width_cm and item.height_cm:
        return (Decimal(item.length_cm), Decimal(item.width_cm), Decimal(item.height_cm))
    default_l, default_w, default_h = settings.SHIPPING_DEFAULT_ITEM_DIMENSIONS_CM
    return (Decimal(str(default_l)), Decimal(str(default_w)), Decimal(str(default_h)))


def calculate_billable_weight(items: list[ShipmentItem]) -> Decimal:
    """Peso facturable total del pedido: el mayor entre peso real y peso
    volumétrico (sumados por ítem), con un piso mínimo configurable
    (`settings.SHIPPING_MIN_WEIGHT_KG`) aplicado al TOTAL del pedido —no
    por ítem— para no inflar artificialmente carritos con varias unidades
    (el piso representa un mínimo de manipuleo por envío, no por producto).

    El peso real de un ítem sin `weight_kg` cargado en el admin se toma
    como 0 (no se inventa un peso real) — el volumétrico ya cubre ese caso,
    que es justamente el escenario típico de un cortante sin medidas
    cargadas todavía.
    """
    divisor = Decimal(str(settings.SHIPPING_VOLUMETRIC_DIVISOR))
    min_weight = Decimal(str(settings.SHIPPING_MIN_WEIGHT_KG))

    total_real = Decimal("0")
    total_volumetric = Decimal("0")

    for item in items:
        qty = Decimal(item.quantity)
        real_per_unit = Decimal(item.weight_kg) if item.weight_kg else Decimal("0")
        length, width, height = _item_dimensions_cm(item)
        volumetric_per_unit = (length * width * height) / divisor

        total_real += real_per_unit * qty
        total_volumetric += volumetric_per_unit * qty

    billable = max(total_real, total_volumetric)
    if billable < min_weight:
        billable = min_weight
    return billable.quantize(Decimal("0.01"))
