from django.urls import path
from .views import CartAPIView, CartItemAPIView, CartQuoteAPIView

urlpatterns = [
    path("", CartAPIView.as_view(), name="cart"),
    path("items/", CartItemAPIView.as_view(), name="cart-item-add"),
    path("items/<int:item_id>/", CartItemAPIView.as_view(), name="cart-item-detail"),
    path("quote/", CartQuoteAPIView.as_view(), name="cart-quote"),
]
