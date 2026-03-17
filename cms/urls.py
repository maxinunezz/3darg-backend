from django.urls import path
from .views import PageByBrandAndSlugAPIView

urlpatterns = [
    path("pages/<slug:brand_slug>/<slug:page_slug>/", PageByBrandAndSlugAPIView.as_view(), name="cms-page-detail"),
]