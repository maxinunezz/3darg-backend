import os
import uuid
import logging
from decimal import Decimal

from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.views.generic import TemplateView
from django.shortcuts import get_object_or_404

from brands.models import Brand
from orders.models import Order, OrderItem
from products.models import Product
from products.services.combo_pricing import compute_unit_prices
from cart.services.cart_discount import compute_cart_pricing
from shipping.services.quote import cheapest_price, get_quotes, select_methods
from .models import MercadoPagoPayment
from .serializers import CheckoutProCreateSerializer
from .services.mercadopago import create_preference, get_payment, is_valid_webhook_signature
from .services.reconciliation import apply_payment_status, reconcile_order

logger = logging.getLogger(__name__)


class MercadoPagoCheckoutProCreateAPIView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
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
            if product.stock < it["quantity"]:
                stock_errors.append(
                    f"'{product.name}': stock insuficiente ({product.stock} disponible(s))"
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
        # el carrito.
        list_prices = compute_unit_prices(
            user,
            [(products_by_id[it["product_id"]], it["quantity"]) for it in items_data],
        )
        lines = [
            (price, it["quantity"]) for it, price in zip(items_data, list_prices)
        ]
        pricing = compute_cart_pricing(brand, lines)
        unit_prices = pricing["discounted_unit_prices"]

        items_for_mp = []
        for it, unit_price in zip(items_data, unit_prices):
            product = products_by_id[it["product_id"]]
            qty = it["quantity"]
            items_for_mp.append({
                "title": product.name,
                "quantity": qty,
                "unit_price": float(unit_price),
            })
        # `subtotal` ya incluye el descuento por monto aplicado — el umbral
        # de envío gratis se evalúa contra lo que el cliente efectivamente
        # paga, no contra el monto de lista.
        subtotal = pricing["total"]

        # Costo de envío: se cobra siempre, salvo que la marca tenga un
        # umbral de envío gratis (`Brand.shipping_config.free_shipping_threshold`)
        # y el subtotal lo alcance. Mismo mecanismo de cotización
        # (`shipping.services.quote`) que usa el preview del carrito
        # (`/api/shipping/calculate/`), para que lo que se cobra acá sea
        # consistente con lo que se mostró antes de pagar.
        free_shipping_threshold = (brand.shipping_config or {}).get("free_shipping_threshold")
        postal_code = (data.get("postal_code") or "").strip()
        province = (data.get("province") or "").strip()
        shipping_method_id = (data.get("shipping_method_id") or "").strip()
        shipping_cost = Decimal("0")
        shipping_method = ""
        shipping_modality = ""
        if free_shipping_threshold and subtotal >= Decimal(str(free_shipping_threshold)):
            shipping_cost = Decimal("0")
            # Aunque el envío salga gratis, igual hace falta saber qué
            # modalidad eligió el comprador (sucursal vs domicilio) para
            # validar la dirección correspondiente más abajo y para el alta
            # real en Correo Argentino (`deliveryType`).
            if shipping_method_id:
                shipping_method, _, shipping_modality = shipping_method_id.partition("_")
        else:
            # `get_quotes()` intenta cotización EN VIVO contra la API real de
            # Correo Argentino (`POST /rates`) cuando se conoce `postal_code`
            # de destino y hay credenciales cargadas; si no (sin CP, sin
            # credenciales, o falla la consulta), cae a la tabla estática por
            # peso/Valor Declarado (ver `quote.py`) — nunca deja un método sin
            # cotizar. Se calcula siempre, se haya mandado CP o no. Si el
            # comprador eligió un método en el selector del carrito
            # (`select_methods()`) se cobra ESE precio y se guarda qué
            # eligió; si no vino `shipping_method_id` o no matchea ningún
            # método, se cae al más barato (mismo comportamiento que antes de
            # este selector).
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
                shipping_method, _, shipping_modality = selected["id"].partition("_")
            else:
                shipping_cost = cheapest_price(quote_result["quotes"])

        # Dirección del comprador — la API real de Correo Argentino (API
        # MiCorreo) NO exige la misma cosa para las dos modalidades: en
        # sucursal solo pide `agency` (código de la sucursal elegida, ver
        # `correo_argentino.py::_build_shipment_payload()`), la dirección
        # completa NO es obligatoria (`shipping.address` solo se exige si
        # `deliveryType != "S"`); en domicilio sí hace falta la dirección
        # completa del comprador. Si el método elegido no matcheó nada
        # (fallback por CP ausente), no se exige nada nuevo — se mantiene el
        # comportamiento histórico de checkout mínimo.
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
                quantity=it["quantity"],
                unit_price=unit_price,
            )
            for it, unit_price in zip(items_data, unit_prices)
        ]
        OrderItem.objects.bulk_create(order_items)

        notification_url = os.getenv("MP_NOTIFICATION_URL", "").strip()
        if not notification_url:
            return Response(
                {"detail": "MP_NOTIFICATION_URL no está configurado"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        frontend_base = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")
        back_urls = {
            "success": f"{frontend_base}/checkout/success/?order_id={order.id}",
            "failure": f"{frontend_base}/checkout/failure/?order_id={order.id}",
            "pending": f"{frontend_base}/checkout/pending/?order_id={order.id}",
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


class OrderReconcileAPIView(APIView):
    """Reconcilia una orden contra MP y devuelve su estado real.

    La llama la página de éxito cuando el cliente vuelve del checkout. Funciona
    para invitados (AllowAny) porque no todas las compras tienen usuario. No
    expone datos sensibles: solo lo necesario para mostrar el resultado.

    A diferencia del webhook, no depende de que MP nos avise: consulta MP por
    external_reference (search_payments) y sincroniza. Es la red que cubre el
    caso "el webhook no llegó pero el cliente sí volvió".
    """
    permission_classes = [AllowAny]

    def post(self, request, order_id):
        order = get_object_or_404(Order, id=order_id)

        try:
            reconcile_order(order)
        except Exception as e:
            # Si MP no responde no rompemos la página de éxito: devolvemos el
            # estado actual que tengamos en la DB.
            logger.error("No se pudo reconciliar la orden %s: %s", order_id, e)

        order.refresh_from_db()

        return Response(
            {
                "order_id": str(order.id),
                "status": order.status,
                "status_display": order.get_status_display(),
                "total_amount": str(order.total_amount),
                "currency": order.currency,
                "items": [
                    {
                        "title": item.product_name,
                        "qty": item.quantity,
                        "unit_price": str(item.unit_price),
                    }
                    for item in order.order_items.all()
                ],
            },
            status=status.HTTP_200_OK,
        )


class PaymentSuccessView(TemplateView):
    template_name = "payments/success.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order_id = self.request.GET.get('order_id')
        context['order'] = get_object_or_404(Order, id=order_id)
        return context
