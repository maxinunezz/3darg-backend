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
        ("Configuración Avanzada (JSON)", {
            "description": "Configuración de estilos (theme) y enlaces a redes sociales.",
            "fields": ("theme", "social_links"),
            "classes": ("collapse",), # Esta sección aparece contraída por defecto
        }),
    )
    
    inlines = [BrandLinkInline]

    # Mejora visual: permite ver qué marcas son hijas de cuáles en el selector
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "parent" in form.base_fields:
            form.base_fields["parent"].label_from_instance = lambda obj: f"{obj.name} (ID: {obj.id})"
        return form