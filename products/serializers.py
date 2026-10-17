from rest_framework import serializers
from .models import Product, Category, ProductImage, ProductVariant


class CategorySerializer(serializers.ModelSerializer):
    # Info del padre "aplanada" para que el frontend pueda agrupar sin pedidos extra.
    parent_id = serializers.IntegerField(source="parent.id", read_only=True, allow_null=True)
    parent_name = serializers.CharField(source="parent.name", read_only=True, allow_null=True, default=None)
    parent_slug = serializers.CharField(source="parent.slug", read_only=True, allow_null=True, default=None)

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "parent_id", "parent_name", "parent_slug", "bundle_discounts"]


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "order", "alt"]


class ProductVariantSerializer(serializers.ModelSerializer):
    """Talle/variante vendible de un producto (`ProductVariant`) — ver
    `products/models.py` para el detalle de precio/stock propios. Solo se
    exponen variantes `is_available=True` (ver
    `ProductSerializer.get_variants()`): una variante apagada no debe
    ofrecerse para comprar, mismo criterio que `Product.is_available`.
    """

    member_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    has_member_discount = serializers.BooleanField(read_only=True)
    final_price = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = [
            "id", "color", "size", "order", "sku",
            "price", "member_price", "final_price", "has_member_discount",
            "stock",
        ]

    def get_final_price(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return obj.price_for(user)


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    brand = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    # Precio con descuento de socio aplicado (incentivo visible también para anónimos).
    member_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    has_member_discount = serializers.BooleanField(read_only=True)
    # Precio efectivo que paga QUIEN consulta (anónimo = price, socio = member_price).
    final_price = serializers.SerializerMethodField()
    # Talles/variantes con precio y stock propios (ver ProductVariant). Un
    # producto sin variantes "reales" sigue teniendo su variante única de
    # Fase 1 acá — el frontend solo muestra el selector de "Talle" si hay
    # más de una. Ordenadas por `order` (no alfabético: Chico/Mediano/
    # Grande no ordena bien como texto).
    variants = serializers.SerializerMethodField()

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
            "variants",
            "created_at",
        ]

    def get_final_price(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return obj.price_for(user)

    def get_variants(self, obj):
        variants = [v for v in obj.variants.all() if v.is_available]
        variants.sort(key=lambda v: (v.order, v.color, v.size))
        return ProductVariantSerializer(variants, many=True, context=self.context).data
