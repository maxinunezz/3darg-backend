import logging
from decimal import Decimal

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from django.shortcuts import get_object_or_404

from products.models import Product
from products.services.combo_pricing import compute_unit_prices
from brands.models import Brand
from .models import Cart, CartItem
from .serializers import CartSerializer, AddToCartSerializer, CartQuoteSerializer

logger = logging.getLogger(__name__)


def get_or_create_cart(user, brand):
    """Devuelve (o crea) el carrito del usuario para una marca puntual.

    `brand` es obligatorio: cada espacio de marca (3DARG incluida) tiene su
    propio carrito aislado del resto.
    """
    cart, _ = Cart.objects.get_or_create(user=user, brand=brand)
    return cart


def resolve_brand_or_400(brand_slug):
    """Busca la Brand por slug. Devuelve (brand, error_response|None)."""
    if not brand_slug:
        return None, Response(
            {"detail": "brand_slug es obligatorio."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    brand = Brand.objects.filter(slug=brand_slug).first()
    if not brand:
        return None, Response(
            {"detail": f"No existe una marca con slug '{brand_slug}'."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return brand, None


class CartAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        brand, error = resolve_brand_or_400(request.query_params.get("brand_slug"))
        if error:
            return error
        cart = get_or_create_cart(request.user, brand)
        return Response(CartSerializer(cart, context={"request": request}).data)

    def delete(self, request):
        brand, error = resolve_brand_or_400(request.query_params.get("brand_slug"))
        if error:
            return error
        cart = get_or_create_cart(request.user, brand)
        cart.items.all().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CartItemAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AddToCartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        brand, error = resolve_brand_or_400(data.get("brand_slug"))
        if error:
            return error

        product = get_object_or_404(
            Product, id=data["product_id"], is_available=True, is_available_web=True
        )

        # El producto tiene que pertenecer a la marca del carrito al que se
        # está agregando (o no tener marca asignada, caso productos genéricos).
        if product.brand_id and product.brand_id != brand.id:
            return Response(
                {"detail": "Este producto no pertenece a la marca actual."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cart = get_or_create_cart(request.user, brand)

        item, created = CartItem.objects.get_or_create(cart=cart, product=product)
        if not created:
            item.quantity += data["quantity"]
        else:
            item.quantity = data["quantity"]
        item.save()

        logger.info(
            "Item agregado al carrito: user=%s brand=%s product=%s qty=%s",
            request.user.email, brand.slug, product.slug, item.quantity,
        )
        return Response(CartSerializer(cart, context={"request": request}).data, status=status.HTTP_200_OK)

    def patch(self, request, item_id):
        item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        qty = request.data.get("quantity")
        if not qty or int(qty) < 1:
            return Response({"detail": "quantity debe ser >= 1"}, status=status.HTTP_400_BAD_REQUEST)
        item.quantity = int(qty)
        item.save()
        return Response(CartSerializer(item.cart, context={"request": request}).data)

    def delete(self, request, item_id):
        item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CartQuoteThrottle(AnonRateThrottle):
    # Se recalcula en vivo en cada cambio de cantidad del carrito de
    # invitado (ver CartContext.tsx) — throttle más permisivo que un form de
    # baja frecuencia, mismo criterio que ShippingQuoteThrottle.
    rate = "60/minute"


class CartQuoteAPIView(APIView):
    """Cotiza precio con combo de categoría para el carrito de invitado
    (localStorage, sin `Cart` en el servidor) — mismo cálculo
    (`compute_unit_prices`) que usan `CartSerializer` (carrito logueado) y
    `MercadoPagoCheckoutProCreateAPIView` (checkout real), para que el
    subtotal mostrado antes de loguearse/pagar no diverja del que se cobra.
    """

    permission_classes = [AllowAny]
    throttle_classes = [CartQuoteThrottle]

    def post(self, request):
        serializer = CartQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        brand, error = resolve_brand_or_400(data.get("brand_slug"))
        if error:
            return error

        items_data = data["items"]
        product_ids = [it["product_id"] for it in items_data]
        products_by_id = {
            p.id: p
            for p in Product.objects.select_related("category").filter(
                id__in=product_ids, brand=brand, is_available=True, is_available_web=True
            )
        }

        # Los product_id que ya no matcheen (ej. se pausó desde que se agregó
        # al carrito de invitado) se omiten: es un preview de precio, no una
        # mutación — el checkout real vuelve a validar disponibilidad/stock.
        valid_items = [
            (products_by_id[it["product_id"]], it["quantity"])
            for it in items_data
            if it["product_id"] in products_by_id
        ]

        user = request.user if request.user.is_authenticated else None
        unit_prices = compute_unit_prices(user, valid_items)

        items_response = []
        total = Decimal("0")
        for (product, quantity), unit_price in zip(valid_items, unit_prices):
            subtotal = unit_price * quantity
            items_response.append({
                "product_id": product.id,
                "quantity": quantity,
                "unit_price": unit_price,
                "subtotal": subtotal,
            })
            total += subtotal

        return Response({"items": items_response, "total": total})
