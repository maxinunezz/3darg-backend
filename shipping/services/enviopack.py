"""Cliente de la API de Envíopack (https://developers.enviopack.com.ar)
para cotizar envíos en tiempo real.

- **Auth**: `POST /auth` con `api-key`/`secret-key` (form-urlencoded) →
  `access_token`, válido 4hs. No cacheamos el token entre requests a
  propósito — con 4hs de vida y el volumen bajo de cotizaciones que tiene
  hoy la tienda, no vale la pena la complejidad de cachearlo (Redis/DB).
  Si el volumen crece y esto se vuelve un cuello de botella, cachear por
  ~3.5hs es la optimización obvia (ver `cache.py` si en algún momento se
  suma Redis al proyecto).
- **Cotización**: `GET /cotizar/costo` con `provincia`/`codigo_postal`/
  `peso`/`paquetes`. Devuelve un array con una tarifa por cada combinación
  courier × modalidad (domicilio/sucursal) × servicio.

Ningún método de este módulo levanta excepción hacia quien lo llama:
cualquier falla (red, timeout, credenciales faltantes, respuesta
inesperada) se loguea acá mismo y se señaliza devolviendo `None` — la
vista (`shipping/views.py`) es la que decide caer al fallback de tarifa
plana. El checkout nunca se puede romper porque Envíopack esté caído.
"""
import logging
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

AUTH_PATH = "/auth"
QUOTE_PATH = "/cotizar/costo"


class EnviopackConfigError(Exception):
    """Faltan credenciales — no es un error de red, es config incompleta
    (mismo criterio "vacío = apagado" que BamBuddy/presupuestos3d/Meta)."""


def _get_access_token() -> str:
    if not settings.ENVIOPACK_API_KEY or not settings.ENVIOPACK_SECRET_KEY:
        raise EnviopackConfigError("ENVIOPACK_API_KEY/ENVIOPACK_SECRET_KEY no configurados en .env")

    response = requests.post(
        f"{settings.ENVIOPACK_API_URL}{AUTH_PATH}",
        data={"api-key": settings.ENVIOPACK_API_KEY, "secret-key": settings.ENVIOPACK_SECRET_KEY},
        timeout=settings.ENVIOPACK_TIMEOUT,
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError(f"Envíopack /auth no devolvió access_token: {response.text}")
    return token


def get_quotes(
    *,
    postal_code: str,
    provincia: str,
    weight_kg: Decimal,
    package_dims_cm: list[tuple] | None = None,
) -> list[dict] | None:
    """Devuelve la lista CRUDA de tarifas de Envíopack (sin normalizar, ver
    `shipping/views.py::_normalize_quotes`) o `None` si no se pudo cotizar.

    `package_dims_cm`: lista de `(largo, ancho, alto)` en cm, una tupla por
    bulto — se manda como `paquetes=LxAxH,LxAxH` (formato propio de la API).
    """
    try:
        token = _get_access_token()

        params = {
            "access_token": token,
            "provincia": provincia,
            "codigo_postal": postal_code,
            "peso": f"{float(weight_kg):.2f}",
        }
        if package_dims_cm:
            params["paquetes"] = ",".join(
                f"{int(l)}x{int(w)}x{int(h)}" for l, w, h in package_dims_cm
            )

        response = requests.get(
            f"{settings.ENVIOPACK_API_URL}{QUOTE_PATH}",
            params=params,
            timeout=settings.ENVIOPACK_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    except EnviopackConfigError as e:
        logger.info("Envíopack no configurado, se usa la tarifa de respaldo: %s", e)
        return None
    except requests.Timeout as e:
        logger.error(
            "Envíopack: timeout al cotizar — codigo_postal=%s provincia=%s: %s",
            postal_code, provincia, e,
        )
        return None
    except requests.RequestException as e:
        body = getattr(e.response, "text", "")
        logger.error(
            "Envíopack: error al cotizar — codigo_postal=%s provincia=%s: %s %s",
            postal_code, provincia, e, body,
        )
        return None
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Envíopack: respuesta inesperada al cotizar — %s", e)
        return None
