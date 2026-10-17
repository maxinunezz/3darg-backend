import json
import os
from datetime import timedelta
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Sentry (monitoreo de errores) ---
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=True,
        enable_logs=True,
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "1.0")),
        profile_session_sample_rate=float(os.getenv("SENTRY_PROFILE_SAMPLE_RATE", "1.0")),
        profile_lifecycle="trace",
        environment="development" if os.getenv("DJANGO_DEBUG", "0") == "1" else "production",
    )

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-secret-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost").split(",") if h.strip()]

# --- Google OAuth (login "Continuar con Google") ---
# Client ID de un proyecto en Google Cloud Console (OAuth consent screen + credencial
# "Web application"). Sin esto, /api/users/google/ responde 400 explicando que falta config.
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")

# --- BamBuddy (cola de impresión automática) ---
BAMBUDDY_URL = os.getenv("BAMBUDDY_URL", "")          # ej: http://localhost:8001
BAMBUDDY_API_KEY = os.getenv("BAMBUDDY_API_KEY", "")  # generado en BamBuddy Settings → API Keys
BAMBUDDY_PRINTER_ID = int(os.getenv("BAMBUDDY_PRINTER_ID", "1"))  # ID de la impresora en BamBuddy

# --- presupuestos3d (aviso de venta online para cargar a mano) ---
# Token de un usuario staff de presupuestos3d (DRF Token, no password) creado
# especialmente para esta integración. Sin esto, _notify_presupuestos3d() es
# un no-op — no rompe el flujo de pago.
PRESUPUESTOS3D_API_URL = os.getenv("PRESUPUESTOS3D_API_URL", "")      # ej: http://localhost:8001
PRESUPUESTOS3D_API_TOKEN = os.getenv("PRESUPUESTOS3D_API_TOKEN", "")

# --- Cotización de envíos: parámetros de cálculo (ver shipping/services/volumetric.py) ---
# Peso mínimo facturable por pedido (kg) — los cortantes son muy livianos, sin este
# piso un pedido chico podría cotizar un flete casi nulo que no cubre el manipuleo real.
SHIPPING_MIN_WEIGHT_KG = float(os.getenv("SHIPPING_MIN_WEIGHT_KG", "0.2"))
# Divisor de peso volumétrico GENERAL (default de `calculate_billable_weight()`
# cuando no se le pasa un `divisor` explícito): kg = (largo × ancho × alto en
# cm) / divisor. 5000 es el estándar más común en Argentina. Hoy el único
# consumidor real (Correo Argentino, sucursal y domicilio) siempre pasa su
# propio divisor (`SHIPPING_CORREO_ARGENTINO_VOLUMETRIC_DIVISOR`, ver abajo),
# así que este default queda sin uso activo — se deja como piso genérico por
# si se suma otro courier con su propia cotización más adelante.
SHIPPING_VOLUMETRIC_DIVISOR = float(os.getenv("SHIPPING_VOLUMETRIC_DIVISOR", "5000"))
# Dimensiones de empaquetado por defecto en cm (largo, ancho, alto) para productos sin
# length_cm/width_cm/height_cm cargados en el admin.
SHIPPING_DEFAULT_ITEM_DIMENSIONS_CM = tuple(
    float(x) for x in os.getenv("SHIPPING_DEFAULT_ITEM_DIMENSIONS_CM", "15,15,5").split(",")
)
# Tarifa plana de emergencia cuando el checkout no recibió código postal (caso
# límite, no debería pasar con el form de dirección obligatorio) — sin esto el
# envío quedaría en $0 por omisión. Ya NO es específica de Andreani: desde que
# Correo Argentino cubre sucursal Y domicilio con tarifa real (ver abajo),
# Andreani salió del selector del carrito (queda en el historial de git si se
# retoma más adelante). Ver shipping/services/quote.py::default_fallback_price().
SHIPPING_FALLBACK_RATES = json.loads(
    os.getenv("SHIPPING_FALLBACK_RATES_JSON", "") or json.dumps({"default": 6500, "zones": {}})
)

