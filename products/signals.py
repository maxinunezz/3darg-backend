import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from products.models import Product
from products.talles_lumy import es_cortante_lumy, normalizar_talles

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Product)
def completar_talles_cortante_lumy(sender, instance, raw=False, **kwargs):
    """Al crear o guardar un cortante de Lumy, completa los talles que falten
    (Chico/Mediano/Grande, ver products/talles_lumy.py) — así un producto
    nuevo cargado desde el admin ya sale con los tres talles sin cargarlos a
    mano. Nunca rompe el guardado del producto: un error se loguea y listo."""
    if raw:  # loaddata/fixtures: no tocar
        return
    # `Product.save()` guarda dos veces al crear: la primera sin SKU (lo
    # calcula con el pk) y la segunda con el SKU real. Se espera a esa
    # segunda para que los talles hereden el SKU del diseño (ej.
    # LUMY-COR-02-000027-CH) y no uno provisorio.
    if not instance.sku:
        return
    try:
        if es_cortante_lumy(instance):
            normalizar_talles(instance)
    except Exception:
        logger.exception("No se pudieron completar los talles de %s (pk=%s)", instance, instance.pk)
