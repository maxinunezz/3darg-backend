"""Lógica de cotización de envío, compartida por dos consumidores:

- `shipping/views.py::ShippingCalculateAPIView` — cotización "en vivo" que
  pide el frontend mientras el comprador completa el carrito (preview, no
  cobra nada).
- `payments/views.py::MercadoPagoCheckoutProCreateAPIView` — cotización REAL
  que se cobra en el checkout, para que el monto que paga el comprador
  incluya el envío (antes no se cobraba nada de envío).

Un solo lugar de verdad para el fallback de tarifa plana y la normalización
de la respuesta de Envíopack, para que el precio mostrado en el carrito y el
que efectivamente se cobra en MercadoPago sean siempre el mismo cálculo.
"""
import logging
from decimal import Decimal

from django.conf import settings

from . import enviopack
from .postal import resolve_provincia_ar
from .volumetric import ShipmentItem, calculate_billable_weight

logger = logging.getLogger(__name__)


def _fallback_quote(postal_code: str) -> dict:
    """Tarifa plana de respaldo cuando Envíopack falla, da timeout, no está
    configurado, o no devuelve ninguna tarifa de los couriers activos.

    Configurable 100% por `SHIPPING_FALLBACK_RATES_JSON` (.env) — nunca
    hardcodeada acá. `zones` es una aproximación por primer dígito del
    código postal (no es una zonificación precisa, ver postal.py), pensada
    solo como red de contención, no como tarifa real de courier.
    """
    rates = settings.SHIPPING_FALLBACK_RATES
    zone_rate = rates.get("zones", {}).get(postal_code[:1]) if postal_code else None
    price = zone_rate if zone_rate is not None else rates.get("default", 0)
    return {
        "carrier": "Tarifa estimada",
        "service": "standard",
        "modality": "domicilio",
        "price": price,
        "delivery_days": None,
        "is_fallback": True,
    }


def _normalize_quotes(raw_quotes: list[dict]) -> list[dict]:
    """Traduce la respuesta cruda de Envíopack a un shape limpio y estable
    para el frontend, filtrando solo los couriers activos configurados en
    `settings.ENVIOPACK_COURIERS` (Correo Argentino / Andreani)."""
    allowed = set(settings.ENVIOPACK_COURIERS)
    normalized = []
    for q in raw_quotes:
        correo = q.get("correo") or {}
        courier_id = correo.get("id", "")
        if allowed and courier_id not in allowed:
            continue

        horas_entrega = q.get("horas_entrega")
        try:
            price = float(q.get("valor", 0))
        except (TypeError, ValueError):
            continue

        normalized.append({
            "carrier": correo.get("nombre", courier_id),
            "service": q.get("servicio"),
            "modality": "sucursal" if q.get("modalidad") == "S" else "domicilio",
            "price": price,
            "delivery_days": round(horas_entrega / 24, 1) if horas_entrega else None,
            "is_fallback": False,
        })
    return normalized


def _build_shipment_items(items: list[tuple]) -> tuple[list[ShipmentItem], list[tuple]]:
    """`items`: lista de `(product, quantity)`. Devuelve `(shipment_items,
    package_dims_cm)` listos para `calculate_billable_weight()`/`enviopack.get_quotes()`."""
    shipment_items = []
    package_dims = []
    default_dims = settings.SHIPPING_DEFAULT_ITEM_DIMENSIONS_CM
    for product, quantity in items:
        shipment_items.append(ShipmentItem(
            quantity=quantity,
            weight_kg=product.weight_kg,
            length_cm=product.length_cm,
            width_cm=product.width_cm,
            height_cm=product.height_cm,
        ))
        dims = (
            product.length_cm or default_dims[0],
            product.width_cm or default_dims[1],
            product.height_cm or default_dims[2],
        )
        package_dims.extend([dims] * quantity)
    return shipment_items, package_dims


def get_quotes(*, postal_code: str, province: str | None, items: list[tuple]) -> dict:
    """Cotiza el envío de `items` (lista de `(product, quantity)`) a
    `postal_code`. Si `province` no viene, se intenta resolver desde el
    código postal (`resolve_provincia_ar`); si no se puede resolver, se cae
    directo al fallback de tarifa plana (nunca se le manda una provincia
    adivinada a Envíopack).

    Devuelve `{postal_code, billable_weight_kg, quotes: [...]}` — siempre
    con al menos una cotización (el fallback garantiza eso).
    """
    province = province or resolve_provincia_ar(postal_code)
    shipment_items, package_dims = _build_shipment_items(items)
    billable_weight = calculate_billable_weight(shipment_items)

    quotes: list[dict] = []
    if province:
        raw_quotes = enviopack.get_quotes(
            postal_code=postal_code,
            provincia=province,
            weight_kg=billable_weight,
            package_dims_cm=package_dims,
        )
        if raw_quotes is not None:
            quotes = _normalize_quotes(raw_quotes)
    else:
        logger.info(
            "No se pudo resolver provincia para codigo_postal=%s — se usa tarifa de respaldo",
            postal_code,
        )

    if not quotes:
        quotes = [_fallback_quote(postal_code)]

    return {
        "postal_code": postal_code,
        "billable_weight_kg": float(billable_weight),
        "quotes": quotes,
    }


def cheapest_price(quotes: list[dict]) -> Decimal:
    """La cotización que efectivamente se cobra en el checkout: la más
    barata de las devueltas por `get_quotes()` (nunca se le ofrece al
    comprador pagar de más si hay una opción más barata disponible)."""
    return Decimal(str(min(q["price"] for q in quotes)))


def default_fallback_price() -> Decimal:
    """Tarifa plana default (sin cotizar nada) — se usa en el checkout real
    cuando el comprador no mandó código postal: así el envío SIEMPRE se
    cobra (aunque sea una estimación), en vez de quedar en $0 por omisión."""
    return Decimal(str(settings.SHIPPING_FALLBACK_RATES.get("default", 0)))
