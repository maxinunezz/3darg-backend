"""Límites de intentos (throttles) compartidos por login, registro y admin.

Ojo con un gotcha de DRF que ya causó un bug real en producción: una subclase
de `AnonRateThrottle` que solo cambia `rate` (sin `scope` propio) guarda su
contador en la MISMA clave de caché que el throttle global "anon"
(`DEFAULT_THROTTLE_CLASSES` en settings). Como ese contador suma cada request
anónima a la API mientras el visitante navega, un formulario con límite
"5/hour" quedaba bloqueado (429) apenas la persona había mirado un par de
páginas. Por eso cada throttle de este proyecto tiene que declarar su propio
`scope`.

Límite conocido: no hay `CACHES` configurado, así que Django usa LocMemCache,
que es por proceso. Con varios workers de gunicorn (`GUNICORN_WORKERS`,
default 3) cada uno lleva su propia cuenta, y el límite real queda
multiplicado por esa cantidad. Igual frena un ataque de fuerza bruta (lo baja
de miles de intentos por minuto a unas decenas por hora); para un límite
exacto haría falta una caché compartida (Redis).

Otro límite conocido: los throttles "por IP" de DRF identifican al cliente con
el header X-Forwarded-For completo (no hay `NUM_PROXIES` configurado), y ese
header lo puede manipular quien hace la request. Por eso la defensa real
contra probar contraseñas es `LoginEmailThrottle` (por cuenta, no por IP),
que no depende de la IP. Configurar `NUM_PROXIES` queda pendiente de
confirmar en producción cuántos proxies pone Railway delante (si se configura
mal, todos los visitantes compartirían una misma "IP" y el límite los
bloquearía a todos juntos).
"""

from django.contrib import admin
from django.core.cache import cache
from django.http import HttpResponse
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


class LoginIPThrottle(AnonRateThrottle):
    """Intentos de login (`/api/auth/token/`) por IP."""

    scope = "login_ip"
    rate = "30/hour"


class LoginEmailThrottle(SimpleRateThrottle):
    """Intentos de login contra una MISMA cuenta, sin importar desde qué IP.

    Es la defensa principal contra probar contraseñas sobre una cuenta
    puntual (por ejemplo la del dueño, que es staff/superuser).
    """

    scope = "login_email"
    rate = "10/hour"

    def get_cache_key(self, request, view):
        email = str(request.data.get("email") or "").strip().lower()
        if not email:
            return None  # sin email no hay cuenta que proteger; el IP throttle sigue
        return self.cache_format % {"scope": self.scope, "ident": email}


class RegisterThrottle(AnonRateThrottle):
    """Altas de cuenta por IP — evita la creación masiva de cuentas falsas."""

    scope = "register"
    rate = "10/hour"


class GoogleAuthThrottle(AnonRateThrottle):
    """Login/registro con Google por IP."""

    scope = "google_auth"
    rate = "30/hour"


# --- Admin de Django ---------------------------------------------------------
# El login del admin no pasa por DRF, así que no lo cubren los throttles de
# arriba. Se envuelve `admin.site.login`: se cuentan solo los intentos
# FALLIDOS, por IP y por cuenta (el usuario tipeado) por separado, y si
# cualquiera de los dos llega al máximo se responde 429 durante la ventana.
# El contador por cuenta es el que no se puede esquivar cambiando de IP (o
# falsificando el header X-Forwarded-For). Un login exitoso resetea ambos.

ADMIN_LOGIN_MAX_FAILURES = 10
ADMIN_LOGIN_WINDOW_SECONDS = 15 * 60

_original_admin_login = admin.site.login


def _client_ip(request):
    # El cliente puede mandar su propio X-Forwarded-For con cualquier valor; el
    # proxy de Railway agrega la IP real AL FINAL. Por eso se toma la última
    # entrada (la que puso el proxy), nunca la primera.
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "")


def throttled_admin_login(request, extra_context=None):
    if request.method != "POST":
        return _original_admin_login(request, extra_context)

    username = str(request.POST.get("username") or "").strip().lower()
    keys = [f"admin_login_failures:ip:{_client_ip(request)}"]
    if username:
        keys.append(f"admin_login_failures:user:{username}")

    counts = {key: cache.get(key, 0) for key in keys}
    if max(counts.values()) >= ADMIN_LOGIN_MAX_FAILURES:
        return HttpResponse(
            "Demasiados intentos fallidos. Probá de nuevo en 15 minutos.",
            status=429,
            content_type="text/plain; charset=utf-8",
        )

    response = _original_admin_login(request, extra_context)
    if request.user.is_authenticated:
        cache.delete_many(keys)
    else:
        for key, count in counts.items():
            cache.set(key, count + 1, ADMIN_LOGIN_WINDOW_SECONDS)
    return response


def install_admin_login_throttle():
    """Se llama desde `config/urls.py` antes de armar `admin.site.urls`."""
    admin.site.login = throttled_admin_login
