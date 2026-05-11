from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Favorite


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["email", "username", "registered_brand", "phone", "is_active", "date_joined"]
    list_filter = ["registered_brand", "is_active", "is_staff"]
    search_fields = ["email", "username", "phone"]
    ordering = ["-date_joined"]
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Datos adicionales", {"fields": ("phone", "registered_brand")}),
    )


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ["user", "product", "created_at"]
    list_filter = ["product__brand"]
    search_fields = ["user__email", "product__name"]
    raw_id_fields = ["user", "product"]
