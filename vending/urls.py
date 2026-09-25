from django.urls import path
from .views import VendingLeadAPIView

urlpatterns = [
    path("leads/", VendingLeadAPIView.as_view(), name="vending-lead"),
]
