import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_decode
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
    has_usable_password = serializers.SerializerMethodField()
    # Solo se pide para confirmar un cambio de email (ver validate()). No es un campo del modelo.
    current_password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = [
            "id", "email", "username", "first_name", "last_name", "phone",
            "registered_brand", "date_joined", "has_usable_password", "current_password",
        ]
        read_only_fields = ["id", "registered_brand", "date_joined", "has_usable_password"]

    def get_has_usable_password(self, obj):
        return obj.has_usable_password()

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("Ya existe una cuenta con ese email.")
        return value

    def validate(self, attrs):
        new_email = attrs.get("email")
        if new_email and new_email != self.instance.email:
            # Las cuentas de Google sin password usable no tienen con qué confirmar
            # (ver GoogleAuthSerializer.create): se deja pasar el cambio sin pedirla.
            if self.instance.has_usable_password():
                current_password = attrs.get("current_password")
                if not current_password or not self.instance.check_password(current_password):
                    raise serializers.ValidationError(
                        {"current_password": "Contraseña actual incorrecta."}
                    )
        attrs.pop("current_password", None)
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    """
    Cambio de password del usuario logueado. Si la cuenta todavía no tiene
    password usable (alta por Google, ver GoogleAuthSerializer.create), no se
    exige current_password — es un alta de password, no un cambio.
    """

    current_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        user = self.context["request"].user
        if user.has_usable_password():
            current_password = attrs.get("current_password")
            if not current_password or not user.check_password(current_password):
                raise serializers.ValidationError(
                    {"current_password": "Contraseña actual incorrecta."}
                )
        return attrs

    def save(self):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """
    Confirma el link de recuperación mandado por PasswordResetRequestView.
    uid/token son los que genera default_token_generator (mismo mecanismo que
    usa el admin de Django) — no hace falta ningún modelo nuevo, el token
    expira solo a los 3 días (PASSWORD_RESET_TIMEOUT, default de Django).
    """

    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        try:
            user = User.objects.get(pk=urlsafe_base64_decode(attrs["uid"]).decode())
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            raise serializers.ValidationError("El link de recuperación no es válido.")
        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError("El link de recuperación no es válido o expiró.")
        self.context["user"] = user
        return attrs

    def save(self):
        user = self.context["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


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
