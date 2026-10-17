"""Separar un teléfono argentino en (código de área, número) — lo que pide
el CSV de "Carga masiva" de MiCorreo (`cod_area_cel` + `cel` por separado,
ver `orders/admin.py::exportar_csv_carga_masiva`), a partir del teléfono que
guardamos en `Order.shipping_phone` como un solo string.

Desde que el checkout usa `react-phone-number-input` (ver
`ecommerce-frontend/components/shipping-address-form.tsx`/`shipping-estimator.tsx`)
las órdenes NUEVAS guardan el teléfono en formato E.164 (`+5491122334455`),
validado y sin ambigüedad. Las órdenes VIEJAS (anteriores a ese cambio)
pueden tener cualquier texto libre que el comprador haya tipeado a mano
("011 15-2233-4455", "1122334455", etc.) — por eso `parse()` también
intenta con la región "AR" por default, para seguir soportando esas.

No usamos `phonenumbers.length_of_national_destination_code()` directo
porque da mal el código de área en números de celular argentinos (el "9"
que antepone el estándar internacional para celulares se mete en el cálculo
del NDC y lo arruina — bug conocido de libphonenumber con Argentina).  En
cambio, parseamos el string ya formateado en NATIONAL (que sí resuelve bien
el "9"/"15" internamente) con una regex simple: `0<area> <15-><resto>`.
"""
import re

import phonenumbers
from phonenumbers import PhoneNumberFormat

_NATIONAL_RE = re.compile(r"^0?(\d+)\s+(?:15[- ]?)?(.+)$")


def split_ar_phone(raw: str) -> tuple[str, str] | None:
    """Devuelve `(codigo_area, numero)` (ambos solo dígitos, sin "0" ni "15")
    si `raw` es parseable como un teléfono argentino válido/posible; `None`
    si está vacío, es basura, o no se pudo determinar con confianza (mejor
    no adivinar mal que mandar un dato incorrecto a Correo Argentino)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        parsed = phonenumbers.parse(raw, "AR")
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_possible_number(parsed):
        return None

    national = phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL)
    match = _NATIONAL_RE.match(national)
    if not match:
        return None

    area_code = match.group(1)
    subscriber = re.sub(r"\D", "", match.group(2))
    if not area_code or not subscriber:
        return None
    return area_code, subscriber
