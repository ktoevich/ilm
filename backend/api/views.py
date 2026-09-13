"""API endpoints.

Two rules hold everywhere in this module:

1. Every queryset is scoped to ``request.user``. There is no anonymous
   fallback -- the previous ``return Field.objects.all()`` for unauthenticated
   callers meant any visitor could read, edit and delete anyone's records.
2. Any object referenced by id in a request body (``field_id``) is resolved
   through the owner-scoped queryset, so an id belonging to somebody else is a
   404, not a silent cross-tenant write.
"""

import json
import logging
from datetime import date

from django.db.models import Count, OuterRef, Subquery, Sum
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .analysis import fertility, urban, vegetation, weeds
from .analysis.environment import analyze_environment
from .analysis.imagery import AnalysisError
from .models import (
    CropRotation,
    CropType,
    Field,
    GrowthMonitoring,
    InvasiveSpeciesReport,
    SoilAnalysis,
    WeedDatabase,
)
from .permissions import IsOwner
from .serializers import (
    AnalyzeRequestSerializer,
    CropRotationSerializer,
    CropTypeBriefSerializer,
    CropTypeSerializer,
    FieldDetectRequestSerializer,
    FieldSerializer,
    GrowthMonitoringDetailSerializer,
    GrowthMonitoringListSerializer,
    InvasiveSpeciesReportDetailSerializer,
    InvasiveSpeciesReportSerializer,
    PlantingRecommendationRequestSerializer,
    SoilAnalysisDetailSerializer,
    SoilAnalysisListSerializer,
    UrbanAnalyzeRequestSerializer,
    WeedDatabaseSerializer,
)
from .services import buildings, osm_fields, sentinel, worldcover
from .validators import BBoxError, parse_bbox

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base classes
# ---------------------------------------------------------------------------
class OwnedQuerysetMixin:
    """Restrict every queryset to the requesting user."""

    model = None
    throttle_scope = 'crud'

    def get_queryset(self):
        return self.model.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class AnalysisView(APIView):
    """Shared plumbing for the bbox-driven analysis endpoints."""

    throttle_scope = 'analysis'
    request_serializer = AnalyzeRequestSerializer

    def parse_request(self, request):
        """Validate the payload, returning ``(bbox, field, save_result, data)``.

        Raises DRF validation errors for bad input; the bbox check in
        particular is what stops a request asking for the whole planet.
        """
        serializer = self.request_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            bbox = parse_bbox(data.get('bbox'))
        except BBoxError as exc:
            raise DRFValidationError({'bbox': str(exc)}) from exc

        field = None
        field_id = data.get('field_id')
        if field_id:
            # Owner-scoped: another user's field id is indistinguishable from a
            # non-existent one.
            field = get_object_or_404(Field, id=field_id, user=request.user)

        return bbox, field, bool(data.get('save_result')), data


def analysis_error_response(exc):
    logger.info('Analysis could not be completed: %s', exc)
    return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
class SessionView(APIView):
    """Confirms the device identity the client is currently using."""

    throttle_scope = 'crud'

    def get(self, request):
        return Response({
            'authenticated': True,
            'user_id': request.user.id,
            'fields_count': Field.objects.filter(user=request.user).count(),
            'capabilities': {
                'sentinel2_ndvi': sentinel.is_available(),
                'field_detection': osm_fields.is_available(),
            },
        })


# ---------------------------------------------------------------------------
# Fertility
# ---------------------------------------------------------------------------
class AnalyzeView(AnalysisView):
    def post(self, request):
        bbox, field, save_result, _ = self.parse_request(request)

        try:
            result = fertility.analyze_fertility(bbox)
            environment = analyze_environment(bbox)
        except AnalysisError as exc:
            return analysis_error_response(exc)

        stats = result['stats']

        if save_result and field is not None:
            analysis = SoilAnalysis(
                user=request.user,
                field=field,
                bbox_json=json.dumps(list(bbox)),
                very_high_percent=stats['very_high'],
                high_percent=stats['high'],
                moderate_percent=stats['moderate'],
                low_percent=stats['low'],
                non_fertile_percent=stats['desert'] + stats['water'] + stats.get('built_up', 0.0),
                overlay_image=result['overlay'],
                notes=f"Метод: {result['method']}",
            )
            analysis.calculate_fertility_index()
            analysis.save()

        return Response({
            'overlay': {'image': result['overlay'], 'bounds': result['bounds']},
            'stats': stats,
            'legend': result['legend'],
            'method': result['method'],
            'imagery': result['imagery'],
            'components': result.get('components', {}),
            'environment': environment,
        })


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------
class FieldListCreateView(OwnedQuerysetMixin, generics.ListCreateAPIView):
    model = Field
    serializer_class = FieldSerializer

    def get_queryset(self):
        latest_index = (
            SoilAnalysis.objects
            .filter(field=OuterRef('pk'))
            .order_by('-analysis_date')
            .values('fertility_index')[:1]
        )
        # Annotating removes the two extra queries the serializer used to run
        # per field.
        return (
            Field.objects
            .filter(user=self.request.user)
            .annotate(
                analyses_count_annotated=Count('analyses', distinct=True),
                latest_fertility_index_annotated=Subquery(latest_index),
            )
            # annotate() adds a GROUP BY, which drops Meta.ordering; pagination
            # needs a deterministic order.
            .order_by('-created_at', '-id')
        )


