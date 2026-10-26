import uuid
from django.conf import settings
from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Borrador"
        PENDING = "PENDING", "Pago pendiente"
        PAID = "PAID", "Pagado"
        REJECTED = "REJECTED", "Rechazado"
        CANCELLED = "CANCELLED", "Cancelado"

    class PaymentChannel(models.TextChoices):
        MERCADOPAGO = "mercadopago", "Mercado Pago"
        # Transferencia bancaria manual ("Opción 1"): el comprador transfiere
        # a la cuenta única del Grupo (`settings.TRANSFER_BANK_*`) y el dueño
        # confirma el ingreso a mano desde el admin — no hay API de banco de
        # por medio, a diferencia de `MERCADOPAGO`. Ver `payments/views.py`
        # ::TransferCheckoutCreateAPIView y `orders/admin.py`
        # ::confirmar_transferencia_recibida.
        TRANSFER = "transfer", "Transferencia bancaria"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Por qué medio se está pagando (o se pagó) este pedido — determina qué
    # pasa al crear la orden (se crea una preferencia de MP vs. se mandan las
    # instrucciones de transferencia) y qué acción de admin corresponde para
    # confirmarlo. Default MERCADOPAGO para no romper pedidos ya existentes
    # (todos eran de MP antes de este campo).
    payment_channel = models.CharField(
        max_length=20, choices=PaymentChannel.choices, default=PaymentChannel.MERCADOPAGO
    )
    # Snapshot del `Brand.transfer_discount_percent` vigente al momento del
    # checkout, aplicado sobre el subtotal SOLO cuando `payment_channel ==
    # TRANSFER` (ver `payments/services/transfer_discount.py`). Se guarda acá
    # (en vez de recalcularlo siempre desde `Brand`) para que el total de un
    # pedido ya creado no cambie si el dueño ajusta el % de descuento después.
    # 0 en pedidos de MercadoPago (el descuento no aplica a ese canal).
    transfer_discount_percent_applied = models.PositiveSmallIntegerField(default=0)

    brand = models.ForeignKey(
        "brands.Brand",
        related_name="orders",
        on_delete=models.PROTECT,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="orders",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    currency = models.CharField(max_length=10, default="ARS")
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Costo de envío cobrado en este pedido — ya incluido en `total_amount`
    # (se suma ahí y se manda como ítem aparte a MercadoPago, ver
    # `payments/views.py`). 0 si hubo envío gratis (umbral de la marca,
    # `Brand.shipping_config`) o si la integración de envío no corrió.
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Código postal informado por el comprador al momento del checkout, solo
    # a fines informativos (no se vuelve a cotizar con esto después).
    shipping_postal_code = models.CharField(max_length=10, blank=True)
    # Método de envío elegido por el comprador en el selector del carrito
    # (ver `shipping/services/quote.py::select_methods()`). Vacío si se cayó
    # al fallback de "más barato" (sin selección explícita o CP no cotizado).
    shipping_method = models.CharField(max_length=30, blank=True)  # "correoargentino" | "" (pedidos viejos pueden tener "andreani", histórico)
    shipping_modality = models.CharField(max_length=20, blank=True)  # "domicilio" | "sucursal" | ""

    # Dirección del comprador, pedida en el checkout antes de pagar. La API
    # real de Correo Argentino (API MiCorreo) NO exige lo mismo para las dos
    # modalidades — ver CLAUDE.md backend, sección "Envíos": sucursal solo
    # necesita `shipping_full_name`/`shipping_phone`/`shipping_province`/
    # `shipping_agency_id` (la dirección completa no es obligatoria para esa
    # modalidad); domicilio sí necesita la dirección completa (calle, altura,
    # ciudad, provincia), sin `shipping_agency_id`.
    shipping_full_name = models.CharField(max_length=150, blank=True)
    shipping_phone = models.CharField(max_length=40, blank=True)
    shipping_street = models.CharField(max_length=150, blank=True)
    shipping_street_number = models.CharField(max_length=20, blank=True)
    shipping_floor = models.CharField(max_length=20, blank=True)
    shipping_department = models.CharField(max_length=20, blank=True)
    shipping_city = models.CharField(max_length=100, blank=True)
    shipping_province = models.CharField(max_length=2, blank=True)  # código AR_PROVINCES (ver shipping/services/postal.py)
    shipping_agency_id = models.CharField(max_length=40, blank=True)

    # Resultado del alta real en Correo Argentino (API MiCorreo,
    # `POST /shipping/import`), disparada por `orders/signals.py` al
    # confirmarse el pago — ver sección "Envíos" en CLAUDE.md. Vacíos si el
    # pedido no es de Correo Argentino, si todavía no se confirmó el pago, o
    # si el alta falló (ver `_sync_error`).
    #
    # OJO: a pesar del nombre, esto NO es un tracking number asignado por el
    # correo — la respuesta real de `/shipping/import` no devuelve ninguno
    # (solo `{"createdAt": ...}`). Este campo guarda nuestro propio
    # `extOrderId` (= `external_reference`), que es el identificador que
    # efectivamente tiene Correo Argentino del envío. Se mantiene el nombre
    # del campo por compatibilidad (no se migra), pero no lo uses para
    # buscar el envío en el panel de MiCorreo salvo que confirmes que ahí
    # también se indexa por `extOrderId`.
    correo_argentino_tracking_number = models.CharField(max_length=40, blank=True)
    correo_argentino_sync_error = models.TextField(blank=True)

    # Comprobante de transferencia subido por el comprador desde la pantalla
    # de "pedido pendiente de transferencia" (ver `checkout/transfer/page.tsx`
    # y `payments/views.py::TransferReceiptUploadAPIView`), para que el dueño
    # pueda verificarla antes de confirmar el pago a mano desde el admin.
    # `FileField` (no `ImageField`): también acepta PDF, y `ImageField` usa
    # Pillow para validar que el contenido sea una imagen real, lo que
    # rechazaría cualquier PDF subido. Re-subir un comprobante REEMPLAZA el
    # anterior (se borra el archivo viejo del storage antes de guardar el
    # nuevo) — no se guarda historial de versiones.
    transfer_receipt = models.FileField(
        upload_to="orders/transfer_receipts/", null=True, blank=True
    )
    transfer_receipt_uploaded_at = models.DateTimeField(null=True, blank=True)

    # Resultado del aviso de venta a presupuestos3d (sistema interno de
    # gestión, repo aparte) — ver `orders/signals.py::_notify_presupuestos3d`.
    # Vacío si la integración no está configurada (`PRESUPUESTOS3D_API_URL`/
    # `_API_TOKEN` en blanco), si el pago todavía no se confirmó, o si el
    # último aviso se envió bien. Mismo criterio que
    # `correo_argentino_sync_error`: nunca rompe la confirmación del pago,
    # solo queda visible acá para que el dueño note un fallo (token vencido,
    # presupuestos3d caído, etc.) y pueda reintentar desde el admin (acción
    # "Reintentar aviso a presupuestos3d").
    presupuestos3d_sync_error = models.TextField(blank=True)

    items = models.JSONField(default=list, blank=True)

    external_reference = models.CharField(max_length=80, unique=True, blank=True)

    customer_email = models.EmailField(blank=True)

    # Regla de negocio (pedido del dueño, 2026-10-21): el stock es
    # información interna, nunca bloquea una compra — el comprador puede
    # pedir cualquier cantidad. Si al confirmarse el pago la cantidad
    # comprada supera el stock disponible en ese momento, el stock del
    # producto/variante queda en negativo (`orders/signals.py::_decrement_stock`)
    # y acá se guarda la marca + el detalle, para que quede visible en el
    # admin sin tener que adivinar por qué un producto quedó en negativo.
    oversold = models.BooleanField(
        default=False,
        help_text="Se marca sola al confirmarse el pago si algún ítem se vendió por encima del stock disponible — ver 'Detalle de stock vendido de más'.",
    )
    oversold_detail = models.TextField(
        blank=True,
        default="",
        help_text="Detalle de qué producto/variante se vendió de más y por cuánto quedó el stock en negativo.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.brand.slug} - {self.id} ({self.status})"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="order_items", on_delete=models.CASCADE)
    product = models.ForeignKey(
        "products.Product",
        related_name="order_items",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    # Talle/variante comprada (Fase 2 de ProductVariant) — null = producto
    # sin variantes reales al momento de la compra. `SET_NULL` porque una
    # variante se puede borrar del catálogo sin que eso invalide un pedido
    # ya hecho (igual criterio que `product` arriba).
    variant = models.ForeignKey(
        "products.ProductVariant",
        related_name="order_items",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    # Snapshot del talle al momento de la compra (ej. "Mediano (5cm)"), para
    # que el historial de pedidos siga mostrando qué talle se compró aunque
    # la variante se borre o se renombre después — mismo criterio que
    # `product_name` abajo.
    variant_label = models.CharField(max_length=100, blank=True)
    product_name = models.CharField(max_length=200)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def subtotal(self):
        # `unit_price`/`quantity` no son nullable en la DB, pero el admin
        # igual instancia un `OrderItem()` sin guardar (la fila "molde"
        # oculta que usa el JS de "Agregar otro" en el inline, se renderiza
        # siempre que haya permiso de alta, sin importar `extra=0`) — ahí sí
        # los dos valen `None`, y `None * None` rompía la página de detalle
        # del pedido en el admin.
        if self.unit_price is None or self.quantity is None:
            return None
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.product_name} x{self.quantity}"
