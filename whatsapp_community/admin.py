from django.contrib import admin

from .models import WhatsAppCommunityLead


@admin.register(WhatsAppCommunityLead)
class WhatsAppCommunityLeadAdmin(admin.ModelAdmin):
    list_display = ("phone", "brand", "segments", "created_at")
    list_filter = ("brand", "created_at")
    search_fields = ("phone", "brand")
    readonly_fields = ("created_at",)
