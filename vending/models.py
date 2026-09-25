from django.db import models


class VendingLead(models.Model):
    class Segmento(models.TextChoices):
        COTILLON = "cotillon", "Cotillón / regalería (venta bajo pedido)"
        EMPRESA = "empresa", "Empresa (máquina in-situ, impresión remota)"
        SUBMARCA = "submarca", "Sub-marca del grupo (shopping, gimnasio, etc.)"
        ALQUILER = "alquiler", "Alquiler para marca privada (edición limitada)"
        OTRO = "otro", "Otro"

    nombre = models.CharField(max_length=150)
    email = models.EmailField()
    telefono = models.CharField(max_length=30, blank=True)
    segmento = models.CharField(max_length=20, choices=Segmento.choices)
    mensaje = models.TextField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.nombre} ({self.get_segmento_display()})"
