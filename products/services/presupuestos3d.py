"""Cliente de la API de costeo de presupuestos3d (sistema interno de
gestión, repo aparte, ver ../../../CLAUDE.md) para traer el costo de
fabricación de un producto a partir de su SKU.

Reusa las mismas credenciales (`PRESUPUESTOS3D_API_URL`/`_API_TOKEN`) que ya
existen para el aviso de venta (`orders/signals.py::_notify_presupuestos3d`),
pero en sentido inverso: ahí avisamos ventas pagadas, acá preguntamos costos
para mostrarlos en la ficha de Precio/Stock/Canales del admin.

Mismo criterio que el resto de las integraciones opcionales del proyecto
(BamBuddy, Meta, Envíopack): vacío en `.env` = apagado, nunca rompe la
pantalla del admin. Si el SKU no matchea ningún producto del lado de
presupuestos3d, `resultados` viene vacío — se traduce a `None` ("costo no
disponible"), no es un error.

No cacheamos la respuesta a propósito (mismo criterio que
`shipping/services/enviopack.py` con el access token de Envíopack): el
volumen de aperturas de ficha de producto en el admin es bajo y no justifica
la complejidad de cachear. Si en algún momento se vuelve un cuello de
botella, es la optimización obvia a agregar.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

COST_PATH = "/api/productos/costo/"
TIMEOUT = 8


class Presupuestos3DConfigError(Exception):
    """Faltan credenciales — no es un error de red, es config incompleta
    (mismo criterio "vacío = apagado" que BamBuddy/Meta/Envíopack)."""


def get_cost(sku: str) -> dict | None:
    """Costo de fabricación para `sku` tal cual lo devuelve presupuestos3d
    (dict crudo, sin normalizar — no tenemos motivo para asumir nombres de
    campo que no estén documentados), o `None` si no está disponible:
    integración apagada, SKU sin match, o cualquier error de red/API.

    Nunca levanta excepción — cualquier falla se loguea acá mismo.
    """
    if not sku:
        return None

    api_url = getattr(settings, "PRESUPUESTOS3D_API_URL", "").rstrip("/")
    api_token = getattr(settings, "PRESUPUESTOS3D_API_TOKEN", "")

    if not api_url or not api_token:
        logger.debug("presupuestos3d no configurado — no se puede traer costo de sku=%s", sku)
        return None

    try:
        response = requests.get(
            f"{api_url}{COST_PATH}",
            params={"sku": sku},
            headers={"Authorization": f"Token {api_token}"},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        resultados = response.json().get("resultados") or []
    except requests.Timeout as e:
        logger.error("presupuestos3d: timeout al pedir costo de sku=%s: %s", sku, e)
        return None
    except requests.RequestException as e:
        body = getattr(e.response, "text", "")
        logger.error("presupuestos3d: error al pedir costo de sku=%s: %s %s", sku, e, body)
        return None
    except (ValueError, KeyError, TypeError) as e:
        logger.error("presupuestos3d: respuesta inesperada al pedir costo de sku=%s: %s", sku, e)
        return None

    for item in resultados:
        if item.get("sku") == sku:
            return item
    return None
