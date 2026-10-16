import logging
import os

from django.conf import settings
from django.core.mail import send_mail
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle

from .models import WhatsAppCommunityLead
from .serializers import WhatsAppCommunityLeadSerializer

logger = logging.getLogger(__name__)

CONTACT_EMAIL = getattr(settings, "CONTACT_EMAIL", "3darg1@gmail.com")


def _resolve_contact_email(brand_slug: str) -> str:
    """Mismo criterio que contact/views.py y wholesale/views.py — cada marca
    puede tener su propio destinatario vía <SLUG>_CONTACT_EMAIL, si no cae a
    CONTACT_EMAIL global."""
    if brand_slug:
        env_key = f"{brand_slug.upper().replace('-', '_')}_CONTACT_EMAIL"
        brand_email = os.getenv(env_key)
        if brand_email:
            return brand_email
    return CONTACT_EMAIL


class WhatsAppCommunityThrottle(AnonRateThrottle):
    rate = "5/hour"


class WhatsAppCommunityLeadAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [WhatsAppCommunityThrottle]

    def post(self, request):
        serializer = WhatsAppCommunityLeadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        lead = serializer.save()
        to_email = _resolve_contact_email(lead.brand)
        segments_label = ", ".join(lead.segments) if lead.segments else "-"

        try:
            send_mail(
                subject="[Comunidad WhatsApp] Nuevo suscriptor",
                message=(
                    f"Marca: {lead.brand or '3DARG'}\n"
                    f"Teléfono: {lead.phone}\n"
                    f"Tipo de cliente: {segments_label}\n"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[to_email],
                fail_silently=True,
            )
        except Exception as exc:
            logger.exception("Error enviando notificación de lead de WhatsApp: %s", exc)

        return Response({"detail": "ok"}, status=status.HTTP_201_CREATED)
