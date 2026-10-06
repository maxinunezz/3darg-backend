import logging
import os

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle

logger = logging.getLogger(__name__)

TELEGRAM_URL = getattr(settings, "TELEGRAM_URL", "https://t.me/3darg")
CONTACT_EMAIL = getattr(settings, "CONTACT_EMAIL", "3darg1@gmail.com")


def _resolve_contact_email(brand_slug: str) -> str:
    """Destinatario del mail interno. Cada marca puede tener el suyo propio vía
    <SLUG>_CONTACT_EMAIL (ej: LUMY_CONTACT_EMAIL) en el .env; si no está seteada,
    cae al CONTACT_EMAIL global. Todo por variable de entorno, sin tocar código."""
    if brand_slug:
        env_key = f"{brand_slug.upper().replace('-', '_')}_CONTACT_EMAIL"
        brand_email = os.getenv(env_key)
        if brand_email:
            return brand_email
    return CONTACT_EMAIL


class ContactThrottle(AnonRateThrottle):
    rate = "5/hour"


class ContactSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    email = serializers.EmailField()
    title = serializers.CharField(max_length=150)
    body = serializers.CharField(max_length=2000)
    # Slug de la marca desde la que se manda la consulta (ej: "lumy"). Opcional:
    # si no se manda, se asume 3DARG (comportamiento previo, sin romper nada).
    brand = serializers.SlugField(max_length=140, required=False, allow_blank=True)


def _build_internal_html(email: str, title: str, body: str, name: str, brand_name: str) -> str:
    from_line = f"{name} &lt;{email}&gt;" if name else email
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
    <h1>Nueva consulta — {brand_name}</h1>
    <div class="label">De</div>
    <div class="value">{from_line}</div>
    <div class="label">Asunto</div>
    <div class="value">{title}</div>
    <div class="label">Mensaje</div>
    <div class="body-block">{body}</div>
  </div>
</body>
</html>
"""


def _build_confirm_html(title: str, telegram_url: str, brand_name: str) -> str:
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
    <div class="tag">{brand_name}</div>
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
    <div class="footer">© {brand_name} · Buenos Aires · Argentina</div>
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

        name = serializer.validated_data.get("name", "")
        email = serializer.validated_data["email"]
        title = serializer.validated_data["title"]
        body = serializer.validated_data["body"]
        brand_slug = serializer.validated_data.get("brand", "")

        brand_name = "3DARG"
        if brand_slug:
            from brands.models import Brand  # import local: evita ciclo de imports entre apps

            brand = Brand.objects.filter(slug=brand_slug).first()
            if brand:
                brand_name = brand.name

        to_email = _resolve_contact_email(brand_slug)

        try:
            # Email interno (a la marca correspondiente, o a CONTACT_EMAIL si no hay override)
            internal = EmailMultiAlternatives(
                subject=f"[Consulta {brand_name}] {title}",
                body=(
                    f"Marca: {brand_name}\n"
                    f"De: {name + ' ' if name else ''}<{email}>\n\n"
                    f"Asunto: {title}\n\n{body}"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[to_email],
                reply_to=[email],
            )
            internal.attach_alternative(_build_internal_html(email, title, body, name, brand_name), "text/html")
            internal.send()

            # Email de confirmación al cliente
            confirm = EmailMultiAlternatives(
                subject=f"Recibimos tu consulta — {brand_name}",
                body=(
                    f"Hola,\n\nRecibimos tu consulta \"{title}\".\n"
                    "Te respondemos en menos de 24 horas hábiles.\n\n"
                    f"Mientras tanto, unite a nuestro canal de Telegram: {TELEGRAM_URL}\n\n"
                    f"— Equipo {brand_name}"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[email],
            )
            confirm.attach_alternative(_build_confirm_html(title, TELEGRAM_URL, brand_name), "text/html")
            confirm.send()

        except Exception as exc:
            logger.exception("Error enviando email de contacto: %s", exc)
            return Response(
                {"detail": "No se pudo enviar el mensaje. Intentá de nuevo más tarde."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({"detail": "ok"}, status=status.HTTP_200_OK)
