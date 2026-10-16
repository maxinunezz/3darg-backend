from django.urls import path

from .views import AgenciesListAPIView, ShippingCalculateAPIView

urlpatterns = [
    path("calculate/", ShippingCalculateAPIView.as_view(), name="shipping-calculate"),
    path("agencies/", AgenciesListAPIView.as_view(), name="shipping-agencies"),
]
