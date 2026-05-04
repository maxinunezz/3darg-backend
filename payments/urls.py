from django.urls import path
from .views import MercadoPagoCheckoutProCreateAPIView, MercadoPagoWebhookAPIView, PaymentSuccessView

urlpatterns = [
    path("mp/checkout-pro/", MercadoPagoCheckoutProCreateAPIView.as_view(), name="mp-checkout-pro"),
    path("mp/webhook/", MercadoPagoWebhookAPIView.as_view(), name="mp-webhook"),
    path('checkout/success/', PaymentSuccessView.as_view(), name='payment_success'),
]