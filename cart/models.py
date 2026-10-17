from django.conf import settings
from django.db import models
from products.models import Product, ProductVariant
from brands.models import Brand


class Cart(models.Model):
    # Un carrito por (usuario, marca): cada espacio de marca (incluida 3DARG
    # como marca madre) tiene su propio carrito, aislado del resto.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="carts",
        on_delete=models.CASCADE,
    )
    brand = models.ForeignKey(
        Brand,
        related_name="carts",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "brand")

    def total(self):
        return sum(item.subtotal() for item in self.items.all())

    def __str__(self):
        return f"Cart de {self.user.email} ({self.brand.slug})"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    # Talle/variante elegida (Fase 2 de ProductVariant) — null = producto sin
    # variantes reales (comportamiento histórico, usa el precio/stock del
    # Product). Dos variantes distintas del mismo producto son líneas
    # separadas del carrito (ver unique_together abajo).
    variant = models.ForeignKey(
        ProductVariant,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cart_items",
    )
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        # No se puede usar unique_together("cart", "product", "variant") a
        # secas: Postgres trata cada NULL como distinto de otro NULL, así
        # que esa constraint no evitaría dos filas (cart, product, NULL)
        # duplicadas para un producto sin variantes reales. Dos constraints
        # condicionales cubren los dos casos sin ese agujero.
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "product", "variant"],
                condition=models.Q(variant__isnull=False),
                name="cart_item_unico_por_variante",
            ),
            models.UniqueConstraint(
                fields=["cart", "product"],
                condition=models.Q(variant__isnull=True),
                name="cart_item_unico_sin_variante",
            ),
        ]

    def subtotal(self):
        price = self.variant.price if self.variant_id else self.product.price
        return price * self.quantity

    def __str__(self):
        talle = f" ({self.variant})" if self.variant_id else ""
        return f"{self.quantity}x {self.product.name}{talle}"
