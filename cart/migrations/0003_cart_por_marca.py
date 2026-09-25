# Migración manual: pasa Cart de "un carrito por usuario" a "un carrito por
# (usuario, marca)". Cada espacio de marca (3DARG incluida) queda con su
# propio carrito, aislado del resto.
#
# Backfill: antes de volver `brand` no-nullable, a todo Cart con brand=null
# se le asigna la marca raíz (slug="3darg"). Si eso genera un choque con la
# futura unique_together (user, brand) porque el usuario ya tenía OTRO cart
# con brand=3darg, se fusionan (merge) los CartItem al carrito que sobrevive
# y se borra el duplicado, sumando cantidades si el mismo producto está en
# ambos.
#
# Nota: es un merge best-effort pensado para el dataset chico de desarrollo.
# En un dataset grande con conflictos de stock/precio entre carritos
# duplicados convendría revisar el resultado a mano antes de confirmar en
# producción — la migración no falla en ningún caso, en el peor caso deja
# cantidades sumadas que el usuario puede ajustar desde el carrito.

from django.db import migrations


def backfill_brand_and_merge_duplicates(apps, schema_editor):
    Cart = apps.get_model("cart", "Cart")
    CartItem = apps.get_model("cart", "CartItem")
    Brand = apps.get_model("brands", "Brand")

    root_brand = Brand.objects.filter(slug="3darg").first()
    if root_brand is None:
        # No debería pasar en un dataset real, pero si no existe la marca raíz
        # no hay a quién asignarle los carritos huérfanos: no rompemos la
        # migración, simplemente no hay nada para backfillear.
        return

    for cart in Cart.objects.filter(brand__isnull=True):
        existing = (
            Cart.objects.filter(user_id=cart.user_id, brand_id=root_brand.id)
            .exclude(id=cart.id)
            .first()
        )
        if existing is None:
            cart.brand_id = root_brand.id
            cart.save(update_fields=["brand"])
            continue

        # Ya existe un carrito de esta marca para el usuario: fusionamos los
        # items de `cart` (sin marca) en `existing` y borramos `cart`.
        for item in CartItem.objects.filter(cart_id=cart.id):
            target_item = CartItem.objects.filter(
                cart_id=existing.id, product_id=item.product_id
            ).first()
            if target_item is not None:
                target_item.quantity += item.quantity
                target_item.save(update_fields=["quantity"])
                item.delete()
            else:
                item.cart_id = existing.id
                item.save(update_fields=["cart"])
        cart.delete()


def noop_reverse(apps, schema_editor):
    # No hay forma razonable de deshacer el merge de carritos duplicados;
    # dejamos el reverse como no-op (dev only).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("cart", "0002_initial"),
        ("brands", "0001_initial"),
        ("users", "0003_favorite"),
    ]

    operations = [
        migrations.RunPython(backfill_brand_and_merge_duplicates, noop_reverse),
    ]
