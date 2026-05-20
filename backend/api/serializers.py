from rest_framework import serializers
from .models import (
    Field, CropType, CropRotation, SoilAnalysis,
    InvasiveSpeciesReport, GrowthMonitoring, WeedDatabase
)

class FieldSerializer(serializers.ModelSerializer):
    analyses_count = serializers.SerializerMethodField()
    latest_fertility_index = serializers.SerializerMethodField()
    
    class Meta:
        model = Field
        fields = [
            'id', 'name', 'description', 'bounds_json',
            'center_lat', 'center_lon', 'area_hectares',
            'created_at', 'updated_at', 'analyses_count', 'latest_fertility_index'
        ]
        read_only_fields = ['created_at', 'updated_at']
    
    def get_analyses_count(self, obj):
        return obj.analyses.count()
    
    def get_latest_fertility_index(self, obj):
        latest = obj.analyses.first()
        return latest.fertility_index if latest else None

class CropTypeSerializer(serializers.ModelSerializer):
    good_predecessors_names = serializers.SerializerMethodField()
    bad_predecessors_names = serializers.SerializerMethodField()
    planting_season_display = serializers.CharField(source='get_planting_season_display', read_only=True)
    nitrogen_requirement_display = serializers.CharField(source='get_nitrogen_requirement_display', read_only=True)
    phosphorus_requirement_display = serializers.CharField(source='get_phosphorus_requirement_display', read_only=True)
    potassium_requirement_display = serializers.CharField(source='get_potassium_requirement_display', read_only=True)
    
    class Meta:
        model = CropType
        fields = [
            'id', 'name', 'name_latin', 'description', 'icon', 'color',
            'good_predecessors', 'bad_predecessors', 'min_return_interval',
            'good_predecessors_names', 'bad_predecessors_names',
            'ph_min', 'ph_max', 'temp_min', 'temp_optimal',
            'nitrogen_requirement', 'nitrogen_requirement_display',
            'phosphorus_requirement', 'phosphorus_requirement_display',
            'potassium_requirement', 'potassium_requirement_display',
            'moisture_min', 'moisture_max',
            'planting_season', 'planting_season_display', 'vegetation_days',
            'planting_depth_cm', 'spacing_cm', 'row_spacing_cm',
            'planting_instructions', 'care_instructions', 'harvest_instructions',
            'expected_yield_min', 'expected_yield_max'
        ]
    
    def get_good_predecessors_names(self, obj):
        return list(obj.good_predecessors.values_list('name', flat=True))
    
    def get_bad_predecessors_names(self, obj):
        return list(obj.bad_predecessors.values_list('name', flat=True))

class CropRotationSerializer(serializers.ModelSerializer):
    crop_type_name = serializers.CharField(source='crop_type.name', read_only=True)
    field_name = serializers.CharField(source='field.name', read_only=True)
    
    class Meta:
        model = CropRotation
        fields = [
            'id', 'field', 'field_name', 'crop_type', 'crop_type_name',
            'year', 'season', 'yield_amount', 'notes', 'created_at'
        ]
        read_only_fields = ['created_at']

class SoilAnalysisSerializer(serializers.ModelSerializer):
    field_name = serializers.CharField(source='field.name', read_only=True)
    
    class Meta:
        model = SoilAnalysis
        fields = [
            'id', 'field', 'field_name', 'analysis_date', 'bbox_json',
            'very_high_percent', 'high_percent', 'moderate_percent',
            'low_percent', 'non_fertile_percent', 'fertility_index',
            'overlay_image', 'notes', 'created_at'
        ]
        read_only_fields = ['created_at', 'fertility_index']

class SoilAnalysisTimeSeriesSerializer(serializers.ModelSerializer):
    class Meta:
        model = SoilAnalysis
        fields = [
            'id', 'analysis_date', 'fertility_index',
            'very_high_percent', 'high_percent', 'moderate_percent',
            'low_percent', 'non_fertile_percent'
        ]

class InvasiveSpeciesReportSerializer(serializers.ModelSerializer):
    field_name = serializers.CharField(source='field.name', read_only=True)
    
    class Meta:
        model = InvasiveSpeciesReport
        fields = [
            'id', 'field', 'field_name', 'species_name', 'species_type',
            'severity', 'location_lat', 'location_lon', 'affected_area',
            'image_base64', 'status', 'recommendations',
            'detected_at', 'resolved_at', 'created_at'
        ]
        read_only_fields = ['created_at']

class GrowthMonitoringSerializer(serializers.ModelSerializer):
    field_name = serializers.CharField(source='field.name', read_only=True)
    
    class Meta:
        model = GrowthMonitoring
        fields = [
            'id', 'field', 'field_name', 'observation_date',
            'ndvi_mean', 'ndvi_min', 'ndvi_max', 'moisture_index',
            'health_score', 'growth_stage', 'ndvi_overlay',
            'data_source', 'notes', 'created_at'
        ]
        read_only_fields = ['created_at']

class GrowthTimeSeriesSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrowthMonitoring
        fields = [
            'id', 'observation_date', 'ndvi_mean', 'health_score', 'growth_stage'
        ]


class WeedDatabaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeedDatabase
        fields = [
            'id', 'name', 'name_latin', 'description',
            'color_signature', 'texture_features', 'reference_images_json',
            'control_methods', 'danger_level', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

class CropRotationRecommendationSerializer(serializers.Serializer):
    recommended_crops = serializers.ListField(child=serializers.DictField())
    not_recommended_crops = serializers.ListField(child=serializers.DictField())
    history = CropRotationSerializer(many=True)
    warnings = serializers.ListField(child=serializers.CharField())