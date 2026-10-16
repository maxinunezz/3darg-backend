from django.urls import path

from .views import WhatsAppCommunityLeadAPIView

urlpatterns = [
    path("leads/", WhatsAppCommunityLeadAPIView.as_view(), name="whatsapp-community-lead"),
]
