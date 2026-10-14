from django.contrib import admin

from .models import WholesaleLead


@admin.register(WholesaleLead)
class WholesaleLeadAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "city_province", "brand", "created_at")
    list_filter = ("brand", "created_at")
    search_fields = ("name", "email", "phone", "city_province")
    readonly_fields = ("created_at",)
