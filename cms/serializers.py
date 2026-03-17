from rest_framework import serializers
from .models import Page, Section


class SectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Section
        fields = ["id", "type", "order", "data"]


class PageSerializer(serializers.ModelSerializer):
    brand = serializers.CharField(source="brand.slug", read_only=True)
    sections = serializers.SerializerMethodField()

    class Meta:
        model = Page
        fields = ["id", "brand", "slug", "title", "sections"]

    def get_sections(self, obj):
        qs = obj.sections.filter(is_active=True).order_by("order", "id")
        return SectionSerializer(qs, many=True).data