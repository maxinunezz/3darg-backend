import importlib
from decimal import Decimal

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from brands.models import Brand
from .models import Category, Product

_migracion_0026 = importlib.import_module(
    "products.migrations.0026_sacar_prefijo_cortante_del_nombre"
)


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


class SacarPrefijoCortanteMigrationTests(TestCase):
    """products/migrations/0026_sacar_prefijo_cortante_del_nombre.py"""

    def setUp(self):
        self.brand = Brand.objects.create(name="Lumy", slug="lumy")
        self.cortantes = Category.objects.create(name="Cortantes", slug="cortantes", brand=self.brand)
        self.selva = Category.objects.create(
            name="Animales de la Selva", slug="cortantes-04-animales-de-la-selva",
            brand=self.brand, parent=self.cortantes,
        )
        self.otra_raiz = Category.objects.create(name="Llaveros", slug="llaveros", brand=self.brand)

        self.cebra = Product.objects.create(
            name="Cortante Cebra", description="", price=100, category=self.selva, brand=self.brand,
        )
        # Producto cuyo category es la raíz "Cortantes" directamente (sin subcategoría).
        self.generico = Product.objects.create(
            name="Cortante Genérico", description="", price=100, category=self.cortantes, brand=self.brand,
        )
        # No debe tocarse: mismo prefijo de nombre, pero de otra categoría raíz.
        self.llavero = Product.objects.create(
            name="Cortante Llavero Pulpo", description="", price=100, category=self.otra_raiz, brand=self.brand,
        )
        # No debe tocarse: no tiene el prefijo.
        self.sin_prefijo = Product.objects.create(
            name="Rodillo Textura Madera", description="", price=100, category=self.selva, brand=self.brand,
        )

    def _run(self, func):
        func(django_apps, None)
        for p in (self.cebra, self.generico, self.llavero, self.sin_prefijo):
            p.refresh_from_db()

    def test_saca_el_prefijo_de_productos_bajo_cortantes(self):
        self._run(_migracion_0026.sacar_prefijo)
        self.assertEqual(self.cebra.name, "Cebra")
        self.assertEqual(self.generico.name, "Genérico")

    def test_no_toca_productos_de_otra_categoria_raiz(self):
        self._run(_migracion_0026.sacar_prefijo)
        self.assertEqual(self.llavero.name, "Cortante Llavero Pulpo")

    def test_no_toca_productos_sin_el_prefijo(self):
        self._run(_migracion_0026.sacar_prefijo)
        self.assertEqual(self.sin_prefijo.name, "Rodillo Textura Madera")

    def test_revertir_vuelve_a_anteponer_el_prefijo(self):
        # Revert "best effort": solo verificamos que restaura los productos
        # que la migración forward realmente tocó — ver limitación
        # documentada en revertir() (no distingue "nunca tuvo el prefijo"
        # de "se lo sacamos" sin estado extra).
        self._run(_migracion_0026.sacar_prefijo)
        self._run(_migracion_0026.revertir)
        self.assertEqual(self.cebra.name, "Cortante Cebra")
        self.assertEqual(self.generico.name, "Cortante Genérico")
        # Sigue sin tocarse (otra categoría raíz).
        self.assertEqual(self.llavero.name, "Cortante Llavero Pulpo")

    def test_es_idempotente(self):
        self._run(_migracion_0026.sacar_prefijo)
        self._run(_migracion_0026.sacar_prefijo)
        self.assertEqual(self.cebra.name, "Cebra")


class ProductAdminCategoryFieldTests(TestCase):
    """Protege el guardado del form de admin frente a los cambios de
    `products/admin.py` (dropdown categoría/subcategoría encadenado vía JS,
    ver `static/products/admin/category_cascade.js`) — el JS solo
    manipula el <select name="category"> en el cliente antes de
    submitear, así que un POST normal al form de admin tiene que seguir
    guardando igual que antes.
    """

    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_superuser(
            username="admin_test", email="admin_test@3darg.com", password="x",
        )
        self.client.force_login(self.staff)

        self.brand = Brand.objects.create(name="Lumy", slug="lumy")
        self.cortantes = Category.objects.create(name="Cortantes", slug="cortantes", brand=self.brand)
        self.selva = Category.objects.create(
            name="Animales de la Selva", slug="cortantes-04-animales-de-la-selva",
            brand=self.brand, parent=self.cortantes,
        )
        self.otra_sub = Category.objects.create(
            name="Halloween", slug="cortantes-24-halloween",
            brand=self.brand, parent=self.cortantes,
        )
        self.product = Product.objects.create(
            name="Cebra", description="Cortante de cebra", price=1500, stock=50,
            category=self.selva, brand=self.brand,
        )

    REQUIRED_DECIMAL_FIELDS = [
        "ml_commission_percent", "ml_fixed_fee", "ml_vat_percent",
        "ml_gross_income_tax_percent", "ml_other_variable_percent", "ml_shipping_cost",
        "web_commission_percent", "web_fixed_fee", "web_vat_percent",
        "web_gross_income_tax_percent", "web_other_variable_percent", "web_shipping_cost",
    ]

    def _post_data(self, **overrides):
        data = {
            "name": self.product.name,
            "slug": self.product.slug,
            "sku": self.product.sku,
            "description": self.product.description,
            "price": "1500",
            "stock": "50",
            "member_discount_percent": "0",
            "category": str(self.selva.pk),
            "brand": str(self.brand.pk),
        }
        for field in self.REQUIRED_DECIMAL_FIELDS:
            data[field] = "0"
        data.update({
            "images-TOTAL_FORMS": "0",
            "images-INITIAL_FORMS": "0",
            "images-MIN_NUM_FORMS": "0",
            "images-MAX_NUM_FORMS": "1000",
        })
        data.update(overrides)
        return data

    def test_changeform_renderiza_con_el_js_de_cascada(self):
        url = reverse("admin:products_product_change", args=[self.product.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        # El nombre real lleva un hash agregado por ManifestStaticFilesStorage
        # (ej: category_cascade.af0992c88981.js), por eso no matcheamos el
        # nombre de archivo exacto.
        self.assertContains(res, "products/admin/category_cascade")
        # El select original agrupado sigue ahí (el JS lo sincroniza, no lo reemplaza).
        self.assertContains(res, 'id="id_category"')

    def test_guardar_el_form_sigue_funcionando(self):
        url = reverse("admin:products_product_change", args=[self.product.pk])
        res = self.client.post(url, self._post_data(category=str(self.otra_sub.pk)))
        self.assertEqual(res.status_code, 302, res.context["adminform"].form.errors if res.status_code == 200 else None)
        self.product.refresh_from_db()
        self.assertEqual(self.product.category_id, self.otra_sub.pk)

    def test_guardar_con_la_categoria_raiz_directamente(self):
        """Categorías raíz sin subcategoría elegida siguen siendo un valor válido
        (ej: "shaker" de Print&Gym, que no tiene hijas)."""
        url = reverse("admin:products_product_change", args=[self.product.pk])
        res = self.client.post(url, self._post_data(category=str(self.cortantes.pk)))
        self.assertEqual(res.status_code, 302, res.context["adminform"].form.errors if res.status_code == 200 else None)
        self.product.refresh_from_db()
        self.assertEqual(self.product.category_id, self.cortantes.pk)
