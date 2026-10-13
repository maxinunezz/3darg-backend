from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from products.models import Product

from .serializers import ShippingCalculateSerializer
from .services.quote import get_quotes


class ShippingQuoteThrottle(AnonRateThrottle):
    # Se consulta en vivo mientras el usuario completa el checkout (no es un
    # formulario de contacto de baja frecuencia) — throttle más permisivo.
    rate = "30/minute"


class ShippingCalculateAPIView(APIView):
    # AllowAny: el checkout permite comprar como invitado (ver regla de
    # negocio #2 en CLAUDE.md), así que cotizar envío tampoco puede exigir login.
    permission_classes = [AllowAny]
    throttle_classes = [ShippingQuoteThrottle]

    def post(self, request):
        serializer = ShippingCalculateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        postal_code = serializer.validated_data["postal_code"]
        province = serializer.validated_data.get("province") or None
        items_data = serializer.validated_data["items"]

        product_ids = [item["product_id"] for item in items_data]
        products = Product.objects.in_bulk(product_ids)
        missing = [pid for pid in product_ids if pid not in products]
        if missing:
            return Response(
                {"detail": f"Productos inexistentes: {missing}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        items = [(products[entry["product_id"]], entry["quantity"]) for entry in items_data]
        result = get_quotes(postal_code=postal_code, province=province, items=items)
        return Response(result)
