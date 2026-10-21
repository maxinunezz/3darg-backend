import os
import uuid
import logging
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image, UnidentifiedImageError
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.throttling import SimpleRateThrottle
from django.views.generic import TemplateView
from django.shortcuts import get_object_or_404
from django.http import Http404

from brands.models import Brand
from orders.models import Order, OrderItem
from products.models import Product, ProductVariant
from products.services.combo_pricing import compute_unit_prices
from cart.services.cart_discount import compute_cart_pricing
from shipping.services.quote import cheapest_price, get_quotes, select_methods
from .models import MercadoPagoPayment
from .serializers import CheckoutProCreateSerializer, TransferCheckoutCreateSerializer
from .services.mercadopago import create_preference, get_payment, is_valid_webhook_signature
from .services.reconciliation import apply_payment_status, reconcile_order
from .services.transfer_discount import apply_transfer_discount
from .services.transfer_notifications import (
    reference_code,
    send_transfer_instructions_email,
    send_transfer_pending_owner_email,
    send_transfer_receipt_uploaded_email,
)

logger = logging.getLogger(__name__)


class CheckoutThrottle(SimpleRateThrottle):
    """Throttle propio del checkout, por IP — a diferencia de
    `AnonRateThrottle` (que no throttlea nada si `request.user` está
    autenticado, ver `get_cache_key` de DRF), este endpoint acepta compra de
    invitado Y de usuario logueado por igual (ver CLAUDE.md, regla 2), así
    que hay que limitarlo por IP sin importar la sesión — sin esto, el único
    límite real era el genérico `user: 50000/day` (`DEFAULT_THROTTLE_RATES`),
    que no frena nada flasheando creación de `Order`s/llamadas a MercadoPago
    desde una cuenta logueada. Mismo patrón que `ContactThrottle`/
    `VendingLeadThrottle`, pero sin el bypass de `AnonRateThrottle`."""

    scope = "checkout"
    rate = "20/hour"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class MercadoPagoCheckoutProCreateAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [CheckoutThrottle]

    @transaction.atomic
    def post(self, request):
        # Chequeo ANTES de crear nada en la base: un `return Response(...)`
        # normal dentro de un bloque `@transaction.atomic` NO hace rollback
        # (Django solo revierte ante una excepción no manejada que se
        # propague fuera del bloque) — antes este chequeo vivía más abajo,
        # después de `Order.objects.create()`/`OrderItem.objects.bulk_create()`,
        # así que si faltaba `MP_NOTIFICATION_URL` la vista devolvía 500 pero
        # la `Order` (con sus `OrderItem`) quedaba creada y confirmada en la
        # base igual — una orden huérfana, sin preferencia de pago ni forma
        # de que el comprador la pague. Resolver esto antes de tocar la base
        # evita depender de las reglas de rollback de `atomic`.
        notification_url = os.getenv("MP_NOTIFICATION_URL", "").strip()
        if not notification_url:
            return Response(
                {"detail": "MP_NOTIFICATION_URL no está configurado"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        serializer = CheckoutProCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        brand = Brand.objects.filter(slug=data["brand_slug"], is_active=True).first()
        if not brand:
            return Response({"detail": "Brand not found"}, status=status.HTTP_404_NOT_FOUND)

        if brand.brand_type == "services":
            return Response(
                {"detail": "This brand is services-only. No checkout available."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user if request.user.is_authenticated else None

        items_data = data["items"]
        product_ids = [it["product_id"] for it in items_data]

        products_qs = Product.objects.select_related("category").filter(
            id__in=product_ids,
            brand=brand,
            is_available=True,
            is_available_web=True,
        )
        products_by_id = {p.id: p for p in products_qs}

        missing = [pid for pid in product_ids if pid not in products_by_id]
        if missing:
            return Response(
                {"detail": f"Producto(s) no disponible(s): {missing}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Talles/variantes (Fase 2 de ProductVariant): se resuelven todas
        # juntas, validando que cada `variant_id` pertenezca al producto que
        # dice acompañar y esté activa — mismo criterio que `cart/views.py`.
        variant_ids = [it["variant_id"] for it in items_data if it.get("variant_id")]
        variants_by_id = {
            v.id: v
            for v in ProductVariant.objects.filter(
                id__in=variant_ids, product_id__in=product_ids, is_available=True
            )
        }
        missing_variants = [
            it["variant_id"] for it in items_data
            if it.get("variant_id") and it["variant_id"] not in variants_by_id
        ]
        if missing_variants:
            return Response(
                {"detail": f"Talle(s) no disponible(s): {missing_variants}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        variants_for_item = {
            it["product_id"]: variants_by_id.get(it["variant_id"])
            for it in items_data
            if it.get("variant_id")
        }

        # Los productos members_only solo pueden comprarlos usuarios con cuenta.
        members_only = [p.name for p in products_by_id.values() if p.members_only]
        if members_only and user is None:
            return Response(
                {"detail": f"Necesitás una cuenta para comprar: {', '.join(members_only)}"},
                status=status.HTTP_403_FORBIDDEN,
            )

        stock_errors = []
        for it in items_data:
            product = products_by_id[it["product_id"]]
            variant = variants_by_id.get(it.get("variant_id"))
            available_stock = variant.stock if variant is not None else product.stock
            if available_stock < it["quantity"]:
                label = f"{product.name} ({variant.label})" if variant is not None else product.name
                stock_errors.append(
                    f"'{label}': stock insuficiente ({available_stock} disponible(s))"
                )
        if stock_errors:
            return Response(
                {"detail": "; ".join(stock_errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Se resuelven TODOS los precios juntos en una sola pasada: el
        # descuento por CANTIDAD TOTAL de unidades del carrito
        # (`Brand.cart_discount_config`, ver `cart/services/cart_discount.py`)
        # depende de la cantidad de TODO el pedido, no se puede calcular
        # línea por línea. Mismo mecanismo
        # que usa el cart (`cart/serializers.py`/`CartQuoteAPIView`), para
        # que el precio cobrado en checkout sea exactamente el que se vio en
        # el carrito. Si el item trae `variant_id`, el precio sale de la
        # variante (talle), no del producto.
        list_prices = compute_unit_prices(
            user,
            [
                (
                    products_by_id[it["product_id"]],
                    it["quantity"],
                    variants_by_id.get(it.get("variant_id")),
                )
                for it in items_data
            ],
        )
        lines = [
            (price, it["quantity"]) for it, price in zip(items_data, list_prices)
        ]
        pricing = compute_cart_pricing(brand, lines)
        unit_prices = pricing["discounted_unit_prices"]

        items_for_mp = []
        for it, unit_price in zip(items_data, unit_prices):
            product = products_by_id[it["product_id"]]
            variant = variants_by_id.get(it.get("variant_id"))
            qty = it["quantity"]
            title = f"{product.name} ({variant.label})" if variant is not None else product.name
            items_for_mp.append({
                "title": title,
                "quantity": qty,
                "unit_price": float(unit_price),
            })
        # `subtotal` ya incluye el descuento por monto aplicado — el umbral
        # de envío gratis se evalúa contra lo que el cliente efectivamente
        # paga, no contra el monto de lista.
        subtotal = pricing["total"]

        # Costo de envío: se cobra siempre, salvo que la marca tenga un
        # umbral de envío gratis para la modalidad elegida
        # (`Brand.shipping_config.free_shipping_threshold_sucursal` /
        # `_domicilio` — separados porque cada modalidad tiene un costo real
        # distinto, no tiene sentido un único umbral para las dos) y el
        # subtotal lo alcance. Mismo mecanismo de cotización
        # (`shipping.services.quote`) que usa el preview del carrito
        # (`/api/shipping/calculate/`), para que lo que se cobra acá sea
        # consistente con lo que se mostró antes de pagar.
        postal_code = (data.get("postal_code") or "").strip()
        province = (data.get("province") or "").strip()
        # `CheckoutProCreateSerializer.shipping_method_id` ya es un
        # `ChoiceField` que solo acepta "correoargentino_sucursal"/
        # "correoargentino_domicilio" — `serializer.is_valid(raise_exception=True)`
        # más arriba ya rechazó con 400 cualquier otro valor (vacío
        # incluido). Por eso `shipping_method`/`shipping_modality` se pueden
        # derivar ACÁ, una sola vez, y quedan garantizados para las dos
        # ramas de abajo (gratis y pagado) — antes se derivaban "si vino
        # `shipping_method_id`" en la rama gratis y "si matcheó una
        # cotización" en la pagada, así que un valor vacío o inválido
        # dejaba `shipping_method`/`shipping_modality` en `""` en cualquiera
        # de las dos ramas y esquivaba por completo la validación de
        # dirección de más abajo (bug real: permitía cobrar envío gratis —o
        # el más barato— sin pedir nunca la dirección ni la sucursal).
        shipping_method_id = data["shipping_method_id"]
        shipping_method, _, shipping_modality = shipping_method_id.partition("_")
        free_shipping_threshold = (brand.shipping_config or {}).get(
            f"free_shipping_threshold_{shipping_modality}"
        )
        if free_shipping_threshold and subtotal >= Decimal(str(free_shipping_threshold)):
            shipping_cost = Decimal("0")
        else:
            # `get_quotes()` intenta cotización EN VIVO contra la API real de
            # Correo Argentino (`POST /rates`) cuando se conoce `postal_code`
            # de destino y hay credenciales cargadas; si no (sin CP, sin
            # credenciales, o falla la consulta), cae a la tabla estática por
            # peso/Valor Declarado (ver `quote.py`) — nunca deja un método sin
            # cotizar. Se calcula siempre, se haya mandado CP o no. Se cobra
            # el precio de la cotización que matchea el método elegido; si
            # por algún motivo no matcheara ninguna (no debería pasar, ya que
            # `select_methods()` siempre devuelve las dos entradas posibles),
            # se cae al más barato como resguardo, sin dejar de exigir la
            # dirección/sucursal correspondiente más abajo.
            shipping_items = [(products_by_id[it["product_id"]], it["quantity"]) for it in items_data]
            quote_result = get_quotes(
                postal_code=postal_code,
                items=shipping_items,
                declared_value=subtotal,
            )
            methods = select_methods(quote_result["quotes"])
            selected = next((m for m in methods if m["id"] == shipping_method_id), None)
            if selected:
                shipping_cost = Decimal(str(selected["price"]))
            else:
                shipping_cost = cheapest_price(quote_result["quotes"])

        # Dirección del comprador — la API real de Correo Argentino (API
        # MiCorreo) NO exige la misma cosa para las dos modalidades: en
        # sucursal solo pide `agency` (código de la sucursal elegida, ver
        # `correo_argentino.py::_build_shipment_payload()`), la dirección
        # completa NO es obligatoria (`shipping.address` solo se exige si
        # `deliveryType != "S"`); en domicilio sí hace falta la dirección
        # completa del comprador. `shipping_method`/`shipping_modality` ya
        # están garantizados (ver arriba), así que esta validación corre
        # siempre, sin importar si la cotización en vivo matcheó o cayó al
        # fallback más barato.
        address_fields = {
            "shipping_full_name": (data.get("full_name") or "").strip(),
            "shipping_phone": (data.get("phone") or "").strip(),
            "shipping_street": (data.get("street") or "").strip(),
            "shipping_street_number": (data.get("street_number") or "").strip(),
            "shipping_floor": (data.get("floor") or "").strip(),
            "shipping_department": (data.get("department") or "").strip(),
            "shipping_city": (data.get("city") or "").strip(),
            "shipping_province": province,
            "shipping_agency_id": (data.get("agency_id") or "").strip(),
        }
        if shipping_method == "correoargentino" and shipping_modality == "sucursal":
            missing_contact = [
                field for field in ("shipping_full_name", "shipping_phone")
                if not address_fields[field]
            ]
            if missing_contact or not province:
                return Response(
                    {"detail": "Falta completar nombre, teléfono y provincia para retirar en sucursal."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not address_fields["shipping_agency_id"]:
                return Response(
                    {"detail": "Falta elegir una sucursal de Correo Argentino."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif shipping_method == "correoargentino" and shipping_modality == "domicilio":
            missing_address = [
                field for field in ("shipping_street", "shipping_street_number", "shipping_city")
                if not address_fields[field]
            ]
            if missing_address or not province:
                return Response(
                    {"detail": "Falta completar la dirección para el envío a domicilio."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if shipping_cost > 0:
            items_for_mp.append({
                "title": "Envío",
                "quantity": 1,
                "unit_price": float(shipping_cost),
            })

        total = subtotal + shipping_cost

        external_reference = uuid.uuid4().hex

        order = Order.objects.create(
            brand=brand,
            user=request.user if request.user.is_authenticated else None,
            status=Order.Status.PENDING,
            currency=os.getenv("MP_CURRENCY", "ARS"),
            total_amount=total,
            shipping_cost=shipping_cost,
            shipping_postal_code=postal_code,
            shipping_method=shipping_method,
            shipping_modality=shipping_modality,
            **address_fields,
            external_reference=external_reference,
            customer_email=(
                data.get("customer_email", "")
                or (request.user.email if request.user.is_authenticated else "")
            ),
        )

        order_items = [
            OrderItem(
                order=order,
                product=products_by_id[it["product_id"]],
                product_name=products_by_id[it["product_id"]].name,
                variant=variants_by_id.get(it.get("variant_id")),
                variant_label=(
                    variants_by_id[it["variant_id"]].label
                    if it.get("variant_id") in variants_by_id
                    else ""
                ),
                quantity=it["quantity"],
                unit_price=unit_price,
            )
            for it, unit_price in zip(items_data, unit_prices)
        ]
        OrderItem.objects.bulk_create(order_items)

        # `notification_url` ya se validó al principio de la vista, antes de
        # crear la `Order` — ver comentario ahí.
        # `brand` viaja como query param para que la página de éxito (que vive
        # en la ruta raíz `/checkout/success`, compartida por todas las
        # marcas) sepa a qué espacio de marca volver — sin esto, "Ver mis
        # pedidos"/"Seguir comprando" mandaban siempre a 3DARG sin importar
        # desde qué sub-marca se compró (ver mismo fix en
        # `TransferCheckoutCreateAPIView`/`checkout/transfer`).
        frontend_base = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")
        back_urls = {
            "success": f"{frontend_base}/checkout/success/?order_id={order.id}&brand={brand.slug}",
            "failure": f"{frontend_base}/checkout/failure/?order_id={order.id}&brand={brand.slug}",
            "pending": f"{frontend_base}/checkout/pending/?order_id={order.id}&brand={brand.slug}",
        }

        pref = create_preference(
            items=items_for_mp,
            external_reference=external_reference,
            notification_url=notification_url,
            back_urls=back_urls,
        )

        mp_payment = MercadoPagoPayment.objects.create(
            order=order,
            preference_id=str(pref.get("id", "")),
            init_point=str(pref.get("init_point", "")),
            sandbox_init_point=str(pref.get("sandbox_init_point", "")),
            status=MercadoPagoPayment.Status.PENDING,
            raw={"preference": pref},
        )

        logger.info("Checkout creado: order=%s brand=%s total=%s", order.id, brand.slug, total)

        return Response(
            {
                "order_id": str(order.id),
                "preference_id": mp_payment.preference_id,
                "init_point": mp_payment.init_point,
                "sandbox_init_point": mp_payment.sandbox_init_point,
            },
            status=status.HTTP_201_CREATED,
        )


class TransferCheckoutCreateAPIView(APIView):
    """Checkout por transferencia bancaria manual ("Opción 1") — alternativa
    a `MercadoPagoCheckoutProCreateAPIView` para quien prefiere pagar por
    transferencia (y, si la marca tiene `transfer_discount_percent`
    cargado, pagar más barato por elegir este canal). Mismo contrato de
    entrada (serializer, validación de stock/dirección/envío) que el
    checkout de MP — lo que cambia es qué pasa después de crear la `Order`:
    no se llama a ninguna API de pago, se manda por mail el alias/CBU y el
    dueño confirma el ingreso a mano desde el admin
    (`orders/admin.py::confirmar_transferencia_recibida`, que reusa el
    signal existente de `orders/signals.py` sin duplicar nada de esa
    lógica).

    Stock: igual criterio que MercadoPago — se VALIDA (no se reserva) acá,
    recién se descuenta cuando la orden pasa a `PAID` (vía el signal). Un
    pedido PENDING por transferencia que nunca se confirma y se cancela
    (a mano o por `expire_pending_transfers`) no necesita restituir nada,
    porque nunca se descontó.
    """
    permission_classes = [AllowAny]
    throttle_classes = [CheckoutThrottle]

    @transaction.atomic
    def post(self, request):
        # Mismo criterio "vacío = apagado" que el resto de las
        # integraciones: sin cuenta bancaria configurada, este canal no
        # existe — chequeado ANTES de tocar la base, mismo motivo que el
        # chequeo de `MP_NOTIFICATION_URL` en el checkout de MP (evitar una
        # `Order` huérfana si `@transaction.atomic` no hace rollback de un
        # `return` normal).
        if not settings.TRANSFER_BANK_ALIAS or not settings.TRANSFER_BANK_CBU:
            return Response(
                {"detail": "El pago por transferencia no está disponible todavía."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = TransferCheckoutCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        brand = Brand.objects.filter(slug=data["brand_slug"], is_active=True).first()
        if not brand:
            return Response({"detail": "Brand not found"}, status=status.HTTP_404_NOT_FOUND)

        if brand.brand_type == "services":
            return Response(
                {"detail": "This brand is services-only. No checkout available."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user if request.user.is_authenticated else None

        items_data = data["items"]
        product_ids = [it["product_id"] for it in items_data]

        products_qs = Product.objects.select_related("category").filter(
            id__in=product_ids,
            brand=brand,
            is_available=True,
            is_available_web=True,
        )
        products_by_id = {p.id: p for p in products_qs}

        missing = [pid for pid in product_ids if pid not in products_by_id]
        if missing:
            return Response(
                {"detail": f"Producto(s) no disponible(s): {missing}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        variant_ids = [it["variant_id"] for it in items_data if it.get("variant_id")]
        variants_by_id = {
            v.id: v
            for v in ProductVariant.objects.filter(
                id__in=variant_ids, product_id__in=product_ids, is_available=True
            )
        }
        missing_variants = [
            it["variant_id"] for it in items_data
            if it.get("variant_id") and it["variant_id"] not in variants_by_id
        ]
        if missing_variants:
            return Response(
                {"detail": f"Talle(s) no disponible(s): {missing_variants}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        members_only = [p.name for p in products_by_id.values() if p.members_only]
        if members_only and user is None:
            return Response(
                {"detail": f"Necesitás una cuenta para comprar: {', '.join(members_only)}"},
                status=status.HTTP_403_FORBIDDEN,
            )

        stock_errors = []
        for it in items_data:
            product = products_by_id[it["product_id"]]
            variant = variants_by_id.get(it.get("variant_id"))
            available_stock = variant.stock if variant is not None else product.stock
            if available_stock < it["quantity"]:
                label = f"{product.name} ({variant.label})" if variant is not None else product.name
                stock_errors.append(
                    f"'{label}': stock insuficiente ({available_stock} disponible(s))"
                )
        if stock_errors:
            return Response(
                {"detail": "; ".join(stock_errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        list_prices = compute_unit_prices(
            user,
            [
                (
                    products_by_id[it["product_id"]],
                    it["quantity"],
                    variants_by_id.get(it.get("variant_id")),
                )
                for it in items_data
            ],
        )
        lines = [
            (price, it["quantity"]) for it, price in zip(items_data, list_prices)
        ]
        pricing = compute_cart_pricing(brand, lines)
        # El umbral de envío gratis (más abajo) se evalúa contra ESTE
        # subtotal (descuento por cantidad, sin el de transferencia todavía)
        # — decisión explícita: elegir transferencia no debería hacer
        # perder el envío gratis que ya se había alcanzado. El descuento de
        # transferencia se aplica después, solo sobre lo que efectivamente
        # se cobra.
        subtotal_before_transfer_discount = pricing["total"]
        pricing = apply_transfer_discount(brand, pricing)
        unit_prices = pricing["discounted_unit_prices"]
        subtotal = pricing["total"]

        postal_code = (data.get("postal_code") or "").strip()
        province = (data.get("province") or "").strip()
        shipping_method_id = data["shipping_method_id"]
        shipping_method, _, shipping_modality = shipping_method_id.partition("_")
        free_shipping_threshold = (brand.shipping_config or {}).get(
            f"free_shipping_threshold_{shipping_modality}"
        )
        if free_shipping_threshold and subtotal_before_transfer_discount >= Decimal(str(free_shipping_threshold)):
            shipping_cost = Decimal("0")
        else:
            shipping_items = [(products_by_id[it["product_id"]], it["quantity"]) for it in items_data]
            quote_result = get_quotes(
                postal_code=postal_code,
                items=shipping_items,
                declared_value=subtotal,
            )
            methods = select_methods(quote_result["quotes"])
            selected = next((m for m in methods if m["id"] == shipping_method_id), None)
            if selected:
                shipping_cost = Decimal(str(selected["price"]))
            else:
                shipping_cost = cheapest_price(quote_result["quotes"])

        address_fields = {
            "shipping_full_name": (data.get("full_name") or "").strip(),
            "shipping_phone": (data.get("phone") or "").strip(),
            "shipping_street": (data.get("street") or "").strip(),
            "shipping_street_number": (data.get("street_number") or "").strip(),
            "shipping_floor": (data.get("floor") or "").strip(),
            "shipping_department": (data.get("department") or "").strip(),
            "shipping_city": (data.get("city") or "").strip(),
            "shipping_province": province,
            "shipping_agency_id": (data.get("agency_id") or "").strip(),
        }
        if shipping_method == "correoargentino" and shipping_modality == "sucursal":
            missing_contact = [
                field for field in ("shipping_full_name", "shipping_phone")
                if not address_fields[field]
            ]
            if missing_contact or not province:
                return Response(
                    {"detail": "Falta completar nombre, teléfono y provincia para retirar en sucursal."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not address_fields["shipping_agency_id"]:
                return Response(
                    {"detail": "Falta elegir una sucursal de Correo Argentino."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif shipping_method == "correoargentino" and shipping_modality == "domicilio":
            missing_address = [
                field for field in ("shipping_street", "shipping_street_number", "shipping_city")
                if not address_fields[field]
            ]
            if missing_address or not province:
                return Response(
                    {"detail": "Falta completar la dirección para el envío a domicilio."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        total = subtotal + shipping_cost
        external_reference = uuid.uuid4().hex

        order = Order.objects.create(
            brand=brand,
            user=request.user if request.user.is_authenticated else None,
            status=Order.Status.PENDING,
            payment_channel=Order.PaymentChannel.TRANSFER,
            transfer_discount_percent_applied=pricing["transfer_discount_percent"],
            currency=os.getenv("MP_CURRENCY", "ARS"),
            total_amount=total,
            shipping_cost=shipping_cost,
            shipping_postal_code=postal_code,
            shipping_method=shipping_method,
            shipping_modality=shipping_modality,
            **address_fields,
            external_reference=external_reference,
            customer_email=(
                data.get("customer_email", "")
                or (request.user.email if request.user.is_authenticated else "")
            ),
        )

        order_items = [
            OrderItem(
                order=order,
                product=products_by_id[it["product_id"]],
                product_name=products_by_id[it["product_id"]].name,
                variant=variants_by_id.get(it.get("variant_id")),
                variant_label=(
                    variants_by_id[it["variant_id"]].label
                    if it.get("variant_id") in variants_by_id
                    else ""
                ),
                quantity=it["quantity"],
                unit_price=unit_price,
            )
            for it, unit_price in zip(items_data, unit_prices)
        ]
        OrderItem.objects.bulk_create(order_items)

        logger.info(
            "Checkout por transferencia creado: order=%s brand=%s total=%s descuento=%s%%",
            order.id, brand.slug, total, pricing["transfer_discount_percent"],
        )

        send_transfer_instructions_email(order)
        send_transfer_pending_owner_email(order)

        return Response(
            {
                "order_id": str(order.id),
                "reference": reference_code(order),
                "total_amount": str(order.total_amount),
                "currency": order.currency,
                "transfer_discount_percent": pricing["transfer_discount_percent"],
                "expires_in_hours": settings.TRANSFER_PENDING_EXPIRATION_HOURS,
                "bank": {
                    "alias": settings.TRANSFER_BANK_ALIAS,
                    "cbu": settings.TRANSFER_BANK_CBU,
                    "holder_name": settings.TRANSFER_BANK_HOLDER_NAME,
                    "cuit": settings.TRANSFER_BANK_CUIT,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class TransferAvailabilityAPIView(APIView):
    """`GET /api/payments/transfer/availability/` — le dice al frontend si
    el canal "Transferencia" existe hoy, SIN exponer ningún dato de cuenta
    (alias/CBU reales solo se devuelven al confirmarse el checkout, ver
    `TransferCheckoutCreateAPIView`). Mismo chequeo "vacío = apagado" que
    usa `TransferCheckoutCreateAPIView` antes de crear la orden — así el
    selector de forma de pago del carrito (`cart-page-content.tsx`,
    `site/cart-content.tsx`) puede ocultar la opción en vez de dejar que el
    comprador la elija y recién se entere con un 400 al confirmar el pedido.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        available = bool(settings.TRANSFER_BANK_ALIAS and settings.TRANSFER_BANK_CBU)
        return Response({"available": available})


class TransferReceiptThrottle(SimpleRateThrottle):
    """Por IP, igual criterio que `CheckoutThrottle` — subir un comprobante
    no requiere sesión (puede ser compra de invitado), así que no alcanza
    con el throttle genérico por usuario."""

    scope = "transfer_receipt"
    rate = "10/hour"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


_TRANSFER_RECEIPT_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
_TRANSFER_RECEIPT_ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/webp", "application/pdf",
}


def _compress_receipt_image(file_obj):
    """Redimensiona (si excede `TRANSFER_RECEIPT_MAX_DIMENSION` de lado más
    largo) y reencodea a JPEG calidad `TRANSFER_RECEIPT_JPEG_QUALITY` — una
    foto de celular de 4-8MB suele bajar a bien por debajo de 1MB sin perder
    legibilidad. Devuelve un `ContentFile` listo para asignar al `FileField`.
    Los PDF no pasan por acá (Pillow no puede "comprimir" un PDF) — se
    guardan tal cual, el cap de tamaño es la única defensa para ese caso."""
    image = Image.open(file_obj)
    # Corrige la orientación real de fotos de celular (EXIF) antes de
    # redimensionar/guardar — si no, algunas fotos sacadas en vertical
    # quedan guardadas "giradas" al perder el metadata EXIF en el proceso.
    try:
        from PIL import ImageOps
        image = ImageOps.exif_transpose(image)
    except Exception:
        pass
    image = image.convert("RGB")

    max_dim = settings.TRANSFER_RECEIPT_MAX_DIMENSION
    if max(image.width, image.height) > max_dim:
        image.thumbnail((max_dim, max_dim), Image.LANCZOS)

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=settings.TRANSFER_RECEIPT_JPEG_QUALITY)
    return ContentFile(buffer.getvalue(), name="comprobante.jpg")


class TransferReceiptUploadAPIView(APIView):
    """`POST /api/payments/orders/<uuid:order_id>/transfer-receipt/` — el
    comprador sube una foto o PDF del comprobante desde la pantalla de
    "pedido pendiente de transferencia" (`/checkout/transfer`), para que el
    dueño pueda verificarlo antes de confirmar el pago a mano desde el
    admin (ver CLAUDE.md → "Flujo de pagos — Transferencia bancaria").

    `AllowAny` (igual criterio que el resto de este canal: compra de
    invitado soportada). Re-subir REEMPLAZA el comprobante anterior — no se
    guarda historial de versiones, decisión explícita del dueño.
    """
    permission_classes = [AllowAny]
    throttle_classes = [TransferReceiptThrottle]

    def post(self, request, order_id):
        order = get_object_or_404(Order, id=order_id)

        if order.payment_channel != Order.PaymentChannel.TRANSFER:
            return Response(
                {"detail": "Este pedido no es de pago por transferencia."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if order.status != Order.Status.PENDING:
            return Response(
                {"detail": "Este pedido ya no está pendiente de pago, no se puede subir un comprobante nuevo."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded = request.FILES.get("receipt")
        if not uploaded:
            return Response(
                {"detail": "Falta el archivo del comprobante."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        extension = os.path.splitext(uploaded.name or "")[1].lower()
        content_type = (uploaded.content_type or "").lower()
        if (
            extension not in _TRANSFER_RECEIPT_ALLOWED_EXTENSIONS
            or content_type not in _TRANSFER_RECEIPT_ALLOWED_CONTENT_TYPES
        ):
            return Response(
                {"detail": "Formato no permitido. Subí una imagen (JPG, PNG, WEBP) o un PDF."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if uploaded.size > settings.MAX_TRANSFER_RECEIPT_BYTES:
            max_mb = settings.MAX_TRANSFER_RECEIPT_BYTES // (1024 * 1024)
            return Response(
                {"detail": f"El archivo es muy grande (máx. {max_mb}MB)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        is_pdf = extension == ".pdf" or content_type == "application/pdf"
        if is_pdf:
            file_to_save = uploaded
        else:
            try:
                file_to_save = _compress_receipt_image(uploaded)
            except (UnidentifiedImageError, OSError):
                return Response(
                    {"detail": "No se pudo leer la imagen. Probá con otra foto."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Guardamos el nombre del comprobante viejo (si hay) ANTES de tocar
        # nada — lo borramos del storage recién después de confirmar que el
        # nuevo se guardó bien. Si borráramos primero y el guardado nuevo
        # fallara (ver try/except abajo: el storage activo puede rechazar el
        # archivo en ese momento, ej. Cloudinary con `BadRequest: Invalid PDF
        # file` ante un PDF corrupto, aunque haya pasado la validación de
        # extensión/content-type de arriba), se perdería el comprobante
        # válido anterior sin ganar uno nuevo a cambio.
        old_receipt_name = order.transfer_receipt.name if order.transfer_receipt else None

        filename = f"comprobante_{order.id}{extension if is_pdf else '.jpg'}"
        try:
            order.transfer_receipt.save(filename, file_to_save, save=False)
        except Exception as e:
            logger.error(
                "Error guardando comprobante de transferencia de la orden %s: %s", order.id, e
            )
            return Response(
                {"detail": "No pudimos guardar el comprobante. Probá con otro archivo o más tarde."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.transfer_receipt_uploaded_at = timezone.now()
        order.save(update_fields=["transfer_receipt", "transfer_receipt_uploaded_at"])

        if old_receipt_name:
            try:
                order.transfer_receipt.storage.delete(old_receipt_name)
            except Exception as e:
                logger.error(
                    "Error borrando comprobante viejo de la orden %s: %s", order.id, e
                )

        receipt_url = request.build_absolute_uri(order.transfer_receipt.url)
        try:
            send_transfer_receipt_uploaded_email(order, receipt_url)
        except Exception as e:
            logger.error(
                "Error enviando aviso de comprobante subido para orden %s: %s", order.id, e
            )

        return Response(
            {
                "uploaded": True,
                "receipt_url": receipt_url,
                "uploaded_at": order.transfer_receipt_uploaded_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )


class MercadoPagoWebhookAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        payment_id = (
            request.GET.get("data.id")
            or request.data.get("data", {}).get("id")
            or request.GET.get("id")
        )
        topic = (
            request.GET.get("type")
            or request.GET.get("topic")
            or request.data.get("type")
        )

        logger.info("Webhook recibido: topic=%s id=%s", topic, payment_id)

        if topic not in ["payment", "opened_dispute", "dispute"]:
            return Response({"ok": True, "detail": f"Topic {topic} ignored"}, status=status.HTTP_200_OK)

        if not payment_id:
            return Response({"error": "No payment ID found"}, status=status.HTTP_400_BAD_REQUEST)

        if not is_valid_webhook_signature(request):
            logger.warning("Webhook rechazado: firma inválida para payment_id=%s", payment_id)
            return Response({"error": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)

        try:
            payment_info = get_payment(str(payment_id))
        except Exception as e:
            logger.error("No se pudo verificar el pago %s en MP: %s", payment_id, e)
            return Response({"error": "MP API unreachable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        external_reference = payment_info.get("external_reference")

        order = Order.objects.filter(external_reference=external_reference).first()
        if not order:
            logger.warning("Pago %s recibido pero orden %s no existe", payment_id, external_reference)
            return Response({"ok": True, "detail": "Order not found in DB"}, status=status.HTTP_200_OK)

        # Toda la lógica de mapeo de estado + idempotencia + signal vive en el
        # servicio de reconciliación (fuente de verdad compartida con la página
        # de éxito y el cron).
        apply_payment_status(order.id, payment_info)

        return Response({"ok": True}, status=status.HTTP_200_OK)


def _reconcile_and_serialize(order):
    """Reconcilia `order` contra MP (no-op inofensivo para transferencia,
    ver docstring de `OrderReconcileAPIView`) y devuelve el dict de estado
    que consumen tanto `OrderReconcileAPIView` como `OrderLookupAPIView` —
    factorizado para no duplicar la rama `payment_channel == TRANSFER` (bank,
    reference, receipt, etc.) entre "ya sé el order_id" (reconcile) y "lo
    busco por código+email" (lookup)."""
    try:
        reconcile_order(order)
    except Exception as e:
        # Si MP no responde no rompemos la página de éxito: devolvemos el
        # estado actual que tengamos en la DB.
        logger.error("No se pudo reconciliar la orden %s: %s", order.id, e)

    order.refresh_from_db()

    data = {
        "order_id": str(order.id),
        "status": order.status,
        "status_display": order.get_status_display(),
        "payment_channel": order.payment_channel,
        "total_amount": str(order.total_amount),
        "currency": order.currency,
        # El comprador que llega acá ya conoce este email (lo escribió él
        # mismo al comprar) — se lo devolvemos para que el frontend pueda
        # mostrárselo de vuelta (ej. aviso de "tu pedido anterior quedó
        # pendiente, buscalo con este código y este email"), sin pedírselo
        # dos veces ni mandarlo nunca por query string.
        "customer_email": order.customer_email,
        "items": [
            {
                "title": item.product_name,
                "qty": item.quantity,
                "unit_price": str(item.unit_price),
            }
            for item in order.order_items.all()
        ],
    }

    if order.payment_channel == Order.PaymentChannel.TRANSFER:
        data.update({
            "reference": reference_code(order),
            "transfer_discount_percent": order.transfer_discount_percent_applied,
            "expires_in_hours": settings.TRANSFER_PENDING_EXPIRATION_HOURS,
            "created_at": order.created_at.isoformat(),
            "bank": {
                "alias": settings.TRANSFER_BANK_ALIAS,
                "cbu": settings.TRANSFER_BANK_CBU,
                "holder_name": settings.TRANSFER_BANK_HOLDER_NAME,
                "cuit": settings.TRANSFER_BANK_CUIT,
            },
            # Para que `/checkout/transfer` sepa (incluso después de un
            # F5) si ya hay un comprobante subido, sin depender de que el
            # frontend lo recuerde solo en estado local — ver
            # `TransferReceiptUploadAPIView` más abajo.
            "has_receipt": bool(order.transfer_receipt),
            "receipt_uploaded_at": (
                order.transfer_receipt_uploaded_at.isoformat()
                if order.transfer_receipt_uploaded_at else None
            ),
        })

    return data


class OrderReconcileAPIView(APIView):
    """Reconcilia una orden contra MP y devuelve su estado real.

    La llama la página de éxito cuando el cliente vuelve del checkout. Funciona
    para invitados (AllowAny) porque no todas las compras tienen usuario. No
    expone datos sensibles: solo lo necesario para mostrar el resultado.

    A diferencia del webhook, no depende de que MP nos avise: consulta MP por
    external_reference (search_payments) y sincroniza. Es la red que cubre el
    caso "el webhook no llegó pero el cliente sí volvió".

    Para órdenes de transferencia (`payment_channel=TRANSFER`) este mismo
    endpoint es seguro de llamar: `reconcile_order()` busca el pago en MP por
    `external_reference`, no encuentra nada (no existe ningún pago de MP para
    esa orden) y devuelve el status actual sin tocar nada — nunca rompe. Se
    aprovecha esto para que la pantalla de instrucciones de transferencia sea
    "reload-safe" sin necesitar un endpoint nuevo: además de los datos de
    siempre, la respuesta suma `reference`/`bank`/etc. cuando corresponde, para
    que un F5 en esa pantalla no pierda el alias/CBU/monto a transferir.
    """
    permission_classes = [AllowAny]

    def post(self, request, order_id):
        order = get_object_or_404(Order, id=order_id)
        return Response(_reconcile_and_serialize(order), status=status.HTTP_200_OK)


class OrderLookupThrottle(SimpleRateThrottle):
    """Por IP, igual criterio que `CheckoutThrottle`/`TransferReceiptThrottle`
    — sin esto, alguien podría usar este endpoint para "probar" códigos de
    referencia (8 caracteres, no son secretos por sí solos) contra un email
    conocido. Con el throttle, combinado con que también hace falta el email
    exacto, el espacio de búsqueda práctico queda acotado."""

    scope = "order_lookup"
    rate = "10/hour"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class OrderLookupAPIView(APIView):
    """`POST /api/payments/orders/lookup/` — alternativa a "Mis pedidos" para
    compradores SIN cuenta: un pedido de invitado nunca queda asociado a
    ningún `User` (ver `Order.user`, siempre `null` en ese caso), así que
    "Mis pedidos" (que exige login) es un callejón sin salida para ellos.

    Busca por `reference_code` (el código corto de 8 caracteres que ya se
    muestra en mails/UI, ver `reference_code()`) + `email` exacto — las dos
    cosas juntas, no el código solo: 8 caracteres no alcanzan para ser
    secretos por sí mismos, pero combinados con el email exacto del
    comprador (que un desconocido no tiene por qué saber) el lookup queda
    razonablemente acotado. `AllowAny` + `OrderLookupThrottle` por IP, mismo
    criterio que el resto del canal de invitado.

    Reusa `_reconcile_and_serialize()` — misma respuesta que ya devuelve
    `OrderReconcileAPIView`, así el frontend puede mostrar el resultado con
    el mismo componente que ya tiene para esa pantalla.
    """
    permission_classes = [AllowAny]
    throttle_classes = [OrderLookupThrottle]

    def post(self, request):
        reference_code_input = (request.data.get("reference_code") or "").strip()
        email = (request.data.get("email") or "").strip()
        brand_slug = (request.data.get("brand") or "").strip()

        if not reference_code_input or not email:
            return Response(
                {"detail": "Completá el código de pedido y el email."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # `reference_code()` es `external_reference[:8].upper()` — para
        # buscar en sentido inverso alcanza con comparar el prefijo en
        # minúscula contra `external_reference` (siempre hex lowercase,
        # `uuid.uuid4().hex`). No es una columna propia: no hace falta
        # desnormalizar nada nuevo en `Order` para este lookup.
        code_prefix = reference_code_input.lower()

        orders = Order.objects.filter(
            customer_email__iexact=email,
            external_reference__startswith=code_prefix,
        )
        if brand_slug:
            orders = orders.filter(brand__slug=brand_slug)

        order = orders.order_by("-created_at").first()
        if not order:
            # Mensaje genérico a propósito: no distinguir "el código está
            # mal" de "el email está mal" evita confirmarle a quien está
            # probando combinaciones cuál de los dos datos acertó.
            return Response(
                {"detail": "No encontramos un pedido con esos datos. Revisá el código y el email."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(_reconcile_and_serialize(order), status=status.HTTP_200_OK)


class PaymentSuccessView(TemplateView):
    template_name = "payments/success.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order_id = self.request.GET.get('order_id')
        # `Order.id` es UUIDField — un `order_id` ausente o con formato
        # inválido (típico de alguien tipeando la URL a mano, o un bot
        # probando parámetros) hacía que `Order.objects.get(id=...)` lanzara
        # `ValueError`/`ValidationError` (UUID mal formado) en vez de
        # `DoesNotExist`, que es lo único que `get_object_or_404` atrapa —
        # resultado: 500 en vez de un 404 prolijo.
        try:
            order_uuid = uuid.UUID(str(order_id))
        except (ValueError, TypeError, AttributeError):
            raise Http404("Pedido no encontrado.")
        context['order'] = get_object_or_404(Order, id=order_uuid)
        return context
