from rest_framework import serializers
from .models import Product, Category, ProductImage


class CategorySerializer(serializers.ModelSerializer):
    # Info del padre "aplanada" para que el frontend pueda agrupar sin pedidos extra.
    parent_id = serializers.IntegerField(source="parent.id", read_only=True, allow_null=True)
    parent_name = serializers.CharField(source="parent.name", read_only=True, allow_null=True, default=None)
    parent_slug = serializers.CharField(source="parent.slug", read_only=True, allow_null=True, default=None)

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "parent_id", "parent_name", "parent_slug"]


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "order", "alt"]


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    brand = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    # Precio con descuento de socio aplicado (incentivo visible también para anónimos).
    member_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    has_member_discount = serializers.BooleanField(read_only=True)
    # Precio efectivo que paga QUIEN consulta (anónimo = price, socio = member_price).
    final_price = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "slug",
            "sku",
            "description",
            "price",
            "member_price",
            "final_price",
            "members_only",
            "member_discount_percent",
            "has_member_discount",
            "bundle_discounts",
            "stock",
            "is_available",
            "is_featured",
            "category",
            "brand",
            "images",
            "created_at",
        ]

    def get_final_price(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return obj.price_for(user)
