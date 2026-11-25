"""
API de solo lectura para los agentes de IA (Roque y su equipo), bajo /api/agentes/.

- Autenticación propia: header `X-Agentes-Token` contra la env var `AGENTES_API_TOKEN`
  (comparación en tiempo constante). Sin la env var, todo responde 403 (falla cerrado).
  No usa JWT ni usuarios: el token no sirve para ningún otro endpoint de la tienda.
- Solo GET, y ninguna vista escribe. No toca pagos: solo lee su estado.
- Sin datos de contacto de clientes (email, teléfono, dirección): solo nombre y ciudad.
"""

import hmac
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from products.models import Product
from vending.models import VendingLead
from whatsapp_community.models import WhatsAppCommunityLead
from wholesale.models import WholesaleLead

from .models import Order


class TokenAgentes(BasePermission):
    message = "Token de agentes inválido o ausente."

    def has_permission(self, request, view):
        esperado = getattr(settings, "AGENTES_API_TOKEN", "") or ""
        recibido = request.headers.get("X-Agentes-Token", "")
        return request.method in ("GET", "HEAD") and bool(esperado) and hmac.compare_digest(recibido, esperado)


class _VistaAgentes(APIView):
    authentication_classes = []
    permission_classes = [TokenAgentes]


def _dinero(x) -> str:
    return str((x or Decimal("0")).quantize(Decimal("0.01")))


def _rango(request, dias_default=30):
    hoy = timezone.localdate()
    try:
        hasta = date.fromisoformat(request.query_params.get("hasta") or hoy.isoformat())
        desde = date.fromisoformat(request.query_params.get("desde") or (hasta - timedelta(days=dias_default)).isoformat())
    except ValueError:
        hasta, desde = hoy, hoy - timedelta(days=dias_default)
    return desde, hasta


def _pedidos(request):
    desde, hasta = _rango(request)
    qs = Order.objects.filter(created_at__date__gte=desde, created_at__date__lte=hasta).exclude(status=Order.Status.DRAFT)
    if request.query_params.get("marca"):
        qs = qs.filter(brand__slug=request.query_params["marca"])
    if request.query_params.get("estado"):
        qs = qs.filter(status=request.query_params["estado"].upper())
    return desde, hasta, qs


class PedidosAgentes(_VistaAgentes):
    """GET /api/agentes/pedidos/?desde&hasta&marca=lumy&estado=PAID — pedidos de la tienda (sin borradores)."""

    def get(self, request):
        desde, hasta, qs = _pedidos(request)
        qs = qs.select_related("brand", "mp_payment").prefetch_related("order_items")
        datos = []
        for o in qs.order_by("-created_at")[:300]:
            pago = getattr(o, "mp_payment", None)  # None si el pedido no pasó por MercadoPago
            datos.append({
                "referencia": o.external_reference or str(o.id)[:8], "marca": o.brand.slug,
                "estado": o.get_status_display(), "canal_pago": o.payment_channel,
                "pago_mp": pago.status if pago else None,
                "total": _dinero(o.total_amount), "envio": _dinero(o.shipping_cost),
                "cliente": (o.shipping_full_name or "").split(" ")[0] or None, "ciudad": o.shipping_city or None,
                "seguimiento": o.correo_argentino_tracking_number or None, "creado": o.created_at,
                "items": [{"producto": i.product_name + (f" ({i.variant_label})" if i.variant_label else ""),
                           "cantidad": i.quantity, "precio": _dinero(i.unit_price)} for i in o.order_items.all()],
            })
        return Response({"desde": desde, "hasta": hasta, "pedidos": datos})


class VentasAgentes(_VistaAgentes):
    """GET /api/agentes/ventas/?desde&hasta — totales por marca y por estado (lo cobrado = estado PAID)."""

    def get(self, request):
        desde, hasta, qs = _pedidos(request)
        por_marca = (qs.values("brand__slug", "status").annotate(n=Count("id"), total=Sum("total_amount"))
                     .order_by("brand__slug", "status"))
        cobrado = qs.filter(status=Order.Status.PAID).aggregate(n=Count("id"), total=Sum("total_amount"))
        return Response({
            "desde": desde, "hasta": hasta,
            "cobrado": {"pedidos": cobrado["n"], "total": _dinero(cobrado["total"])},
            "por_marca_y_estado": [{"marca": r["brand__slug"], "estado": r["status"], "pedidos": r["n"],
                                    "total": _dinero(r["total"])} for r in por_marca],
        })


class ProductosAgentes(_VistaAgentes):
    """GET /api/agentes/productos/?marca=lumy — catálogo con precio, stock y disponibilidad por canal."""

    def get(self, request):
        qs = Product.objects.select_related("brand", "category")
        if request.query_params.get("marca"):
            qs = qs.filter(brand__slug=request.query_params["marca"])
        return Response({"productos": [
            {"nombre": p.name, "sku": p.sku or None, "marca": p.brand.slug if p.brand_id else None,
             "categoria": p.category.name if p.category_id else None, "precio": _dinero(p.price),
             "stock": p.stock, "disponible": p.is_available, "web": p.is_available_web, "mercadolibre": p.is_available_ml,
             "destacado": p.is_featured}
            for p in qs.order_by("brand__slug", "name")[:500]
        ]})


class LeadsAgentes(_VistaAgentes):
    """GET /api/agentes/leads/?desde&hasta — consultas de máquina expendedora, mayoristas y comunidad (sin contactos)."""

    def get(self, request):
        desde, hasta = _rango(request, dias_default=60)
        f = {"created_at__date__gte": desde, "created_at__date__lte": hasta}
        return Response({
            "desde": desde, "hasta": hasta,
            "maquina_expendedora": [{"nombre": x.nombre, "segmento": x.get_segmento_display(), "creado": x.created_at}
                                    for x in VendingLead.objects.filter(**f).order_by("-created_at")[:200]],
            "mayoristas": [{"nombre": x.name, "ciudad": x.city_province, "marca": x.brand or None, "creado": x.created_at}
                           for x in WholesaleLead.objects.filter(**f).order_by("-created_at")[:200]],
            "comunidad_whatsapp": [{"marca": x.brand or None, "segmentos": x.segments, "creado": x.created_at}
                                   for x in WhatsAppCommunityLead.objects.filter(**f).order_by("-created_at")[:200]],
        })
