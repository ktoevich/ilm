from rest_framework import serializers

from .models import (
    CropRotation,
    CropType,
    Field,
    GrowthMonitoring,
    InvasiveSpeciesReport,
    SoilAnalysis,
    WeedDatabase,
)


class FieldSerializer(serializers.ModelSerializer):
    """A user's plot.

    ``analyses_count`` and ``latest_fertility_index`` are read from queryset
    annotations when present (see ``FieldListCreateView``); the fallbacks keep
    the serializer usable on an un-annotated instance, e.g. right after create.
    """

    analyses_count = serializers.SerializerMethodField()
    latest_fertility_index = serializers.SerializerMethodField()

    class Meta:
        model = Field
        fields = [
            'id', 'name', 'description', 'bounds_json',
            'center_lat', 'center_lon', 'area_hectares',
            'created_at', 'updated_at', 'analyses_count', 'latest_fertility_index',
        ]
        # The owner is taken from the authenticated request, never from input.
        read_only_fields = ['created_at', 'updated_at']

    def get_analyses_count(self, obj):
        annotated = getattr(obj, 'analyses_count_annotated', None)
        return annotated if annotated is not None else obj.analyses.count()

    def get_latest_fertility_index(self, obj):
        if hasattr(obj, 'latest_fertility_index_annotated'):
            return obj.latest_fertility_index_annotated
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
            'expected_yield_min', 'expected_yield_max',
        ]

    def get_good_predecessors_names(self, obj):
        return [crop.name for crop in obj.good_predecessors.all()]

    def get_bad_predecessors_names(self, obj):
        return [crop.name for crop in obj.bad_predecessors.all()]


class CropTypeBriefSerializer(serializers.ModelSerializer):
    """Compact form for recommendation lists, where the full record is noise."""

    class Meta:
        model = CropType
        fields = ['id', 'name', 'name_latin', 'icon', 'color',
                  'ph_min', 'ph_max', 'vegetation_days']


class OwnedFieldMixin:
    """Reject a ``field`` that belongs to someone else.

    Every record that hangs off a field must stay inside its owner's account.
    Without this check any authenticated device could attach growth records
    or weed reports to another user's plot -- the queryset filters only
    protected reads, not writes.
    """

    def validate_field(self, field):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user is None or field.user_id != getattr(user, 'id', None):
            raise serializers.ValidationError('Этот участок принадлежит другому пользователю.')
        return field


class CropRotationSerializer(OwnedFieldMixin, serializers.ModelSerializer):
    crop_type_name = serializers.CharField(source='crop_type.name', read_only=True)
    field_name = serializers.CharField(source='field.name', read_only=True)

    class Meta:
        model = CropRotation
        fields = [
            'id', 'field', 'field_name', 'crop_type', 'crop_type_name',
            'year', 'season', 'yield_amount', 'notes', 'created_at',
        ]
        read_only_fields = ['created_at']


class SoilAnalysisListSerializer(serializers.ModelSerializer):
    """List form: no ``overlay_image``.

    The overlay is a base64 PNG that routinely exceeds 300 KB. Including it in
    list responses meant a page of 20 analyses shipped several megabytes; fetch
    the detail endpoint when the picture is actually needed.
    """

    field_name = serializers.CharField(source='field.name', read_only=True)
    has_overlay = serializers.SerializerMethodField()

    class Meta:
        model = SoilAnalysis
        fields = [
            'id', 'field', 'field_name', 'analysis_date', 'bbox_json',
            'very_high_percent', 'high_percent', 'moderate_percent',
            'low_percent', 'non_fertile_percent', 'fertility_index',
            'has_overlay', 'notes', 'created_at',
        ]
        read_only_fields = ['created_at', 'fertility_index']

    def get_has_overlay(self, obj):
        return bool(obj.overlay_image)


class SoilAnalysisDetailSerializer(SoilAnalysisListSerializer):
    class Meta(SoilAnalysisListSerializer.Meta):
        fields = SoilAnalysisListSerializer.Meta.fields + ['overlay_image']


class InvasiveSpeciesReportSerializer(OwnedFieldMixin, serializers.ModelSerializer):
    field_name = serializers.CharField(source='field.name', read_only=True)

    class Meta:
        model = InvasiveSpeciesReport
        fields = [
            'id', 'field', 'field_name', 'species_name', 'species_type',
            'severity', 'location_lat', 'location_lon', 'affected_area',
            'status', 'recommendations', 'detected_at', 'resolved_at', 'created_at',
        ]
        read_only_fields = ['created_at']


class InvasiveSpeciesReportDetailSerializer(InvasiveSpeciesReportSerializer):
    class Meta(InvasiveSpeciesReportSerializer.Meta):
        fields = InvasiveSpeciesReportSerializer.Meta.fields + ['image_base64']


class GrowthMonitoringListSerializer(OwnedFieldMixin, serializers.ModelSerializer):
    """List form: excludes the base64 overlay for the same reason as above."""

    field_name = serializers.CharField(source='field.name', read_only=True)
    index_type = serializers.SerializerMethodField()

    class Meta:
        model = GrowthMonitoring
        fields = [
            'id', 'field', 'field_name', 'observation_date',
            'ndvi_mean', 'ndvi_min', 'ndvi_max', 'index_type', 'moisture_index',
            'health_score', 'growth_stage', 'data_source', 'notes', 'created_at',
        ]
        read_only_fields = ['created_at']

    def get_index_type(self, obj):
        # The columns are named after NDVI. Records from Sentinel-2 hold real
        # NDVI; records from the RGB basemap hold Excess Green. ``data_source``
        # tells them apart, and the reader must not mix the two scales.
        return 'NDVI' if obj.data_source == 'sentinel2' else 'ExG'


class GrowthMonitoringDetailSerializer(GrowthMonitoringListSerializer):
    class Meta(GrowthMonitoringListSerializer.Meta):
        fields = GrowthMonitoringListSerializer.Meta.fields + ['ndvi_overlay']


class WeedDatabaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeedDatabase
        fields = [
            'id', 'name', 'name_latin', 'description',
            'control_methods', 'danger_level', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class AnalyzeRequestSerializer(serializers.Serializer):
    """Input for every bbox-driven analysis endpoint."""

    bbox = serializers.JSONField()
    field_id = serializers.IntegerField(required=False, allow_null=True)
    save_result = serializers.BooleanField(required=False, default=False)


class UrbanAnalyzeRequestSerializer(AnalyzeRequestSerializer):
    analysis_type = serializers.ChoiceField(
        choices=['infrastructure', 'prediction', 'urban_filter'],
        required=False,
        default='infrastructure',
    )


class FieldDetectRequestSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)
    radius_m = serializers.IntegerField(required=False, allow_null=True,
                                        min_value=100, max_value=5000)


class PlantingRecommendationRequestSerializer(serializers.Serializer):
    ph = serializers.FloatField(min_value=0, max_value=14)
    nitrogen = serializers.FloatField(min_value=0)
    phosphorus = serializers.FloatField(min_value=0)
    potassium = serializers.FloatField(min_value=0)
    moisture = serializers.FloatField(min_value=0, max_value=100)
