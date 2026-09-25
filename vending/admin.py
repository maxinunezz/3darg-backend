from django.contrib import admin
from .models import VendingLead


@admin.register(VendingLead)
class VendingLeadAdmin(admin.ModelAdmin):
    list_display = ("nombre", "email", "segmento", "telefono", "created_at")
    list_filter = ("segmento", "created_at")
    search_fields = ("nombre", "email", "telefono", "mensaje")
    readonly_fields = ("created_at",)
