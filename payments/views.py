import os
import uuid
from decimal import Decimal

from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from brands.models import Brand
from orders.models import Order
from .models import MercadoPagoPayment
from .serializers import CheckoutProCreateSerializer
from .services.mercadopago import create_preference, get_payment


class MercadoPagoCheckoutProCreateAPIView(APIView):
    """
    POST /api/payments/mp/checkout-pro/
    Crea Order + Preference y devuelve init_point.
    """

    @transaction.atomic
    def post(self, request):
        serializer = CheckoutProCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        brand = Brand.objects.filter(slug=data["brand_slug"], is_active=True).first()
        if not brand:
            return Response({"detail": "Brand not found"}, status=status.HTTP_404_NOT_FOUND)

        # Regla: solo marcas ecommerce/hybrid pueden pagar
        if brand.brand_type == "services":
            return Response(
                {"detail": "This brand is services-only. No checkout available."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        items_for_mp = data["items"]

        # Total real (fase 1: viene de items; fase 2: sale de DB de productos)
        total = Decimal("0")
        for it in items_for_mp:
            total += Decimal(str(it["unit_price"])) * Decimal(str(it["quantity"]))

        external_reference = uuid.uuid4().hex  # único, fácil de mapear

        order = Order.objects.create(
            brand=brand,
            status=Order.Status.PENDING,
            currency=os.getenv("MP_CURRENCY", "ARS"),
            total_amount=total,
            items=[  # guardo en formato "humano"
                {"title": it["title"], "qty": it["quantity"], "unit_price": it["unit_price"]}
                for it in items_for_mp
            ],
            external_reference=external_reference,
            customer_email=data.get("customer_email", ""),
        )

        frontend_base = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")
        back_urls = {
            "success": f"{frontend_base}/checkout/success?order_id={order.id}",
            "failure": f"{frontend_base}/checkout/failure?order_id={order.id}",
            "pending": f"{frontend_base}/checkout/pending?order_id={order.id}",
        }

        # IMPORTANTE: notification_url debe ser accesible públicamente para MP (en dev usás ngrok)
        # Por ahora lo ponemos por env para no hardcodear
        notification_url = os.getenv("MP_NOTIFICATION_URL", "").strip()
        if not notification_url:
            return Response(
                {"detail": "MP_NOTIFICATION_URL no está configurado (webhook URL)"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

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
    """
    POST /api/payments/mp/webhook/
    Mercado Pago pega acá. Guardamos el evento y resolvemos el pago.

    Nota: MP puede reintentar → endpoint debe ser idempotente.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        payload = request.data or {}

        # MP suele mandar identificadores en payload o query.
        # No asumimos formato exacto: buscamos "data.id" o "id".
        payment_id = None
        if isinstance(payload, dict):
            payment_id = payload.get("data", {}).get("id") or payload.get("id")

        if not payment_id:
            # igual respondemos 200 para que MP no reintente infinito por payload raro
            return Response({"ok": True, "detail": "No payment id in webhook"}, status=200)

        try:
            payment = get_payment(str(payment_id))
        except Exception as e:
            # si falla, devolvemos 200 pero registrá el error luego
            return Response({"ok": True, "detail": f"Could not fetch payment: {e}"}, status=200)

        external_reference = str(payment.get("external_reference", "")).strip()
        status_mp = str(payment.get("status", "")).strip().lower()

        # Mapeo de estados MP -> nuestro estado
        if status_mp == "approved":
            new_order_status = Order.Status.PAID
            new_mp_status = MercadoPagoPayment.Status.APPROVED
        elif status_mp in ("rejected", "cancelled"):
            new_order_status = Order.Status.REJECTED
            new_mp_status = MercadoPagoPayment.Status.REJECTED
        else:
            new_order_status = Order.Status.PENDING
            new_mp_status = MercadoPagoPayment.Status.PENDING

        # Buscamos order por external_reference (lo más confiable)
        order = Order.objects.filter(external_reference=external_reference).first()
        if not order:
            return Response({"ok": True, "detail": "Order not found for external_reference"}, status=200)

        mp_payment_obj, _ = MercadoPagoPayment.objects.get_or_create(order=order)

        # Idempotencia: si ya está PAID, no lo “bajamos” jamás
        if order.status != Order.Status.PAID:
            order.status = new_order_status
            order.save(update_fields=["status", "updated_at"])

        mp_payment_obj.mp_payment_id = str(payment.get("id", "")) or str(payment_id)
        mp_payment_obj.status = new_mp_status

        # Guardamos evidencia
        raw = mp_payment_obj.raw or {}
        raw.setdefault("webhooks", []).append(payload)
        raw["last_payment_fetch"] = payment
        mp_payment_obj.raw = raw
        mp_payment_obj.save(update_fields=["mp_payment_id", "status", "raw", "updated_at"])

        return Response({"ok": True}, status=200)