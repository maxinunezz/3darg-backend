from decimal import Decimal

from rest_framework import serializers
from products.serializers import ProductSerializer, ProductVariantSerializer
from products.services.combo_pricing import compute_unit_prices
from .models import Cart, CartItem
from .services.cart_discount import compute_cart_pricing


class CartItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    variant = ProductVariantSerializer(read_only=True)
    # Precio unitario y subtotal con descuento de socio + descuento por
    # cantidad total de unidades del carrito ya aplicados (mismo % en
    # todas las líneas, ver `Brand.cart_discount_config`). Depende de la
    # cantidad de TODO el carrito, así que no se puede resolver línea por
    # línea acá —
    # `CartSerializer.to_representation()` lo calcula una sola vez
    # (`compute_cart_pricing`) y lo cachea en el contexto compartido,
    # keyed por `CartItem.id`.
    unit_price = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = ["id", "product", "variant", "quantity", "unit_price", "subtotal"]

    def _unit_price(self, obj):
        cache = self.context.get("_cart_unit_prices")
        if cache is not None and obj.id in cache:
            return cache[obj.id]
        # Fallback defensivo (no debería pasar si se serializa vía
        # CartSerializer, que siempre precalcula el cache): precio de
        # lista/socio sin el descuento por cantidad del carrito.
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if obj.variant_id:
            return obj.variant.price_for(user)
        return obj.product.price_for(user)

    def get_unit_price(self, obj):
        return self._unit_price(obj)

    def get_subtotal(self, obj):
        return self._unit_price(obj) * obj.quantity


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    subtotal = serializers.SerializerMethodField()
    discount_percent = serializers.SerializerMethodField()
    discount_amount = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    discount_progress = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = [
            "id", "brand", "items",
            "subtotal", "discount_percent", "discount_amount", "total",
            "discount_progress", "updated_at",
        ]

    def to_representation(self, instance):
        # Se calcula UNA sola vez por request y se cachea en el contexto
        # compartido para que lo lean `CartItemSerializer` (unit_price/
        # subtotal por línea) y los demás SerializerMethodField de acá
        # abajo, sin recalcular ni duplicar la lógica de descuento.
        request = self.context.get("request")
        user = getattr(request, "user", None)
        cart_items = list(
            instance.items.select_related("product__category", "variant").all()
        )
        list_prices = compute_unit_prices(
            user, [(ci.product, ci.quantity, ci.variant) for ci in cart_items]
        )
        lines = [(price, ci.quantity) for ci, price in zip(cart_items, list_prices)]
        pricing = compute_cart_pricing(instance.brand, lines)
        self.context["_cart_pricing"] = pricing
        self.context["_cart_unit_prices"] = {
            ci.id: unit_price
            for ci, unit_price in zip(cart_items, pricing["discounted_unit_prices"])
        }
        return super().to_representation(instance)

    def _pricing(self, obj):
        pricing = self.context.get("_cart_pricing")
        if pricing is not None:
            return pricing
        # Fallback defensivo (no debería pasar en uso normal).
        request = self.context.get("request")
        user = getattr(request, "user", None)
        lines = [
            (
                item.variant.price_for(user) if item.variant_id else item.product.price_for(user),
                item.quantity,
            )
            for item in obj.items.all()
        ]
        return compute_cart_pricing(obj.brand, lines)

    def get_subtotal(self, obj):
        return self._pricing(obj)["raw_subtotal"]

    def get_discount_percent(self, obj):
        return self._pricing(obj)["discount_percent"]

    def get_discount_amount(self, obj):
        return self._pricing(obj)["discount_amount"]

    def get_total(self, obj):
        return self._pricing(obj)["total"]

    def get_discount_progress(self, obj):
        return self._pricing(obj)["progress"]


class AddToCartSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    # Opcional: solo se manda si el producto tiene talles/variantes reales
    # cargadas (ver `ProductSerializer.variants`). `None`/ausente = producto
    # sin variantes, comportamiento histórico.
    variant_id = serializers.IntegerField(required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=1, default=1)
    # Obligatorio: cada carrito pertenece a una única marca (ver cart/models.py).
    brand_slug = serializers.CharField()


class CartQuoteItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    variant_id = serializers.IntegerField(required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=1)


class CartQuoteSerializer(serializers.Serializer):
    # Cotiza precio con combo para el carrito de invitado (localStorage, sin
    # `Cart` en el servidor) — ver CartQuoteAPIView. Mismo criterio de
    # validación que ShippingCalculateSerializer (shipping/serializers.py).
    brand_slug = serializers.CharField()
    items = CartQuoteItemSerializer(many=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("El carrito está vacío.")
        return value
