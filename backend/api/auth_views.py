from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token

class EmailOnlyView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        if not email:
            return Response({"error": "Пожалуйста, укажите email"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_email(email)
        except ValidationError:
            return Response({"error": "Некорректный формат email адреса"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Get or create user
        user = User.objects.filter(email=email).first()
        if not user:
            user = User.objects.filter(username=email).first()
            if not user:
                user = User.objects.create_user(username=email, email=email)
            else:
                user.email = email
                user.save()
                
        token, _ = Token.objects.get_or_create(user=user)
        
        return Response({
            "token": token.key,
            "user": {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name
            }
        }, status=status.HTTP_200_OK)
