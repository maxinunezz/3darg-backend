import logging
from functools import lru_cache
from string import Template

import requests
from django.utils import timezone

from .models import MLCredentials, MLListingTemplate

logger = logging.getLogger(__name__)

ML_API_BASE = "https://api.mercadolibre.com"
ML_TOKEN_URL = f"{ML_API_BASE}/oauth/token"

# Mercado Libre penaliza el "quality score" de la publicación con menos de 3 fotos
# (regla PICTURES_QUANTITY_MIN de GET /items/{id}/performance) — lo exigimos como piso
# duro acá en vez de dejarlo como sugerencia, para no publicar fichas de baja calidad.
MIN_ML_PICTURES = 3

# sale_terms.WARRANTY_TYPE para MLA375405 (value_type="list"), confirmado en vivo vía
# GET /categories/MLA375405/sale_terms con un access_token real — "Garantía del
# vendedor" es la única opción que tiene sentido acá (no es garantía de fábrica, un
# tercero no nos la emite).
ML_WARRANTY_TYPE_SELLER_VALUE_ID = "2230280"

# IS_DISHWASHER_SAFE.value_id para MLA375405 (value_type="boolean"), confirmado en vivo
# vía GET /categories/MLA375405/attributes — ML pide el value_id puntual, no alcanza con
# mandar un booleano suelto.
ML_DISHWASHER_SAFE_VALUE_IDS = {True: "242085", False: "242084"}

# Margen de seguridad antes de que venza el access_token: lo renovamos un poco
# antes para no arriesgarnos a que expire a mitad de una sync.
TOKEN_REFRESH_MARGIN = timezone.timedelta(minutes=5)


class MLSyncError(Exception):
    """Error de negocio al sincronizar un producto con Mercado Libre (mensaje ya en español, listo para mostrar en el admin)."""


def _refresh_access_token(creds, client_id, client_secret):
    """Pide un access_token nuevo con el refresh_token guardado.

    ML rota el refresh_token en cada uso (el viejo queda inválido) — hay que
    guardar siempre el que venga en la respuesta, no reusar el anterior.
    """
    response = requests.post(
        ML_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": creds.refresh_token,
        },
        timeout=15,
    )
    if not response.ok:
        logger.error("Error renovando token de ML: %s", response.text)
        raise MLSyncError(
            "No se pudo renovar la conexión con Mercado Libre. "
            "Probablemente haya que reconectar la cuenta desde el admin."
        )
    data = response.json()
    creds.access_token = data["access_token"]
    creds.refresh_token = data["refresh_token"]
    creds.expires_at = timezone.now() + timezone.timedelta(seconds=data["expires_in"])
    creds.save()
    return creds.access_token


def get_valid_access_token():
    """Devuelve un access_token vigente, renovándolo si está por vencer."""
    from django.conf import settings

    if not settings.ML_CLIENT_ID or not settings.ML_CLIENT_SECRET:
        raise MLSyncError("Falta configurar ML_CLIENT_ID/ML_CLIENT_SECRET en el .env del backend.")

    creds = MLCredentials.load()
    if not creds.is_connected:
        raise MLSyncError(
            "La cuenta de Mercado Libre todavía no está conectada. "
            "Andá a Mercado Libre → Credenciales de Mercado Libre y conectala."
        )
    if not creds.expires_at or timezone.now() >= creds.expires_at - TOKEN_REFRESH_MARGIN:
        return _refresh_access_token(creds, settings.ML_CLIENT_ID, settings.ML_CLIENT_SECRET)
    return creds.access_token


def _request(method, path, **kwargs):
    token = get_valid_access_token()
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    response = requests.request(method, f"{ML_API_BASE}{path}", headers=headers, timeout=20, **kwargs)
    if not response.ok:
        logger.error("Error de la API de Mercado Libre (%s %s): %s", method, path, response.text)
        raise MLSyncError(f"Mercado Libre rechazó la operación: {_describe_ml_error(response)}")
    return response.json() if response.content else {}


def _describe_ml_error(response):
    """Arma un detalle legible a partir del error de ML.

    El `message` de nivel superior (ej: "body.required_fields") suele ser un
    código genérico — el detalle de qué campo falta específicamente viene en
    `cause` (lista de strings o de dicts con `message`/`code`).
    """
    try:
        data = response.json()
    except ValueError:
        return response.text

    parts = []
    causes = data.get("cause") or []
    if not isinstance(causes, list):
        causes = [causes]
    for cause in causes:
        if isinstance(cause, dict):
            parts.append(cause.get("message") or cause.get("code") or str(cause))
        else:
            parts.append(str(cause))

    message = data.get("message", response.text)
    if parts:
        return f"{message} ({'; '.join(parts)})"
    return message


