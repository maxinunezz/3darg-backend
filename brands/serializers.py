from rest_framework import serializers
from .models import Brand


class BrandSerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = Brand
        fields = [
            "id",
            "name",
            "slug",
            "brand_type",
            "slogan",
            "logo",
            "navbar_order",
            "children",
        ]

    def get_children(self, obj):
        children = obj.children.filter(is_active=True)
        return BrandSerializer(children, many=True).data