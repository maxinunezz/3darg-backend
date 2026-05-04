from rest_framework import serializers
from .models import Brand, BrandLink

class BrandLinkSerializer(serializers.ModelSerializer):
    """
    Serializer para los links adicionales (Instagram, Tienda, etc.)
    """
    class Meta:
        model = BrandLink
        fields = ["label", "url", "order", "is_active"]

class BrandSerializer(serializers.ModelSerializer):
    """
    Serializer principal para las marcas de 3DARG
    """
    children = serializers.SerializerMethodField()
    links = BrandLinkSerializer(many=True, read_only=True)

    class Meta:
        model = Brand
        fields = [
            "id",
            "name",
            "slug",
            "brand_type",
            "is_active",
            "show_in_navbar",
            "navbar_order",
            "slogan",
            "short_description",
            "description",
            "logo",
            "cover_image",
            "theme",          # Colores y tipografía
            "social_links",   # Redes sociales
            "links",          # Relación con BrandLink
            "children",       # Marcas hijas (MiniSlam, Print & Gym)
            "created_at",
            "updated_at",
        ]

    def get_children(self, obj):
        """
        Recupera de forma recursiva las marcas hijas activas
        """
        children = obj.children.filter(is_active=True)
        return BrandSerializer(children, many=True).data