# --- Correo Argentino (API MiCorreo real, NO "PaqAr v2") — integración directa,
# sucursal Y domicilio ---
# Confirmado contra la documentación oficial ("Correo Argentino - API
# MiCorreo.pdf") y la cuenta real del dueño en MiCorreo (customerId
# 0002005182): auth por HTTP Basic (`POST /token`) que devuelve un JWT con
# vencimiento (`{"token", "expires"}`), usado después como
# `Authorization: Bearer <token>` — NO es el esquema `Apikey`/`agreement`
# que se asumió en una iteración anterior de esta integración (esa
# documentación, "PaqAr v2", resultó ser de otro producto). A diferencia de
# lo asumido antes, esta API SÍ tiene un endpoint de cotización real
# (`POST /rates`) — se usa como cotización primaria, con la tabla estática
# de abajo como fallback (sin red, o si falla la consulta en vivo). Ver
# shipping/services/correo_argentino.py.
CORREO_ARGENTINO_TEST_MODE = os.getenv("CORREO_ARGENTINO_TEST_MODE", "1") == "1"
CORREO_ARGENTINO_BASE_URL = os.getenv(
    "CORREO_ARGENTINO_BASE_URL",
    "https://apitest.correoargentino.com.ar/micorreo/v1"
    if CORREO_ARGENTINO_TEST_MODE
    else "https://api.correoargentino.com.ar/micorreo/v1",
)
# Credenciales de acceso a la API (HTTP Basic para pedir el token) — distintas
# del login web del panel de MiCorreo, hay que solicitarlas a Correo Argentino
# para cada ambiente (test/productivo). Vacío = integración apagada (alta real,
# sucursales y cotización en vivo quedan apagadas; la cotización sigue
# funcionando vía la tabla estática de abajo).
CORREO_ARGENTINO_USER = os.getenv("CORREO_ARGENTINO_USER", "")
CORREO_ARGENTINO_PASSWORD = os.getenv("CORREO_ARGENTINO_PASSWORD", "")
# Identificador de cliente de MiCorreo (ej. "0002005182", visible en el panel) —
# va en el body/query de /agencies, /rates y /shipping/import.
CORREO_ARGENTINO_CUSTOMER_ID = os.getenv("CORREO_ARGENTINO_CUSTOMER_ID", "")
CORREO_ARGENTINO_PRODUCT_TYPE = os.getenv("CORREO_ARGENTINO_PRODUCT_TYPE", "CP")  # "Correo Argentino Clásico"
CORREO_ARGENTINO_TIMEOUT = float(os.getenv("CORREO_ARGENTINO_TIMEOUT", "8"))

# Datos del remitente — van en cada `/shipping/import` como `sender` (todos
# opcionales según la doc, pero conviene completarlos) y `sender.originAddress`
# (usado también como `postalCodeOrigin` de `/rates`: la cotización en vivo
# siempre es desde esta sucursal/domicilio de origen hacia el CP del comprador).
# Completar cuando el dueño confirme desde dónde despacha realmente.
CORREO_ARGENTINO_SENDER_NAME = os.getenv("CORREO_ARGENTINO_SENDER_NAME", "")
CORREO_ARGENTINO_SENDER_PHONE = os.getenv("CORREO_ARGENTINO_SENDER_PHONE", "")
CORREO_ARGENTINO_SENDER_EMAIL = os.getenv("CORREO_ARGENTINO_SENDER_EMAIL", "")
CORREO_ARGENTINO_SENDER_STREET = os.getenv("CORREO_ARGENTINO_SENDER_STREET", "")
CORREO_ARGENTINO_SENDER_STREET_NUMBER = os.getenv("CORREO_ARGENTINO_SENDER_STREET_NUMBER", "")
CORREO_ARGENTINO_SENDER_CITY = os.getenv("CORREO_ARGENTINO_SENDER_CITY", "")
CORREO_ARGENTINO_SENDER_PROVINCE = os.getenv("CORREO_ARGENTINO_SENDER_PROVINCE", "")
CORREO_ARGENTINO_SENDER_ZIP = os.getenv("CORREO_ARGENTINO_SENDER_ZIP", "")

# Tarifario de respaldo (fallback) — se usa SOLO si no hay credenciales
# cargadas, si falla la consulta en vivo a `POST /rates`, o si no se conoce
# el código postal de destino. Tabla real "Encomienda Correo Clásica",
# columna Nacional — tramos por peso facturable (hasta N kg → precio) +
# cargo por Valor Declarado. Configurable sin tocar código si el tarifario
# cambia.
CORREO_ARGENTINO_TARIFF = json.loads(
    os.getenv("CORREO_ARGENTINO_TARIFF_JSON", "")
    or json.dumps({"1": 26400, "5": 32000, "10": 45200, "15": 56000, "20": 65800, "25": 80900})
)
# Cargo por Valor Declarado (se suma al precio de envío de respaldo, sobre el
# subtotal del carrito): lista de brackets `[tope, cargo]` — `cargo` es un
# monto fijo en $ o un string "N%" para un porcentaje del valor declarado.
# Por defecto: $0,01 a $20.000 → $600 fijo; $20.000,01 a $200.000 → 3%; sin
# tope documentado arriba de $200.000 → se sigue aplicando el último bracket
# (3%) por defecto.
CORREO_ARGENTINO_VALOR_DECLARADO = json.loads(
    os.getenv("CORREO_ARGENTINO_VALOR_DECLARADO_JSON", "")
    or json.dumps({"brackets": [[20000, 600], [200000, "3%"]]})
)
# Divisor de peso volumétrico usado SOLO por la tabla de respaldo de arriba
# (la API real de Correo Argentino no pide peso volumétrico — toma peso real
# en gramos + dimensiones en cm directo, ver /rates en la doc).
SHIPPING_CORREO_ARGENTINO_VOLUMETRIC_DIVISOR = float(
    os.getenv("SHIPPING_CORREO_ARGENTINO_VOLUMETRIC_DIVISOR", "6000")
)

