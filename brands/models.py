from django.core.validators import MaxValueValidator
from django.db import models
from django.utils.text import slugify


class Brand(models.Model):
    SERVICES = "services"
    ECOMMERCE = "ecommerce"
    HYBRID = "hybrid"

    BRAND_TYPE_CHOICES = [
        (SERVICES, "Services"),
        (ECOMMERCE, "Ecommerce"),
        (HYBRID, "Hybrid"),
    ]

    # Jerarquía: 3DARG como parent, hijas apuntan a parent
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.PROTECT,
        help_text="Marca madre (ej: 3DARG). Dejar vacío si esta marca es la principal."
    )

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)

    # Código corto y FIJO para armar el SKU de los productos de esta marca
    # (ej: "LUMY", "PYG"). A diferencia del slug, este código NO debería
    # cambiar nunca una vez asignado — los SKU ya generados lo llevan
    # "congelado" y se comparten con Mercado Libre, el feed de Google/Meta
    # y presupuestos3d. Ver Product.generate_sku().
    sku_prefix = models.CharField(
        max_length=10,
        blank=True,
        help_text=(
            "Código corto para el SKU de productos de esta marca (ej: LUMY, "
            "PYG, MSL, CYW). Elegilo con cuidado: una vez que hay productos "
            "usándolo no se debe cambiar (rompería el significado de los SKU "
            "ya publicados en la web/Mercado Libre). Vacío = se usa el slug "
            "en mayúsculas como fallback."
        ),
    )

    brand_type = models.CharField(
        max_length=20,
        choices=BRAND_TYPE_CHOICES,
        default=SERVICES,
    )

    is_active = models.BooleanField(default=True)
    show_in_navbar = models.BooleanField(default=True)
    navbar_order = models.PositiveIntegerField(default=0)

    # Branding
    slogan = models.CharField(max_length=160, blank=True)
    short_description = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    logo = models.ImageField(upload_to="brands/logos/", null=True, blank=True)
    cover_image = models.ImageField(upload_to="brands/covers/", null=True, blank=True)

    # Theme/config (ej: colores light/dark, tipografía, etc.)
    theme = models.JSONField(default=dict, blank=True)

    # Social links: {"instagram": "...", "tiktok": "...", "web": "..."}
    social_links = models.JSONField(default=dict, blank=True)

    # Integración Meta Business (Pixel, Conversions API, Catalog, WhatsApp).
    # Claves esperadas: pixel_id, conversions_api_access_token, catalog_id,
    # whatsapp_business_phone_id. Todas opcionales; vacío = integración apagada
    # para esa marca (mismo patrón que GOOGLE_OAUTH_CLIENT_ID en el backend).
    meta_config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Configuración de Meta Business por marca. Claves disponibles: "
            "pixel_id, conversions_api_access_token, catalog_id, "
            "whatsapp_business_phone_id."
        ),
    )

    # Configuración completa de la landing page (copy, secciones, features, etc.)
    # Ver documentación en BRAND_PAGE_CONFIG_SCHEMA
    page_config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Personalización de la landing. Claves disponibles: "
            "sections (lista de secciones a mostrar), "
            "hero_style (minimal|full|split), "
            "lifestyle_headline, lifestyle_subheadline, lifestyle_cta, "
            "features ([{icon, title, desc}]), "
            "stats ([{value, label}]), "
            "newsletter_title, newsletter_subtitle, newsletter_cta."
        ),
    )

    # Configuración de envío por marca — hoy solo el umbral de envío gratis.
    # Clave esperada: `free_shipping_threshold` (número, en la moneda de la
    # marca — ARS). Vacío/sin la clave = sin envío gratis, el comprador
    # siempre paga el costo de envío cotizado (mismo criterio "vacío =
    # apagado" que `meta_config`/`page_config`). Se resuelve contra el
    # SUBTOTAL del pedido (antes de sumar el envío), ver
    # `payments/views.py::MercadoPagoCheckoutProCreateAPIView`.
    shipping_config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Configuración de envío por marca. Clave disponible: "
            "free_shipping_threshold (monto a partir del cual el envío es "
            "gratis; vacío o 0 = sin envío gratis)."
        ),
    )

    # Descuento informativo por pagar por transferencia — se muestra como
    # cartel en la ficha de producto (precio tachado + "X% OFF por
    # transferencia"), en el mismo lugar donde antes vivía el selector
    # "Llevá 1/2/3". Es puramente de DISPLAY: el cobro real sigue yendo
    # 100% por MercadoPago Checkout Pro al precio de lista, la diferencia
    # se concilia por fuera del sistema. 0 = no se muestra el cartel.
    transfer_discount_percent = models.PositiveSmallIntegerField(
        "Descuento por transferencia (%)",
        default=0,
        validators=[MaxValueValidator(100)],
        help_text=(
            "Descuento informativo que se muestra en la ficha de producto "
            "por pagar por transferencia (cartel con precio tachado). No "
            "afecta el cobro real del checkout, que sigue yendo 100% por "
            "MercadoPago al precio de lista. 0 = no se muestra el cartel."
        ),
    )

    # Descuento por MONTO TOTAL del carrito (no por categoría ni cantidad de
    # artículos — reemplaza al viejo combo de Category.bundle_discounts,
    # ver products/models.py). Lista de tramos, ej:
    # [{"min_amount": 50000, "discount_percent": 5}, {"min_amount": 100000, "discount_percent": 10}].
    # Se resuelve contra el SUBTOTAL del carrito (antes de envío), tomando
    # el tramo de mayor monto que el subtotal alcance. Vacío = sin
    # descuento por monto. Cada carrito es aislado por (usuario, marca)
    # — ver cart.Cart —, así que este descuento nunca cruza entre marcas.
    cart_discount_config = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Tramos de descuento por monto TOTAL del carrito (no por "
            "categoría ni cantidad de artículos). Lista de tramos, ej: "
            '[{"min_amount": 50000, "discount_percent": 5}, '
            '{"min_amount": 100000, "discount_percent": 10}]. '
            "Se aplica sobre el subtotal del carrito (antes del envío), "
            "tomando el tramo de mayor monto alcanzado. Vacío = sin "
            "descuento por monto."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["navbar_order", "name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class BrandLink(models.Model):
    """
    Links extra por marca (por ejemplo: catálogo, linktree, marketplace, etc.)
    """
    brand = models.ForeignKey(Brand, related_name="links", on_delete=models.CASCADE)
    label = models.CharField(max_length=80)  # ej: "Instagram", "Tienda", "Catálogo"
    url = models.URLField(max_length=500)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "label"]

    def __str__(self):
        return f"{self.brand.name} - {self.label}"