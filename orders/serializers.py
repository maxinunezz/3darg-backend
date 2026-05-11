from rest_framework import serializers
from .models import Order, OrderItem


class OrderItemSerializer(serializers.ModelSerializer):
    product_slug = serializers.SlugRelatedField(
        source="product", slug_field="slug", read_only=True
    )
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ["id", "product_id", "product_slug", "product_name", "quantity", "unit_price", "subtotal"]


class OrderSerializer(serializers.ModelSerializer):
    brand = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    order_items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "brand",
            "status",
            "status_display",
            "currency",
            "total_amount",
            "order_items",
            "external_reference",
            "customer_email",
            "created_at",
            "updated_at",
        ]


class OrderSummarySerializer(serializers.Serializer):
    total_orders = serializers.IntegerField()
    total_spent = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField()
    orders_by_status = serializers.DictField(child=serializers.IntegerField())
    last_order_at = serializers.DateTimeField(allow_null=True)
