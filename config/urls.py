from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path("admin/", admin.site.urls),

    # Auth JWT
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
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
    path("api/cart/", include("cart.urls")),

    # Contacto
    path("api/contact/", include("contact.urls")),

    # Máquina expendedora — landing de validación de mercado
    path("api/vending/", include("vending.urls")),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
