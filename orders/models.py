import uuid
from django.conf import settings
from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING = "PENDING", "Pending payment"
        PAID = "PAID", "Paid"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

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

    items = models.JSONField(default=list, blank=True)

    external_reference = models.CharField(max_length=80, unique=True, blank=True)

    customer_email = models.EmailField(blank=True)

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
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.product_name} x{self.quantity}"
