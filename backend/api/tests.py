from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework.authtoken.models import Token

class AuthenticationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.register_url = reverse('auth-register')
        self.login_url = reverse('auth-login')
        self.me_url = reverse('auth-me')
        self.logout_url = reverse('auth-logout')

    def test_user_registration_success(self):
        data = {
            "email": "testuser@example.com",
            "password": "strongpassword123",
            "first_name": "Тест Имя"
        }
        response = self.client.post(self.register_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("token", response.data)
        self.assertEqual(response.data["user"]["email"], "testuser@example.com")
        self.assertEqual(response.data["user"]["first_name"], "Тест Имя")

    def test_user_registration_duplicate_email(self):
        User.objects.create_user(username="testuser@example.com", email="testuser@example.com", password="password123")
        data = {
            "email": "testuser@example.com",
            "password": "newpassword123"
        }
        response = self.client.post(self.register_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_user_login_success(self):
        user = User.objects.create_user(username="farmer@example.com", email="farmer@example.com", password="password123")
        data = {
            "email": "farmer@example.com",
            "password": "password123"
        }
        response = self.client.post(self.login_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)

    def test_user_login_invalid_password(self):
        User.objects.create_user(username="farmer@example.com", email="farmer@example.com", password="password123")
        data = {
            "email": "farmer@example.com",
            "password": "wrongpassword"
        }
        response = self.client.post(self.login_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_me_endpoint(self):
        user = User.objects.create_user(username="me@example.com", email="me@example.com", password="password123")
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "me@example.com")
