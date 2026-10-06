from django.db import migrations, models


def backfill_sku(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    for product in Product.objects.filter(sku="").order_by("pk"):
        product.sku = f"3DARG-{product.pk:06d}"
        product.save(update_fields=["sku"])


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0007_meta_catalog_fields'),
    ]

    operations = [
        migrations.RunPython(backfill_sku, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name='product',
            name='sku',
            field=models.CharField(blank=True, help_text='Identificador único de catálogo (feeds de Meta/Google). Se autogenera desde el ID si se deja vacío.', max_length=64, unique=True),
        ),
    ]
