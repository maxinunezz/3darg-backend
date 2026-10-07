import logging
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.utils import timezone

from .models import MLCredentials

logger = logging.getLogger(__name__)

ML_AUTH_URL = "https://auth.mercadolibre.com.ar/authorization"
ML_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"


@staff_member_required
def authorize(request):
    """Arranca el handshake OAuth: redirige al login/autorización de ML."""
    if not settings.ML_CLIENT_ID or not settings.ML_REDIRECT_URI:
        return HttpResponseBadRequest(
            "Falta configurar ML_CLIENT_ID y/o ML_REDIRECT_URI en el .env del backend."
        )
    params = {
        "response_type": "code",
        "client_id": settings.ML_CLIENT_ID,
        "redirect_uri": settings.ML_REDIRECT_URI,
    }
    return redirect(f"{ML_AUTH_URL}?{urlencode(params)}")


@staff_member_required
def callback(request):
    """Recibe el `code` de ML y lo cambia por access_token/refresh_token."""
    code = request.GET.get("code")
    if not code:
        error = request.GET.get("error", "sin código de autorización")
        return HttpResponseBadRequest(f"Error de Mercado Libre: {error}")

    try:
        response = requests.post(
            ML_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.ML_CLIENT_ID,
                "client_secret": settings.ML_CLIENT_SECRET,
                "code": code,
                "redirect_uri": settings.ML_REDIRECT_URI,
            },
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Error intercambiando code por token con ML: %s", exc)
        return HttpResponseBadRequest(f"No se pudo conectar con Mercado Libre: {exc}")

    data = response.json()

    creds = MLCredentials.load()
    creds.ml_user_id = data.get("user_id")
    creds.access_token = data["access_token"]
    creds.refresh_token = data["refresh_token"]
    creds.expires_at = timezone.now() + timezone.timedelta(seconds=data["expires_in"])
    creds.save()

    messages.success(request, "Cuenta de Mercado Libre conectada correctamente.")
    return redirect("admin:mercadolibre_mlcredentials_changelist")
