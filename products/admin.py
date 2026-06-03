from django.contrib import admin
from .models import Product, Category, ProductImage


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "slug", "brand"]
    list_filter = ["brand"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        "name", "brand", "price", "member_discount_percent", "members_only",
        "stock", "is_available", "is_featured",
    ]
    list_filter = ["brand", "category", "members_only", "is_featured", "is_available"]
    list_editable = ["member_discount_percent", "members_only"]
    search_fields = ["name", "description"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProductImageInline]
    fieldsets = (
        (None, {"fields": ("name", "slug", "description", "category", "brand")}),
        ("Precio y stock", {"fields": ("price", "stock", "is_available", "is_featured")}),
        ("Socios", {
            "fields": ("members_only", "member_discount_percent"),
            "description": (
                "members_only: el producto solo lo ven y compran usuarios con cuenta. "
                "member_discount_percent: descuento (%) que reciben los socios."
            ),
        }),
    )