def _fmt_num(value):
    """Decimal 8.000 -> '8', 8.500 -> '8.5' (sin ceros de más en el texto)."""
    return format(value.normalize(), "f")


def _build_medidas(product):
    dims = [product.length_cm, product.width_cm, product.height_cm]
    if not any(dims):
        return "Ver detalle en las fotos de la publicación"
    return " x ".join(f"{_fmt_num(d)} cm" for d in dims if d)


def _build_title(product):
    """Título SEO de ML: nombre del producto + lo fijo (set + material).

    Mercado Libre corta a 60 caracteres (MLA375405: max_title_length=60) y, para esta
    categoría, el título queda fijo para siempre una vez creado el ítem (no se puede
    editar después) — por eso el recorte, si hace falta, nunca parte una palabra a la
    mitad (ej: "Jirafa" -> "Jira"), sino que corta por la última palabra completa que
    entre. Las medidas no van en el título (ya están en la ficha técnica de la
    descripción); meterlas acá le robaba demasiado espacio al nombre del producto.
    """
    suffix = " - Cortante y Marcador PLA Apto Alimentos"
    available = 60 - len(suffix)
    name = product.name
    if len(name) > available:
        name = name[:available].rsplit(" ", 1)[0].rstrip()
    return f"{name}{suffix}"[:60]


def _build_description(product):
    template = MLListingTemplate.load().description_template
    return Template(template).safe_substitute(
        modelo=product.name,
        medidas=_build_medidas(product),
    )


@lru_cache(maxsize=32)
def _fetch_category_attribute_ids(category_id):
    """IDs de atributos que admite `category_id` en Mercado Libre (ej: si la
    categoría tiene COLOR, SIZE, etc. entre sus atributos propios).

    Endpoint público (`GET /categories/{id}/attributes`, no necesita
    access_token) — se cachea en memoria por categoría porque la lista no
    cambia en caliente y evita pegarle a la API una vez por producto en una
    publicación en lote (`publicar_en_mercadolibre` puede correr sobre
    varios productos de la misma categoría). Usado para decidir si mandar
    `color`/`size` del producto como atributos reales de la publicación (ver
    `_build_payload()`) sin asumir que toda categoría los admite — distintas
    sub-marcas pueden terminar publicando en categorías de ML muy distintas
    (ej: indumentaria con talle real vs. cortantes sin atributo de tamaño).

    Devuelve un frozenset vacío si la consulta falla (red, categoría
    inválida, etc.) — es una mejora opcional de la publicación, nunca debe
    bloquearla.
    """
    try:
        response = requests.get(f"{ML_API_BASE}/categories/{category_id}/attributes", timeout=15)
        response.raise_for_status()
        return frozenset(attr["id"] for attr in response.json())
    except (requests.RequestException, ValueError, KeyError, TypeError):
        logger.warning("No se pudieron consultar los atributos de la categoría %s de Mercado Libre.", category_id)
        return frozenset()


