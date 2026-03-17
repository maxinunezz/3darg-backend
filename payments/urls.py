from django.urls import path
from .views import MercadoPagoCheckoutProCreateAPIView, MercadoPagoWebhookAPIView

urlpatterns = [
    path("mp/checkout-pro/", MercadoPagoCheckoutProCreateAPIView.as_view(), name="mp-checkout-pro"),
    path("mp/webhook/", MercadoPagoWebhookAPIView.as_view(), name="mp-webhook"),
]