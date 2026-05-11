from django.contrib import admin
from .models import Cart, CartItem


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = ["subtotal"]

    def subtotal(self, obj):
        return obj.subtotal()


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ["user", "brand", "updated_at"]
    inlines = [CartItemInline]
