from django.contrib import admin
from .models import Product, Category, ProductImage
from mercadolibre.services import sync_product, MLSyncError


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ["image", "channel", "order", "ml_order", "alt"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "slug", "brand", "parent", "sku_prefix"]
    list_filter = ["brand", "parent"]
    search_fields = ["name", "slug", "sku_prefix"]
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ["parent"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        "name", "brand", "sku", "price", "member_discount_percent", "members_only",
        "stock", "is_available", "is_available_web", "is_available_ml", "is_featured",
    ]
    list_filter = [
        "brand", "category", "members_only", "is_featured",
        "is_available", "is_available_web", "is_available_ml",
    ]
    list_editable = [
        "member_discount_percent", "members_only", "is_available", "is_available_web",
        "is_available_ml", "is_featured",
    ]
    search_fields = ["name", "description", "sku", "color", "size"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["ml_item_id"]
    inlines = [ProductImageInline]
    actions = ["publicar_en_mercadolibre", "regenerar_sku"]
    fieldsets = (
        (None, {
            "fields": ("name", "slug", "sku", "description", "category", "brand"),
            "description": (
                "El SKU se precarga solo al crear el producto (Product.generate_sku()), "
                "pero el campo queda editable por si hace falta corregirlo a mano "
                "(ej: typo, migración de un código viejo, etc.) — ver el help text "
                "del campo para el formato esperado. Guardalo dejándolo vacío para que "
                "se regenere automáticamente al crear el producto."
            ),
        }),
        ("Color y tamaño", {
            "fields": ("color", "size"),
            "description": (
                "Solo informativo (no son variantes con stock propio). Si los "
                "cargás, usá la acción \"Regenerar SKU\" de la lista para que "
                "queden reflejados en el SKU — no se recalcula solo al guardar."
            ),
        }),
        ("Precio y stock", {"fields": ("price", "stock", "is_available", "is_featured")}),
        ("Canales de venta", {
            "fields": ("is_available_web", "is_available_ml"),
            "description": (
                "Prender/apagar este producto en cada canal por separado, sin "
                "afectar a los demás (ej: pausarlo en Mercado Libre pero "
                "dejarlo visible en la web, o al revés). 'is_available' (arriba) "
                "sigue siendo el apagado general: si está apagado, no se vende "
                "en ningún lado sin importar estos dos. Mercado Libre: después "
                "de cambiar is_available_ml corré la acción \"Publicar/Actualizar "
                "en Mercado Libre\" para que el pausado/reactivado se refleje "
                "ahí — no es automático. También se apaga solo cuando Mercado "
                "Libre nos avisa (webhook) que el ítem ya no está activo."
            ),
        }),
        ("Descuento por volumen", {
            "fields": ("bundle_discounts",),
            "description": (
                'Tramos de descuento por cantidad (mismo producto), ej: '
                '[{"quantity": 2, "discount_percent": 10}, {"quantity": 3, "discount_percent": 15}]. '
                "Vacío = no se muestra el selector de cantidad con descuento en el detalle del producto."
            ),
        }),
        ("Socios", {
            "fields": ("members_only", "member_discount_percent"),
            "description": (
                "members_only: el producto solo lo ven y compran usuarios con cuenta. "
                "member_discount_percent: descuento (%) que reciben los socios."
            ),
        }),
        ("Meta / Google Catalog", {
            "fields": ("google_product_category",),
            "description": (
                "Categoría de la taxonomía de Google/Meta para el feed de Meta Catalog "
                "(ej: 'Sporting Goods > Exercise & Fitness Equipment')."
            ),
        }),
        ("Mercado Libre", {
            "fields": ("ml_item_id", "ml_category_id", "weight_kg", "length_cm", "width_cm", "height_cm"),
            "description": (
                "ml_category_id y las dimensiones/peso son necesarios para publicar. "
                "ml_item_id se completa solo al publicar por primera vez."
            ),
        }),
    )

    @admin.action(description="Regenerar SKU")
    def regenerar_sku(self, request, queryset):
        """Recalcula el SKU con Product.generate_sku() usando el estado
        actual del producto (marca, categoría, color, tamaño).

        El SKU no se recalcula solo en cada guardado a propósito (ver
        help_text del campo) — esta acción es la forma explícita de
        actualizarlo, por ejemplo después de cargar color/tamaño por primera
        vez. Ojo: si el producto ya está publicado en Mercado Libre o en el
        feed, cambiar el SKU ahí puede romper el matching/historial.
        """
        actualizados = 0
        for product in queryset:
            nuevo_sku = product.generate_sku()
            if nuevo_sku != product.sku:
                product.sku = nuevo_sku
                product.save(update_fields=["sku"])
                actualizados += 1
        if actualizados:
            self.message_user(request, f"{actualizados} SKU regenerado(s).")
        else:
            self.message_user(request, "Ningún SKU cambió (ya estaban al día).")

    @admin.action(description="Publicar/Actualizar en Mercado Libre")
    def publicar_en_mercadolibre(self, request, queryset):
        ok, fail = 0, 0
        for product in queryset:
            try:
                sync_product(product)
                ok += 1
            except MLSyncError as exc:
                fail += 1
                self.message_user(request, f"{product.name}: {exc}", level="error")
            except Exception as exc:  # error inesperado (red, etc.) — no debe frenar el resto del lote
                fail += 1
                self.message_user(request, f"{product.name}: error inesperado ({exc})", level="error")
        if ok:
            self.message_user(request, f"{ok} producto(s) publicado(s)/actualizado(s) en Mercado Libre.")
        if fail:
            self.message_user(request, f"{fail} producto(s) con error, revisá los mensajes de arriba.", level="warning")
