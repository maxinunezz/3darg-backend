from django.urls import path
from .views import ProductListAPIView, ProductDetailAPIView, CategoryListAPIView

urlpatterns = [
    path("products/", ProductListAPIView.as_view(), name="product-list"),
    path("products/<slug:slug>/", ProductDetailAPIView.as_view(), name="product-detail"),
    path("categories/", CategoryListAPIView.as_view(), name="category-list"),
]
