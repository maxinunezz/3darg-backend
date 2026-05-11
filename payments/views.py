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
from .models import MercadoPagoPayment
from .serializers import CheckoutProCreateSerializer
from .services.mercadopago import create_preference, get_payment, is_valid_webhook_signature

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

        items_data = data["items"]
        product_ids = [it["product_id"] for it in items_data]

        products_qs = Product.objects.filter(
            id__in=product_ids,
            brand=brand,
            is_available=True,
        )
        products_by_id = {p.id: p for p in products_qs}

        missing = [pid for pid in product_ids if pid not in products_by_id]
        if missing:
            return Response(
                {"detail": f"Producto(s) no disponible(s): {missing}"},
                status=status.HTTP_400_BAD_REQUEST,
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

        items_for_mp = []
        total = Decimal("0")
        for it in items_data:
            product = products_by_id[it["product_id"]]
            qty = it["quantity"]
            items_for_mp.append({
                "title": product.name,
                "quantity": qty,
                "unit_price": float(product.price),
            })
            total += product.price * qty

        external_reference = uuid.uuid4().hex

        order = Order.objects.create(
            brand=brand,
            user=request.user if request.user.is_authenticated else None,
            status=Order.Status.PENDING,
            currency=os.getenv("MP_CURRENCY", "ARS"),
            total_amount=total,
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
                unit_price=products_by_id[it["product_id"]].price,
            )
            for it in items_data
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

        status_mp = payment_info.get("status")
        external_reference = payment_info.get("external_reference")

        order = Order.objects.filter(external_reference=external_reference).first()
        if not order:
            logger.warning("Pago %s recibido pero orden %s no existe", payment_id, external_reference)
            return Response({"ok": True, "detail": "Order not found in DB"}, status=status.HTTP_200_OK)

        if status_mp == "approved":
            new_order_status = Order.Status.PAID
            new_mp_status = MercadoPagoPayment.Status.APPROVED
        elif status_mp in ["rejected", "cancelled"]:
            new_order_status = Order.Status.REJECTED
            new_mp_status = MercadoPagoPayment.Status.REJECTED
        else:
            new_order_status = order.status
            new_mp_status = MercadoPagoPayment.Status.PENDING

        mp_payment = MercadoPagoPayment.objects.filter(order=order).first()

        if mp_payment and mp_payment.mp_payment_id == str(payment_id) and mp_payment.status == new_mp_status:
            logger.info("Webhook duplicado ignorado: payment_id=%s status=%s", payment_id, new_mp_status)
            return Response({"ok": True, "detail": "Already processed"}, status=status.HTTP_200_OK)

        order.status = new_order_status
        order.save()

        if mp_payment:
            mp_payment.status = new_mp_status
            mp_payment.mp_payment_id = str(payment_id)
            raw_data = mp_payment.raw or {}
            raw_data["last_api_check"] = payment_info
            mp_payment.raw = raw_data
            mp_payment.save()

        logger.info("Orden %s actualizada: status=%s mp_status=%s", order.id, new_order_status, new_mp_status)

        return Response({"ok": True}, status=status.HTTP_200_OK)


class PaymentSuccessView(TemplateView):
    template_name = "payments/success.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order_id = self.request.GET.get('order_id')
        context['order'] = get_object_or_404(Order, id=order_id)
        return context