def _build_payload(product):
    if not product.ml_category_id:
        raise MLSyncError("El producto no tiene categoría de Mercado Libre cargada (ml_category_id).")

    ml_images = product.images.filter(channel="ml").order_by("order")
    pictures = [{"source": image.image.url} for image in ml_images if image.image]
    if len(pictures) < MIN_ML_PICTURES:
        raise MLSyncError(
            f"El producto necesita al menos {MIN_ML_PICTURES} imágenes en el apartado "
            "\"Imágenes — Mercado Libre\" — Mercado Libre penaliza la calidad de la "
            f"publicación con menos de {MIN_ML_PICTURES} fotos. Hoy tiene {len(pictures)}."
        )

    payload = {
        # MLA375405 tiene attribute_types="variations": ML exige family_name y ahí genera
        # el título solo — no se puede mandar "title" aparte ni editarlo después de creado.
        # Como no hay un atributo que diferencie variantes (color/talle), el título final
        # queda igual al family_name, así que acá va directo el texto SEO ya armado.
        "family_name": _build_title(product),
        "category_id": product.ml_category_id,
        "price": float(product.price),
        "currency_id": "ARS",
        "available_quantity": product.stock,
        "condition": "new",
        "listing_type_id": "gold_special",
        "buying_mode": "buy_it_now",
        "pictures": pictures,
        "attributes": [
            {"id": "BRAND", "value_name": "3DARG"},
            {"id": "MODEL", "value_name": product.sku},
            # SELLER_SKU es el campo que ML reserva para el código interno del
            # vendedor (distinto de MODEL, que es un atributo genérico de
            # catálogo) — mandamos el mismo valor acá para que el SKU quede
            # también en el lugar "correcto" de la publicación, sin tocar
            # MODEL por las dudas de que algún listing ya viejo dependa de él.
            {"id": "SELLER_SKU", "value_name": product.sku},
        ],
    }

    # HEIGHT/WIDTH/DEPTH: mismos datos que ya cargamos para `shipping.dimensions`, pero
    # ML también los pide como atributos propios — sin esto el ítem queda marcado con el
    # tag `incomplete_technical_specs` y puede quedar trabado en revisión manual
    # (status=under_review, sub_status=waiting_for_patch).
    if product.height_cm:
        payload["attributes"].append({"id": "HEIGHT", "value_name": f"{_fmt_num(product.height_cm)} cm"})
    if product.width_cm:
        payload["attributes"].append({"id": "WIDTH", "value_name": f"{_fmt_num(product.width_cm)} cm"})
    if product.length_cm:
        payload["attributes"].append({"id": "DEPTH", "value_name": f"{_fmt_num(product.length_cm)} cm"})

    # GTIN es opcional en esta categoría (no tiene EMPTY_GTIN_REASON) — solo lo mandamos
    # si el producto tiene un código de barras real cargado. No inventar uno: ML valida
    # el checksum y rechaza el POST si el formato no es válido.
    if product.gtin:
        payload["attributes"].append({"id": "GTIN", "value_name": product.gtin})

    # color/size son campos genéricos del producto (también se usan para armar el SKU,
    # ver Product.generate_sku()) — se mandan como atributos reales de ML (COLOR/SIZE)
    # SOLO si la categoría cargada los admite (confirmado en vivo vía
    # _fetch_category_attribute_ids), para no romper el publish en categorías que no
    # los tengan (ej: MLA375405 "Cortantes" no tiene atributo de tamaño/talle).
    category_attribute_ids = _fetch_category_attribute_ids(product.ml_category_id)
    if product.color and "COLOR" in category_attribute_ids:
        payload["attributes"].append({"id": "COLOR", "value_name": product.color})
    if product.size and "SIZE" in category_attribute_ids:
        payload["attributes"].append({"id": "SIZE", "value_name": product.size})
    # "Características secundarias" en el panel de ML (forma, apto lavavajillas) — no
    # son obligatorias para publicar, pero suman a la "calidad de la publicación"
    # (ML las muestra ahí mismo como "0 características completas" si quedan vacías).
    if product.shape and "COOKIE_CUTTER_SHAPE" in category_attribute_ids:
        payload["attributes"].append({"id": "COOKIE_CUTTER_SHAPE", "value_name": product.shape})
    if product.is_dishwasher_safe is not None and "IS_DISHWASHER_SAFE" in category_attribute_ids:
        payload["attributes"].append({
            "id": "IS_DISHWASHER_SAFE",
            "value_id": ML_DISHWASHER_SAFE_VALUE_IDS[product.is_dishwasher_safe],
            "value_name": "Sí" if product.is_dishwasher_safe else "No",
        })

    # sale_terms es una clave aparte de "attributes" (confirmado en vivo contra
    # GET /categories/MLA375405/sale_terms) — WARRANTY_TIME necesita value_struct, no
    # alcanza con un value_name de texto libre.
    if product.warranty_months:
        payload["sale_terms"] = [
            {
                "id": "WARRANTY_TYPE",
                "value_id": ML_WARRANTY_TYPE_SELLER_VALUE_ID,
                "value_name": "Garantía del vendedor",
            },
            {
                "id": "WARRANTY_TIME",
                "value_name": f"{product.warranty_months} meses",
                "value_struct": {"number": product.warranty_months, "unit": "meses"},
            },
        ]

    shipping = {}
    if product.weight_kg and product.length_cm and product.width_cm and product.height_cm:
        weight_grams = int(product.weight_kg * 1000)
        shipping["mode"] = "me2"
        shipping["dimensions"] = (
            f"{int(product.length_cm)}x{int(product.width_cm)}x"
            f"{int(product.height_cm)},{weight_grams}"
        )
    if product.free_shipping_seller_paid:
        shipping["free_shipping"] = True
    if shipping:
        payload["shipping"] = shipping

    return payload


ML_ACTIVE_STATUS = "active"


def _format_ml_warnings(warnings):
    """Traduce los `warnings` que ML devuelve en el BODY de una respuesta 200
    (ej: `shipping.free_shipping.cost_exceeded` cuando el precio es muy bajo
    para absorber el costo de envío) a mensajes legibles.

    Son distintos de los errores que maneja `_describe_ml_error()`: acá el
    request en sí fue aceptado (status 2xx, no levanta MLSyncError), pero ML
    igual puede ignorar en silencio una parte del payload (ej: no activar
    `free_shipping`) — si no se muestran estos mensajes en algún lado, el
    campo queda "prendido" en nuestro admin pero sin efecto real en la
    publicación, sin que nadie se entere.
    """
    return [f"{w.get('code', '?')}: {w.get('message', '')}" for w in (warnings or [])]


