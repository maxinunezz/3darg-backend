"""Lógica de cotización de envío, compartida por dos consumidores:

- `shipping/views.py::ShippingCalculateAPIView` — cotización "en vivo" que
  pide el frontend mientras el comprador completa el carrito (preview, no
  cobra nada).
- `payments/views.py::MercadoPagoCheckoutProCreateAPIView` — cotización REAL
  que se cobra en el checkout, para que el monto que paga el comprador
  incluya el envío.

A diferencia de una iteración anterior de esta integración (que asumía que
Correo Argentino no tenía cotización en vivo), la API real de MiCorreo SÍ
tiene un endpoint de cotización (`POST /rates`,
`correo_argentino.py::get_rates()`) — se intenta primero, por cada
modalidad, y se cae a la tabla estática de respaldo (`tariff.py`) solo
cuando no se puede cotizar en vivo: sin credenciales, error de red, o sin
código postal de destino conocido (caso típico del selector de sucursal,
que no le pide CP al comprador — ver `shipping-estimator.tsx`).

Las dos modalidades (sucursal y domicilio) son Correo Argentino
(`correoargentino_sucursal` / `correoargentino_domicilio`) — Andreani salió
del selector del carrito (reemplazado por completo, ver CLAUDE.md →
"Envíos") y su código de respaldo por zona de CP queda en el historial de
git, no en este módulo.

Un solo lugar de verdad para que el precio mostrado en el carrito y el que
efectivamente se cobra en MercadoPago sean siempre el mismo cálculo.
"""
import logging
from decimal import Decimal

from django.conf import settings

from . import correo_argentino, tariff
from .volumetric import ShipmentItem, calculate_billable_weight

logger = logging.getLogger(__name__)

_METHOD_LABELS = {
    ("correoargentino", "sucursal"): "Correo Argentino a sucursal",
    ("correoargentino", "domicilio"): "Correo Argentino a domicilio",
}

# (modalidad interna, "deliveredType" real de la API) — "S"/"D" confirmado
# literal en la doc ("D" (no "S") envío a domicilio, "S" envío a sucursal).
_MODALITIES = (("sucursal", "S"), ("domicilio", "D"))


def _build_shipment_items(items: list[tuple]) -> list[ShipmentItem]:
    """`items`: lista de `(product, quantity)`. Devuelve los `ShipmentItem`
    listos para `calculate_billable_weight()`."""
    shipment_items = []
    for product, quantity in items:
        shipment_items.append(ShipmentItem(
            quantity=quantity,
            weight_kg=product.weight_kg,
            length_cm=product.length_cm,
            width_cm=product.width_cm,
            height_cm=product.height_cm,
        ))
    return shipment_items


def _infer_declared_value(items: list[tuple]) -> Decimal:
    """Si no se manda `declared_value` explícito (ej. la cotización preview
    del carrito, antes de resolver descuentos), se infiere del precio de
    lista — un valor aproximado alcanza para calcular el cargo de Valor
    Declarado, que es una fracción chica del total."""
    total = Decimal("0")
    for product, quantity in items:
        price = getattr(product, "price", None)
        if price is not None:
            total += Decimal(str(price)) * quantity
    return total


def _raw_weight_grams_and_dims(items: list[tuple]) -> tuple[int, dict]:
    """Peso real total (en gramos, sin volumétrico) y dimensiones del bulto
    — la API real de Correo Argentino (`/rates`) pide esto directo, a
    diferencia de la tabla de respaldo que trabaja con peso facturable
    (volumétrico). Usa las medidas más grandes entre los ítems como proxy
    del bulto único (mismo criterio que `correo_argentino.py::_parcel_weight_and_dims()`,
    duplicado acá porque ese toma un `Order` ya persistido y acá todavía no
    existe — se cotiza antes de crear la orden)."""
    default_l, default_w, default_h = settings.SHIPPING_DEFAULT_ITEM_DIMENSIONS_CM
    total_weight_kg = Decimal("0")
    max_l, max_w, max_h = Decimal(str(default_l)), Decimal(str(default_w)), Decimal(str(default_h))

    for product, quantity in items:
        if getattr(product, "weight_kg", None):
            total_weight_kg += Decimal(str(product.weight_kg)) * quantity
        if getattr(product, "length_cm", None) and product.length_cm > max_l:
            max_l = Decimal(str(product.length_cm))
        if getattr(product, "width_cm", None) and product.width_cm > max_w:
            max_w = Decimal(str(product.width_cm))
        if getattr(product, "height_cm", None) and product.height_cm > max_h:
            max_h = Decimal(str(product.height_cm))

    if total_weight_kg <= 0:
        total_weight_kg = Decimal(str(settings.SHIPPING_MIN_WEIGHT_KG))

    weight_grams = int((total_weight_kg * 1000).to_integral_value(rounding="ROUND_HALF_UP"))
    return weight_grams, {"height": int(max_h), "width": int(max_w), "length": int(max_l)}


