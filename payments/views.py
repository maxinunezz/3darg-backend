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
from orders.models import Order
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

        items_for_mp = data["items"]
        total = Decimal("0")
        for it in items_for_mp:
            total += Decimal(str(it["unit_price"])) * Decimal(str(it["quantity"]))

        external_reference = uuid.uuid4().hex

        order = Order.objects.create(
            brand=brand,
            user=request.user if request.user.is_authenticated else None,
            status=Order.Status.PENDING,
            currency=os.getenv("MP_CURRENCY", "ARS"),
            total_amount=total,
            items=[
                {"title": it["title"], "qty": it["quantity"], "unit_price": it["unit_price"]}
                for it in items_for_mp
            ],
            external_reference=external_reference,
            customer_email=data.get("customer_email", "") or (request.user.email if request.user.is_authenticated else ""),
        )

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
        payment_id = request.GET.get("data.id") or request.data.get("data", {}).get("id") or request.GET.get("id")
        topic = request.GET.get("type") or request.GET.get("topic") or request.data.get("type")

        logger.info("Webhook recibido: topic=%s id=%s", topic, payment_id)

        if topic not in ["payment", "opened_dispute", "dispute"]:
            return Response({"ok": True, "detail": f"Topic {topic} ignored"}, status=status.HTTP_200_OK)

        if not payment_id:
            return Response({"error": "No payment ID found"}, status=status.HTTP_400_BAD_REQUEST)

        is_signature_valid = is_valid_webhook_signature(request)

        try:
            payment_info = get_payment(str(payment_id))
        except Exception as e:
            logger.error("No se pudo verificar el pago %s en MP: %s", payment_id, e)
            if not is_signature_valid:
                return Response({"error": "Unauthorized and API check failed"}, status=status.HTTP_403_FORBIDDEN)
            return Response({"error": "MP API unreachable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        status_mp = payment_info.get("status")
        external_reference = payment_info.get("external_reference")

        if not (is_signature_valid or status_mp in ["approved", "in_process", "rejected"]):
            logger.warning("Firma inválida y estado sospechoso para pago %s", payment_id)
            return Response({"error": "Security check failed"}, status=status.HTTP_403_FORBIDDEN)

        order = Order.objects.filter(external_reference=external_reference).first()
        if not order:
            logger.warning("Pago %s recibido pero orden %s no existe", payment_id, external_reference)
            return Response({"ok": True, "detail": "Order not found in DB"}, status=status.HTTP_200_OK)

        if status_mp == "approved":
            order.status = Order.Status.PAID
            new_mp_status = MercadoPagoPayment.Status.APPROVED
            logger.info("Orden %s marcada como PAGADA", order.id)
        elif status_mp in ["rejected", "cancelled"]:
            order.status = Order.Status.REJECTED
            new_mp_status = MercadoPagoPayment.Status.REJECTED
        else:
            new_mp_status = MercadoPagoPayment.Status.PENDING

        order.save()

        mp_payment = MercadoPagoPayment.objects.filter(order=order).first()
        if mp_payment:
            mp_payment.status = new_mp_status
            mp_payment.mp_payment_id = str(payment_id)
            raw_data = mp_payment.raw or {}
            raw_data["last_api_check"] = payment_info
            raw_data["signature_was_valid"] = is_signature_valid
            mp_payment.raw = raw_data
            mp_payment.save()

        return Response(
            {"ok": True, "validated_by": "signature" if is_signature_valid else "api"},
            status=status.HTTP_200_OK,
        )


class PaymentSuccessView(TemplateView):
    template_name = "payments/success.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order_id = self.request.GET.get('order_id')
        context['order'] = get_object_or_404(Order, id=order_id)
        return context
