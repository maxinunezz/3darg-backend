from django.contrib import admin
from .models import Brand, BrandLink


class BrandLinkInline(admin.TabularInline):
    model = BrandLink
    extra = 1


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    # Organización de la lista principal
    list_display = (
        "name",
        "slug",
        "brand_type",
        "parent",
        "is_active",
        "show_in_navbar",
        "navbar_order",
    )
    list_filter = ("brand_type", "is_active", "show_in_navbar", "parent")
    search_fields = ("name", "slug", "slogan")
    ordering = ("navbar_order", "name")
    prepopulated_fields = {"slug": ("name",)}
    
    # Organización del formulario de edición por secciones (Fieldsets)
    fieldsets = (
        ("Información Básica", {
            "fields": ("parent", "name", "slug", "brand_type", "is_active")
        }),
        ("Navegación", {
            "fields": ("show_in_navbar", "navbar_order")
        }),
        ("Branding y Contenido", {
            "fields": ("slogan", "short_description", "description", "logo", "cover_image")
        }),
        ("Estilos y Redes (JSON)", {
            "description": "theme: CSS custom properties (colores). social_links: redes sociales.",
            "fields": ("theme", "social_links"),
            "classes": ("collapse",),
        }),
        ("Configuración de Landing Page (JSON)", {
            "description": (
                "page_config controla el contenido y secciones de la página de la marca. "
                "Claves genéricas (landing estándar, la usan la mayoría de las marcas): sections, "
                "features, stats, lifestyle_headline, lifestyle_subheadline, lifestyle_cta, "
                "features_title, newsletter_title, newsletter_subtitle, newsletter_cta.<br><br>"
                "Clave especial <code>lumy</code> (solo la usa la home a medida de Lumy, "
                "slug=\"lumy\" — el resto de las marcas la ignora): objeto anidado con todo el copy "
                "editable de esa home. Sub-claves: <code>nav_links</code> (array {href,label} del menú), "
                "<code>hero</code> ({rail_top, rail_bottom, title_line1, title_line2, title_highlight, "
                "title_line3, script_text, cta_primary_label, cta_secondary_label}), "
                "<code>marquee_words</code> (array de strings), <code>proceso</code> ({eyebrow, "
                "title_prefix, title_highlight, cta_label, steps: array {n,t,d,a}}), "
                "<code>manifiesto</code> ({eyebrow_prefix, text — las stats van en el campo <code>stats</code> "
                "de arriba, compartido con la landing genérica}), <code>tienda</code> ({title_prefix, "
                "title_highlight, empty_text}), <code>inspiracion</code> ({eyebrow, title_prefix, "
                "title_highlight, cta_label, items: array {label,tag,title}}), <code>cta_band</code> "
                "({script, title_lines: array de líneas, subtitle, button_label}). "
                "Todas las sub-claves son opcionales: lo que no se cargue usa el copy por defecto del código."
            ),
            "fields": ("page_config",),
            "classes": ("collapse",),
        }),
        ("Integración Meta Business (JSON)", {
            "description": (
                "Claves: pixel_id (Meta Pixel de esta marca), catalog_id (Commerce Manager), "
                "conversions_api_access_token (token server-side para Conversions API — "
                "NUNCA se expone en la API pública, solo se usa desde el backend), "
                "whatsapp_business_phone_id."
            ),
            "fields": ("meta_config",),
            "classes": ("collapse",),
        }),
    )
    
    inlines = [BrandLinkInline]

    # Mejora visual: permite ver qué marcas son hijas de cuáles en el selector
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "parent" in form.base_fields:
            form.base_fields["parent"].label_from_instance = lambda obj: f"{obj.name} (ID: {obj.id})"
        return form
