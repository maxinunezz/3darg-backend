import re

from django.conf import settings
from django.contrib.auth import get_user_model
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import serializers
from products.serializers import ProductSerializer
from .models import Favorite

User = get_user_model()


def _generate_username(email):
    """Genera un username único a partir del email (para altas via Google)."""
    base = re.sub(r"[^a-zA-Z0-9_]", "", email.split("@")[0]) or "user"
    username = base
    suffix = 1
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f"{base}{suffix}"
    return username


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


class GoogleAuthSerializer(serializers.Serializer):
    """
    Login/registro con "Continuar con Google". El frontend manda el id_token
    (JWT) que devuelve Google Identity Services; acá lo verificamos contra
    GOOGLE_OAUTH_CLIENT_ID y hacemos get_or_create del User por email.

    Cuenta unificada: no importa desde qué marca se loguee, es el mismo User
    de siempre (ver RegisterSerializer). brand_slug es solo informativo,
    igual que en el registro por password.
    """

    id_token = serializers.CharField(write_only=True)
    brand_slug = serializers.CharField(write_only=True, required=False, allow_blank=True)

    def validate_id_token(self, value):
        if not settings.GOOGLE_OAUTH_CLIENT_ID:
            raise serializers.ValidationError(
                "Login con Google no está configurado en el servidor."
            )
        try:
            payload = google_id_token.verify_oauth2_token(
                value, google_requests.Request(), settings.GOOGLE_OAUTH_CLIENT_ID
            )
        except ValueError:
            raise serializers.ValidationError("Token de Google inválido o expirado.")

        if not payload.get("email"):
            raise serializers.ValidationError("La cuenta de Google no tiene email asociado.")
        if not payload.get("email_verified", False):
            raise serializers.ValidationError("El email de Google no está verificado.")

        self.context["google_payload"] = payload
        return value

    def create(self, validated_data):
        payload = self.context["google_payload"]
        email = payload["email"]
        brand_slug = validated_data.get("brand_slug")

        user = User.objects.filter(email=email).first()
        is_new = user is None

        if is_new:
            user = User.objects.create_user(
                email=email,
                username=_generate_username(email),
                password=None,  # set_password(None) -> set_unusable_password()
                first_name=payload.get("given_name", "")[:150],
                last_name=payload.get("family_name", "")[:150],
            )

        if is_new and brand_slug:
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
