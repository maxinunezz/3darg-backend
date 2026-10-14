from django.urls import path

from .views import WholesaleLeadAPIView

urlpatterns = [
    path("leads/", WholesaleLeadAPIView.as_view(), name="wholesale-lead"),
]
