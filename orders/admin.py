from django.contrib import admin
from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "product_name", "quantity", "unit_price", "subtotal")
    fields = ("product", "product_name", "quantity", "unit_price", "subtotal")

    def subtotal(self, obj):
        return obj.subtotal
    subtotal.short_description = "Subtotal"


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "brand", "user", "status", "total_amount", "currency", "created_at")
    list_filter = ("brand", "status")
    search_fields = ("id", "external_reference", "customer_email", "user__email")
    readonly_fields = ("id", "external_reference", "created_at", "updated_at")
    inlines = [OrderItemInline]


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "product_name", "quantity", "unit_price")
    search_fields = ("product_name", "order__external_reference")
