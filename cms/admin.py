from django import forms
from django.contrib import admin
from django.db import models
from django.utils.html import format_html, format_html_join
from .models import Page, Section, SectionImage


# Qué "key" de SectionImage espera cada Section, por (page_slug, section.type).
# Sirve solo para mostrar el texto de ayuda en el admin — no se valida en runtime,
# el frontend simplemente busca la key exacta al pedir una imagen (ver lib/cms.ts
# del frontend, getSectionImage(section, key)).
#
# Si una Section no aparece acá (o tiene lista vacía), significa que ese bloque
# es 100% texto y no maneja imágenes.
IMAGE_KEYS_HELP = {
    ("home", "detalle"): [
        ("detalle_0", "Primera foto macro (detalle 1: la capa que no se ve)"),
        ("detalle_1", "Segunda foto macro (detalle 2: el borde lijado a mano)"),
        ("detalle_2", "Tercera foto macro (detalle 3: el encastre que entra justo)"),
    ],
    ("home", "enseñanza"): [
        ("taller", "Foto del taller para la sección \"Enseñar lo que sabemos\""),
    ],
    ("nosotros", "intro"): [
        ("taller", "Foto del taller, al lado del texto de introducción"),
    ],
    ("nosotros", "equipo"): [
        ("equipo_0", "Foto del primer equipo (Equipo de diseño)"),
        ("equipo_1", "Foto del segundo equipo (Equipo de producción)"),
        ("equipo_2", "Foto del tercer equipo (Equipo de atención)"),
    ],
    ("casos-de-exito", "casos"): [
        ("caso_0", "Foto del primer caso (Gastronomía)"),
        ("caso_1", "Foto del segundo caso (Deporte)"),
        ("caso_2", "Foto del tercer caso (Industria)"),
    ],
    ("capacidades", "cta"): [
        ("taller", "Foto del taller para el cierre/CTA de Capacidades"),
    ],
    ("contacto", "canales"): [
        ("taller", "Foto de la entrada del taller"),
    ],
    ("footer", "footer"): [
        ("logo", "Logo alternativo para el footer (opcional; si no se sube, se usa el logo blanco por defecto)"),
    ],
}


class SectionInline(admin.TabularInline):
    """Alta rápida de secciones nuevas desde la Page.

    Para subir imágenes hay que entrar a la Section individual: Django admin
    no soporta inlines anidados a 2 niveles (Page -> Section -> SectionImage).
    """
    model = Section
    extra = 1


class SectionImageInline(admin.TabularInline):
    model = SectionImage
    extra = 1
    fields = ("key", "image", "alt_text", "order")


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("brand", "slug", "title", "is_published")
    list_filter = ("brand", "is_published")
    search_fields = ("slug", "title")
    inlines = [SectionInline]


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("page", "type", "order", "is_active")
    list_filter = ("type", "is_active", "page__brand")
    ordering = ("page", "order")
    inlines = [SectionImageInline]
    formfield_overrides = {
        # Textarea más grande para editar cómodamente el JSON de "data".
        models.JSONField: {"widget": forms.Textarea(attrs={"rows": 12, "cols": 100})},
    }
    readonly_fields = ("image_upload_help",)
    fields = ("page", "type", "order", "is_active", "data", "image_upload_help")

    def image_upload_help(self, obj):
        """Texto informativo (solo lectura) con instrucciones de cómo subir
        cada foto de esta Section y qué "key" usar, para que el dueño del
        sitio no tenga que adivinar. Se calcula según (page.slug, type)."""
        if not obj or not obj.pk:
            return "Guardá la Section primero para ver las instrucciones de imágenes."

        keys = IMAGE_KEYS_HELP.get((obj.page.slug, obj.type), [])

        if not keys:
            return format_html(
                "<div style='max-width:640px;line-height:1.5'>"
                "Esta sección es solo de texto: no tiene fotos para subir. "
                "Todo lo que se edita acá se hace desde el campo <b>data</b> de arriba."
                "</div>"
            )

        items_html = format_html_join(
            "", "<li style='margin-bottom:4px'><code>{}</code> — {}</li>", keys
        )
        return format_html(
            "<div style='max-width:640px;line-height:1.5'>"
            "<p><b>Cómo subir una foto acá:</b> bajá hasta el bloque "
            "\"Section images\" (más abajo en esta misma página), hacé clic en "
            "<b>\"Add another Section image\"</b>, elegí el archivo en el campo "
            "<b>Image</b> y escribí <u>exactamente</u> una de estas keys en el "
            "campo <b>Key</b> (sin espacios, tal cual está escrita):</p>"
            "<ul style='margin:0 0 8px 18px'>{}</ul>"
            "<p style='color:#666'>Si escribís una key distinta a estas, la foto "
            "se sube igual pero el sitio no la va a usar en ningún lugar.</p>"
            "</div>",
            items_html,
        )

    image_upload_help.short_description = "Ayuda: cómo subir imágenes en esta sección"
