import logging

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class ResendAPIEmailBackend(BaseEmailBackend):
    """Manda mails vía la API HTTP de Resend (no SMTP).

    Railway bloquea el tráfico saliente por los puertos SMTP (confirmado:
    timeout real al conectar a smtp.resend.com:587 desde el container) —
    la API HTTP de Resend corre sobre 443, que sí está abierto, así que
    evita el problema de raíz en vez de depender de que el hosting abra
    el puerto. Usa `EMAIL_HOST_PASSWORD` como API key, igual que el backend
    SMTP que reemplaza, para no tener que tocar el resto del `.env`.
    """

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        api_key = getattr(settings, "EMAIL_HOST_PASSWORD", "")
        if not api_key:
            if not self.fail_silently:
                raise ValueError("Falta EMAIL_HOST_PASSWORD (API key de Resend)")
            return 0

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        sent = 0
        for message in email_messages:
            payload = {
                "from": message.from_email,
                "to": message.to,
                "subject": message.subject,
                "text": message.body,
            }
            if message.cc:
                payload["cc"] = message.cc
            if message.bcc:
                payload["bcc"] = message.bcc
            if message.reply_to:
                payload["reply_to"] = message.reply_to

            for content, mimetype in getattr(message, "alternatives", []):
                if mimetype == "text/html":
                    payload["html"] = content
                    break

            try:
                response = requests.post(RESEND_API_URL, json=payload, headers=headers, timeout=10)
                response.raise_for_status()
                sent += 1
            except requests.RequestException:
                logger.error("Error enviando email vía Resend API", exc_info=True)
                if not self.fail_silently:
                    raise
        return sent
