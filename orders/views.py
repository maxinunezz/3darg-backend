from django.db.models import Count, Q, Sum
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Order
from .serializers import OrderSerializer, OrderSummarySerializer


class OrderListAPIView(generics.ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = (
            Order.objects.filter(user=self.request.user)
            .select_related("brand")
            .prefetch_related("order_items__product")
        )
        status = self.request.query_params.get("status")
        if status:
            qs = qs.filter(status=status.upper())
        return qs


class OrderDetailAPIView(generics.RetrieveAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "id"

    def get_queryset(self):
        return (
            Order.objects.filter(user=self.request.user)
            .select_related("brand")
            .prefetch_related("order_items__product")
        )


class OrderSummaryAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = Order.objects.filter(user=request.user)

        total_spent = qs.filter(status=Order.Status.PAID).aggregate(
            total=Sum("total_amount")
        )["total"] or 0

        status_counts = qs.values("status").annotate(count=Count("id"))
        orders_by_status = {row["status"]: row["count"] for row in status_counts}

        last_order = qs.order_by("-created_at").values_list("created_at", flat=True).first()

        data = {
            "total_orders": qs.count(),
            "total_spent": total_spent,
            "currency": "ARS",
            "orders_by_status": orders_by_status,
            "last_order_at": last_order,
        }

        serializer = OrderSummarySerializer(data)
        return Response(serializer.data)
