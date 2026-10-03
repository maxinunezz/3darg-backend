from django.contrib import admin
from .models import Product, Category, ProductImage


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


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
    readonly_fields = ["sku"]
    inlines = [ProductImageInline]
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
    )
