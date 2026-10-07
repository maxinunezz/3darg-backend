import os
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

from django.db.models import Prefetch
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from .models import Product, Category, ProductImage
from .serializers import ProductSerializer, CategorySerializer
from brands.models import Brand

# Fotos marcadas "Solo Mercado Libre" no se muestran en la web/el feed de Meta-Google.
WEB_IMAGES_PREFETCH = Prefetch("images", queryset=ProductImage.objects.exclude(channel="ml"))


class ProductListAPIView(generics.ListAPIView):
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]
    search_fields = ["name", "description"]
    filterset_fields = ["is_featured", "is_available", "category__slug"]
    ordering_fields = ["name", "price", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        qs = (
            Product.objects.visible_to(self.request.user)
            .prefetch_related(WEB_IMAGES_PREFETCH)
            .select_related("category", "brand")
        )
        brand_slug = self.request.query_params.get("brand_slug")
        if brand_slug:
            qs = qs.filter(brand__slug=brand_slug)
        return qs


class ProductDetailAPIView(generics.RetrieveAPIView):
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"

    def get_queryset(self):
        # Los productos members_only devuelven 404 a anónimos (no se filtran al frontend).
        return (
            Product.objects.visible_to(self.request.user)
            .prefetch_related(WEB_IMAGES_PREFETCH)
            .select_related("category", "brand")
        )


class CategoryListAPIView(generics.ListAPIView):
    serializer_class = CategorySerializer
    permission_classes = [AllowAny]
    # Las categorias alimentan el selector de filtro del shop: se necesitan todas
    # de una, no tiene sentido paginarlas (a diferencia de los productos).
    pagination_class = None

    def get_queryset(self):
        qs = Category.objects.all()
        brand_slug = self.request.query_params.get("brand_slug")
        if brand_slug:
            qs = qs.filter(brand__slug=brand_slug)
        return qs


class ProductFeedAPIView(APIView):
    """
    Feed XML (formato RSS + namespace `g:` de Google Shopping, que Meta
    Commerce Manager también consume) para el catálogo de una marca.

    Meta re-scrapea esta URL periódicamente (Data Feed en Commerce Manager) —
    no requiere push desde nuestro lado. Se registra una vez por marca en
    Commerce Manager → Catálogo → Fuentes de datos → Programado.

    Solo incluye productos públicos: `is_available=True` y `members_only=False`
    (un producto de socios no es una landing válida para tráfico anónimo pago).
    """

    permission_classes = [AllowAny]

    def get(self, request, brand_slug):
        brand = get_object_or_404(Brand, slug=brand_slug, is_active=True)

        products = (
            Product.objects.filter(
                brand=brand,
                is_available=True,
                members_only=False,
            )
            .prefetch_related(WEB_IMAGES_PREFETCH)
            .select_related("category", "brand")
            .order_by("name")
        )

        frontend_base = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")
        currency = os.getenv("MP_CURRENCY", "ARS")

        rss = Element("rss", {
            "version": "2.0",
            "xmlns:g": "http://base.google.com/ns/1.0",
        })
        channel = SubElement(rss, "channel")
        SubElement(channel, "title").text = f"{brand.name} — Catálogo"
        SubElement(channel, "link").text = self._brand_url(frontend_base, brand)
        SubElement(channel, "description").text = brand.short_description or brand.name

        for product in products:
            item = SubElement(channel, "item")
            SubElement(item, "g:id").text = product.sku
            SubElement(item, "g:title").text = product.name
            SubElement(item, "g:description").text = product.description or product.name
            SubElement(item, "g:link").text = self._product_url(frontend_base, brand, product)

            image = product.images.first()
            if image and image.image:
                SubElement(item, "g:image_link").text = request.build_absolute_uri(image.image.url)

            SubElement(item, "g:availability").text = "in stock" if product.stock > 0 else "out of stock"
            SubElement(item, "g:price").text = f"{product.price} {currency}"
            SubElement(item, "g:brand").text = brand.name
            SubElement(item, "g:condition").text = "new"
            if product.google_product_category:
                SubElement(item, "g:google_product_category").text = product.google_product_category

        xml_bytes = tostring(rss, encoding="utf-8")
        pretty_xml = minidom.parseString(xml_bytes).toprettyxml(indent="  ", encoding="utf-8")
        return HttpResponse(pretty_xml, content_type="application/xml")

    @staticmethod
    def _brand_url(frontend_base, brand):
        if brand.parent_id is None:
            return frontend_base
        return f"{frontend_base}/{brand.slug}"

    @staticmethod
    def _product_url(frontend_base, brand, product):
        if brand.parent_id is None:
            return f"{frontend_base}/product/{product.slug}"
        return f"{frontend_base}/{brand.slug}/product/{product.slug}"
