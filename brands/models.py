from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils.text import slugify


# Claves válidas de `meta_config` (ver help_text del campo abajo). Un typo
# acá (ej. "pixle_id") dejaba la marca sin Pixel/Conversions API sin ningún
# aviso — `meta_conversions.py` simplemente no encuentra la clave esperada y
# hace un no-op silencioso (mismo criterio "vacío = apagado" de siempre,
# pero sin que nadie se entere de que en realidad fue un error de tipeo).
META_CONFIG_KEYS = {
    "pixel_id",
    "conversions_api_access_token",
    "catalog_id",
    "whatsapp_business_phone_id",
}

# Claves válidas de nivel superior de `page_config` — espejo exacto de
# `BrandPageConfig` en `ecommerce-frontend/types/brands.ts` (la fuente de
# verdad real; el help_text del campo/`BrandAdmin` describe solo el
# subconjunto "genérico" y quedó desactualizado frente a lo que el frontend
# ya consume de verdad — confirmado contra `Brand.objects.all()` en dev,
# donde Lumy/Print&Gym/MiniSlam/CyberWeed ya usan varias de estas claves).
# Si el frontend agrega una clave nueva a `BrandPageConfig`, hay que sumarla
# acá también — si no, esta validación empieza a rechazar page_config válido.
# `lumy`/`whatsapp_channel` son objetos anidados especiales (con sub-claves
# opcionales en varios niveles) — acá solo se valida que sean dict, no su
# estructura interna completa.
PAGE_CONFIG_KEYS = {
    "lumy",
    "sections",
    "panels",
    "hero_style",
    "stats",
    "features",
    "features_title",
    "lifestyle_headline",
    "lifestyle_subheadline",
    "lifestyle_cta",
    "newsletter_title",
    "newsletter_subtitle",
    "newsletter_cta",
    "about_cases",
    "community_headline",
    "community_subheadline",
    "community_description",
    "community_benefits",
    "community_bg_variant",
    "community_bg_image",
    "community_cta_register",
    "community_cta_login",
    "whatsapp_channel",
}

HERO_STYLE_CHOICES = {"minimal", "full", "split"}


