from rest_framework.generics import ListAPIView
from .models import Brand
from .serializers import BrandSerializer


class BrandListAPIView(ListAPIView):
    serializer_class = BrandSerializer

    def get_queryset(self):
        return Brand.objects.filter(
            parent__isnull=True,
            is_active=True,
            show_in_navbar=True
        ).order_by("navbar_order")