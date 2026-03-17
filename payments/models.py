from django.db import models


class MercadoPagoPayment(models.Model):
    class Status(models.TextChoices):
        INIT = "INIT", "Init"
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"
        UNKNOWN = "UNKNOWN", "Unknown"

    order = models.OneToOneField(
        "orders.Order",
        related_name="mp_payment",
        on_delete=models.CASCADE,
    )

    preference_id = models.CharField(max_length=120, blank=True)
    init_point = models.URLField(max_length=800, blank=True)
    sandbox_init_point = models.URLField(max_length=800, blank=True)

    mp_payment_id = models.CharField(max_length=120, blank=True)  # llega por webhook o consulta
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INIT)

    raw = models.JSONField(default=dict, blank=True)  # guardar payloads/eventos

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"MP {self.order_id} ({self.status})"