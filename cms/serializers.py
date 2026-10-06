from rest_framework import serializers
from .models import Page, Section, SectionImage


class SectionImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = SectionImage
        fields = ["id", "key", "image", "alt_text", "order"]


class SectionSerializer(serializers.ModelSerializer):
    images = SectionImageSerializer(many=True, read_only=True)

    class Meta:
        model = Section
        fields = ["id", "type", "order", "data", "images"]


class PageSerializer(serializers.ModelSerializer):
    brand = serializers.CharField(source="brand.slug", read_only=True)
    sections = serializers.SerializerMethodField()

    class Meta:
        model = Page
        fields = ["id", "brand", "slug", "title", "sections"]

    def get_sections(self, obj):
        qs = obj.sections.filter(is_active=True).order_by("order", "id")
        return SectionSerializer(qs, many=True, context=self.context).data
