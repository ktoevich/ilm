from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.authtoken.models import Token
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')
        first_name = request.data.get('first_name', '').strip()

        if not email or not password:
            return Response(
                {"error": "Пожалуйста, укажите email и пароль"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            validate_email(email)
        except ValidationError:
            return Response(
                {"error": "Некорректный формат email адреса"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(password) < 6:
            return Response(
                {"error": "Пароль должен содержать не менее 6 символов"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        if User.objects.filter(username=email).exists() or User.objects.filter(email=email).exists():
            return Response(
                {"error": "Пользователь с таким email уже зарегистрирован"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=first_name
        )

        token, _ = Token.objects.get_or_create(user=user)

        return Response({
            "token": token.key,
            "user": {
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name or email.split('@')[0],
                "username": user.username
            }
        }, status=status.HTTP_201_CREATED)

class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')

        if not email or not password:
            return Response(
                {"error": "Пожалуйста, введите email и пароль"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        user = User.objects.filter(email=email).first() or User.objects.filter(username=email).first()

        if not user or not user.check_password(password):
            return Response(
                {"error": "Неверный email или пароль"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        token, _ = Token.objects.get_or_create(user=user)

        return Response({
            "token": token.key,
            "user": {
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name or email.split('@')[0],
                "username": user.username
            }
        }, status=status.HTTP_200_OK)

class UserMeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name or user.email.split('@')[0],
            "username": user.username
        })

class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            request.user.auth_token.delete()
        except Exception:
            pass
        return Response({"message": "Успешный выход из системы"}, status=status.HTTP_200_OK)
