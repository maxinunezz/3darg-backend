from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models


class User(AbstractUser):
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=30, blank=True)
    registered_brand = models.ForeignKey(
        "brands.Brand",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="registered_users",
    )

    # Dirección de envío preferida, cargada una vez desde "Mis datos" del
    # frontend (`account-settings-content.tsx`) para autocompletar el
    # selector de envío del carrito (`ShippingEstimator`) sin que el
    # comprador tenga que volver a tipearla en cada compra. Mismo shape que
    # `ShippingAddress` del frontend (`types/shipping.ts`) menos `fullName`/
    # `phone`, que ya viven en este mismo modelo (`first_name`/`last_name`/
    # `phone`) — no duplicarlos acá. Todos opcionales: una cuenta nueva no
    # tiene ninguno cargado y el checkout sigue funcionando igual que
    # siempre (invitado o logueado sin preferencia guardada).
    class ShippingModality(models.TextChoices):
        SUCURSAL = "sucursal", "Retirar en sucursal Correo Argentino"
        DOMICILIO = "domicilio", "Envío a domicilio"
        LOCAL = "local", "Retirar en el local"

    shipping_modality = models.CharField(
        max_length=20, choices=ShippingModality.choices, blank=True
    )
    # Compartido por las dos modalidades (sucursal la usa para listar
    # agencias, domicilio como parte de la dirección real) — mismo criterio
    # que `ShippingAddress.province` en el frontend, un solo campo.
    shipping_province = models.CharField(max_length=50, blank=True)
    # Solo para "sucursal" — código real de Correo Argentino (API MiCorreo).
    shipping_agency_id = models.CharField(max_length=50, blank=True)
    # Solo para "domicilio".
    shipping_street = models.CharField(max_length=255, blank=True)
    shipping_street_number = models.CharField(max_length=20, blank=True)
    shipping_floor = models.CharField(max_length=20, blank=True)
    shipping_department = models.CharField(max_length=20, blank=True)
    shipping_city = models.CharField(max_length=100, blank=True)
    shipping_postal_code = models.CharField(max_length=20, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return self.email


class Favorite(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorites",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.CASCADE,
        related_name="favorited_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "product")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} → {self.product.name}"
