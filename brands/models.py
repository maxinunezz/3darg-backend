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