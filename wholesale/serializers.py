from rest_framework import serializers

from .models import WholesaleLead


class WholesaleLeadSerializer(serializers.ModelSerializer):
    brand = serializers.SlugField(max_length=140, required=False, allow_blank=True)

    class Meta:
        model = WholesaleLead
        fields = ["name", "email", "phone", "city_province", "brand"]
