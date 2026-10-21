import csv
import io
import json
from decimal import Decimal

from django.conf import settings
from django.contrib import admin, messages
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.html import format_html

from payments.services.transfer_notifications import reference_code
from shipping.services import correo_argentino
from shipping.services.phone import split_ar_phone
from .models import Order, OrderItem
from .services.transfer_receipt_retention import delete_old_transfer_receipts
from .signals import _create_correo_argentino_shipment

# Encabezados EXACTOS de la plantilla de "Carga masiva" del portal web de
# MiCorreo (Nuevo envío → Paquetería → Masivo → "Plantilla de datos",
# descargada del panel real el 17/10/2026) — no es la API, es un CSV que se
# sube a mano en micorreo.com.ar. Útil como alta manual de la guía mientras
# no tengamos las credenciales reales de API para `create_shipment()` (ver
# CLAUDE.md, sección "Envíos"). El orden de columnas importa.
_CARGA_MASIVA_CSV_KEYS = [
    "tipo_producto", "largo", "ancho", "altura", "peso", "valor_del_contenido",
    "provincia_destino", "sucursal_destino", "localidad_destino", "calle_destino",
    "altura_destino", "piso", "dpto", "codpostal_destino", "destino_nombre",
    "destino_email", "cod_area_tel", "tel", "cod_area_cel", "cel", "numero_orden",
]
_CARGA_MASIVA_CSV_HEADERS = [
    "tipo_producto(obligatorio)", "largo(obligatorio en CM)", "ancho(obligatorio en CM)",
    "altura(obligatorio en CM)", "peso(obligatorio en KG)",
    "valor_del_contenido(obligatorio en pesos argentinos)", "provincia_destino(obligatorio)",
    "sucursal_destino(obligatorio solo en caso de no ingresar localidad de destino)",
    "localidad_destino(obligatorio solo en caso de no ingresar sucursal de destino)",
    "calle_destino(obligatorio solo en caso de no ingresar sucursal de destino)",
    "altura_destino(obligatorio solo en caso de no ingresar sucursal de destino)",
    "piso(opcional solo en caso de no ingresar sucursal de destino)",
    "dpto(opcional solo en caso de no ingresar sucursal de destino)",
    "codpostal_destino(obligatorio solo en caso de no ingresar sucursal de destino)",
    "destino_nombre(obligatorio)", "destino_email(obligatorio, debe ser un email valido)",
    "cod_area_tel(opcional)", "tel(opcional)", "cod_area_cel(obligatorio)",
    "cel(obligatorio)", "numero_orden(opcional)",
]


