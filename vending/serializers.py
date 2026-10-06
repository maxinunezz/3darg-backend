from rest_framework import serializers
from .models import VendingLead


class VendingLeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = VendingLead
        fields = ["nombre", "email", "telefono", "segmento", "mensaje"]
