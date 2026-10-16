from rest_framework import serializers

from .models import WhatsAppCommunityLead


class WhatsAppCommunityLeadSerializer(serializers.ModelSerializer):
    brand = serializers.SlugField(max_length=140, required=False, allow_blank=True)
    segments = serializers.ListField(
        child=serializers.CharField(max_length=60), required=False, default=list
    )

    class Meta:
        model = WhatsAppCommunityLead
        fields = ["phone", "brand", "segments"]
