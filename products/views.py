import logging
import os
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

from django.db.models import Prefetch
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Product, Category, ProductImage, CostTemplate, ProductVariant
from .serializers import ProductSerializer, CategorySerializer
from brands.models import Brand
from mercadolibre.services import MLSyncError, sync_product

logger = logging.getLogger(__name__)

# Fotos marcadas "Solo Mercado Libre" no se muestran en la web/el feed de Meta-Google.
WEB_IMAGES_PREFETCH = Prefetch("images", queryset=ProductImage.objects.exclude(channel="ml"))


class ProductListAPIView(generics.ListAPIView):
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]
    search_fields = ["name", "description"]
    # "category__slug" NO va en filterset_fields a propósito: django-filter solo
    # sabe hacer match exacto, y necesitamos que una categoría raíz con
    # subcategorías (Cortantes, Rodillos Texturizadores) traiga también los
    # productos de sus hijas (ver "Todos" más abajo) — se resuelve a mano en
    # get_queryset().
    filterset_fields = ["is_featured", "is_available"]
    ordering_fields = ["name", "price", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        qs = (
            Product.objects.visible_to(self.request.user)
            .filter(is_available=True, is_available_web=True)
            .prefetch_related(WEB_IMAGES_PREFETCH)
            .select_related("category", "brand")
        )
        brand_slug = self.request.query_params.get("brand_slug")
        if brand_slug:
            qs = qs.filter(brand__slug=brand_slug)

        category_slug = self.request.query_params.get("category__slug")
        if category_slug:
            category = Category.objects.filter(slug=category_slug).first()
            if category is None:
                return qs.none()
            if category.parent_id is None:
                # Categoría raíz (ej: Cortantes) con subcategorías temáticas +
                # "Todos"/"Sets" (ver products/admin.py::_GroupedCategoryIterator) —
                # el link "Todos" del sidebar apunta acá (al slug de la raíz, no al
                # de la subcategoría "Todos") y debe traer TODOS los productos de
                # la raíz y de cada una de sus hijas, no solo los suyos propios
                # (casi nunca hay productos colgados directo de la raíz).
                category_ids = [category.id, *category.children.values_list("id", flat=True)]
                qs = qs.filter(category_id__in=category_ids)
            else:
                qs = qs.filter(category_id=category.id)
        return qs


class ProductDetailAPIView(generics.RetrieveAPIView):
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"

    def get_queryset(self):
        # Los productos members_only devuelven 404 a anónimos (no se filtran al
        # frontend). Los apagados puntualmente en el canal web (is_available_web)
        # o en general (is_available) también devuelven 404 — mismo criterio.
        return (
            Product.objects.visible_to(self.request.user)
            .filter(is_available=True, is_available_web=True)
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

    Solo incluye productos públicos: `is_available=True`, `is_available_web=True`
    y `members_only=False` (un producto de socios no es una landing válida para
    tráfico anónimo pago; uno apagado puntualmente en el canal web tampoco
    debería traer tráfico pago a una página que ya no se muestra).
    """

    permission_classes = [AllowAny]

    def get(self, request, brand_slug):
        brand = get_object_or_404(Brand, slug=brand_slug, is_active=True)

        products = (
            Product.objects.filter(
                brand=brand,
                is_available=True,
                is_available_web=True,
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


# Campos de medidas que presupuestos3d puede mandar junto con el precio — se
# aplican SOLO si vienen en el payload (si un campo no viene, el producto
# conserva el valor que ya tenía; no se pisa con null).
_MEASUREMENT_FIELDS = ("weight_kg", "length_cm", "width_cm", "height_cm")


class CosteoSyncAPIView(APIView):
    """
    POST /api/products/costeo-sync/

    La invoca `presupuestos3d` (`config/api_3darg.py::sync_costeo_ecommerce()`)
    cuando se guarda un `Producto` de costeo marcado `es_producto_ecommerce=True`
    — ese `Producto` representa un PRESUPUESTO de costeo compartido por muchos
    diseños distintos del catálogo (ej: "Cortante 4cm", "Shaker grande"), no
    un producto puntual. Por eso esta vista no toca `Product`/`ProductVariant`
    por nombre ni por tag: hace upsert de un `CostTemplate` por `external_ref`
    (referencia estable que no cambia si renombran el presupuesto allá) y
    propaga el precio/medidas nuevos a TODAS las `ProductVariant` que ya
    estén vinculadas a ese template — vínculo que se arma a mano, por
    producto, desde el admin de 3darg-backend (`ProductVariant.cost_template`).

    Payload esperado (JSON):
      - `external_ref` (obligatorio): referencia estable del `Producto` de
        costeo en presupuestos3d (ej: `"presupuestos3d:42"`). Es la clave de
        upsert del `CostTemplate` — no el nombre, que puede cambiar.
      - `nombre` (obligatorio): nombre a mostrar del template (se actualiza
        en cada sync, así un rename en presupuestos3d se refleja acá).
      - `sale_price` (obligatorio): precio de venta a propagar a las
        variantes vinculadas.
      - `weight_kg`/`length_cm`/`width_cm`/`height_cm` (opcionales): si no
        vienen, no se tocan (no se asume que faltan = "borrar medida").

    A propósito NO se tocan `category`/`sku`/`ml_category_id` de ningún
    `Product` — esos son del diseño puntual, no del template compartido, y
    pisarlos en bloque rompería el catálogo. Tampoco crea `Product`/
    `ProductVariant` nuevos: solo actualiza las variantes que ya están
    vinculadas al template (si todavía no hay ninguna, `actualizados` da 0 —
    es esperable para un template recién creado hasta que alguien lo asigne
    desde el admin).

    Fase 1: cada `ProductVariant` corresponde 1:1 a un `Product` (ver
    migración `0035_migrar_productos_a_variantes_y_costtemplate`), y nada del
    checkout/Mercado Libre/el feed lee `ProductVariant` todavía — por eso acá
    se actualiza la variante Y el `Product` subyacente en el mismo golpe,
    para que el precio nuevo tenga efecto real hoy mismo. Cuando el catálogo
    tenga variantes de verdad (fases siguientes), este espejo deja de hacer
    falta.

    Si algún `Product` afectado tiene `is_available_ml=True`, además se
    vuelve a publicar en Mercado Libre (`sync_product()`) para que el precio
    y las medidas nuevas lleguen a la publicación real sin acción manual —
    los errores de un producto puntual (ej: le faltan fotos) no frenan al
    resto del lote, se devuelven en `ml_errores`.

    Auth: `TokenAuthentication` con el token de la cuenta de integración
    dedicada (usuario staff `integracion_presupuestos3d`, ver
    `CLAUDE.md` para cómo generarlo) + `IsAdminUser` — mismo criterio que
    usa `presupuestos3d` para sus propios endpoints de integración.
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAdminUser]

    def post(self, request, *args, **kwargs):
        external_ref = request.data.get("external_ref")
        if not external_ref:
            return Response(
                {"error": "external_ref es obligatorio."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        nombre = request.data.get("nombre")
        if not nombre:
            return Response(
                {"error": "nombre es obligatorio."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sale_price_raw = request.data.get("sale_price")
        try:
            sale_price = Decimal(str(sale_price_raw))
        except (InvalidOperation, TypeError):
            return Response(
                {"error": "sale_price es obligatorio y tiene que ser numérico."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        measurement_updates = {}
        for field in _MEASUREMENT_FIELDS:
            raw = request.data.get(field)
            if raw is None or raw == "":
                continue
            try:
                measurement_updates[field] = Decimal(str(raw))
            except InvalidOperation:
                return Response(
                    {"error": f"{field} tiene que ser numérico."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        template, _created = CostTemplate.objects.update_or_create(
            external_ref=external_ref,
            defaults={"nombre": nombre, "sale_price": sale_price, **measurement_updates},
        )

        variant_qs = ProductVariant.objects.filter(cost_template=template)
        product_ids = list(variant_qs.values_list("product_id", flat=True).distinct())
        if not product_ids:
            return Response({"actualizados": 0, "ml_republicados": 0, "ml_errores": []})

        variant_update_kwargs = {"price": sale_price, **measurement_updates}
        variant_qs.update(**variant_update_kwargs)

        product_update_kwargs = {"price": sale_price, **measurement_updates}
        Product.objects.filter(pk__in=product_ids).update(**product_update_kwargs)

        ml_ok = []
        ml_errores = []
        for product in Product.objects.filter(pk__in=product_ids, is_available_ml=True):
            try:
                sync_product(product)
                ml_ok.append(product.sku)
            except MLSyncError as exc:
                ml_errores.append({"sku": product.sku, "error": str(exc)})
            except Exception:
                logger.exception(
                    "Error inesperado republicando en Mercado Libre tras sync de costeo (sku=%s)",
                    product.sku,
                )
                ml_errores.append({"sku": product.sku, "error": "Error inesperado, ver logs del servidor."})

        return Response({
            "actualizados": len(product_ids),
            "ml_republicados": len(ml_ok),
            "ml_errores": ml_errores,
        })
