from django.contrib import admin
from .models import MercadoPagoPayment


@admin.register(MercadoPagoPayment)
class MercadoPagoPaymentAdmin(admin.ModelAdmin):
    list_display = ("order", "status", "preference_id", "mp_payment_id", "updated_at")
    list_filter = ("status",)
    search_fields = ("order__id", "preference_id", "mp_payment_id")