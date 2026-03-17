from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import NotFound
from .models import Page
from .serializers import PageSerializer


class PageByBrandAndSlugAPIView(APIView):
    def get(self, request, brand_slug, page_slug):
        page = (
            Page.objects.select_related("brand")
            .filter(brand__slug=brand_slug, slug=page_slug, is_published=True)
            .first()
        )

        if not page:
            raise NotFound("Page not found")

        return Response(PageSerializer(page).data)