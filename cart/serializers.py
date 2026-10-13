from decimal import Decimal

from rest_framework import serializers
from products.serializers import ProductSerializer
from products.services.combo_pricing import compute_unit_prices
from .models import Cart, CartItem


class CartItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    # Precio unitario y subtotal con descuento de socio + bundle del propio
    # producto + combo de categoría (productos DISTINTOS de la misma
    # subcategoría exacta) aplicados. El combo de categoría depende de la
    # cantidad sumada entre varias líneas del carrito, así que no se puede
    # resolver línea por línea acá — `CartSerializer.to_representation()`
    # los calcula TODOS JUNTOS una sola vez por request (`compute_unit_prices`)
    # y los cachea en el contexto compartido, keyed por `CartItem.id`.
    unit_price = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = ["id", "product", "quantity", "unit_price", "subtotal"]

    def _unit_price(self, obj):
        cache = self.context.get("_combo_unit_prices")
        if cache is not None and obj.id in cache:
            return cache[obj.id]
        # Fallback defensivo (no debería pasar si se serializa vía
        # CartSerializer, que siempre precalcula el cache): aísla el
        # cálculo, sin el combo de categoría.
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return obj.product.unit_price_for(user, obj.quantity)

    def get_unit_price(self, obj):
        return self._unit_price(obj)

    def get_subtotal(self, obj):
        return self._unit_price(obj) * obj.quantity


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ["id", "brand", "items", "total", "updated_at"]

    def to_representation(self, instance):
        # El combo de categoría necesita ver TODAS las líneas del carrito a
        # la vez (la cantidad del tramo se suma entre productos distintos
        # de la misma subcategoría) — se calcula una sola vez acá y se
        # cachea en el contexto compartido para que lo lean
        # `CartItemSerializer` (unit_price/subtotal por línea) y
        # `get_total()` sin recalcular ni duplicar la lógica de combo.
        request = self.context.get("request")
        user = getattr(request, "user", None)
        cart_items = list(instance.items.select_related("product__category").all())
        prices = compute_unit_prices(user, [(ci.product, ci.quantity) for ci in cart_items])
        self.context["_combo_unit_prices"] = {
            ci.id: price for ci, price in zip(cart_items, prices)
        }
        self.context["_combo_total"] = sum(
            (price * ci.quantity for ci, price in zip(cart_items, prices)),
            Decimal("0"),
        )
        return super().to_representation(instance)

    def get_total(self, obj):
        total = self.context.get("_combo_total")
        if total is not None:
            return total
        # Fallback defensivo (no debería pasar en uso normal).
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return sum(
            (item.product.unit_price_for(user, item.quantity) * item.quantity for item in obj.items.all()),
            Decimal("0"),
        )


class AddToCartSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, default=1)
    # Obligatorio: cada carrito pertenece a una única marca (ver cart/models.py).
    brand_slug = serializers.CharField()
