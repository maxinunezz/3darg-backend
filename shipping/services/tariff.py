"""Tarifa de envío de **respaldo** (fallback), calculada LOCALMENTE sin
llamar a ninguna API — la API real de Correo Argentino (MiCorreo) SÍ tiene
cotización en vivo (`POST /rates`, ver `correo_argentino.py::get_rates()`),
que es la fuente primaria usada por `quote.py`. Esta tabla estática solo se
usa cuando esa consulta en vivo no está disponible: sin credenciales
cargadas, error de red, o sin código postal de destino conocido (caso del
selector de sucursal, que no pide CP al comprador).

- Tabla real "Encomienda Correo Clásica", columna Nacional (la más simple y
  la que nunca cobra de menos) + el cargo por Valor Declarado sobre el
  subtotal del carrito. Es el MISMO precio para las dos modalidades de
  entrega (igual que en la cotización real: Correo Argentino cotiza por
  peso/zona, el `deliveryType` que de verdad distingue sucursal de domicilio
  solo importa en el alta real, ver `correo_argentino.py`). Configurable vía
  `settings.CORREO_ARGENTINO_TARIFF`/`CORREO_ARGENTINO_VALOR_DECLARADO` sin
  tocar código.
- **Andreani**: se descartó del selector del carrito (ver CLAUDE.md →
  "Envíos") ahora que Correo Argentino cubre domicilio con tarifa real —
  el código de la integración de respaldo queda en el historial de git, no
  en este archivo.
"""
from decimal import Decimal

from django.conf import settings


def correo_argentino_fallback_price(billable_weight_kg: Decimal, declared_value: Decimal) -> Decimal:
    """Busca el tramo de peso facturable en `CORREO_ARGENTINO_TARIFF` (columna
    Nacional) y le suma el cargo por Valor Declarado calculado sobre
    `declared_value` (subtotal del carrito). Vale tanto para "a sucursal"
    como para "a domicilio" — ver docstring del módulo. Usar solo cuando
    `correo_argentino.get_rates()` no está disponible (ver `quote.py`).

    Si el peso supera el tramo más alto configurado, se usa ese tramo tope
    (nunca se deja sin cotizar un pedido pesado — mejor cobrar la tarifa
    más alta conocida que dejarlo en $0).
    """
    tariff: dict = settings.CORREO_ARGENTINO_TARIFF
    brackets = sorted(((Decimal(k), Decimal(str(v))) for k, v in tariff.items()), key=lambda b: b[0])
    if not brackets:
        base_price = Decimal("0")
    else:
        base_price = brackets[-1][1]
        for max_kg, price in brackets:
            if billable_weight_kg <= max_kg:
                base_price = price
                break

    return (base_price + _valor_declarado_surcharge(declared_value)).quantize(Decimal("0.01"))


def _valor_declarado_surcharge(declared_value: Decimal) -> Decimal:
    """Cargo adicional por Valor Declarado — tabla configurable en
    `CORREO_ARGENTINO_VALOR_DECLARADO_JSON`: lista de brackets
    `[tope, cargo]`, `cargo` es un monto fijo o un string "N%". El último
    bracket se sigue aplicando por default a cualquier valor que lo supere
    (no hay tramo documentado arriba de $200.000 hoy).
    """
    if declared_value <= 0:
        return Decimal("0")

    config = settings.CORREO_ARGENTINO_VALOR_DECLARADO
    brackets = config.get("brackets", [])
    if not brackets:
        return Decimal("0")

    def _charge_for(cargo, value: Decimal) -> Decimal:
        if isinstance(cargo, str) and cargo.strip().endswith("%"):
            pct = Decimal(cargo.strip().rstrip("%"))
            return (value * pct / Decimal("100"))
        return Decimal(str(cargo))

    for tope, cargo in brackets:
        if declared_value <= Decimal(str(tope)):
            return _charge_for(cargo, declared_value)

    # Supera el último tramo documentado: se sigue aplicando el cargo del
    # último bracket (hoy, 3%) por defecto.
    last_tope, last_cargo = brackets[-1]
    return _charge_for(last_cargo, declared_value)
