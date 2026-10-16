"""Catálogo de provincias argentinas + resolución de provincia (ISO
3166-2:AR, sin el prefijo "AR-") a partir del código postal.

Desde la integración directa con Correo Argentino (PaqAr v2), la provincia
ya no se infiere más: se le pide directo al comprador en el formulario de
dirección del checkout (`ShippingAddressSerializer`, reusado por
`payments`) — PaqAr v2 la exige como parte de `shippingData.address`, y
listar sucursales (`GET /v1/agencies`) también necesita el código real
(`stateId`). `resolve_provincia_ar()` queda de todos modos para la
cotización "preview" del carrito (`ShippingCalculateSerializer.province`,
opcional) cuando todavía no se completó el formulario de dirección.
"""

# (código ISO 3166-2:AR sin prefijo, nombre) — 24 provincias + CABA, el
# mismo catálogo que usa Correo Argentino en `stateId`. Espejado en el
# frontend (`types/`), no tocar uno sin el otro.
AR_PROVINCES: list[tuple[str, str]] = [
    ("C", "Ciudad Autónoma de Buenos Aires"),
    ("B", "Buenos Aires"),
    ("K", "Catamarca"),
    ("H", "Chaco"),
    ("U", "Chubut"),
    ("X", "Córdoba"),
    ("W", "Corrientes"),
    ("E", "Entre Ríos"),
    ("P", "Formosa"),
    ("Y", "Jujuy"),
    ("L", "La Pampa"),
    ("F", "La Rioja"),
    ("M", "Mendoza"),
    ("N", "Misiones"),
    ("Q", "Neuquén"),
    ("R", "Río Negro"),
    ("A", "Salta"),
    ("J", "San Juan"),
    ("D", "San Luis"),
    ("Z", "Santa Cruz"),
    ("S", "Santa Fe"),
    ("G", "Santiago del Estero"),
    ("V", "Tierra del Fuego"),
    ("T", "Tucumán"),
]

# (código_postal_desde, código_postal_hasta, código ISO 3166-2:AR)
# Rangos públicos de CPA de Correo Argentino. Ampliar solo con bloques
# verificados — es preferible "no resuelto" (→ fallback) a un dato mal
# inferido que termine cotizando con datos de otra provincia.
_KNOWN_RANGES: list[tuple[int, int, str]] = [
    (1000, 1499, "C"),  # CABA
]


def resolve_provincia_ar(postal_code: str) -> str | None:
    try:
        code = int(postal_code)
    except (TypeError, ValueError):
        return None
    for start, end, provincia in _KNOWN_RANGES:
        if start <= code <= end:
            return provincia
    return None
