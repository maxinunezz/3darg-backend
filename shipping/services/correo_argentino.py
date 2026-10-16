"""Cliente de la API real de Correo Argentino — **API MiCorreo**, confirmada
contra la documentación oficial ("Correo Argentino - API MiCorreo.pdf") y la
cuenta real del dueño en el panel de MiCorreo (customerId `0002005182`).

Reemplaza una integración anterior de esta misma función que se había
implementado sobre una documentación equivocada ("PaqAr v2": auth
`Apikey`/`agreement`, sin endpoint de cotización, con AltaOrden/labels/cancel
que no existen acá) — quedó descartada por completo, no es un producto de
Correo Argentino que el dueño tenga contratado.

Puntos clave de la API real:
- **Auth**: `POST /token` con HTTP Basic (`CORREO_ARGENTINO_USER`/`PASSWORD`)
  devuelve `{"token": "<jwt>", "expires": "YYYY-MM-DD HH:MM:SS"}`. Todas las
  demás llamadas usan `Authorization: Bearer <token>` — el token vence, se
  cachea en memoria de proceso y se renueva solo (`_get_token()`).
- **SÍ tiene cotización real** (`POST /rates`) — a diferencia de lo asumido
  antes, no hace falta una tabla estática para cotizar (se usa igual como
  fallback si no hay credenciales, falla la red, o no se conoce el CP
  destino, ver `shipping/services/quote.py`).
- **`POST /shipping/import` no devuelve tracking number en la respuesta**
  (solo `{"createdAt": ...}`) — el identificador del envío de cara a
  Correo Argentino es el `extOrderId` que nosotros mandamos
  (`order.external_reference`), no algo que ellos generen y nos devuelvan.
- **No existe generación de etiquetas ni cancelación de envío** en esta API
  — por eso no hay `get_labels()`/`cancel_order()` acá (si hiciera falta
  alguna de las dos, hay que pedirle a Correo Argentino un mecanismo
  distinto, no está en esta documentación).
- Vacío `CORREO_ARGENTINO_USER`/`PASSWORD`/`CUSTOMER_ID` = integración
  apagada (mismo criterio "vacío = apagado" de siempre): `list_agencies()`
  devuelve `[]`, `get_rates()` devuelve `None`, `create_shipment()` lanza
  `CorreoArgentinoConfigError`. La cotización de respaldo (tabla estática,
  `tariff.py`) sigue funcionando igual, no depende de esto.
- Llamadas de lectura (`list_agencies`, `get_rates`, `get_tracking`) nunca
  lanzan excepción: loguean y devuelven `None`/`[]`. `create_shipment()` SÍ
  puede lanzar `CorreoArgentinoError` — el caller (`orders/signals.py`,
  `orders/admin.py`) decide qué hacer (loguear sin romper el flujo de pago,
  o mostrar el error en el admin).
"""
import logging
import threading
from datetime import datetime, timedelta
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Caché de token en memoria de proceso — un solo token compartido por todos
# los requests del worker (no hace falta por-usuario, es credencial de
# aplicación). `threading.Lock` porque gunicorn puede atender requests
# concurrentes en el mismo proceso (threads).
_token_lock = threading.Lock()
_token_cache: dict = {"token": None, "expires_at": None}

# Margen de seguridad antes del vencimiento real del token, para no arrancar
# un request con un token que vence a mitad de la llamada.
_TOKEN_SAFETY_MARGIN = timedelta(minutes=2)


class CorreoArgentinoConfigError(Exception):
    """Faltan credenciales — no es un error de red, es config incompleta."""


class CorreoArgentinoError(Exception):
    """La API respondió con un error real (ej. shipping/import rechazado)."""


def _configured() -> bool:
    return bool(
        settings.CORREO_ARGENTINO_USER
        and settings.CORREO_ARGENTINO_PASSWORD
        and settings.CORREO_ARGENTINO_CUSTOMER_ID
    )


def _base_url() -> str:
    return settings.CORREO_ARGENTINO_BASE_URL.rstrip("/")


