from rest_framework import generics
from rest_framework.permissions import AllowAny
from .models import Product, Category
from .serializers import ProductSerializer, CategorySerializer


class ProductListAPIView(generics.ListAPIView):
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]
    search_fields = ["name", "description"]
    filterset_fields = ["is_featured", "is_available", "category__slug"]
    ordering_fields = ["name", "price", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        qs = Product.objects.prefetch_related("images").select_related("category", "brand")
        brand_slug = self.request.query_params.get("brand_slug")
        if brand_slug:
            qs = qs.filter(brand__slug=brand_slug)
        return qs


class ProductDetailAPIView(generics.RetrieveAPIView):
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"
    queryset = Product.objects.prefetch_related("images").select_related("category", "brand")


class CategoryListAPIView(generics.ListAPIView):
    serializer_class = CategorySerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        qs = Category.objects.all()
        brand_slug = self.request.query_params.get("brand_slug")
        if brand_slug:
            qs = qs.filter(brand__slug=brand_slug)
        return qs
