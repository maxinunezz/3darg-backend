from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from brands.models import Brand
from .models import Category, Product


class ProductAPITests(APITestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name="PrintGym", slug="print-gym")
        self.cat = Category.objects.create(name="Accesorios", slug="accesorios")
        self.product = Product.objects.create(
            name="Llavero proteína",
            description="Porta proteína compacto",
            price=2500,
            stock=10,
            category=self.cat,
            brand=self.brand,
            is_available=True,
        )

    def test_list_products(self):
        res = self.client.get(reverse("product-list"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)

    def test_filter_by_brand(self):
        res = self.client.get(reverse("product-list"), {"brand_slug": "print-gym"})
        self.assertEqual(res.data["count"], 1)

    def test_filter_wrong_brand(self):
        res = self.client.get(reverse("product-list"), {"brand_slug": "otro"})
        self.assertEqual(res.data["count"], 0)

    def test_search(self):
        res = self.client.get(reverse("product-list"), {"search": "proteína"})
        self.assertEqual(res.data["count"], 1)

    def test_detail(self):
        res = self.client.get(reverse("product-detail", kwargs={"slug": self.product.slug}))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["name"], "Llavero proteína")

    def test_detail_not_found(self):
        res = self.client.get(reverse("product-detail", kwargs={"slug": "no-existe"}))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


class ProductSkuGenerationTests(APITestCase):
    """SKU = MARCA-CATEGORIA-NNNNNN[-VARIANTE], ver Product.generate_sku()."""

    def setUp(self):
        self.brand = Brand.objects.create(name="Lumy", slug="lumy", sku_prefix="LUMY")
        self.root_cat = Category.objects.create(
            name="Cortantes", slug="cortantes", brand=self.brand, sku_prefix="COR"
        )

    def test_sku_usa_prefijo_de_marca_y_categoria(self):
        p = Product.objects.create(
            name="Cortante Jirafa", description="", price=100, category=self.root_cat, brand=self.brand,
        )
        self.assertEqual(p.sku, f"LUMY-COR-{p.pk:06d}")

    def test_sku_usa_categoria_raiz_no_la_subcategoria(self):
        sub = Category.objects.create(
            name="Animales de la Selva", slug="cortantes-animales-selva",
            brand=self.brand, parent=self.root_cat,
        )
        p = Product.objects.create(
            name="Cortante León", description="", price=100, category=sub, brand=self.brand,
        )
        # Usa el código de la raíz (COR), no uno propio de la subcategoría
        # (que no tiene sku_prefix cargado) — así no se vuelve obsoleto si
        # se reordenan subcategorías más adelante.
        self.assertEqual(p.sku, f"LUMY-COR-{p.pk:06d}")

    def test_sku_fallback_sin_prefijo_cargado(self):
        brand_sin_prefijo = Brand.objects.create(name="Print&Gym", slug="print-and-gym")
        cat_sin_prefijo = Category.objects.create(
            name="Llaveros", slug="llaveros-fallback", brand=brand_sin_prefijo,
        )
        p = Product.objects.create(
            name="Llavero", description="", price=100, category=cat_sin_prefijo, brand=brand_sin_prefijo,
        )
        # Sin sku_prefix cargado: usa el slug como fallback (primeras letras en mayúsculas).
        self.assertTrue(p.sku.startswith("PRIN-LLA-"))

    def test_sku_incluye_color_y_tamano_si_estan_cargados_al_crear(self):
        p = Product.objects.create(
            name="Aro mini", description="", price=100, category=self.root_cat, brand=self.brand,
            color="Verde", size="M",
        )
        self.assertEqual(p.sku, f"LUMY-COR-{p.pk:06d}-VERDE-M")

    def test_sku_no_se_recalcula_solo_al_cambiar_categoria_o_color(self):
        p = Product.objects.create(
            name="Cortante Jirafa", description="", price=100, category=self.root_cat, brand=self.brand,
        )
        sku_original = p.sku
        otra_cat = Category.objects.create(name="Otra", slug="otra-categoria", brand=self.brand, sku_prefix="OTR")
        p.category = otra_cat
        p.color = "Rojo"
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.sku, sku_original)

    def test_generate_sku_recalcula_bajo_demanda(self):
        """Usado por la acción de admin "Regenerar SKU"."""
        p = Product.objects.create(
            name="Cortante Jirafa", description="", price=100, category=self.root_cat, brand=self.brand,
        )
        p.color = "Rojo"
        nuevo_sku = p.generate_sku()
        self.assertEqual(nuevo_sku, f"LUMY-COR-{p.pk:06d}-ROJO")
