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
    product_name = models.CharField(max_length=200)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def subtotal(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.product_name} x{self.quantity}"