# --- Tarifa plana TEMPORAL por modalidad (decisión explícita del dueño,
# 2026-10-17) — mientras Correo Argentino no entregue las credenciales
# reales de API, se cobra un monto fijo por modalidad en vez de calcular la
# tabla de respaldo (`CORREO_ARGENTINO_TARIFF`/`_valor_declarado_surcharge`),
# que daba montos que no reflejaban bien el costo real. Ver
# `quote.py::get_quotes()`: si el modality tiene entrada acá, se usa este
# precio fijo en el camino de fallback, sin tocar el camino de cotización en
# vivo. Vacío ({}) = sin override, se vuelve al cálculo de `tariff.py` de
# toda la vida. SACAR (o vaciar el JSON) cuando lleguen las credenciales
# reales de Correo Argentino y se confirme que la cotización en vivo da
# precios razonables.
SHIPPING_TEMP_FIXED_RATES = json.loads(
    os.getenv("SHIPPING_TEMP_FIXED_RATES_JSON", "")
    or json.dumps({"sucursal": 5850, "domicilio": 7100})
)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'rest_framework.authtoken',  # Token fijo para integraciones server-to-server (ver products/views.py::CosteoSyncAPIView)
    'django_filters',
    'brands',
    'cms',
    'orders',
    'payments',
    'products',
    'users',
    'cart',
    'contact',
    'vending',
    'wholesale',
    'whatsapp_community',
    'mercadolibre',
    'shipping',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

AUTH_USER_MODEL = 'users.User'

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB"),
        "USER": os.getenv("POSTGRES_USER"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
        "HOST": os.getenv("POSTGRES_HOST", "db"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

# --- Django REST Framework ---
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '10000/day',
        'user': '50000/day',
    },
}

# --- JWT ---
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
}

# --- CORS ---
# En dev el default cubre localhost; en prod se setean por env con la URL real
# del frontend (ej: CORS_ALLOWED_ORIGINS=https://tienda.3darg.com).
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CSRF_TRUSTED_ORIGINS", "https://*.ngrok-free.app"
    ).split(",")
    if o.strip()
]

# --- Seguridad detrás de un reverse proxy (Caddy) en producción ---
# Caddy termina TLS y reenvía por HTTP interno con X-Forwarded-Proto=https.
# Sin esto Django cree que la request es http y rompe cookies/redirects seguros.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.getenv("DJANGO_SECURE_SSL_REDIRECT", "0") == "1"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# --- Email ---
# Proveedor: Resend, vía su API HTTP (`config/email_backends.py`), no SMTP —
# Railway bloquea el tráfico saliente por los puertos SMTP (confirmado con un
# timeout real al conectar), así que el backend de Django manda cada mail con
# un POST a la API de Resend sobre 443 en vez de abrir una conexión SMTP.
# EMAIL_HOST_PASSWORD = API key de Resend. Dominio verificado: 3darg.com.
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "Lumy <noreply@3darg.com>")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "3darg1@gmail.com")
TELEGRAM_URL = os.getenv("TELEGRAM_URL", "https://t.me/3darg")

# --- Mercado Libre (publicación de productos) ---
# Una sola cuenta de vendedor para todo el grupo (3darg), no es por marca.
# Vacío = integración apagada (botón "Publicar en ML" del admin tira error claro),
# mismo patrón que GOOGLE_OAUTH_CLIENT_ID/CLOUDINARY_URL.
ML_CLIENT_ID = os.getenv("ML_CLIENT_ID", "")
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "")
ML_REDIRECT_URI = os.getenv("ML_REDIRECT_URI", "")
ML_SITE_ID = os.getenv("ML_SITE_ID", "MLA")

# --- Media & Static ---
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Cloudinary (storage de imágenes de producto) ---
# Vacío = sigue usando disco local (FileSystemStorage), igual patrón que
# GOOGLE_OAUTH_CLIENT_ID: la integración se "prende" sola al cargar la env var,
# sin tocar código. CLOUDINARY_URL tiene el formato:
#   cloudinary://<api_key>:<api_secret>@<cloud_name>
# La lee automáticamente el SDK de `cloudinary` desde el entorno.
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "")

STORAGES = {
    "default": {
        "BACKEND": (
            "cloudinary_storage.storage.MediaCloudinaryStorage"
            if CLOUDINARY_URL
            else "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
# Nota: `cloudinary_storage`/`cloudinary` NO están en INSTALLED_APPS a propósito.
# Solo usamos la clase `cloudinary_storage.storage.MediaCloudinaryStorage` como
# backend (importada por dotted path en STORAGES, sin necesidad de registrar la
# app) — evita que `cloudinary_storage` pise el `collectstatic` de whitenoise
# (su override para el widget de admin choca con el STORAGES nuevo de Django).

# --- Auth ---
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --- Internacionalización ---
LANGUAGE_CODE = 'es-ar'
TIME_ZONE = 'America/Argentina/Buenos_Aires'
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- Logging ---
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}
