from django.db import models


class WholesaleLead(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=40)
    city_province = models.CharField(max_length=150)
    # Slug de la marca desde la que se manda la solicitud (ej: "lumy"). Opcional
    # para poder reusar este mismo endpoint si otra sub-marca suma su propio
    # programa de mayoristas más adelante, sin tocar código.
    brand = models.CharField(max_length=140, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.email})"
