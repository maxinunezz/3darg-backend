from django.contrib import admin
from .models import Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "brand", "status", "total_amount", "currency", "created_at")
    list_filter = ("brand", "status")
    search_fields = ("id", "external_reference", "customer_email")