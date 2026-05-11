from rest_framework import serializers


class CheckoutItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=999)


class CheckoutProCreateSerializer(serializers.Serializer):
    brand_slug = serializers.CharField()
    customer_email = serializers.EmailField(required=False, allow_blank=True)
    items = CheckoutItemSerializer(many=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Se requiere al menos un ítem.")
        return value
