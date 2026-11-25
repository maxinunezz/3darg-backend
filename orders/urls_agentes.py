from django.urls import path

from .api_agentes import LeadsAgentes, PedidosAgentes, ProductosAgentes, VentasAgentes

# Solo lectura para los agentes de IA (token propio, ver orders/api_agentes.py)
urlpatterns = [
    path("pedidos/", PedidosAgentes.as_view(), name="agentes-pedidos"),
    path("ventas/", VentasAgentes.as_view(), name="agentes-ventas"),
    path("productos/", ProductosAgentes.as_view(), name="agentes-productos"),
    path("leads/", LeadsAgentes.as_view(), name="agentes-leads"),
]