class TieneErrorCorreoArgentinoFilter(admin.SimpleListFilter):
    """Filtro dedicado (en vez del genérico `EmptyFieldListFilter`) para que
    el título en el sidebar sea explícito sobre qué significa — pedido del
    dueño tras no notar que "Reintentar alta en Correo Argentino" había
    fallado en silencio (el error quedaba guardado en
    `correo_argentino_sync_error` pero no se veía en ningún lado sin abrir
    cada pedido)."""
    title = "Envío Correo Argentino con error"
    parameter_name = "tiene_error_correo_argentino"

    def lookups(self, request, model_admin):
        return (("si", "Sí, con error"), ("no", "No / sin error"))

    def queryset(self, request, queryset):
        if self.value() == "si":
            return queryset.exclude(correo_argentino_sync_error="")
        if self.value() == "no":
            return queryset.filter(correo_argentino_sync_error="")
        return queryset


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "product_name", "variant", "variant_label", "quantity", "unit_price", "subtotal")
    fields = ("product", "product_name", "variant", "variant_label", "quantity", "unit_price", "subtotal")

    def has_add_permission(self, request, obj=None):
        # Los items de un pedido son un snapshot de la compra (todos los
        # campos de arriba son readonly) — nunca tuvo sentido "agregar" uno
        # desde acá. Además de ser inútil, permitir el alta hacía que Django
        # renderizara la fila-molde oculta del botón "Agregar otro" con un
        # `OrderItem()` sin guardar (quantity/unit_price en None), que
        # rompía la página de detalle al calcular `subtotal` (None * None).
        return False

    def subtotal(self, obj):
        return obj.subtotal
    subtotal.short_description = "Subtotal"


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "codigo_referencia", "id", "brand", "user", "status", "payment_channel", "total_amount",
        "shipping_cost", "shipping_method", "shipping_modality", "estado_envio_correo_argentino",
        "tiene_comprobante", "vendido_de_mas", "currency", "created_at",
    )
    list_filter = (
        "brand", "status", "payment_channel", "shipping_method", "oversold",
        ("transfer_receipt", admin.EmptyFieldListFilter),
        TieneErrorCorreoArgentinoFilter,
    )
    search_fields = (
        "id", "external_reference", "customer_email", "user__email",
        "correo_argentino_tracking_number",
    )
    readonly_fields = (
        "id", "external_reference", "created_at", "updated_at",
        "correo_argentino_tracking_number", "correo_argentino_sync_error_detalle",
        "transfer_receipt_uploaded_at", "transfer_receipt_preview",
        "oversold", "oversold_detail",
    )
    inlines = [OrderItemInline]
    actions = [
        "confirmar_transferencia_recibida",
        "cancelar_pedido_pendiente",
        "reintentar_alta_correo_argentino",
        "consultar_tracking_correo_argentino",
        "exportar_csv_carga_masiva",
        "eliminar_comprobantes_vencidos",
    ]

    fieldsets = (
        (None, {
            "fields": (
                "id", "external_reference", "brand", "user", "status",
                "payment_channel", "transfer_discount_percent_applied",
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
            "fields": ("correo_argentino_tracking_number", "correo_argentino_sync_error_detalle"),
        }),
        ("Transferencia — comprobante", {
            "fields": ("transfer_receipt", "transfer_receipt_uploaded_at", "transfer_receipt_preview"),
        }),
        ("Alerta — vendido por encima del stock", {
            "description": (
                "El stock es información interna: nunca bloquea una compra, así que un comprador "
                "puede pedir más unidades de las que hay disponibles. Si eso pasó acá, el stock del "
                "producto/variante involucrado quedó en negativo a propósito — es la señal de que "
                "hay que reponer o producir más. Estos dos campos los completa solo el sistema al "
                "confirmarse el pago, no se editan a mano."
            ),
            "fields": ("oversold", "oversold_detail"),
        }),
    )

    @admin.display(description="Código de referencia")
    def codigo_referencia(self, obj):
        """Mismo código corto (8 caracteres, mayúsculas) que ve el comprador
        en el mail/pantalla de transferencia y que pone como concepto al
        transferir (`reference_code()`, ver
        `payments/services/transfer_notifications.py`) — antes solo se podía
        ubicar el pedido buscando el UUID completo (`id`/`external_reference`)
        a mano; con esta columna alcanza con mirar la lista y comparar contra
        lo que el comprador mandó por mail/WhatsApp."""
        return reference_code(obj)

    @admin.display(description="¿Tiene comprobante?", boolean=True)
    def tiene_comprobante(self, obj):
        return bool(obj.transfer_receipt)

    @admin.display(description="¿Vendido de más?", boolean=True)
    def vendido_de_mas(self, obj):
        return obj.oversold

    @admin.display(description="Estado envío (Correo Argentino)")
    def estado_envio_correo_argentino(self, obj):
        """Columna de un vistazo en el listado — antes había que abrir cada
        pedido para notar que 'Reintentar alta en Correo Argentino' había
        fallado (el error quedaba solo en `correo_argentino_sync_error`,
        sin ningún indicio visible desde el listado ni desde el mensaje
        genérico de la acción). El `title` del `<span>` muestra el error
        completo al pasar el mouse, sin tener que entrar al detalle."""
        if obj.shipping_method != "correoargentino":
            return "—"
        if obj.correo_argentino_sync_error:
            return format_html(
                '<span style="color: #b91c1c; font-weight: 600; cursor: help;" title="{}">'
                "⚠ Error</span>",
                obj.correo_argentino_sync_error,
            )
        if obj.correo_argentino_tracking_number:
            return format_html(
                '<span style="color: #15803d; font-weight: 600;">✓ Dado de alta</span>'
            )
        return format_html('<span style="color: #6b7280;">Pendiente</span>')

    @admin.display(description="Error de sincronización")
    def correo_argentino_sync_error_detalle(self, obj):
        """Mismo dato que el campo `correo_argentino_sync_error` crudo, pero
        resaltado en rojo en la ficha del pedido — antes se veía como texto
        plano readonly, fácil de pasar por alto entre el resto de los
        campos de envío."""
        if not obj.correo_argentino_sync_error:
            return "(sin error)"
        return format_html(
            '<div style="color:#b91c1c; background:#fee2e2; border:1px solid #fecaca; '
            'border-radius:6px; padding:10px 14px; font-weight:600; max-width:640px;">{}</div>',
            obj.correo_argentino_sync_error,
        )

    @admin.display(description="Vista previa del comprobante")
    def transfer_receipt_preview(self, obj):
        if not obj.transfer_receipt:
            return "(sin comprobante)"
        url = obj.transfer_receipt.url
        if url.lower().endswith(".pdf"):
            return format_html('<a href="{}" target="_blank" rel="noopener">Ver PDF del comprobante</a>', url)
        return format_html(
            '<a href="{0}" target="_blank" rel="noopener">'
            '<img src="{0}" style="max-width: 300px; max-height: 300px;" />'
            '</a>',
            url,
        )

    @admin.action(description="Confirmar transferencia recibida")
    def confirmar_transferencia_recibida(self, request, queryset):
        """Flip manual de `status` a `PAID` para pedidos del canal
        transferencia que todavía están `PENDING` — lo corre el dueño una
        vez que ve el ingreso en el banco con el código de referencia
        (`reference_code()`, ver `payments/services/transfer_notifications.py`).

        No duplica nada de la lógica de confirmación: `orders/signals.py::
        handle_order_status_change` ya reacciona a CUALQUIER transición a
        `PAID` sin importar `payment_channel` (descuenta stock, manda el
        mail de confirmación al comprador, avisa al dueño, dispara Meta
        CAPI/presupuestos3d/Correo Argentino) — acá solo hace falta guardar
        el nuevo status y dejar que el signal haga el resto.
        """
        afectadas = 0
        omitidas = 0
        for order in queryset:
            if order.payment_channel != Order.PaymentChannel.TRANSFER or order.status != Order.Status.PENDING:
                omitidas += 1
                continue
            order.status = Order.Status.PAID
            order.save()
            afectadas += 1

        if afectadas:
            self.message_user(
                request,
                f"Se confirmó el pago por transferencia de {afectadas} pedido(s) — "
                "se descontó stock y se mandaron los mails correspondientes.",
            )
        if omitidas:
            self.message_user(
                request,
                f"{omitidas} pedido(s) no son de transferencia pendiente — se omitieron.",
                level=messages.WARNING,
            )

    @admin.action(description="Cancelar pedido pendiente")
    def cancelar_pedido_pendiente(self, request, queryset):
        """Cancela a mano pedidos de transferencia que quedaron `PENDING`
        (ej. el comprador avisó que no va a transferir) — no hace falta
        restituir stock porque el canal transferencia nunca lo descuenta
        mientras está `PENDING` (mismo criterio que MercadoPago, ver
        `CLAUDE.md` backend). Mismo guard que la acción de arriba, invertido.
        """
        afectadas = 0
        omitidas = 0
        for order in queryset:
            if order.payment_channel != Order.PaymentChannel.TRANSFER or order.status != Order.Status.PENDING:
                omitidas += 1
                continue
            order.status = Order.Status.CANCELLED
            order.save()
            afectadas += 1

        if afectadas:
            self.message_user(request, f"Se cancelaron {afectadas} pedido(s) pendiente(s) de transferencia.")
        if omitidas:
            self.message_user(
                request,
                f"{omitidas} pedido(s) no son de transferencia pendiente — se omitieron.",
                level=messages.WARNING,
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

        Antes esto solo mostraba un mensaje genérico ("se reintentó para N
        orden(es)") sin decir si había fallado — había que abrir cada pedido
        a mano para notar el error real en `correo_argentino_sync_error`. Acá
        se chequea el resultado de cada orden (el mismo objeto `order` que
        pasamos a `_create_correo_argentino_shipment` queda actualizado en
        memoria, no hace falta `refresh_from_db()`) y se muestra el error
        real como mensaje ROJO por cada orden que siguió fallando.
        """
        exitosas = 0
        fallidas = []
        omitidas = 0
        for order in queryset:
            if order.shipping_method != "correoargentino":
                omitidas += 1
                continue
            _create_correo_argentino_shipment(order)
            if order.correo_argentino_sync_error:
                fallidas.append(order)
            else:
                exitosas += 1

        if exitosas:
            self.message_user(
                request,
                f"Se dio de alta el envío en Correo Argentino para {exitosas} orden(es).",
            )
        for order in fallidas:
            self.message_user(
                request,
                f"Orden {reference_code(order)} ({order.id}) — Correo Argentino rechazó el alta: "
                f"{order.correo_argentino_sync_error}",
                level=messages.ERROR,
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
            ultimo_estado = correo_argentino.extract_last_status(eventos)
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

    @admin.action(description="Exportar CSV de carga masiva (MiCorreo)")
    def exportar_csv_carga_masiva(self, request, queryset):
        """Exporta las órdenes seleccionadas al formato EXACTO del CSV de
        "Carga masiva" del portal web de MiCorreo (Nuevo envío → Paquetería
        → Masivo), ver `_CARGA_MASIVA_CSV_KEYS`/`_CARGA_MASIVA_CSV_HEADERS`
        arriba. Es un alta MANUAL (subida a mano en micorreo.com.ar con el
        login normal del dueño) — no pasa por la API ni por
        `create_shipment()` — útil como vía alternativa de alta real mientras
        no tengamos las credenciales de API (ver CLAUDE.md, sección
        "Envíos").

        Reusa `correo_argentino._parcel_weight_and_dims(order)` para
        largo/ancho/altura/peso (mismo criterio que usa el payload real de la
        API) y la misma fórmula de valor declarado
        (`total_amount - shipping_cost`) que `_build_shipment_payload()`.

        `cod_area_cel`/`cel` se separan automáticamente a partir de
        `shipping_phone` con `shipping.services.phone.split_ar_phone()`
        (basado en `phonenumbers`/libphonenumber) — funciona tanto con el
        formato E.164 que guarda el checkout actual (`react-phone-number-input`)
        como con texto libre de órdenes viejas ("011 15-2233-4455",
        "1122334455", etc.). Si no se puede parsear con confianza, se cae al
        comportamiento anterior (todo el string en `cel`, área vacía) y se
        avisa cuántas órdenes quedaron así, para revisar a mano.

        OJO — limitación conocida, no resuelta acá: no valida los límites de
        tamaño/peso de Correo Argentino (50kg, lado mayor ≤200cm, suma de 3
        lados ≤300cm, mínimo 11x16x0.5cm) — si una orden los excede, el
        portal la va a rechazar al subir el CSV, no acá.
        """
        rows = []
        omitidas = []
        sin_area_detectada = 0
        for order in queryset:
            if order.shipping_method != "correoargentino":
                omitidas.append((order, "no es de Correo Argentino (shipping_method)"))
                continue

            is_sucursal = order.shipping_modality == "sucursal"
            if is_sucursal and not order.shipping_agency_id:
                omitidas.append((order, "falta shipping_agency_id (modalidad sucursal)"))
                continue
            if not is_sucursal and not (
                order.shipping_street and order.shipping_city and order.shipping_postal_code
            ):
                omitidas.append((order, "falta calle/localidad/código postal (modalidad domicilio)"))
                continue

            weight_grams, dims = correo_argentino._parcel_weight_and_dims(order)
            peso_kg = (Decimal(weight_grams) / Decimal(1000)).quantize(Decimal("0.001"))
            valor_contenido = (order.total_amount - order.shipping_cost).quantize(Decimal("0.01"))

            phone_split = split_ar_phone(order.shipping_phone)
            if phone_split:
                cod_area_cel, cel = phone_split
            else:
                cod_area_cel, cel = "", order.shipping_phone
                sin_area_detectada += 1

            row = {
                "tipo_producto": settings.CORREO_ARGENTINO_PRODUCT_TYPE,
                "largo": dims["length"],
                "ancho": dims["width"],
                "altura": dims["height"],
                "peso": peso_kg,
                "valor_del_contenido": valor_contenido,
                "provincia_destino": order.shipping_province,
                "sucursal_destino": order.shipping_agency_id if is_sucursal else "",
                "localidad_destino": "" if is_sucursal else order.shipping_city,
                "calle_destino": "" if is_sucursal else order.shipping_street,
                "altura_destino": "" if is_sucursal else order.shipping_street_number,
                "piso": "" if is_sucursal else order.shipping_floor,
                "dpto": "" if is_sucursal else order.shipping_department,
                "codpostal_destino": "" if is_sucursal else order.shipping_postal_code,
                "destino_nombre": order.shipping_full_name,
                "destino_email": order.customer_email,
                "cod_area_tel": "",
                "tel": "",
                "cod_area_cel": cod_area_cel,
                "cel": cel,
                "numero_orden": order.external_reference,
            }
            rows.append(row)

        if not rows:
            self.message_user(
                request,
                "Ninguna de las órdenes seleccionadas es elegible para exportar "
                "(revisá que sean de Correo Argentino y tengan los datos de envío completos).",
                level=messages.WARNING,
            )
            return None

        # Se arma el CSV entero en memoria (buffer de texto) y se codifica una
        # sola vez al final con "utf-8-sig" — escribir directo sobre
        # `HttpResponse` con ese charset agrega el BOM en CADA llamada a
        # `.write()` (cada `writerow()`), no solo al principio del archivo,
        # dejando bytes BOM metidos en el medio del CSV.
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(_CARGA_MASIVA_CSV_HEADERS)
        for row in rows:
            writer.writerow([row[key] for key in _CARGA_MASIVA_CSV_KEYS])

        response = HttpResponse(
            buffer.getvalue().encode("utf-8-sig"),
            content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = 'attachment; filename="carga_masiva_correo_argentino.csv"'

        if omitidas:
            detalle = "; ".join(f"orden {o.id} ({motivo})" for o, motivo in omitidas)
            self.message_user(
                request,
                f"Se exportaron {len(rows)} orden(es). {len(omitidas)} se omitieron: {detalle}.",
                level=messages.WARNING,
            )
        else:
            self.message_user(request, f"Se exportaron {len(rows)} orden(es).")

        if sin_area_detectada:
            self.message_user(
                request,
                f"No se pudo separar el código de área en {sin_area_detectada} de {len(rows)} "
                "orden(es) exportada(s) — quedaron con el teléfono completo en 'cel' y "
                "'cod_area_cel' vacío. Revisá/completá esas filas a mano antes de subir el CSV al "
                "portal de MiCorreo.",
                level=messages.WARNING,
            )
        return response

    @admin.action(description="Eliminar comprobantes de pedidos confirmados (más de N días)")
    def eliminar_comprobantes_vencidos(self, request, queryset):
        """Respaldo manual de `cleanup_old_transfer_receipts` (ver
        `orders/services/transfer_receipt_retention.py`) — borra el
        comprobante de los pedidos TRANSFER/PAID seleccionados que ya
        pasaron `settings.TRANSFER_RECEIPT_RETENTION_DAYS` días desde su
        confirmación, sin esperar al próximo disparo del Cron Job de
        Railway. Pedidos sin comprobante, no confirmados, o confirmados
        hace menos tiempo quedan afuera silenciosamente (es el mismo filtro
        que usa el comando).
        """
        days = settings.TRANSFER_RECEIPT_RETENTION_DAYS
        if days <= 0:
            self.message_user(
                request,
                "La retención de comprobantes está desactivada "
                "(TRANSFER_RECEIPT_RETENTION_DAYS <= 0) — no se borró nada.",
                level=messages.WARNING,
            )
            return

        borrados = delete_old_transfer_receipts(days=days, queryset=queryset)
        if borrados:
            refs = ", ".join(o.external_reference or str(o.id) for o in borrados)
            self.message_user(
                request,
                f"Se eliminaron {len(borrados)} comprobante(s) de transferencia "
                f"(pedidos: {refs}).",
            )
        else:
            self.message_user(
                request,
                "Ninguno de los pedidos seleccionados tiene un comprobante elegible "
                f"para borrar (TRANSFER + PAID + confirmado hace más de {days} días).",
                level=messages.WARNING,
            )


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "product_name", "variant_label", "quantity", "unit_price")
    search_fields = ("product_name", "order__external_reference")
