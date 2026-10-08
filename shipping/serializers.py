from rest_framework import serializers


class ShippingItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class ShippingCalculateSerializer(serializers.Serializer):
    postal_code = serializers.CharField(max_length=10)
    # Opcional: si el checkout ya le pide la provincia al comprador, mandarla
    # acá (ISO 3166-2:AR sin prefijo, ej: "C", "B", "X") evita tener que
    # adivinarla a partir del código postal (ver services/postal.py).
    province = serializers.CharField(max_length=2, required=False, allow_blank=True)
    items = ShippingItemSerializer(many=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("El carrito está vacío.")
        return value
