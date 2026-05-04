from django.shortcuts import render
from .models import Product, Category
from .serializers import ProductSerializer, CategorySerializer
from rest_framework import generics

class ProductListAPIView(generics.ListAPIView):
    serializer_class = ProductSerializer

    def get_queryset(self):
        queryset = Product.objects.all()
        # Esto permite que Next.js filtre usando ?is_featured=true
        is_featured = self.request.query_params.get('is_featured')
        if is_featured is not None:
            queryset = queryset.filter(is_featured=(is_featured.lower() == 'true'))
        brand_slug = self.request.query_params.get('brand_slug')
        if brand_slug:
            queryset = queryset.filter(brand__slug=brand_slug)
        return queryset

class CategoryListAPIView(generics.ListAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
