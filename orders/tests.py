from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from brands.models import Brand
from products.models import Category, Product
from .models import Order, OrderItem

User = get_user_model()


class OrderAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="buyer@example.com", username="buyer", password="pass1234"
        )
        self.other_user = User.objects.create_user(
            email="other@example.com", username="other", password="pass1234"
        )
        self.brand = Brand.objects.create(name="TestBrand", slug="testbrand")
        self.order = Order.objects.create(
            brand=self.brand,
            user=self.user,
            status=Order.Status.PAID,
            total_amount=1500,
            external_reference="abc123",
            customer_email=self.user.email,
        )

    def test_list_requires_auth(self):
        res = self.client.get(reverse("order-list"))
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_returns_own_orders(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.get(reverse("order-list"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)

    def test_other_user_cannot_see_orders(self):
        self.client.force_authenticate(user=self.other_user)
        res = self.client.get(reverse("order-list"))
        self.assertEqual(res.data["count"], 0)

    def test_detail(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.get(reverse("order-detail", kwargs={"id": self.order.id}))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(str(res.data["id"]), str(self.order.id))


class StockSignalTests(TestCase):
    def setUp(self):
        self.brand = Brand.objects.create(name="StockBrand", slug="stockbrand")
        self.category = Category.objects.create(name="Cat", slug="cat", brand=self.brand)
        self.product = Product.objects.create(
            name="Test Product",
            slug="test-product",
            description="desc",
            price=Decimal("100"),
            stock=10,
            category=self.category,
            brand=self.brand,
        )
        self.order = Order.objects.create(
            brand=self.brand,
            status=Order.Status.PENDING,
            total_amount=Decimal("300"),
            external_reference="ref-stock-1",
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            product_name=self.product.name,
            quantity=3,
            unit_price=Decimal("100"),
        )

    def test_stock_unchanged_when_order_is_pending(self):
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)

    def test_stock_decrements_on_transition_to_paid(self):
        self.order.status = Order.Status.PAID
        self.order.save()
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 7)

    def test_stock_restored_when_cancelled_after_paid(self):
        self.order.status = Order.Status.PAID
        self.order.save()
        self.order.status = Order.Status.CANCELLED
        self.order.save()
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)

    def test_stock_restored_when_rejected_after_paid(self):
        self.order.status = Order.Status.PAID
        self.order.save()
        self.order.status = Order.Status.REJECTED
        self.order.save()
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)

    def test_stock_not_changed_when_pending_to_cancelled(self):
        self.order.status = Order.Status.CANCELLED
        self.order.save()
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)

    def test_stock_not_double_decremented_on_idempotent_save(self):
        self.order.status = Order.Status.PAID
        self.order.save()
        self.order.save()
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 7)
