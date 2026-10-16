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
    # `shipping/services/quote.py::select_methods()`, ej. "correoargentino_domicilio").
    # Si no viene o no matchea ninguna cotización vigente, se cae al más
    # barato (`cheapest_price()`), igual que antes de este selector.
    shipping_method_id = serializers.CharField(required=False, allow_blank=True, max_length=40)

    # Dirección completa del comprador — se exige para los dos métodos de
    # envío (PaqAr v2 la pide siempre, aunque sea "a sucursal", ver CLAUDE.md
    # backend). Opcionales a nivel serializer porque un checkout sin CP/método
    # todavía es válido (cae al fallback plano); la validación cruzada real
    # ("si elegiste sucursal, hace falta agency_id"; "si elegiste domicilio,
    # hace falta la dirección completa") la hace la vista, una vez que sabe
    # qué método se eligió.
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=40)
    street = serializers.CharField(required=False, allow_blank=True, max_length=150)
    street_number = serializers.CharField(required=False, allow_blank=True, max_length=20)
    floor = serializers.CharField(required=False, allow_blank=True, max_length=20)
    department = serializers.CharField(required=False, allow_blank=True, max_length=20)
    city = serializers.CharField(required=False, allow_blank=True, max_length=100)
    agency_id = serializers.CharField(required=False, allow_blank=True, max_length=40)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Se requiere al menos un ítem.")
        return value