def _parse_expires(raw: str) -> datetime | None:
    """`expires` viene como `"YYYY-MM-DD HH:MM:SS"` (sin timezone, hora local
    de Argentina según la doc) — se interpreta naive y se compara contra
    `datetime.now()` (también naive), para no depender de pytz/zoneinfo acá."""
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _get_token() -> str | None:
    """Devuelve un JWT válido, pidiendo uno nuevo a `POST /token` (HTTP
    Basic Auth) si no hay uno cacheado o si está por vencer. Devuelve `None`
    si no hay credenciales configuradas o si la autenticación falla (se
    loguea el motivo) — nunca lanza excepción, para que `list_agencies()`/
    `get_rates()` puedan degradar a `[]`/`None` sin romper nada; el único
    caller que sí necesita tratar esto como error duro es
    `create_shipment()`, que revisa el `None` y lanza `CorreoArgentinoError`
    explícito."""
    if not _configured():
        return None

    with _token_lock:
        cached_token = _token_cache.get("token")
        expires_at = _token_cache.get("expires_at")
        if cached_token and expires_at and datetime.now() < expires_at - _TOKEN_SAFETY_MARGIN:
            return cached_token

        try:
            response = requests.post(
                f"{_base_url()}/token",
                auth=(settings.CORREO_ARGENTINO_USER, settings.CORREO_ARGENTINO_PASSWORD),
                timeout=settings.CORREO_ARGENTINO_TIMEOUT,
            )
            if not response.ok:
                logger.error(
                    "Correo Argentino: no se pudo obtener token — HTTP %s: %s",
                    response.status_code, response.text,
                )
                return None
            data = response.json()
            token = data.get("token")
            if not token:
                logger.error("Correo Argentino: respuesta de /token sin campo 'token': %s", data)
                return None
            _token_cache["token"] = token
            _token_cache["expires_at"] = _parse_expires(data.get("expires", "")) or (
                datetime.now() + timedelta(minutes=55)
            )
            return token
        except requests.RequestException as e:
            logger.error("Correo Argentino: error de red al pedir token: %s", e)
            return None
        except ValueError as e:
            logger.error("Correo Argentino: respuesta inválida de /token: %s", e)
            return None


