from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework.authtoken.models import Token

class AuthenticationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.email_auth_url = reverse('auth-email')

    def test_user_login_success(self):
        data = {
            "email": "farmer@example.com"
        }
        response = self.client.post(self.email_auth_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)

