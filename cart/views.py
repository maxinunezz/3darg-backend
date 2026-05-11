import logging
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from products.models import Product
from brands.models import Brand
from .models import Cart, CartItem
from .serializers import CartSerializer, AddToCartSerializer

logger = logging.getLogger(__name__)


def get_or_create_cart(user):
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart


class CartAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        cart = get_or_create_cart(request.user)
        return Response(CartSerializer(cart).data)

    def delete(self, request):
        cart = get_or_create_cart(request.user)
        cart.items.all().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CartItemAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AddToCartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        product = get_object_or_404(Product, id=data["product_id"], is_available=True)
        cart = get_or_create_cart(request.user)

        if data.get("brand_slug") and not cart.brand:
            brand = Brand.objects.filter(slug=data["brand_slug"]).first()
            if brand:
                cart.brand = brand
                cart.save(update_fields=["brand"])

        item, created = CartItem.objects.get_or_create(cart=cart, product=product)
        if not created:
            item.quantity += data["quantity"]
        else:
            item.quantity = data["quantity"]
        item.save()

        logger.info("Item agregado al carrito: user=%s product=%s qty=%s", request.user.email, product.slug, item.quantity)
        return Response(CartSerializer(cart).data, status=status.HTTP_200_OK)

    def patch(self, request, item_id):
        cart = get_or_create_cart(request.user)
        item = get_object_or_404(CartItem, id=item_id, cart=cart)
        qty = request.data.get("quantity")
        if not qty or int(qty) < 1:
            return Response({"detail": "quantity debe ser >= 1"}, status=status.HTTP_400_BAD_REQUEST)
        item.quantity = int(qty)
        item.save()
        return Response(CartSerializer(cart).data)

    def delete(self, request, item_id):
        cart = get_or_create_cart(request.user)
        item = get_object_or_404(CartItem, id=item_id, cart=cart)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
