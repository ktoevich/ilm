import json
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, generics
from .models import (
    Field, CropType, CropRotation, SoilAnalysis, 
    InvasiveSpeciesReport, GrowthMonitoring, WeedDatabase
)
from .serializers import (
    FieldSerializer, CropTypeSerializer, CropRotationSerializer, 
    SoilAnalysisSerializer, InvasiveSpeciesReportSerializer, 
    GrowthMonitoringSerializer, WeedDatabaseSerializer
)
from .processing import (
    generate_mock_overlay, analyze_ndvi, detect_weeds, 
    analyze_environment_with_crops, detect_buildings, predict_development, filter_urban_areas
)

class AnalyzeView(APIView):
    def post(self, request):
        bbox = request.data.get('bbox')
        field_id = request.data.get('field_id')
        save_result = request.data.get('save_result', False)
        if not bbox:
            return Response({"error": "BBOX required"}, status=status.HTTP_400_BAD_REQUEST)

        overlay_image, actual_bounds, stats = generate_mock_overlay(bbox)

        if not overlay_image:
            return Response({"error": "Failed to process image"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        env_data = analyze_environment_with_crops(bbox)

        if save_result and field_id:
            field = get_object_or_404(Field, id=field_id)
            user = request.user if request.user.is_authenticated else None
            analysis = SoilAnalysis.objects.create(
                user=user,
                field=field,
                bbox_json=json.dumps(bbox),
                very_high_percent=stats.get('very_high', 0),
                high_percent=stats.get('high', 0),
                moderate_percent=stats.get('moderate', 0),
                low_percent=stats.get('low', 0),
                non_fertile_percent=stats.get('desert', 0) + stats.get('water', 0),
                overlay_image=overlay_image,
                notes=f"Method: {stats.get('analysis_method', 'Unknown')}"
            )
            analysis.calculate_fertility_index()

        legend = {
            "Очень высокое плодородие": "rgba(0, 100, 0, 0.7)",
            "Высокое плодородие": "rgba(0, 200, 0, 0.7)",
            "Умеренное плодородие": "rgba(0, 255, 255, 0.7)",
            "Низкое плодородие": "rgba(0, 165, 255, 0.7)",
            "Горы / Скалистый рельеф": "rgba(100, 70, 50, 0.7)",
            "Засушливая земля / Пустыня": "rgba(150, 150, 150, 0.7)",
            "Вода / Тень": "rgba(0, 0, 255, 0.7)"
        }

        return Response({
            "overlay": {
                "image": overlay_image,
                "bounds": actual_bounds
            },
            "stats": stats,
            "legend": legend,
            "environment": env_data
        })

class FieldListCreateView(generics.ListCreateAPIView):
    serializer_class = FieldSerializer

    def get_queryset(self):
        if self.request.user.is_authenticated:
            return Field.objects.filter(user=self.request.user)
        return Field.objects.all()

    def perform_create(self, serializer):
        if self.request.user.is_authenticated:
            serializer.save(user=self.request.user)
        else:
            serializer.save()

class FieldDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = FieldSerializer

    def get_queryset(self):
        if self.request.user.is_authenticated:
            return Field.objects.filter(user=self.request.user)
        return Field.objects.all()

class CropTypeListView(generics.ListCreateAPIView):
    queryset = CropType.objects.all()
    serializer_class = CropTypeSerializer

class CropTypeDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = CropType.objects.all()
    serializer_class = CropTypeSerializer

class CropRotationListView(generics.ListCreateAPIView):
    serializer_class = CropRotationSerializer

    def get_queryset(self):
        qs = CropRotation.objects.all()
        if self.request.user.is_authenticated:
            qs = qs.filter(user=self.request.user)
        field_id = self.request.query_params.get('field_id')
        if field_id:
            qs = qs.filter(field_id=field_id)
        return qs

    def perform_create(self, serializer):
        if self.request.user.is_authenticated:
            serializer.save(user=self.request.user)
        else:
            serializer.save()

class CropRotationRecommendationView(APIView):
    def get(self, request, field_id):
        field = get_object_or_404(Field, id=field_id)
        last_rotation = CropRotation.objects.filter(field=field).order_by('-year').first()
        
        recommendations = []
        if last_rotation:
            prev_crop = last_rotation.crop_type
            good_next = prev_crop.good_successors.all()
            for crop in good_next:
                recommendations.append({
                    "crop": CropTypeSerializer(crop).data,
                    "reason": f"Хороший последователь для {prev_crop.name}"
                })
        
        if not recommendations:
            crops = CropType.objects.all()[:3]
            for crop in crops:
                recommendations.append({
                    "crop": CropTypeSerializer(crop).data,
                    "reason": "Базовая рекомендация"
                })
                
        return Response(recommendations)

class CropPlantingRecommendationView(APIView):
    def post(self, request):
        field_id = request.data.get('field_id')
        ph = request.data.get('ph')
        n = request.data.get('nitrogen')
        p = request.data.get('phosphorus')
        k = request.data.get('potassium')
        moisture = request.data.get('moisture')
        
        if not all([ph, n, p, k, moisture]):
            return Response({"error": "All soil parameters are required"}, status=400)
            
        crops = CropType.objects.all()
        results = []
        
        for crop in crops:
            comp = crop.check_soil_compatibility(ph, n, p, k, moisture)
            results.append({
                "crop": CropTypeSerializer(crop).data,
                "compatibility": comp
            })
            
        results.sort(key=lambda x: x['compatibility']['compatibility_percent'], reverse=True)
        return Response(results)

class SoilAnalysisListView(generics.ListAPIView):
    serializer_class = SoilAnalysisSerializer
    
    def get_queryset(self):
        qs = SoilAnalysis.objects.all()
        if self.request.user.is_authenticated:
            qs = qs.filter(user=self.request.user)
        field_id = self.request.query_params.get('field_id')
        if field_id:
            qs = qs.filter(field_id=field_id)
        return qs

class SoilAnalysisTimeSeriesView(APIView):
    def get(self, request, field_id):
        analyses = SoilAnalysis.objects.filter(field_id=field_id).order_by('analysis_date')
        data = {
            "dates": [a.analysis_date.strftime('%Y-%m-%d') for a in analyses],
            "fertility_index": [a.fertility_index for a in analyses],
            "very_high": [a.very_high_percent for a in analyses],
            "high": [a.high_percent for a in analyses],
            "moderate": [a.moderate_percent for a in analyses],
            "low": [a.low_percent for a in analyses]
        }
        return Response(data)

class GrowthMonitoringListView(generics.ListCreateAPIView):
    serializer_class = GrowthMonitoringSerializer

    def get_queryset(self):
        if self.request.user.is_authenticated:
            return GrowthMonitoring.objects.filter(user=self.request.user)
        return GrowthMonitoring.objects.all()

    def perform_create(self, serializer):
        if self.request.user.is_authenticated:
            serializer.save(user=self.request.user)
        else:
            serializer.save()

class GrowthAnalyzeView(APIView):
    def post(self, request):
        bbox = request.data.get('bbox')
        field_id = request.data.get('field_id')
        save_result = request.data.get('save_result', False)
        
        if not bbox:
            return Response({"error": "BBOX required"}, status=400)
            
        data = analyze_ndvi(bbox)
        if not data:
            return Response({"error": "Failed to analyze Growth"}, status=500)
            
        if save_result and field_id:
            field = get_object_or_404(Field, id=field_id)
            from datetime import date
            user = request.user if request.user.is_authenticated else None
            GrowthMonitoring.objects.update_or_create(
                field=field,
                observation_date=date.today(),
                defaults={
                    "user": user,
                    "ndvi_mean": data["ndvi_mean"],
                    "ndvi_min": data["ndvi_min"],
                    "ndvi_max": data["ndvi_max"],
                    "health_score": data["health_score"],
                    "growth_stage": data["growth_stage"],
                    "ndvi_overlay": data["overlay"]
                }
            )
            
        return Response({
            "ndvi": {
                "ndvi_mean": data["ndvi_mean"],
                "ndvi_min": data["ndvi_min"],
                "ndvi_max": data["ndvi_max"],
                "health_score": data["health_score"],
                "growth_stage": data["growth_stage"]
            },
            "overlay": {
                "image": data["overlay"],
                "bounds": data["bounds"]
            }
        })

class GrowthTimeSeriesView(APIView):
    def get(self, request, field_id):
        records = GrowthMonitoring.objects.filter(field_id=field_id).order_by('observation_date')
        data = {
            "dates": [r.observation_date.strftime('%Y-%m-%d') for r in records],
            "ndvi_mean": [r.ndvi_mean for r in records],
            "health_score": [r.health_score for r in records]
        }
        return Response(data)

class InvasiveSpeciesListView(generics.ListCreateAPIView):
    serializer_class = InvasiveSpeciesReportSerializer

    def get_queryset(self):
        if self.request.user.is_authenticated:
            return InvasiveSpeciesReport.objects.filter(user=self.request.user)
        return InvasiveSpeciesReport.objects.all()

    def perform_create(self, serializer):
        if self.request.user.is_authenticated:
            serializer.save(user=self.request.user)
        else:
            serializer.save()

class InvasiveSpeciesDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = InvasiveSpeciesReportSerializer

    def get_queryset(self):
        if self.request.user.is_authenticated:
            return InvasiveSpeciesReport.objects.filter(user=self.request.user)
        return InvasiveSpeciesReport.objects.all()

class WeedDetectionView(APIView):
    def post(self, request):
        bbox = request.data.get('bbox')
        field_id = request.data.get('field_id')
        save_result = request.data.get('save_result', False)
        if not bbox:
            return Response({"error": "BBOX required"}, status=400)
            
        data = detect_weeds(bbox)
        if not data:
            return Response({"error": "Failed to detect weeds"}, status=500)
            
        if save_result and field_id:
            field = get_object_or_404(Field, id=field_id)
            user = request.user if request.user.is_authenticated else None
            for d in data.get('detections', []):
                InvasiveSpeciesReport.objects.create(
                    user=user,
                    field=field,
                    species_name=d['name'],
                    severity=d['severity'],
                    location_lat=d['lat'],
                    location_lon=d['lon'],
                    affected_area=d['area'],
                    recommendations=d['recommendations']
                )
                
        return Response(data)

class WeedDatabaseListView(generics.ListAPIView):
    queryset = WeedDatabase.objects.all()
    serializer_class = WeedDatabaseSerializer


class DashboardView(APIView):
    def get(self, request):
        total_fields = Field.objects.count()
        total_area = sum(f.area_hectares for f in Field.objects.all())
        latest_analyses = SoilAnalysis.objects.all()[:5]
        latest_reports = InvasiveSpeciesReport.objects.filter(status='detected')[:5]
        
        return Response({
            "stats": {
                "fields_count": total_fields,
                "total_area_ha": round(total_area, 2),
                "active_reports": latest_reports.count()
            },
            "recent_analyses": SoilAnalysisSerializer(latest_analyses, many=True).data,
            "active_threats": InvasiveSpeciesReportSerializer(latest_reports, many=True).data
        })

class UrbanAnalyzeView(APIView):
    def post(self, request):
        bbox = request.data.get('bbox')
        analysis_type = request.data.get('analysis_type', 'infrastructure')
        
        if not bbox:
            return Response({"error": "BBOX required"}, status=400)
            
        if analysis_type == 'infrastructure':
            data = detect_buildings(bbox)
        elif analysis_type == 'prediction':
            data = predict_development(bbox)
        elif analysis_type == 'urban_filter':
            data = filter_urban_areas(bbox)
            return Response({
                "data": data,
                "overlay": {
                    "image": data["overlay"],
                    "bounds": data["bounds"]
                },
                "legend": {
                    "Городская застройка": "rgba(80, 70, 70, 0.8)",
                    "Природный ландшафт": "rgba(0, 0, 0, 0)"
                }
            })
        else:
            return Response({"error": "Invalid analysis type"}, status=400)
            
        if not data:
            return Response({"error": "Analysis failed"}, status=500)
            
        return Response({
            "data": data,
            "overlay": {
                "image": data["overlay"],
                "bounds": data["bounds"]
            }
        })
