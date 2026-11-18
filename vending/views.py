import logging
from django.conf import settings
from config.email_from import brand_from_email
from django.core.mail import send_mail
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle
from .models import VendingLead
from .serializers import VendingLeadSerializer

logger = logging.getLogger(__name__)

CONTACT_EMAIL = getattr(settings, "CONTACT_EMAIL", "3darg1@gmail.com")


class VendingLeadThrottle(AnonRateThrottle):
    # Contador propio (ver config/throttles.py): sin `scope`, compartía el del
    # throttle global "anon" y navegar el sitio agotaba este límite.
    scope = "vending_lead"
    rate = "5/hour"


class VendingLeadAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [VendingLeadThrottle]

    def post(self, request):
        serializer = VendingLeadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        lead = serializer.save()

        try:
            send_mail(
                subject=f"[Máquina expendedora] Nuevo interesado — {lead.get_segmento_display()}",
                message=(
                    f"Nombre: {lead.nombre}\n"
                    f"Email: {lead.email}\n"
                    f"Teléfono: {lead.telefono or '-'}\n"
                    f"Segmento: {lead.get_segmento_display()}\n\n"
                    f"Mensaje:\n{lead.mensaje or '-'}"
                ),
                from_email=brand_from_email(),
                recipient_list=[CONTACT_EMAIL],
                fail_silently=True,
            )
        except Exception as exc:
            logger.exception("Error enviando notificación de lead de vending: %s", exc)

        return Response({"detail": "ok"}, status=status.HTTP_201_CREATED)
