import uuid
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

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    currency = models.CharField(max_length=10, default="ARS")
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # items “simples” hasta tener catálogo
    # ejemplo: [{"title": "Scoop 5g", "qty": 2, "unit_price": 3500}]
    items = models.JSONField(default=list, blank=True)

    # referencia externa para MP (ideal para mapear webhooks)
    external_reference = models.CharField(max_length=80, unique=True, blank=True)

    customer_email = models.EmailField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.brand.slug} - {self.id} ({self.status})"