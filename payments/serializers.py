# payments/serializers.py
from rest_framework import serializers

class CheckoutProCreateSerializer(serializers.Serializer):
    brand_slug = serializers.CharField()
    customer_email = serializers.EmailField(required=False, allow_blank=True)
    items = serializers.ListField(
        child=serializers.DictField(), # Esto permite que pase cualquier objeto en la lista
        min_length=1
    )