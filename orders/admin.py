import json

from django.contrib import admin, messages
from django.shortcuts import render

from shipping.services import correo_argentino
from .models import Order, OrderItem
from .signals import _create_correo_argentino_shipment


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "product_name", "variant", "variant_label", "quantity", "unit_price", "subtotal")
    fields = ("product", "product_name", "variant", "variant_label", "quantity", "unit_price", "subtotal")

    def subtotal(self, obj):
        return obj.subtotal
    subtotal.short_description = "Subtotal"


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id", "brand", "user", "status", "total_amount", "shipping_cost",
        "shipping_method", "shipping_modality", "correo_argentino_tracking_number",
        "currency", "created_at",
    )
    list_filter = ("brand", "status", "shipping_method")
    search_fields = (
        "id", "external_reference", "customer_email", "user__email",
        "correo_argentino_tracking_number",
    )
    readonly_fields = (
        "id", "external_reference", "created_at", "updated_at",
        "correo_argentino_tracking_number", "correo_argentino_sync_error",
    )
    inlines = [OrderItemInline]
    actions = [
        "reintentar_alta_correo_argentino",
        "consultar_tracking_correo_argentino",
    ]

    fieldsets = (
        (None, {
            "fields": (
                "id", "external_reference", "brand", "user", "status",
                "currency", "total_amount", "customer_email",
                "created_at", "updated_at",
            ),
        }),
        ("Envío — método y costo", {
            "fields": ("shipping_method", "shipping_modality", "shipping_cost", "shipping_postal_code"),
        }),
        ("Envío — dirección del comprador", {
            "fields": (
                "shipping_full_name", "shipping_phone",
                "shipping_street", "shipping_street_number",
                "shipping_floor", "shipping_department",
                "shipping_city", "shipping_province", "shipping_agency_id",
            ),
        }),
        ("Envío — Correo Argentino (API MiCorreo)", {
            "fields": ("correo_argentino_tracking_number", "correo_argentino_sync_error"),
        }),
    )

    @admin.action(description="Reintentar alta en Correo Argentino")
    def reintentar_alta_correo_argentino(self, request, queryset):
        """Vuelve a llamar `create_shipment()` para las órdenes seleccionadas
        que son de Correo Argentino — útil cuando `correo_argentino_sync_error`
        quedó con un mensaje (ej. faltaba configurar las credenciales y ya se
        cargaron, o la API rechazó el alta por un dato puntual ya corregido).
        No es idempotente contra la API en el sentido de "no reintentar dos
        veces" — `extOrderId` es siempre `order.external_reference`, así que
        un reintento sobre una orden ya dada de alta debería ser rechazado
        por la API con "La orden ya fue importada con anterioridad" (queda
        reflejado en el error, no genera un envío duplicado).
        """
        afectadas = 0
        omitidas = 0
        for order in queryset:
            if order.shipping_method != "correoargentino":
                omitidas += 1
                continue
            _create_correo_argentino_shipment(order)
            afectadas += 1

        if afectadas:
            self.message_user(
                request,
                f"Se reintentó el alta en Correo Argentino para {afectadas} orden(es). "
                "Revisá 'correo_argentino_tracking_number'/'correo_argentino_sync_error' de cada una.",
            )
        if omitidas:
            self.message_user(
                request,
                f"{omitidas} orden(es) no son de Correo Argentino (shipping_method) — se omitieron.",
                level=messages.WARNING,
            )

    @admin.action(description="Consultar estado de envío en Correo Argentino")
    def consultar_tracking_correo_argentino(self, request, queryset):
        """Llama `get_tracking(shipping_id)` por orden (la API real toma un
        solo `shippingId` por llamada, no un batch — a diferencia de lo
        asumido en una iteración anterior de esta integración).

        OJO: `correo_argentino_tracking_number` guarda nuestro propio
        `extOrderId` (ver `orders/signals.py`), no necesariamente el
        `shippingId` real que asigna Correo Argentino al envío — la doc no
        confirma que ambos sean intercambiables. Si la API no reconoce el
        valor, la consulta devuelve "(sin datos)" para esa orden en vez de
        romper; no hay generación de etiquetas en esta API (no existe ese
        endpoint).
        """
        orders = [o for o in queryset if o.correo_argentino_tracking_number]
        if not orders:
            self.message_user(
                request,
                "Ninguna de las órdenes seleccionadas tiene un envío dado de alta en Correo Argentino "
                "(hace falta dar de alta el envío primero).",
                level=messages.WARNING,
            )
            return None

        resultados = []
        for order in orders:
            eventos = correo_argentino.get_tracking(order.correo_argentino_tracking_number)
            ultimo_estado = None
            if eventos:
                ultimo = eventos[-1]
                if isinstance(ultimo, dict):
                    ultimo_estado = (
                        ultimo.get("status") or ultimo.get("lastStatus")
                        or ultimo.get("description") or ultimo.get("event") or ultimo.get("state")
                    )
            resultados.append({
                "order": order,
                "tracking_number": order.correo_argentino_tracking_number,
                "ultimo_estado": ultimo_estado or "(sin datos)",
                "raw": json.dumps(eventos, indent=2, ensure_ascii=False) if eventos else "(sin datos para este envío)",
            })

        return render(
            request,
            "admin/orders/order/resultado_tracking.html",
            {
                "resultados": resultados,
                "title": "Estado de envío — Correo Argentino",
                "opts": self.model._meta,
            },
        )


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "product_name", "variant_label", "quantity", "unit_price")
    search_fields = ("product_name", "order__external_reference")