class FieldDetailView(OwnedQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    model = Field
    serializer_class = FieldSerializer
    permission_classes = generics.RetrieveUpdateDestroyAPIView.permission_classes + [IsOwner]


class FieldDetectView(APIView):
    """Field boundaries at a point, so the user need not draw one.

    Backed by OpenStreetMap through Overpass -- free and keyless. It returns
    what has been *mapped*, so coverage varies: dense across Europe, absent in
    places. An unmapped location answers 404 rather than a guessed rectangle.
    """

    throttle_scope = 'analysis'

    def post(self, request):
        serializer = FieldDetectRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        radius = params.get('radius_m') or osm_fields.DEFAULT_RADIUS_M
        features = osm_fields.lookup_fields(params['lat'], params['lon'], radius)

        if not features:
            return Response(
                {'error': 'В OpenStreetMap нет размеченных участков рядом с этой точкой'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({
            'features': features[:50],
            'source': 'OpenStreetMap',
        })


class CapabilitiesView(APIView):
    """Which data sources are configured, so the UI can adapt."""

    throttle_scope = 'crud'

    def get(self, request):
        return Response({
            'sentinel2_ndvi': sentinel.is_available(),
            'field_detection': osm_fields.is_available(),
            'land_cover': worldcover.is_available(),
            'buildings': buildings.is_available(),
            'sources': {
                'imagery': 'Sentinel-2 L2A (Microsoft Planetary Computer)',
                'productivity': 'Sentinel-2 NDVI за несколько сезонов (Microsoft Planetary Computer)',
                'land_cover': 'ESA WorldCover 2020/2021 (Microsoft Planetary Computer)',
                'buildings': 'OpenStreetMap',
                'field_boundaries': 'OpenStreetMap',
                'soil': 'ISRIC SoilGrids v2.0 с квантилями неопределённости',
                'weather': 'Open-Meteo',
                'elevation': 'Copernicus GLO-90',
            },
        })


# ---------------------------------------------------------------------------
# Crop catalogue (read-only over the API; edited through the admin)
# ---------------------------------------------------------------------------
class CropTypeListView(generics.ListAPIView):
    """Shared reference data.

    Read-only on purpose: this table is global, so an open write endpoint let
    any visitor rewrite the agronomic thresholds every recommendation uses.
    """

    throttle_scope = 'crud'
    serializer_class = CropTypeSerializer
    queryset = CropType.objects.prefetch_related('good_predecessors', 'bad_predecessors')


class CropTypeDetailView(generics.RetrieveAPIView):
    throttle_scope = 'crud'
    serializer_class = CropTypeSerializer
    queryset = CropType.objects.prefetch_related('good_predecessors', 'bad_predecessors')


class WeedDatabaseListView(generics.ListAPIView):
    throttle_scope = 'crud'
    queryset = WeedDatabase.objects.all()
    serializer_class = WeedDatabaseSerializer


# ---------------------------------------------------------------------------
# Crop rotation
# ---------------------------------------------------------------------------
class CropRotationListView(OwnedQuerysetMixin, generics.ListCreateAPIView):
    model = CropRotation
    serializer_class = CropRotationSerializer

    def get_queryset(self):
        queryset = (
            CropRotation.objects
            .filter(user=self.request.user)
            .select_related('field', 'crop_type')
        )
        field_id = self.request.query_params.get('field_id')
        if field_id:
            queryset = queryset.filter(field_id=field_id)
        return queryset

    def perform_create(self, serializer):
        # The field must belong to the caller, otherwise rotations could be
        # attached to someone else's plot.
        field = serializer.validated_data['field']
        if field.user_id != self.request.user.id:
            raise DRFValidationError({'field': 'Этот участок принадлежит другому пользователю.'})
        serializer.save(user=self.request.user)


class CropRotationRecommendationView(APIView):
    throttle_scope = 'crud'

    def get(self, request, field_id):
        field = get_object_or_404(Field, id=field_id, user=request.user)
        last_rotation = (
            CropRotation.objects
            .filter(field=field, user=request.user)
            .select_related('crop_type')
            .order_by('-year')
            .first()
        )

        recommendations = []
        if last_rotation:
            previous = last_rotation.crop_type
            for crop in previous.good_successors.all():
                recommendations.append({
                    'crop': CropTypeBriefSerializer(crop).data,
                    'reason': f'Хороший последователь для «{previous.name}»',
                })

        if not recommendations:
            recommendations = [
                {'crop': CropTypeBriefSerializer(crop).data, 'reason': 'Базовая рекомендация'}
                for crop in CropType.objects.all()[:3]
            ]

        return Response({
            'field': field.name,
            'previous_crop': last_rotation.crop_type.name if last_rotation else None,
            'recommendations': recommendations,
        })


class CropPlantingRecommendationView(APIView):
    throttle_scope = 'crud'

    def post(self, request):
        serializer = PlantingRecommendationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        results = []
        for crop in CropType.objects.all():
            compatibility = crop.check_soil_compatibility(
                params['ph'], params['nitrogen'], params['phosphorus'],
                params['potassium'], params['moisture'],
            )
            results.append({
                'crop': CropTypeBriefSerializer(crop).data,
                'compatibility': compatibility,
            })

        results.sort(key=lambda item: item['compatibility']['compatibility_percent'], reverse=True)
        return Response(results)


# ---------------------------------------------------------------------------
# Soil analyses
# ---------------------------------------------------------------------------
class SoilAnalysisListView(OwnedQuerysetMixin, generics.ListAPIView):
    model = SoilAnalysis
    serializer_class = SoilAnalysisListSerializer

    def get_queryset(self):
        queryset = SoilAnalysis.objects.filter(user=self.request.user).select_related('field')
        field_id = self.request.query_params.get('field_id')
        if field_id:
            queryset = queryset.filter(field_id=field_id)
        return queryset


class SoilAnalysisDetailView(OwnedQuerysetMixin, generics.RetrieveDestroyAPIView):
    """Single analysis, including the overlay image."""

    model = SoilAnalysis
    serializer_class = SoilAnalysisDetailSerializer
    permission_classes = generics.RetrieveDestroyAPIView.permission_classes + [IsOwner]


class SoilAnalysisTimeSeriesView(APIView):
    throttle_scope = 'crud'

    def get(self, request, field_id):
        field = get_object_or_404(Field, id=field_id, user=request.user)
        analyses = (
            SoilAnalysis.objects
            .filter(field=field, user=request.user)
            .order_by('analysis_date')
            .values('analysis_date', 'fertility_index', 'very_high_percent',
                    'high_percent', 'moderate_percent', 'low_percent')
        )

        return Response({
            'dates': [item['analysis_date'].strftime('%Y-%m-%d') for item in analyses],
            'fertility_index': [item['fertility_index'] for item in analyses],
            'very_high': [item['very_high_percent'] for item in analyses],
            'high': [item['high_percent'] for item in analyses],
            'moderate': [item['moderate_percent'] for item in analyses],
            'low': [item['low_percent'] for item in analyses],
        })


# ---------------------------------------------------------------------------
# Growth monitoring
# ---------------------------------------------------------------------------
class GrowthMonitoringListView(OwnedQuerysetMixin, generics.ListCreateAPIView):
    model = GrowthMonitoring
    serializer_class = GrowthMonitoringListSerializer

    def get_queryset(self):
        return GrowthMonitoring.objects.filter(user=self.request.user).select_related('field')


class GrowthMonitoringDetailView(OwnedQuerysetMixin, generics.RetrieveDestroyAPIView):
    model = GrowthMonitoring
    serializer_class = GrowthMonitoringDetailSerializer
    permission_classes = generics.RetrieveDestroyAPIView.permission_classes + [IsOwner]


class GrowthAnalyzeView(AnalysisView):
    def post(self, request):
        bbox, field, save_result, _ = self.parse_request(request)

        try:
            result = vegetation.analyze_vegetation(bbox)
        except AnalysisError as exc:
            return analysis_error_response(exc)

        if save_result and field is not None:
            GrowthMonitoring.objects.update_or_create(
                field=field,
                observation_date=date.today(),
                defaults={
                    'user': request.user,
                    # The columns are named after NDVI. ``data_source`` records
                    # whether the value is real NDVI (Sentinel-2) or ExG from
                    # the RGB basemap; the serializer reports ``index_type``
                    # from it so the two scales are never mixed.
                    'ndvi_mean': result['index_mean'],
                    'ndvi_min': result['index_min'],
                    'ndvi_max': result['index_max'],
                    'moisture_index': result.get('moisture_index'),
                    'health_score': result['health_score'],
                    'growth_stage': result['growth_stage'],
                    'ndvi_overlay': result['overlay'],
                    'data_source': 'sentinel2' if result['index_type'] == 'NDVI' else 'local_analysis',
                },
            )

        return Response({
            'vegetation': {
                'index_type': result['index_type'],
                'index_label': result['index_label'],
                'index_mean': result['index_mean'],
                'index_min': result['index_min'],
                'index_max': result['index_max'],
                'health_score': result['health_score'],
                'growth_stage': result['growth_stage'],
                'moisture_index': result.get('moisture_index'),
                'moisture_label': result.get('moisture_label'),
                'reference_ndvi': result.get('reference_ndvi'),
                'reference_years': result.get('reference_years', []),
                'ndvi_anomaly': result.get('ndvi_anomaly'),
                'anomaly_label': result.get('anomaly_label'),
            },
            'overlay': {'image': result['overlay'], 'bounds': result['bounds']},
            'method': result['method'],
            'imagery': result['imagery'],
        })


class GrowthTimeSeriesView(APIView):
    throttle_scope = 'crud'

    def get(self, request, field_id):
        field = get_object_or_404(Field, id=field_id, user=request.user)
        records = list(
            GrowthMonitoring.objects
            .filter(field=field, user=request.user)
            .order_by('observation_date')
        )

        return Response({
            'index_type': 'ExG',
            'dates': [record.observation_date.strftime('%Y-%m-%d') for record in records],
            'index_mean': [record.ndvi_mean for record in records],
            'health_score': [record.health_score for record in records],
            'summary': vegetation.summarise_history(records),
        })


# ---------------------------------------------------------------------------
# Invasive species / weeds
# ---------------------------------------------------------------------------
class InvasiveSpeciesListView(OwnedQuerysetMixin, generics.ListCreateAPIView):
    model = InvasiveSpeciesReport
    serializer_class = InvasiveSpeciesReportSerializer

    def get_queryset(self):
        return InvasiveSpeciesReport.objects.filter(user=self.request.user).select_related('field')


class InvasiveSpeciesDetailView(OwnedQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    model = InvasiveSpeciesReport
    serializer_class = InvasiveSpeciesReportDetailSerializer
    permission_classes = generics.RetrieveUpdateDestroyAPIView.permission_classes + [IsOwner]


class WeedDetectionView(AnalysisView):
    def post(self, request):
        bbox, field, save_result, _ = self.parse_request(request)

        try:
            result = weeds.detect_weeds(bbox)
        except AnalysisError as exc:
            return analysis_error_response(exc)

        if save_result and field is not None:
            InvasiveSpeciesReport.objects.bulk_create([
                InvasiveSpeciesReport(
                    user=request.user,
                    field=field,
                    species_name=detection['name'],
                    severity=detection['severity'],
                    location_lat=detection['lat'],
                    location_lon=detection['lon'],
                    affected_area=detection['area'],
                    recommendations=detection['recommendations'],
                )
                # One row per contour used to mean hundreds of inserts for a
                # busy scene; cap it at the patches that actually matter.
                for detection in result['detections'][:50]
            ])

        return Response(result)


# ---------------------------------------------------------------------------
# Urban
# ---------------------------------------------------------------------------
class UrbanAnalyzeView(AnalysisView):
    request_serializer = UrbanAnalyzeRequestSerializer

    _PIPELINES = {
        'infrastructure': urban.detect_buildings,
        'prediction': urban.predict_development,
        'urban_filter': urban.filter_urban_areas,
    }

    def post(self, request):
        bbox, _field, _save, data = self.parse_request(request)
        pipeline = self._PIPELINES[data['analysis_type']]

        try:
            result = pipeline(bbox)
        except AnalysisError as exc:
            return analysis_error_response(exc)

        response = {
            'data': result,
            'overlay': {'image': result['overlay'], 'bounds': result['bounds']},
            'method': result['method'],
        }
        if 'legend' in result:
            response['legend'] = result['legend']
        return Response(response)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class DashboardView(APIView):
    throttle_scope = 'crud'

    def get(self, request):
        user = request.user

        # Aggregate in the database instead of loading every row into memory.
        totals = Field.objects.filter(user=user).aggregate(
            fields_count=Count('id'),
            total_area=Sum('area_hectares'),
        )

        active_reports = InvasiveSpeciesReport.objects.filter(user=user, status='detected')
        latest_analyses = (
            SoilAnalysis.objects.filter(user=user).select_related('field')[:5]
        )

        return Response({
            'stats': {
                'fields_count': totals['fields_count'] or 0,
                'total_area_ha': round(totals['total_area'] or 0.0, 2),
                # count() on the full queryset -- slicing first capped this at 5.
                'active_reports': active_reports.count(),
            },
            'recent_analyses': SoilAnalysisListSerializer(latest_analyses, many=True).data,
            'active_threats': InvasiveSpeciesReportSerializer(
                active_reports.select_related('field')[:5], many=True
            ).data,
        })