def _headers() -> dict | None:
    token = _get_token()
    if not token:
        return None
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def list_agencies(province_code: str) -> list[dict]:
    """`GET /agencies` — lista de sucursales reales de una provincia, para
    que el comprador elija una al retirar en sucursal. Devuelve `[]` si no
    hay credenciales configuradas o si falla la consulta — nunca rompe el
    checkout (el frontend simplemente no muestra opciones todavía).

    Cada sucursal trae `{code, name, manager, email, phone,
    services:{packageReception, pickupAvailability}, location:{address:{...},
    latitude, longitude}, hours:{...}, status}` (confirmado contra la doc
    real — no son nombres de campo supuestos)."""
    headers = _headers()
    if not headers:
        logger.debug("Correo Argentino no configurado — list_agencies() devuelve []")
        return []

    try:
        response = requests.get(
            f"{_base_url()}/agencies",
            params={
                "customerId": settings.CORREO_ARGENTINO_CUSTOMER_ID,
                "provinceCode": province_code,
            },
            headers=headers,
            timeout=settings.CORREO_ARGENTINO_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except requests.RequestException as e:
        logger.error("Correo Argentino: error al listar sucursales (provincia=%s): %s", province_code, e)
        return []
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Correo Argentino: respuesta inesperada al listar sucursales: %s", e)
        return []


def _parcel_weight_and_dims(order) -> tuple[int, dict]:
    """Peso real total (en gramos) y dimensiones del bulto, a partir de los
    `OrderItem` reales — usa las medidas más grandes entre los ítems como
    proxy del bulto único que se despacha (un solo parcel por envío, no uno
    por producto — `/rates/calculate`/`/rates/packages` permitirían apilar
    varios bultos lógicos, no implementado todavía, ver TODO en
    `get_rates()`). Si ningún ítem tiene medidas cargadas, cae a las
    dimensiones default de `settings.SHIPPING_DEFAULT_ITEM_DIMENSIONS_CM`.
    """
    default_l, default_w, default_h = settings.SHIPPING_DEFAULT_ITEM_DIMENSIONS_CM
    total_weight_kg = Decimal("0")
    max_l, max_w, max_h = Decimal(str(default_l)), Decimal(str(default_w)), Decimal(str(default_h))

    for item in order.order_items.select_related("product").all():
        product = item.product
        if not product:
            continue
        if product.weight_kg:
            total_weight_kg += Decimal(product.weight_kg) * item.quantity
        if product.length_cm and product.length_cm > max_l:
            max_l = Decimal(product.length_cm)
        if product.width_cm and product.width_cm > max_w:
            max_w = Decimal(product.width_cm)
        if product.height_cm and product.height_cm > max_h:
            max_h = Decimal(product.height_cm)

    if total_weight_kg <= 0:
        total_weight_kg = Decimal(str(settings.SHIPPING_MIN_WEIGHT_KG))

    weight_grams = int((total_weight_kg * 1000).to_integral_value(rounding="ROUND_HALF_UP"))
    return weight_grams, {"height": int(max_h), "width": int(max_w), "length": int(max_l)}


def get_rates(*, postal_code_destination: str, weight_grams: int, height_cm: int,
               width_cm: int, length_cm: int, delivered_type: str | None = None) -> list[dict] | None:
    """`POST /rates` — cotización real de Correo Argentino. `delivered_type`
    es `"D"` (domicilio) o `"S"` (sucursal); `None` pide las dos de una
    (la API las devuelve juntas en `rates[]`, ver doc). El origen lo toma la
    API de la sucursal/domicilio dado de alta para `CUSTOMER_ID` — igual se
    manda `postalCodeOrigin` (`CORREO_ARGENTINO_SENDER_ZIP`) porque la doc lo
    marca como requerido.

    Devuelve la lista `rates` tal cual la manda la API
    (`[{deliveredType, productType, productName, price, deliveryTimeMin,
    deliveryTimeMax}, ...]`), o `None` si no hay credenciales, falla la red,
    o la respuesta no es la esperada — el caller (`quote.py`) cae a la tabla
    estática de respaldo en ese caso."""
    headers = _headers()
    if not headers:
        logger.debug("Correo Argentino no configurado — get_rates() devuelve None")
        return None
    if not settings.CORREO_ARGENTINO_SENDER_ZIP:
        logger.warning("Correo Argentino: falta CORREO_ARGENTINO_SENDER_ZIP (postalCodeOrigin) — get_rates() devuelve None")
        return None

    payload = {
        "customerId": settings.CORREO_ARGENTINO_CUSTOMER_ID,
        "postalCodeOrigin": settings.CORREO_ARGENTINO_SENDER_ZIP,
        "postalCodeDestination": postal_code_destination,
        "dimensions": {
            "weight": weight_grams,
            "height": height_cm,
            "width": width_cm,
            "length": length_cm,
        },
    }
    if delivered_type:
        payload["deliveredType"] = delivered_type

    try:
        response = requests.post(
            f"{_base_url()}/rates",
            json=payload,
            headers=headers,
            timeout=settings.CORREO_ARGENTINO_TIMEOUT,
        )
        if not response.ok:
            logger.error("Correo Argentino: /rates rechazado — HTTP %s: %s", response.status_code, response.text)
            return None
        data = response.json()
        rates = data.get("rates")
        return rates if isinstance(rates, list) else None
    except requests.RequestException as e:
        logger.error("Correo Argentino: error de red al cotizar: %s", e)
        return None
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Correo Argentino: respuesta inesperada de /rates: %s", e)
        return None


def _build_shipment_payload(order) -> dict:
    weight_grams, dims = _parcel_weight_and_dims(order)
    declared_value = float(order.total_amount - order.shipping_cost)

    sender = {
        "name": settings.CORREO_ARGENTINO_SENDER_NAME or None,
        "phone": settings.CORREO_ARGENTINO_SENDER_PHONE or None,
        "email": settings.CORREO_ARGENTINO_SENDER_EMAIL or None,
        "originAddress": {
            "streetName": settings.CORREO_ARGENTINO_SENDER_STREET or None,
            "streetNumber": settings.CORREO_ARGENTINO_SENDER_STREET_NUMBER or None,
            "city": settings.CORREO_ARGENTINO_SENDER_CITY or None,
            "provinceCode": settings.CORREO_ARGENTINO_SENDER_PROVINCE or None,
            "postalCode": settings.CORREO_ARGENTINO_SENDER_ZIP or None,
        },
    }

    # "D" (domicilio) vs "S" (sucursal) — único campo que distingue la
    # modalidad en el payload real (la doc dice textual: "D" (no "S") envío
    # a domicilio, "S" envío a sucursal).
    is_sucursal = order.shipping_modality == "sucursal"
    shipping: dict = {
        "deliveryType": "S" if is_sucursal else "D",
        "productType": settings.CORREO_ARGENTINO_PRODUCT_TYPE,
        "weight": weight_grams,
        "declaredValue": declared_value,
        "height": dims["height"],
        "length": dims["length"],
        "width": dims["width"],
    }
    if is_sucursal:
        shipping["agency"] = order.shipping_agency_id
        # La dirección completa solo es obligatoria para domicilio
        # (`shipping.deliveryType != "S"`, confirmado en la doc) — para
        # sucursal no hace falta mandarla.
    else:
        shipping["address"] = {
            "streetName": order.shipping_street,
            "streetNumber": order.shipping_street_number,
            "floor": (order.shipping_floor or "")[:3],
            "apartment": (order.shipping_department or "")[:3],
            "city": order.shipping_city,
            "provinceCode": order.shipping_province,
            "postalCode": order.shipping_postal_code,
        }

    return {
        "customerId": settings.CORREO_ARGENTINO_CUSTOMER_ID,
        "extOrderId": order.external_reference,
        "orderNumber": str(order.id),
        "sender": sender,
        "recipient": {
            "name": order.shipping_full_name,
            "phone": order.shipping_phone,
            "cellPhone": order.shipping_phone,
            "email": order.customer_email,
        },
        "shipping": shipping,
    }


def create_shipment(order) -> dict:
    """`POST /shipping/import`. Usa `order.external_reference` como
    `extOrderId` (UUID hex único) — un reintento manda el mismo valor; la
    doc dice que la API rechaza con el mensaje "La orden ya fue importada
    con anterioridad" en ese caso, así que el reintento es seguro (no crea
    un envío duplicado, solo falla de forma reconocible).

    **La respuesta exitosa es solo `{"createdAt": "..."}` — no trae ningún
    tracking number.** El identificador del envío de cara a Correo
    Argentino es nuestro propio `extOrderId`; si se necesita el
    `trackingNumber`/`shippingId` real que asigna el correo, hay que
    consultarlo aparte (no confirmado en esta doc cómo se obtiene a partir
    del `extOrderId` — `get_tracking()` pide `shippingId`, que no es lo
    mismo).

    Lanza `CorreoArgentinoConfigError` si no hay credenciales, o
    `CorreoArgentinoError` con el mensaje de la API si la rechaza — el
    caller decide qué hacer (ver `orders/signals.py`).
    """
    headers = _headers()
    if not headers:
        raise CorreoArgentinoConfigError(
            "CORREO_ARGENTINO_USER/CORREO_ARGENTINO_PASSWORD/CORREO_ARGENTINO_CUSTOMER_ID no configurados"
        )

    payload = _build_shipment_payload(order)
    try:
        response = requests.post(
            f"{_base_url()}/shipping/import",
            json=payload,
            headers=headers,
            timeout=settings.CORREO_ARGENTINO_TIMEOUT,
        )
        if not response.ok:
            raise CorreoArgentinoError(f"HTTP {response.status_code}: {response.text}")
        return response.json()
    except requests.RequestException as e:
        raise CorreoArgentinoError(f"Error de red al importar el envío: {e}") from e


def get_tracking(shipping_id: str) -> list[dict] | None:
    """`GET /shipping/tracking` — seguimiento de UN envío (la API toma un
    solo `shippingId` por llamada vía body JSON, no una lista — a diferencia
    de lo asumido en una iteración anterior de esta integración). Devuelve
    la lista de eventos tal cual la manda la API, o `None` si no hay
    credenciales, falla la red, o la respuesta indica error."""
    headers = _headers()
    if not headers:
        logger.debug("Correo Argentino no configurado — get_tracking() devuelve None")
        return None
    try:
        response = requests.get(
            f"{_base_url()}/shipping/tracking",
            json={"shippingId": shipping_id},
            headers=headers,
            timeout=settings.CORREO_ARGENTINO_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            logger.warning("Correo Argentino: tracking %s respondió error: %s", shipping_id, data.get("error"))
            return None
        return data if isinstance(data, list) else [data]
    except requests.RequestException as e:
        logger.error("Correo Argentino: error al consultar tracking %s: %s", shipping_id, e)
        return None
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Correo Argentino: respuesta inesperada al consultar tracking: %s", e)
        return None
