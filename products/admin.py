from django.contrib import admin
from .models import Product, Category, ProductImage
from mercadolibre.services import sync_product, MLSyncError


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ["image", "channel", "order", "ml_order", "alt"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "slug", "brand", "parent"]
    list_filter = ["brand", "parent"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ["parent"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        "name", "brand", "sku", "price", "member_discount_percent", "members_only",
        "stock", "is_available", "is_featured",
    ]
    list_filter = ["brand", "category", "members_only", "is_featured", "is_available"]
    list_editable = ["member_discount_percent", "members_only"]
    search_fields = ["name", "description", "sku"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["sku", "ml_item_id"]
    inlines = [ProductImageInline]
    actions = ["publicar_en_mercadolibre"]
    fieldsets = (
        (None, {"fields": ("name", "slug", "sku", "description", "category", "brand")}),
        ("Precio y stock", {"fields": ("price", "stock", "is_available", "is_featured")}),
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
