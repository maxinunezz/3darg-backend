# Cambios de esquema propiamente dichos, separados del backfill de datos
# (0003_cart_por_marca) porque Postgres no permite un ALTER TABLE en la misma
# transacción que un UPDATE/DELETE con triggers de FK pendientes
# ("cannot ALTER TABLE because it has pending trigger events").

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("cart", "0003_cart_por_marca"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cart",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="carts",
                to="users.user",
            ),
        ),
        migrations.AlterField(
            model_name="cart",
            name="brand",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="carts",
                to="brands.brand",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="cart",
            unique_together={("user", "brand")},
        ),
    ]
