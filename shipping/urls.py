from django.urls import path

from .views import ShippingCalculateAPIView

urlpatterns = [
    path("calculate/", ShippingCalculateAPIView.as_view(), name="shipping-calculate"),
]
