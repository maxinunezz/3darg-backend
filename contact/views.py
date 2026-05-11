import logging
from django.conf import settings
from django.core.mail import send_mail, EmailMultiAlternatives
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle

logger = logging.getLogger(__name__)

TELEGRAM_URL = getattr(settings, "TELEGRAM_URL", "https://t.me/3darg")
CONTACT_EMAIL = getattr(settings, "CONTACT_EMAIL", "3darg1@gmail.com")


class ContactThrottle(AnonRateThrottle):
    rate = "5/hour"


class ContactSerializer(serializers.Serializer):
    email = serializers.EmailField()
    title = serializers.CharField(max_length=150)
    body = serializers.CharField(max_length=2000)


def _build_internal_html(email: str, title: str, body: str) -> str:
    return f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: monospace; background: #080808; color: #e0e0e0; margin: 0; padding: 0; }}
    .wrap {{ max-width: 600px; margin: 0 auto; padding: 40px 32px; }}
    .label {{ font-size: 10px; letter-spacing: 0.35em; color: #555; text-transform: uppercase; margin-bottom: 4px; }}
    .value {{ font-size: 14px; color: #ddd; margin-bottom: 24px; border-left: 2px solid #333; padding-left: 12px; }}
    .body-block {{ white-space: pre-wrap; font-size: 14px; color: #ccc; background: #111; padding: 16px; border: 1px solid #222; }}
    h1 {{ font-size: 13px; letter-spacing: 0.3em; text-transform: uppercase; color: #888; margin-bottom: 32px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Nueva consulta — 3DARG</h1>
    <div class="label">De</div>
    <div class="value">{email}</div>
    <div class="label">Asunto</div>
    <div class="value">{title}</div>
    <div class="label">Mensaje</div>
    <div class="body-block">{body}</div>
  </div>
</body>
</html>
"""


def _build_confirm_html(title: str, telegram_url: str) -> str:
    return f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: monospace; background: #080808; color: #e0e0e0; margin: 0; padding: 0; }}
    .wrap {{ max-width: 600px; margin: 0 auto; padding: 48px 32px; }}
    .tag {{ font-size: 9px; letter-spacing: 0.4em; color: #444; text-transform: uppercase; margin-bottom: 32px; }}
    h1 {{ font-size: 20px; font-weight: bold; color: #fff; margin-bottom: 16px; line-height: 1.3; }}
    p {{ font-size: 13px; color: #888; line-height: 1.7; margin-bottom: 24px; }}
    .cta {{ display: inline-block; background: #fff; color: #000; padding: 14px 28px;
            font-size: 10px; letter-spacing: 0.3em; text-transform: uppercase;
            text-decoration: none; font-weight: bold; margin-top: 8px; }}
    .footer {{ margin-top: 48px; font-size: 9px; letter-spacing: 0.3em; color: #333; text-transform: uppercase; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="tag">3DARG · Manufactura Aditiva Industrial</div>
    <h1>Recibimos tu consulta.</h1>
    <p>
      Tu mensaje "<strong style="color:#ccc">{title}</strong>" llegó correctamente a nuestro equipo.
      Te respondemos en menos de 24 horas hábiles con un presupuesto detallado.
    </p>
    <p>
      Mientras tanto, sumáte a nuestra comunidad de Telegram donde compartimos
      novedades, proyectos y avances del sector:
    </p>
    <a href="{telegram_url}" class="cta">Unirse al canal</a>
    <div class="footer">© 3DARG · Buenos Aires · Argentina</div>
  </div>
</body>
</html>
"""


class ContactAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ContactThrottle]

    def post(self, request):
        serializer = ContactSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data["email"]
        title = serializer.validated_data["title"]
        body = serializer.validated_data["body"]

        try:
            # Email interno a 3DARG
            internal = EmailMultiAlternatives(
                subject=f"[Consulta] {title}",
                body=f"De: {email}\n\nAsunto: {title}\n\n{body}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[CONTACT_EMAIL],
                reply_to=[email],
            )
            internal.attach_alternative(_build_internal_html(email, title, body), "text/html")
            internal.send()

            # Email de confirmación al cliente
            confirm = EmailMultiAlternatives(
                subject="Recibimos tu consulta — 3DARG",
                body=(
                    f"Hola,\n\nRecibimos tu consulta \"{title}\".\n"
                    "Te respondemos en menos de 24 horas hábiles.\n\n"
                    f"Mientras tanto, unite a nuestro canal de Telegram: {TELEGRAM_URL}\n\n"
                    "— Equipo 3DARG"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[email],
            )
            confirm.attach_alternative(_build_confirm_html(title, TELEGRAM_URL), "text/html")
            confirm.send()

        except Exception as exc:
            logger.exception("Error enviando email de contacto: %s", exc)
            return Response(
                {"detail": "No se pudo enviar el mensaje. Intentá de nuevo más tarde."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({"detail": "ok"}, status=status.HTTP_200_OK)
