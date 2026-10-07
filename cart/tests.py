from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from brands.models import Brand
from products.models import Category, Product
from .models import Cart, CartItem

User = get_user_model()


class CartAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="shopper@example.com", username="shopper", password="pass1234"
        )
        self.brand = Brand.objects.create(name="PrintGym", slug="print-gym")
        self.cat = Category.objects.create(name="Accesorios", slug="accesorios")
        self.product = Product.objects.create(
            name="Llavero proteína",
            description="desc",
            price=2500,
            stock=10,
            category=self.cat,
            brand=self.brand,
            is_available=True,
        )
        self.client.force_authenticate(user=self.user)

    def test_get_empty_cart(self):
        res = self.client.get(reverse("cart"), {"brand_slug": self.brand.slug})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data["items"]), 0)

    def test_add_item(self):
        res = self.client.post(reverse("cart-item-add"), {
            "product_id": self.product.id,
            "quantity": 2,
            "brand_slug": self.brand.slug,
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data["items"]), 1)
        self.assertEqual(res.data["items"][0]["quantity"], 2)

    def test_remove_item(self):
        cart = Cart.objects.create(user=self.user, brand=self.brand)
        item = CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        res = self.client.delete(reverse("cart-item-detail", kwargs={"item_id": item.id}))
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)

    def test_clear_cart(self):
        cart = Cart.objects.create(user=self.user, brand=self.brand)
        CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        res = self.client.delete(f"{reverse('cart')}?brand_slug={self.brand.slug}")
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)

    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        res = self.client.get(reverse("cart"), {"brand_slug": self.brand.slug})
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
