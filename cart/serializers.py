from decimal import Decimal

from rest_framework import serializers
from products.serializers import ProductSerializer
from .models import Cart, CartItem


class CartItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    # Precio unitario y subtotal con descuento de socio + descuento por volumen
    # (bundle_discounts) aplicados — unit_price_for() combina ambos (el dueño
    # del cart siempre está autenticado, así que ya parte de member_price).
    unit_price = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = ["id", "product", "quantity", "unit_price", "subtotal"]

    def _user(self):
        request = self.context.get("request")
        return getattr(request, "user", None)

    def get_unit_price(self, obj):
        return obj.product.unit_price_for(self._user(), obj.quantity)

    def get_subtotal(self, obj):
        return obj.product.unit_price_for(self._user(), obj.quantity) * obj.quantity


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ["id", "brand", "items", "total", "updated_at"]

    def get_total(self, obj):
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
