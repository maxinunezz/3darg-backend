"""Remitente de los mails con el nombre de la marca que corresponde.

Antes todos los mails salían con `DEFAULT_FROM_EMAIL` tal cual
("Lumy <noreply@3darg.com>"), así que un pedido de MiniSlam o una consulta de
Print&Gym llegaban firmados por "Lumy". Ahora se respeta la DIRECCIÓN
configurada en `DEFAULT_FROM_EMAIL` (la verificada en Resend, no se toca) y
solo se cambia el NOMBRE visible por el de la marca. Sin marca (ej:
recuperación de contraseña, máquina expendedora) sale como la marca madre.
"""

from email.utils import formataddr, parseaddr

from django.conf import settings

ROOT_BRAND_NAME = "3DARG"


def brand_from_email(brand=None, brand_slug: str = "") -> str:
    """`"<Nombre de marca> <direccion@...>"` para usar como `from_email`.

    Acepta el objeto `Brand` o, si solo se tiene el slug (leads de
    contacto/mayoristas/comunidad), el slug — se resuelve contra la DB.
    Nunca lanza: ante cualquier problema cae al nombre de la marca madre.
    """
    _, address = parseaddr(settings.DEFAULT_FROM_EMAIL)
    if not address:
        return settings.DEFAULT_FROM_EMAIL

    name = ""
    if brand is not None:
        name = getattr(brand, "name", "") or ""
    elif brand_slug:
        try:
            from brands.models import Brand  # import local: evita ciclo de imports entre apps

            found = Brand.objects.filter(slug=brand_slug).only("name").first()
            name = found.name if found else ""
        except Exception:
            name = ""

    return formataddr((name or ROOT_BRAND_NAME, address))
