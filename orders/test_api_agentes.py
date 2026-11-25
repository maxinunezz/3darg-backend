from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from brands.models import Brand
from payments.models import MercadoPagoPayment
from vending.models import VendingLead

from .models import Order, OrderItem

TOKEN = "token-de-prueba-agentes"
URLS = ["pedidos", "ventas", "productos", "leads"]


@override_settings(AGENTES_API_TOKEN=TOKEN)
class ApiAgentesTests(APITestCase):
    def setUp(self):
        self.ok = {"HTTP_X_AGENTES_TOKEN": TOKEN}
        user = get_user_model().objects.create_user(email="c@x.com", username="c", password="pass1234")
        self.lumy = Brand.objects.create(name="Lumy", slug="lumy")
        self.mini = Brand.objects.create(name="MiniSlam", slug="minislam")
        self.pagado = Order.objects.create(brand=self.lumy, user=user, status=Order.Status.PAID, total_amount=1500,
                                           external_reference="ref-1", customer_email="c@x.com",
                                           shipping_full_name="Ana Pérez", shipping_city="Córdoba",
                                           shipping_phone="351555")
        OrderItem.objects.create(order=self.pagado, product_name="Cortante corazón", quantity=2, unit_price=750)
        MercadoPagoPayment.objects.create(order=self.pagado, status="APPROVED")
        Order.objects.create(brand=self.mini, status=Order.Status.PENDING, total_amount=900, external_reference="ref-2")
        Order.objects.create(brand=self.mini, status=Order.Status.DRAFT, total_amount=100, external_reference="ref-3")

    def test_sin_token_o_token_malo_responde_403(self):
        for u in URLS:
            self.assertEqual(self.client.get(f"/api/agentes/{u}/").status_code, 403, u)
            self.assertEqual(self.client.get(f"/api/agentes/{u}/", HTTP_X_AGENTES_TOKEN="x").status_code, 403, u)

    @override_settings(AGENTES_API_TOKEN="")
    def test_sin_token_configurado_todo_cerrado(self):
        self.assertEqual(self.client.get("/api/agentes/pedidos/", HTTP_X_AGENTES_TOKEN="").status_code, 403)

    def test_no_se_puede_escribir(self):
        for metodo in ("post", "put", "patch", "delete"):
            r = getattr(self.client, metodo)("/api/agentes/pedidos/", {}, format="json", **self.ok)
            self.assertIn(r.status_code, (403, 405), metodo)

    def test_el_token_no_abre_los_pedidos_de_usuarios(self):
        self.assertEqual(self.client.get("/api/orders/", **self.ok).status_code, 401)

    def test_pedidos_sin_borradores_ni_datos_de_contacto(self):
        d = self.client.get("/api/agentes/pedidos/", **self.ok).json()
        refs = {p["referencia"] for p in d["pedidos"]}
        self.assertEqual(refs, {"ref-1", "ref-2"})
        p = next(x for x in d["pedidos"] if x["referencia"] == "ref-1")
        self.assertEqual(p["cliente"], "Ana")
        self.assertEqual(p["pago_mp"], "APPROVED")
        self.assertEqual(p["items"][0]["cantidad"], 2)
        texto = str(d)
        for dato in ("c@x.com", "351555", "Pérez"):
            self.assertNotIn(dato, texto)

    def test_filtro_por_marca(self):
        d = self.client.get("/api/agentes/pedidos/?marca=minislam", **self.ok).json()
        self.assertEqual([p["referencia"] for p in d["pedidos"]], ["ref-2"])

    def test_ventas_cobrado_y_por_marca(self):
        d = self.client.get("/api/agentes/ventas/", **self.ok).json()
        self.assertEqual(d["cobrado"], {"pedidos": 1, "total": "1500.00"})
        self.assertEqual(len(d["por_marca_y_estado"]), 2)

    def test_productos_y_leads_responden(self):
        VendingLead.objects.create(nombre="Kiosco Juan", email="j@x.com", segmento=VendingLead.Segmento.choices[0][0])
        self.assertEqual(self.client.get("/api/agentes/productos/", **self.ok).status_code, 200)
        d = self.client.get("/api/agentes/leads/", **self.ok).json()
        self.assertEqual(d["maquina_expendedora"][0]["nombre"], "Kiosco Juan")
        self.assertNotIn("j@x.com", str(d))
