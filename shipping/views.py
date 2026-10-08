import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from products.models import Product

from .serializers import ShippingCalculateSerializer
from .services import enviopack
from .services.postal import resolve_provincia_ar
from .services.volumetric import ShipmentItem, calculate_billable_weight

logger = logging.getLogger(__name__)


class ShippingQuoteThrottle(AnonRateThrottle):
    # Se consulta en vivo mientras el usuario completa el checkout (no es un
    # formulario de contacto de baja frecuencia) — throttle más permisivo.
    rate = "30/minute"


def _fallback_quote(postal_code: str) -> dict:
    """Tarifa plana de respaldo cuando Envíopack falla, da timeout, no está
    configurado, o no devuelve ninguna tarifa de los couriers activos.

    Configurable 100% por `SHIPPING_FALLBACK_RATES_JSON` (.env) — nunca
    hardcodeada acá. `zones` es una aproximación por primer dígito del
    código postal (no es una zonificación precisa, ver postal.py), pensada
    solo como red de contención, no como tarifa real de courier.
    """
    rates = settings.SHIPPING_FALLBACK_RATES
    zone_rate = rates.get("zones", {}).get(postal_code[:1]) if postal_code else None
    price = zone_rate if zone_rate is not None else rates.get("default", 0)
    return {
        "carrier": "Tarifa estimada",
        "service": "standard",
        "modality": "domicilio",
        "price": price,
        "delivery_days": None,
        "is_fallback": True,
    }


def _normalize_quotes(raw_quotes: list[dict]) -> list[dict]:
    """Traduce la respuesta cruda de Envíopack a un shape limpio y estable
    para el frontend, filtrando solo los couriers activos configurados en
    `settings.ENVIOPACK_COURIERS` (Correo Argentino / Andreani)."""
    allowed = set(settings.ENVIOPACK_COURIERS)
    normalized = []
    for q in raw_quotes:
        correo = q.get("correo") or {}
        courier_id = correo.get("id", "")
        if allowed and courier_id not in allowed:
            continue

        horas_entrega = q.get("horas_entrega")
        try:
            price = float(q.get("valor", 0))
        except (TypeError, ValueError):
            continue

        normalized.append({
            "carrier": correo.get("nombre", courier_id),
            "service": q.get("servicio"),
            "modality": "sucursal" if q.get("modalidad") == "S" else "domicilio",
            "price": price,
            "delivery_days": round(horas_entrega / 24, 1) if horas_entrega else None,
            "is_fallback": False,
        })
    return normalized


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
        province = serializer.validated_data.get("province") or resolve_provincia_ar(postal_code)
        items_data = serializer.validated_data["items"]

        product_ids = [item["product_id"] for item in items_data]
        products = Product.objects.in_bulk(product_ids)
        missing = [pid for pid in product_ids if pid not in products]
        if missing:
            return Response(
                {"detail": f"Productos inexistentes: {missing}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        shipment_items = []
        package_dims = []
        default_dims = settings.SHIPPING_DEFAULT_ITEM_DIMENSIONS_CM
        for entry in items_data:
            product = products[entry["product_id"]]
            shipment_items.append(ShipmentItem(
                quantity=entry["quantity"],
                weight_kg=product.weight_kg,
                length_cm=product.length_cm,
                width_cm=product.width_cm,
                height_cm=product.height_cm,
            ))
            dims = (
                product.length_cm or default_dims[0],
                product.width_cm or default_dims[1],
                product.height_cm or default_dims[2],
            )
            package_dims.extend([dims] * entry["quantity"])

        billable_weight = calculate_billable_weight(shipment_items)

        quotes = []
        if province:
            raw_quotes = enviopack.get_quotes(
                postal_code=postal_code,
                provincia=province,
                weight_kg=billable_weight,
                package_dims_cm=package_dims,
            )
            if raw_quotes is not None:
                quotes = _normalize_quotes(raw_quotes)
        else:
            logger.info(
                "No se pudo resolver provincia para codigo_postal=%s — se usa tarifa de respaldo",
                postal_code,
            )

        if not quotes:
            quotes = [_fallback_quote(postal_code)]

        return Response({
            "postal_code": postal_code,
            "billable_weight_kg": float(billable_weight),
            "quotes": quotes,
        })
