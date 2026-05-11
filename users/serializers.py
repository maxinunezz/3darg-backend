from django.contrib.auth import get_user_model
from rest_framework import serializers
from products.serializers import ProductSerializer
from .models import Favorite

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    brand_slug = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ["email", "username", "password", "phone", "brand_slug"]

    def create(self, validated_data):
        brand_slug = validated_data.pop("brand_slug", None)

        user = User.objects.create_user(
            email=validated_data["email"],
            username=validated_data.get("username", validated_data["email"]),
            password=validated_data["password"],
            phone=validated_data.get("phone", ""),
        )

        if brand_slug:
            from brands.models import Brand
            brand = Brand.objects.filter(slug=brand_slug, is_active=True).first()
            if brand:
                user.registered_brand = brand
                user.save(update_fields=["registered_brand"])

        return user


class UserSerializer(serializers.ModelSerializer):
    registered_brand = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "username", "phone", "registered_brand", "date_joined"]
        read_only_fields = ["id", "registered_brand", "date_joined"]


class FavoriteSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    product_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = Favorite
        fields = ["id", "product", "product_id", "created_at"]

    def validate_product_id(self, value):
        from products.models import Product
        if not Product.objects.filter(id=value).exists():
            raise serializers.ValidationError("Producto no encontrado.")
        return value

    def create(self, validated_data):
        user = self.context["request"].user
        product_id = validated_data["product_id"]
        favorite, _ = Favorite.objects.get_or_create(user=user, product_id=product_id)
        return favorite
