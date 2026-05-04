import os
import uuid
from decimal import Decimal

from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.views.generic import TemplateView
from django.shortcuts import get_object_or_404

from brands.models import Brand
from orders.models import Order
from .models import MercadoPagoPayment
from .serializers import CheckoutProCreateSerializer
from .services.mercadopago import create_preference, get_payment, is_valid_webhook_signature


class MercadoPagoCheckoutProCreateAPIView(APIView):
    """
    POST /api/payments/mp/checkout-pro/
    Crea Order + Preference y devuelve init_point.
    """

    @transaction.atomic
    def post(self, request):
        print(f"DEBUG: Body recibido -> {request.body}")
        print(f"DEBUG: Data parseada -> {request.data}")
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
            status=Order.Status.PENDING,
            currency=os.getenv("MP_CURRENCY", "ARS"),
            total_amount=total,
            items=[
                {"title": it["title"], "qty": it["quantity"], "unit_price": it["unit_price"]}
                for it in items_for_mp
            ],
            external_reference=external_reference,
            customer_email=data.get("customer_email", ""),
        )

        backend_base = os.getenv("MP_NOTIFICATION_URL").split("/api/")[0]
        back_urls = {
            "success": f"{backend_base}/api/payments/checkout/success/?order_id={order.id}",
            "failure": f"{backend_base}/api/payments/checkout/failure/?order_id={order.id}",
            "pending": f"{backend_base}/api/payments/checkout/pending/?order_id={order.id}",
        }

        # 1. Definimos y validamos la URL de notificación una sola vez
        notification_url = os.getenv("MP_NOTIFICATION_URL", "").strip()
        if not notification_url:
            return Response(
                {"detail": "MP_NOTIFICATION_URL no está configurado (webhook URL)"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # 2. Creamos la preferencia una sola vez
        pref = create_preference(
            items=items_for_mp,
            external_reference=external_reference,
            notification_url=notification_url,
            back_urls=back_urls,
        )

        # 3. Guardamos el registro del pago
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
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        # 1. Extraer identificadores del Webhook
        # MP puede enviar el ID por Query Params (?id=...) o en el Body ({"data": {"id": ...}})
        payment_id = request.GET.get("data.id") or request.data.get("data", {}).get("id") or request.GET.get("id")
        topic = request.GET.get("type") or request.GET.get("topic") or request.data.get("type")

        print(f"DEBUG Webhook: Topic={topic}, ID={payment_id}")

        # Si no es un evento de pago, respondemos 200 para que MP deje de notificar
        if topic not in ["payment", "opened_dispute", "dispute"]:
            return Response({"ok": True, "detail": f"Topic {topic} ignored"}, status=status.HTTP_200_OK)

        if not payment_id:
            return Response({"error": "No payment ID found"}, status=status.HTTP_400_BAD_REQUEST)

        # 2. SEGURIDAD: Validar firma (Capa 1)
        is_signature_valid = is_valid_webhook_signature(request)
        
        # 3. CONSULTA A LA API (Capa 2: Fuente de Verdad)
        try:
            # Consultamos directamente a MP usando nuestro ACCESS_TOKEN
            payment_info = get_payment(str(payment_id))
        except Exception as e:
            print(f"ERROR: No se pudo verificar el pago {payment_id} contra la API de MP: {e}")
            # Si no podemos consultar la API, y la firma falló, rechazamos.
            if not is_signature_valid:
                return Response({"error": "Unauthorized and API check failed"}, status=status.HTTP_403_FORBIDDEN)
            # Si la firma era válida pero la API falló (raro), reintentamos luego
            return Response({"error": "MP API unreachable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # 4. LÓGICA DE DECISIÓN BLINDADA
        status_mp = payment_info.get("status")
        external_reference = payment_info.get("external_reference")

        # CRITERIO DE ACEPTACIÓN:
        # Aceptamos la notificación SI la firma es válida O SI la API nos confirma que el pago es real
        if not (is_signature_valid or status_mp in ["approved", "in_process", "rejected"]):
            print(f"AVISO: Firma inválida y estado sospechoso para ID {payment_id}. Bloqueando.")
            return Response({"error": "Security check failed"}, status=status.HTTP_403_FORBIDDEN)

        # 5. ACTUALIZACIÓN DE BASE DE DATOS
        order = Order.objects.filter(external_reference=external_reference).first()
        if not order:
            print(f"AVISO: Se recibió pago {payment_id} pero no existe la orden {external_reference}")
            return Response({"ok": True, "detail": "Order not found in DB"}, status=status.HTTP_200_OK)

        # Mapeo de estados de la Orden y del Pago
        if status_mp == "approved":
            order.status = Order.Status.PAID
            new_mp_status = MercadoPagoPayment.Status.APPROVED
            print(f"ORDEN {order.id}: Marcada como PAGADA (Verificado vía API)")
        elif status_mp in ["rejected", "cancelled"]:
            order.status = Order.Status.REJECTED
            new_mp_status = MercadoPagoPayment.Status.REJECTED
        else:
            # "in_process", "in_mediation", "pending"
            new_mp_status = MercadoPagoPayment.Status.PENDING

        order.save()

        # Actualizar el registro detallado de MercadoPagoPayment
        mp_payment = MercadoPagoPayment.objects.filter(order=order).first()
        if mp_payment:
            mp_payment.status = new_mp_status
            mp_payment.mp_payment_id = str(payment_id)
            # Guardamos el JSON de MP para auditoría
            raw_data = mp_payment.raw or {}
            raw_data["last_api_check"] = payment_info
            raw_data["signature_was_valid"] = is_signature_valid
            mp_payment.raw = raw_data
            mp_payment.save()

        return Response({"ok": True, "validated_by": "api" if not is_signature_valid else "signature"}, status=status.HTTP_200_OK)
    

class PaymentSuccessView(TemplateView):
    template_name = "payments/success.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Obtenemos el order_id que viene en la URL (?order_id=...)
        order_id = self.request.GET.get('order_id')
        # Buscamos la orden o tiramos 404 si no existe
        context['order'] = get_object_or_404(Order, id=order_id)
        return context