def sync_product(product):
    """Crea o actualiza la publicación de `product` en Mercado Libre.

    Primera vez (sin ml_item_id): POST /items y guarda el id devuelto.
    Siguientes veces: PUT /items/{id} con los mismos datos (actualiza precio,
    stock, fotos, etc. de la publicación existente).

    `is_available_ml` controla el canal ML por separado de la web: si está
    apagado y el ítem ya existe, esta llamada lo PAUSA en vez de actualizarlo
    (no se tocan precio/stock/fotos mientras esté pausado); si está apagado y
    todavía no se publicó, no se puede publicar por primera vez así (tiene que
    prenderse antes). Si está prendido y el ítem venía pausado, esta misma
    llamada lo reactiva.

    Devuelve `(ml_item_id, warnings)` — `warnings` es una lista (puede estar
    vacía) de avisos NO bloqueantes que ML devolvió junto con la respuesta
    200 (ver `_format_ml_warnings`), para mostrarlos en el admin. Lanza
    MLSyncError con mensaje en español ante cualquier problema bloqueante
    (sin categoría, sin imágenes, rechazo de la API, etc.).
    """
    if not product.is_available_ml:
        if not product.ml_item_id:
            raise MLSyncError(
                "Este producto tiene desactivado el canal Mercado Libre "
                "(is_available_ml) y todavía no se publicó — activalo antes "
                "de publicarlo por primera vez."
            )
        _request("PUT", f"/items/{product.ml_item_id}", json={"status": "paused"})
        return product.ml_item_id, []

    payload = _build_payload(product)

    if product.ml_item_id:
        # family_name, listing_type_id y shipping.mode/dimensions son inmutables una vez
        # creado el ítem — ML rechaza cualquier PUT que los incluya (BODY_INVALID_FIELDS /
        # field_not_updatable), incluso si el valor no cambió. Solo van en el POST inicial.
        # shipping.free_shipping SÍ es mutable (confirmado en vivo), así que lo conservamos
        # aparte en vez de tirar todo el dict "shipping".
        update_payload = {
            k: v for k, v in payload.items()
            if k not in ("family_name", "listing_type_id")
        }
        if "shipping" in update_payload:
            shipping_update = {
                k: v for k, v in update_payload["shipping"].items() if k == "free_shipping"
            }
            if shipping_update:
                update_payload["shipping"] = shipping_update
            else:
                update_payload.pop("shipping")
        # Por si el ítem estaba pausado (is_available_ml se acaba de reactivar).
        update_payload["status"] = ML_ACTIVE_STATUS
        response_data = _request("PUT", f"/items/{product.ml_item_id}", json=update_payload)
        item_id = product.ml_item_id
    else:
        response_data = _request("POST", "/items", json=payload)
        item_id = response_data["id"]
        product.ml_item_id = item_id
        product.save(update_fields=["ml_item_id"])

    _request(
        "PUT",
        f"/items/{item_id}/description",
        json={"plain_text": _build_description(product)},
    )

    return item_id, _format_ml_warnings(response_data.get("warnings"))


def handle_item_notification(item_id):
    """Procesa una notificación push de ML (topic=items, ver `views.webhook`).

    No confía en el payload del webhook (ML no lo firma) — vuelve a pedir el
    recurso por API con nuestro propio access_token y recién ahí decide. Si el
    ítem ya no está activo (pausado, cerrado, eliminado, en revisión), apaga
    `is_available_ml` del producto asociado para que el admin refleje la
    realidad sin que alguien tenga que entrar a Mercado Libre a revisar a
    mano; si volvió a estar activo (lo reactivaron directo en ML), lo prende
    de nuevo. No hace nada si `item_id` no matchea ningún producto nuestro.
    """
    from products.models import Product  # import diferido: products no depende de mercadolibre

    data = _request("GET", f"/items/{item_id}")
    item_status = data.get("status")

    product = Product.objects.filter(ml_item_id=item_id).first()
    if not product:
        return

    should_be_available = item_status == ML_ACTIVE_STATUS
    if product.is_available_ml != should_be_available:
        product.is_available_ml = should_be_available
        product.save(update_fields=["is_available_ml"])
        logger.info(
            "Producto %s (%s): is_available_ml -> %s (status ML=%s, vía webhook)",
            product.pk, product.name, should_be_available, item_status,
        )
