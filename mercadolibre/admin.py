from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import MLCredentials, MLListingTemplate


@admin.register(MLCredentials)
class MLCredentialsAdmin(admin.ModelAdmin):
    list_display = ("ml_user_id", "is_connected", "is_expired", "updated_at")
    fields = (
        "connect_link",
        "ml_user_id",
        "is_connected",
        "is_expired",
        "access_token_display",
        "refresh_token_display",
        "expires_at",
        "updated_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Singleton: nos aseguramos de que la fila (pk=1) exista para que
        # siempre aparezca en el listado, aunque todavía no se haya conectado.
        MLCredentials.load()
        return super().changelist_view(request, extra_context)

    def connect_link(self, obj):
        url = reverse("ml-authorize")
        label = "Reconectar con Mercado Libre" if obj and obj.is_connected else "Conectar con Mercado Libre"
        return format_html('<a class="button" href="{}">{}</a>', url, label)
    connect_link.short_description = "Conexión"

    def access_token_display(self, obj):
        return f"{obj.access_token[:8]}…" if obj.access_token else "—"
    access_token_display.short_description = "Access token"

    def refresh_token_display(self, obj):
        return f"{obj.refresh_token[:8]}…" if obj.refresh_token else "—"
    refresh_token_display.short_description = "Refresh token"


@admin.register(MLListingTemplate)
class MLListingTemplateAdmin(admin.ModelAdmin):
    fields = ("description_template",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        MLListingTemplate.load()
        return super().changelist_view(request, extra_context)
