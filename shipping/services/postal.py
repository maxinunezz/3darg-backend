"""Resolución de provincia (ISO 3166-2:AR, sin el prefijo "AR-") a partir
del código postal.

Envíopack exige `provincia` para cotizar (ver `/cotizar/costo`), pero esta
tienda hoy solo le pide al comprador el código postal en el checkout — y el
sistema viejo de códigos postales de 4 dígitos NO tiene un mapeo 1:1
confiable a provincia (los rangos históricos no son contiguos). Por eso
esta función cubre ÚNICAMENTE bloques inequívocos y bien conocidos; para
cualquier otro código devuelve `None` y quien la llama cae al fallback de
tarifa plana en vez de arriesgar una provincia incorrecta (que Envíopack
podría aceptar igual y cotizar mal, sin avisar del error).

Lo ideal a mediano plazo: que el formulario de checkout le pida la
provincia directo al comprador (lo más común en un checkout argentino) y la
mande en el body de `/api/shipping/calculate` (`province`) — ahí esta
función ni se usa. Ver `shipping/views.py`.
"""

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