def _list_of_dicts_error(value, field_label, expected_subkeys):
    """Valida que `value` (ej. `page_config["features"]`) sea una lista de
    objetos con al menos una de las claves esperadas. Devuelve un mensaje de
    error en español, o `None` si está todo bien (incluye `value is None`,
    o sea que la clave ni se cargó — sigue siendo válido, todo es opcional).
    """
    if value is None:
        return None
    if not isinstance(value, list):
        return f"{field_label} debe ser una lista."
    for item in value:
        if not isinstance(item, dict):
            return f"{field_label} debe ser una lista de objetos."
        if not expected_subkeys & set(item):
            return (
                f"Un elemento de {field_label} no tiene ninguna de las claves "
                f"esperadas ({', '.join(sorted(expected_subkeys))})."
            )
    return None


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

    # Configuración de envío por marca — umbral de envío gratis, separado por
    # MODALIDAD (sucursal vs domicilio, cada una con su propio costo real de
    # Correo Argentino — no tiene sentido un único umbral para las dos).
    # Claves esperadas: `free_shipping_threshold_sucursal` /
    # `free_shipping_threshold_domicilio` (número, en la moneda de la marca —
    # ARS). Vacío/sin la clave = sin envío gratis para esa modalidad, el
    # comprador siempre paga el costo de envío cotizado (mismo criterio
    # "vacío = apagado" que `meta_config`/`page_config`). Se resuelve contra
    # el SUBTOTAL del pedido (antes de sumar el envío), ver
    # `payments/views.py::MercadoPagoCheckoutProCreateAPIView`.
    # (Forma vieja, ya migrada: `free_shipping_threshold` único — ver
    # `brands/migrations/0009_free_shipping_threshold_por_modalidad.py`.)
    shipping_config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Configuración de envío por marca. Claves disponibles: "
            "free_shipping_threshold_sucursal / free_shipping_threshold_domicilio "
            "(monto a partir del cual el envío de esa modalidad es gratis; "
            "vacío o 0 = sin envío gratis para esa modalidad)."
        ),
    )

    # Descuento por pagar por transferencia — se muestra como cartel en la
    # ficha de producto (precio tachado + "X% OFF por transferencia"), en el
    # mismo lugar donde antes vivía el selector "Llevá 1/2/3". DESDE que
    # existe el canal de pago "Transferencia bancaria" (`Order.PaymentChannel
    # .TRANSFER`, ver `payments/services/transfer_discount.py`) este % SÍ
    # afecta el cobro real cuando el comprador elige ese canal en el carrito
    # — se aplica sobre el subtotal (después del descuento por cantidad,
    # antes de sumar el envío) y se snapshotea en
    # `Order.transfer_discount_percent_applied` al crear el pedido. El canal
    # MercadoPago nunca lo aplica (siempre cobra precio de lista/socio). 0 =
    # no se muestra el cartel y el checkout por transferencia no tiene
    # descuento (pero sigue disponible si hay cuenta bancaria configurada,
    # ver `settings.TRANSFER_BANK_ALIAS`).
    transfer_discount_percent = models.PositiveSmallIntegerField(
        "Descuento por transferencia (%)",
        default=0,
        validators=[MaxValueValidator(100)],
        help_text=(
            "Descuento que se muestra en la ficha de producto (cartel con "
            "precio tachado) y que se cobra realmente cuando el comprador "
            "elige pagar por transferencia bancaria en el carrito. El canal "
            "MercadoPago nunca lo aplica. 0 = no se muestra el cartel ni se "
            "descuenta nada en transferencia."
        ),
    )

    # Descuento por CANTIDAD TOTAL de unidades del carrito (sumando todas
    # las líneas, sin importar el producto — no por categoría ni por monto
    # en $; reemplaza al mecanismo anterior por monto total y al viejo
    # combo de Category.bundle_discounts, ver products/models.py). Lista
    # de tramos, ej:
    # [{"min_quantity": 5, "discount_percent": 5}, {"min_quantity": 10, "discount_percent": 10}].
    # Se resuelve contra la CANTIDAD de unidades del carrito (no el
    # subtotal), tomando el tramo de mayor cantidad que el carrito alcance
    # — el % sigue aplicándose sobre el monto (es un descuento en $, solo
    # que lo dispara la cantidad de unidades, no cuánto suman en pesos).
    # Vacío = sin descuento. Cada carrito es aislado por (usuario, marca)
    # — ver cart.Cart —, así que este descuento nunca cruza entre marcas.
    cart_discount_config = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Tramos de descuento por CANTIDAD TOTAL de unidades del "
            "carrito (sumando todos los productos, no por categoría ni "
            "por monto en $). Lista de tramos, ej: "
            '[{"min_quantity": 5, "discount_percent": 5}, '
            '{"min_quantity": 10, "discount_percent": 10}]. '
            "Se aplica sobre el total del carrito (el % sigue siendo un "
            "descuento en $, pero lo dispara la cantidad de unidades, no "
            "el monto), tomando el tramo de mayor cantidad alcanzada. "
            "Vacío = sin descuento."
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

    def clean(self):
        """Valida el esquema de `theme`/`meta_config`/`page_config`
        (JSONField de forma libre) para atrapar errores de tipeo ANTES de
        guardar — sin esto, una clave mal escrita (ej. "pixle_id",
        "lifestyle_headlin") no rompe nada del lado del backend, pero el
        frontend simplemente no encuentra el dato esperado y se cae en
        silencio a su default (o, en el peor caso, no renderiza la sección).
        No valida la estructura interna completa de `page_config.lumy`/
        `page_config.whatsapp_channel` (objetos anidados, con sub-claves
        opcionales en varios niveles, ver `BrandPageConfig` en
        `ecommerce-frontend/types/brands.ts`) — alcanza con confirmar que
        sean dict, el resto se audita a mano si hace falta. Se corre vía
        `ModelForm.full_clean()`, mismo mecanismo que `Product.clean()`.
        """
        super().clean()
        errors = {}

        if not isinstance(self.theme, dict):
            errors["theme"] = "theme debe ser un objeto JSON (clave: valor)."
        else:
            bad = sorted(k for k, v in self.theme.items() if not isinstance(v, str))
            if bad:
                errors["theme"] = (
                    f"Los valores de theme deben ser texto (CSS custom "
                    f"properties) — revisá: {', '.join(bad)}."
                )

        if not isinstance(self.meta_config, dict):
            errors["meta_config"] = "meta_config debe ser un objeto JSON (clave: valor)."
        else:
            unknown = sorted(set(self.meta_config) - META_CONFIG_KEYS)
            if unknown:
                errors["meta_config"] = (
                    f"Clave(s) desconocida(s) en meta_config: {', '.join(unknown)}. "
                    f"Válidas: {', '.join(sorted(META_CONFIG_KEYS))}."
                )
            else:
                bad = sorted(
                    k for k, v in self.meta_config.items()
                    if v is not None and not isinstance(v, str)
                )
                if bad:
                    errors["meta_config"] = (
                        f"Los valores de meta_config deben ser texto — revisá: {', '.join(bad)}."
                    )

        if not isinstance(self.page_config, dict):
            errors["page_config"] = "page_config debe ser un objeto JSON (clave: valor)."
        else:
            unknown = sorted(set(self.page_config) - PAGE_CONFIG_KEYS)
            if unknown:
                errors["page_config"] = (
                    f"Clave(s) desconocida(s) en page_config: {', '.join(unknown)}. "
                    f"Válidas: {', '.join(sorted(PAGE_CONFIG_KEYS))}."
                )
            else:
                hero_style = self.page_config.get("hero_style")
                nested_dict_keys = sorted(
                    k for k in ("lumy", "whatsapp_channel")
                    if self.page_config.get(k) is not None
                    and not isinstance(self.page_config.get(k), dict)
                )
                if hero_style is not None and hero_style not in HERO_STYLE_CHOICES:
                    errors["page_config"] = (
                        f"hero_style inválido ({hero_style!r}) — válidos: "
                        f"{', '.join(sorted(HERO_STYLE_CHOICES))}."
                    )
                elif nested_dict_keys:
                    errors["page_config"] = (
                        f"Debe ser un objeto JSON: {', '.join(f'page_config.{k}' for k in nested_dict_keys)}."
                    )
                else:
                    msg = _list_of_dicts_error(
                        self.page_config.get("features"), "page_config.features",
                        {"icon", "title", "desc"},
                    ) or _list_of_dicts_error(
                        self.page_config.get("stats"), "page_config.stats",
                        {"value", "label"},
                    )
                    if msg:
                        errors["page_config"] = msg

        if errors:
            raise ValidationError(errors)

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