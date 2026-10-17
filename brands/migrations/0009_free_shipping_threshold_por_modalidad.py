# Generated manually (mismo patrón que 0008_cart_discount_config_por_cantidad.py)

from django.db import migrations, models


def dividir_umbral_por_modalidad(apps, schema_editor):
    """El umbral de envío gratis era único (`free_shipping_threshold`), sin
    distinguir sucursal/domicilio. Ahora hay dos umbrales independientes
    (`free_shipping_threshold_sucursal` / `_domicilio`) porque cada
    modalidad tiene un costo real distinto de Correo Argentino. No hay forma
    de derivar dos números distintos del único valor que había cargado, así
    que se copia el mismo valor a las dos claves nuevas — el dueño ajusta
    después cada una por separado desde el admin si quiere diferenciarlas."""
    Brand = apps.get_model("brands", "Brand")
    for brand in Brand.objects.exclude(shipping_config={}):
        config = brand.shipping_config or {}
        old_value = config.get("free_shipping_threshold")
        if old_value is None:
            continue
        new_config = {k: v for k, v in config.items() if k != "free_shipping_threshold"}
        new_config.setdefault("free_shipping_threshold_sucursal", old_value)
        new_config.setdefault("free_shipping_threshold_domicilio", old_value)
        brand.shipping_config = new_config
        brand.save(update_fields=["shipping_config"])


class Migration(migrations.Migration):

    dependencies = [
        ('brands', '0008_cart_discount_config_por_cantidad'),
    ]

    operations = [
        migrations.AlterField(
            model_name='brand',
            name='shipping_config',
            field=models.JSONField(blank=True, default=dict, help_text='Configuración de envío por marca. Claves disponibles: free_shipping_threshold_sucursal / free_shipping_threshold_domicilio (monto a partir del cual el envío de esa modalidad es gratis; vacío o 0 = sin envío gratis para esa modalidad).'),
        ),
        migrations.RunPython(dividir_umbral_por_modalidad, migrations.RunPython.noop),
    ]