def _delivery_days_label(rate: dict) -> str | None:
    dmin, dmax = rate.get("deliveryTimeMin"), rate.get("deliveryTimeMax")
    if dmin is None and dmax is None:
        return None
    if dmin == dmax:
        return f"{dmin} días hábiles"
    return f"{dmin} a {dmax} días hábiles"


def get_quotes(*, postal_code: str, items: list[tuple], declared_value: Decimal | None = None) -> dict:
    """Cotiza el envío de `items` (lista de `(product, quantity)`) para las
    dos modalidades que deja elegir el checkout: Correo Argentino a
    sucursal y a domicilio. Intenta la cotización EN VIVO (`POST /rates`)
    cuando se conoce `postal_code` de destino; si no (sin CP, sin
    credenciales, o falla la consulta), cae a la tabla de respaldo por
    modalidad — nunca deja una modalidad sin cotizar.

    Devuelve `{postal_code, billable_weight_kg, quotes: [...]}`, cada quote
    con `is_fallback` indicando si vino de la tabla estática o de la API
    real.
    """
    shipment_items = _build_shipment_items(items)
    if declared_value is None:
        declared_value = _infer_declared_value(items)

    billable_weight_ca = calculate_billable_weight(
        shipment_items, divisor=settings.SHIPPING_CORREO_ARGENTINO_VOLUMETRIC_DIVISOR,
    )

    live_rates = None
    postal_code = (postal_code or "").strip()
    if postal_code:
        weight_grams, dims = _raw_weight_grams_and_dims(items)
        live_rates = correo_argentino.get_rates(
            postal_code_destination=postal_code,
            weight_grams=weight_grams,
            height_cm=dims["height"],
            width_cm=dims["width"],
            length_cm=dims["length"],
        )

    quotes = []
    for modality, delivered_type in _MODALITIES:
        live_entry = None
        if live_rates:
            live_entry = next((r for r in live_rates if r.get("deliveredType") == delivered_type), None)

        if live_entry and live_entry.get("price") is not None:
            quotes.append({
                "carrier": "Correo Argentino",
                "service": live_entry.get("productName") or live_entry.get("productType") or settings.CORREO_ARGENTINO_PRODUCT_TYPE,
                "modality": modality,
                "price": float(live_entry["price"]),
                "delivery_days": _delivery_days_label(live_entry),
                "is_fallback": False,
            })
        else:
            # Tarifa fija TEMPORAL (ver settings.SHIPPING_TEMP_FIXED_RATES):
            # mientras no tengamos credenciales reales de Correo Argentino,
            # el dueño pidió cobrar un monto fijo por modalidad en vez del
            # cálculo de la tabla de respaldo. Si no hay override para esta
            # modalidad (dict vacío o sin esa key), se cae al cálculo de
            # siempre.
            fixed_price = settings.SHIPPING_TEMP_FIXED_RATES.get(modality)
            if fixed_price is not None:
                price = float(fixed_price)
            else:
                price = float(tariff.correo_argentino_fallback_price(billable_weight_ca, declared_value))
            quotes.append({
                "carrier": "Correo Argentino",
                "service": settings.CORREO_ARGENTINO_PRODUCT_TYPE,
                "modality": modality,
                "price": price,
                "delivery_days": None,
                "is_fallback": True,
            })

    return {
        "postal_code": postal_code,
        "billable_weight_kg": float(billable_weight_ca),
        "quotes": quotes,
    }


def cheapest_price(quotes: list[dict]) -> Decimal:
    """La cotización que efectivamente se cobra en el checkout cuando no
    hay un método explícito elegido: la más barata de las devueltas por
    `get_quotes()`."""
    return Decimal(str(min(q["price"] for q in quotes)))


def select_methods(quotes: list[dict]) -> list[dict]:
    """Traduce las cotizaciones de `get_quotes()` a los métodos que el
    checkout deja elegir al comprador, con el `id` estable que viaja como
    `shipping_method_id` (ej. "correoargentino_sucursal")."""
    methods = []
    for q in quotes:
        carrier_id = "correoargentino"
        label = _METHOD_LABELS.get((carrier_id, q["modality"]), q["carrier"])
        methods.append({
            "id": f"{carrier_id}_{q['modality']}",
            "carrier": q["carrier"],
            "modality": q["modality"],
            "label": label,
            "price": q["price"],
            "delivery_days": q["delivery_days"],
            "is_fallback": q["is_fallback"],
        })
    return methods


def default_fallback_price() -> Decimal:
    """Tarifa plana default (sin cotizar nada) — se usa en el checkout real
    cuando el comprador no mandó código postal: así el envío SIEMPRE se
    cobra (aunque sea una estimación), en vez de quedar en $0 por omisión."""
    return Decimal(str(settings.SHIPPING_FALLBACK_RATES.get("default", 0)))
