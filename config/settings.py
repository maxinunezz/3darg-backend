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

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
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
# Proveedor elegido: Resend (SMTP relay). Apagado hasta tener dominio verificado:
# EMAIL_BACKEND sigue en "console" (no manda mails reales) hasta que se cree la
# cuenta Resend, se verifique el dominio de Lumy y se cargue EMAIL_HOST_PASSWORD
# con la API key real. Ver 3darg-backend/CLAUDE.md para el detalle de activación.
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.resend.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "resend")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "Lumy <noreply@lumy.com>")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "3darg1@gmail.com")
TELEGRAM_URL = os.getenv("TELEGRAM_URL", "https://t.me/3darg")

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
