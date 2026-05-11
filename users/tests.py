from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model

User = get_user_model()


class AuthTests(APITestCase):
    def setUp(self):
        self.register_url = reverse("user-register")
        self.token_url = reverse("token_obtain_pair")
        self.me_url = reverse("user-me")
        self.user_data = {
            "email": "test@example.com",
            "username": "testuser",
            "password": "securepass123",
        }

    def test_register(self):
        res = self.client.post(self.register_url, self.user_data)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(User.objects.count(), 1)

    def test_login_returns_tokens(self):
        User.objects.create_user(**self.user_data)
        res = self.client.post(self.token_url, {
            "email": self.user_data["email"],
            "password": self.user_data["password"],
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("access", res.data)

    def test_me_requires_auth(self):
        res = self.client.get(self.me_url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_user(self):
        user = User.objects.create_user(**self.user_data)
        self.client.force_authenticate(user=user)
        res = self.client.get(self.me_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["email"], self.user_data["email"])
