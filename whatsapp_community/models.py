from django.db import models


class WhatsAppCommunityLead(models.Model):
    """Suscriptor captado por el pop-up/botón flotante de "unirse al canal de
    WhatsApp" (frontend: components/whatsapp-community-widget.tsx). Solo pide
    teléfono + de qué tipo de cliente es (checkboxes configurables por marca,
    ver Brand.page_config.whatsapp_channel.segments) — no hay confirmación de
    alta real al canal en sí, eso lo arma cada marca a mano en WhatsApp."""

    phone = models.CharField(max_length=30)
    # Slug de la marca desde la que se suscribió (ej: "lumy"). Igual criterio que
    # wholesale.WholesaleLead: string, no FK — así el popup queda listo para
    # cualquier sub-marca sin requerir que la Brand ya exista en este momento.
    brand = models.CharField(max_length=140, blank=True)
    # Keys de los checkboxes marcados (ej: ["pasteleria"]) — match contra
    # Brand.page_config.whatsapp_channel.segments[].key, texto libre a
    # propósito (no un TextChoices fijo) porque cada marca define los suyos.
    segments = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.phone} ({self.brand or '3darg'})"
