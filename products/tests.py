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
