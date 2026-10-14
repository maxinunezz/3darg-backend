from rest_framework import serializers


class CheckoutItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=999)


class CheckoutProCreateSerializer(serializers.Serializer):
    brand_slug = serializers.CharField()
    customer_email = serializers.EmailField(required=False, allow_blank=True)
    items = CheckoutItemSerializer(many=True)
    # Opcionales: si el comprador los completó en el carrito (ver
    # ShippingEstimator en el frontend), se usan para cotizar el envío real
    # que se cobra en este checkout. Sin código postal, se cobra la tarifa
    # plana de respaldo (`SHIPPING_FALLBACK_RATES_JSON`) salvo que aplique
    # envío gratis — ver `MercadoPagoCheckoutProCreateAPIView`.
    postal_code = serializers.CharField(required=False, allow_blank=True, max_length=10)
    province = serializers.CharField(required=False, allow_blank=True, max_length=2)
    # Id del método elegido en el selector del carrito (ver
    # `shipping/services/quote.py::select_methods()`, ej. "andreani_domicilio").
    # Si no viene o no matchea ninguna cotización vigente, se cae al más
    # barato (`cheapest_price()`), igual que antes de este selector.
    shipping_method_id = serializers.CharField(required=False, allow_blank=True, max_length=40)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Se requiere al menos un ítem.")
        return value
