from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

import config.admin_dashboard  # noqa: F401 — aplica el reagrupamiento del sidebar del admin
from config.throttles import LoginEmailThrottle, LoginIPThrottle, install_admin_login_throttle

# Tiene que ir antes de `admin.site.urls` (que toma `admin.site.login` al armarse).
install_admin_login_throttle()

urlpatterns = [
    # Healthcheck de Railway: mientras el deploy nuevo no responda acá, sigue sirviendo el anterior.
    path("salud/", lambda request: JsonResponse({"ok": True}), name="salud"),
    path("admin/", admin.site.urls),

    # Auth JWT — con límite de intentos por IP y por cuenta (ver config/throttles.py)
    path(
        "api/auth/token/",
        TokenObtainPairView.as_view(throttle_classes=[LoginIPThrottle, LoginEmailThrottle]),
        name="token_obtain_pair",
    ),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # Usuarios
    path("api/users/", include("users.urls")),

    # Core API
    path("api/brands/", include("brands.urls")),
    path("api/cms/", include("cms.urls")),
    path("api/payments/", include("payments.urls")),
    path("api/", include("products.urls")),

    # Órdenes y carrito
    path("api/orders/", include("orders.urls")),
    path("api/agentes/", include("orders.urls_agentes")),  # solo lectura, token de agentes
    path("api/cart/", include("cart.urls")),

    # Contacto
    path("api/contact/", include("contact.urls")),

    # Máquina expendedora — landing de validación de mercado
    path("api/vending/", include("vending.urls")),

    # Mayoristas — alta de cuenta mayorista (hoy solo linkeado desde Lumy)
    path("api/wholesale/", include("wholesale.urls")),

    # Comunidad de WhatsApp — popup + botón flotante, configurable por marca
    path("api/whatsapp/", include("whatsapp_community.urls")),

    # Mercado Libre — handshake OAuth (alta/renovación de credenciales)
    path("api/mercadolibre/", include("mercadolibre.urls")),

    # Cotización de envíos en tiempo real (Envíopack)
    path("api/shipping/", include("shipping.urls")),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
