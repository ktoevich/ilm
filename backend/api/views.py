from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .processing import generate_mock_overlay
import os

class AnalyzeView(APIView):
    def post(self, request):
        """
        Receives coordinates/bbox, downloads image, processes it, and returns fertility map.
        """
        # 1. Get coordinates from request
        data = request.data
        bbox = data.get('bbox') # [min_lon, min_lat, max_lon, max_lat]
        
        if not bbox:
            return Response({"error": "No bbox provided"}, status=status.HTTP_400_BAD_REQUEST)

        # 2. Generate Real Overlay
        overlay_image, actual_bounds, stats = generate_mock_overlay(bbox)
        
        if not overlay_image:
            return Response({"error": "Failed to generate analysis. Check backend logs."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "status": "success",
            "message": "Analysis Complete",
            "stats": stats,
            "overlay": {
                "image": overlay_image,
                "bounds": actual_bounds
            },
            "legend": {
                "Очень высокое плодородие": "rgba(0, 100, 0, 0.7)",
                "Высокое плодородие": "rgba(0, 200, 0, 0.7)",
                "Умеренное плодородие": "rgba(0, 255, 255, 0.7)",
                "Низкое плодородие": "rgba(0, 165, 255, 0.7)",
                "Неплодородная/Вода": "rgba(0, 0, 255, 0.7)"
            }
        })
