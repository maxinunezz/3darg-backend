from django.urls import path
from .views import (
    MercadoPagoCheckoutProCreateAPIView,
    MercadoPagoWebhookAPIView,
    OrderLookupAPIView,
    OrderReconcileAPIView,
    PaymentSuccessView,
    TransferAvailabilityAPIView,
    TransferCheckoutCreateAPIView,
    TransferReceiptUploadAPIView,
)

urlpatterns = [
    path("mp/checkout-pro/", MercadoPagoCheckoutProCreateAPIView.as_view(), name="mp-checkout-pro"),
    path("mp/webhook/", MercadoPagoWebhookAPIView.as_view(), name="mp-webhook"),
    path("orders/<uuid:order_id>/reconcile/", OrderReconcileAPIView.as_view(), name="mp-order-reconcile"),
    path("orders/lookup/", OrderLookupAPIView.as_view(), name="order-lookup"),
    path("transfer/checkout/", TransferCheckoutCreateAPIView.as_view(), name="transfer-checkout"),
    path("transfer/availability/", TransferAvailabilityAPIView.as_view(), name="transfer-availability"),
    path(
        "orders/<uuid:order_id>/transfer-receipt/",
        TransferReceiptUploadAPIView.as_view(),
        name="transfer-receipt-upload",
    ),
    path('checkout/success/', PaymentSuccessView.as_view(), name='payment_success'),
]