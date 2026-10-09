from django.urls import path
from .views import (
    ProductListAPIView,
    ProductDetailAPIView,
    CategoryListAPIView,
    ProductFeedAPIView,
    CosteoSyncAPIView,
)

urlpatterns = [
    path("products/feed/<slug:brand_slug>/", ProductFeedAPIView.as_view(), name="product-feed"),
    path("products/costeo-sync/", CosteoSyncAPIView.as_view(), name="product-costeo-sync"),
    path("products/", ProductListAPIView.as_view(), name="product-list"),
    path("products/<slug:slug>/", ProductDetailAPIView.as_view(), name="product-detail"),
    path("categories/", CategoryListAPIView.as_view(), name="category-list"),
]
