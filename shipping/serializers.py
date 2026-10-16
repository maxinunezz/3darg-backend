from decimal import Decimal

from rest_framework import serializers

from .services.postal import AR_PROVINCES

PROVINCE_CHOICES = [(code, name) for code, name in AR_PROVINCES]


class ShippingItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class ShippingCalculateSerializer(serializers.Serializer):
    # Opcional: si se conoce el código postal de destino (típico del
    # checkout a domicilio; el selector de sucursal no lo pide), `quote.py`
    # intenta cotización EN VIVO contra la API real de Correo Argentino
    # (`POST /rates`) antes de caer a la tabla estática por peso/Valor
    # Declarado. Sin CP (o sin credenciales, o si la consulta falla) se usa
    # directamente la tabla de respaldo — nunca queda sin cotizar.
    postal_code = serializers.CharField(max_length=10, required=False, allow_blank=True, default="")
    items = ShippingItemSerializer(many=True)
    # Opcional: si ya se conoce el subtotal del carrito (con descuentos
    # aplicados), se usa para el cargo por Valor Declarado de Correo
    # Argentino. Si no viene, se infiere del precio de lista de `items`
    # (ver `shipping/services/quote.py::_infer_declared_value`).
    declared_value = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, min_value=Decimal("0"),
    )

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("El carrito está vacío.")
        return value


class ShippingAddressSerializer(serializers.Serializer):
    """No la usa ningún endpoint real — queda como documentación viva de la
    forma del payload de dirección que sí valida `payments.CheckoutProCreateSerializer`
    (campos planos, todos opcionales a este nivel). La validación cruzada real
    vive en `payments/views.py`, que hoy exige:
    - sucursal: `full_name` + `phone` + `province` + `agency_id` — la API
      real de Correo Argentino (API MiCorreo) solo pide el código de la
      sucursal (`shipping.agency`) para esta modalidad, no la dirección
      completa (`shipping.address` solo es obligatoria si `deliveryType !=
      "S"`, ver `correo_argentino.py::_build_shipment_payload()`), así que
      no hace falta que el comprador tipee calle/altura/CP para retirar en
      sucursal.
    - domicilio: `full_name` + `phone` + `street` + `street_number` + `city` +
      `province` (dirección real del comprador, sin `agency_id`).
    """
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=40)
    street = serializers.CharField(max_length=150, required=False, allow_blank=True)
    street_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    floor = serializers.CharField(max_length=20, required=False, allow_blank=True)
    department = serializers.CharField(max_length=20, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    province = serializers.ChoiceField(choices=PROVINCE_CHOICES)
    postal_code = serializers.CharField(max_length=10, required=False, allow_blank=True)
    agency_id = serializers.CharField(max_length=40, required=False, allow_blank=True)
