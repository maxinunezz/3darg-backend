import logging
import os

from django.conf import settings
from django.core.mail import send_mail
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle

from .models import WholesaleLead
from .serializers import WholesaleLeadSerializer

logger = logging.getLogger(__name__)

CONTACT_EMAIL = getattr(settings, "CONTACT_EMAIL", "3darg1@gmail.com")


def _resolve_contact_email(brand_slug: str) -> str:
    """Mismo criterio que contact/views.py::_resolve_contact_email — cada marca
    puede tener su propio destinatario vía <SLUG>_CONTACT_EMAIL, si no cae a
    CONTACT_EMAIL global."""
    if brand_slug:
        env_key = f"{brand_slug.upper().replace('-', '_')}_CONTACT_EMAIL"
        brand_email = os.getenv(env_key)
        if brand_email:
            return brand_email
    return CONTACT_EMAIL


class WholesaleThrottle(AnonRateThrottle):
    rate = "5/hour"


class WholesaleLeadAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [WholesaleThrottle]

    def post(self, request):
        serializer = WholesaleLeadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        lead = serializer.save()
        to_email = _resolve_contact_email(lead.brand)

        try:
            send_mail(
                subject="[Mayoristas] Nueva solicitud de alta",
                message=(
                    f"Marca: {lead.brand or '3DARG'}\n"
                    f"Nombre y apellido: {lead.name}\n"
                    f"Email: {lead.email}\n"
                    f"Teléfono: {lead.phone}\n"
                    f"Ciudad y provincia: {lead.city_province}\n"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[to_email],
                fail_silently=True,
            )
        except Exception as exc:
            logger.exception("Error enviando notificación de lead de mayoristas: %s", exc)

        return Response({"detail": "ok"}, status=status.HTTP_201_CREATED)
