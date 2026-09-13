from django.urls import path

from .views import (
    AnalyzeView,
    CapabilitiesView,
    CropPlantingRecommendationView,
    CropRotationListView,
    CropRotationRecommendationView,
    CropTypeDetailView,
    CropTypeListView,
    DashboardView,
    FieldDetailView,
    FieldDetectView,
    FieldListCreateView,
    GrowthAnalyzeView,
    GrowthMonitoringDetailView,
    GrowthMonitoringListView,
    GrowthTimeSeriesView,
    HealthView,
    InvasiveSpeciesDetailView,
    InvasiveSpeciesListView,
    SessionView,
    SoilAnalysisDetailView,
    SoilAnalysisListView,
    SoilAnalysisTimeSeriesView,
    UrbanAnalyzeView,
    WeedDatabaseListView,
    WeedDetectionView,
)

urlpatterns = [
    path('health/', HealthView.as_view(), name='health'),
    path('session/', SessionView.as_view(), name='session'),
    path('capabilities/', CapabilitiesView.as_view(), name='capabilities'),

    path('analyze/', AnalyzeView.as_view(), name='analyze'),
    path('urban/analyze/', UrbanAnalyzeView.as_view(), name='urban-analyze'),

    path('dashboard/', DashboardView.as_view(), name='dashboard'),

    path('fields/', FieldListCreateView.as_view(), name='field-list'),
    path('fields/detect/', FieldDetectView.as_view(), name='field-detect'),
    path('fields/<int:pk>/', FieldDetailView.as_view(), name='field-detail'),

    path('crops/', CropTypeListView.as_view(), name='crop-list'),
    path('crops/<int:pk>/', CropTypeDetailView.as_view(), name='crop-detail'),
    path('crops/recommend/', CropPlantingRecommendationView.as_view(), name='crop-planting-recommend'),

    path('rotations/', CropRotationListView.as_view(), name='rotation-list'),
    path('rotations/recommend/<int:field_id>/', CropRotationRecommendationView.as_view(),
         name='rotation-recommend'),

    path('soil-analyses/', SoilAnalysisListView.as_view(), name='soil-analysis-list'),
    path('soil-analyses/<int:pk>/', SoilAnalysisDetailView.as_view(), name='soil-analysis-detail'),
    path('soil-analyses/timeseries/<int:field_id>/', SoilAnalysisTimeSeriesView.as_view(),
         name='soil-analysis-timeseries'),

    path('growth/', GrowthMonitoringListView.as_view(), name='growth-list'),
    path('growth/<int:pk>/', GrowthMonitoringDetailView.as_view(), name='growth-detail'),
    path('growth/analyze/', GrowthAnalyzeView.as_view(), name='growth-analyze'),
    path('growth/timeseries/<int:field_id>/', GrowthTimeSeriesView.as_view(), name='growth-timeseries'),

    path('invasive/', InvasiveSpeciesListView.as_view(), name='invasive-list'),
    path('invasive/<int:pk>/', InvasiveSpeciesDetailView.as_view(), name='invasive-detail'),
    path('weeds/detect/', WeedDetectionView.as_view(), name='weed-detect'),
    path('weeds/database/', WeedDatabaseListView.as_view(), name='weed-database'),
]
