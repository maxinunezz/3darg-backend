from django.urls import path
from .views import BrandListAPIView

urlpatterns = [
    path("", BrandListAPIView.as_view(), name="brand-list"),
]