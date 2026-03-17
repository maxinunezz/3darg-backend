from django.contrib import admin
from .models import Brand, BrandLink


class BrandLinkInline(admin.TabularInline):
    model = BrandLink
    extra = 1


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "brand_type",
        "parent",
        "is_active",
        "show_in_navbar",
        "navbar_order",
    )
    list_filter = ("brand_type", "is_active", "show_in_navbar")
    search_fields = ("name", "slug")
    ordering = ("navbar_order", "name")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [BrandLinkInline]