from django.urls import path
from .views import OrderDetailAPIView, OrderListAPIView, OrderSummaryAPIView

urlpatterns = [
    path("", OrderListAPIView.as_view(), name="order-list"),
    path("summary/", OrderSummaryAPIView.as_view(), name="order-summary"),
    path("<uuid:id>/", OrderDetailAPIView.as_view(), name="order-detail"),
]
