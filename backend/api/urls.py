from django.urls import path
from .views import (
    AnalyzeView,
    FieldListCreateView, FieldDetailView,
    CropTypeListView, CropTypeDetailView, CropRotationListView, 
    CropRotationRecommendationView, CropPlantingRecommendationView,
    SoilAnalysisListView, SoilAnalysisTimeSeriesView,
    GrowthMonitoringListView, GrowthAnalyzeView, GrowthTimeSeriesView,
    InvasiveSpeciesListView, InvasiveSpeciesDetailView, WeedDetectionView, WeedDatabaseListView,
    DashboardView, UrbanAnalyzeView
)

urlpatterns = [
    path('analyze/', AnalyzeView.as_view(), name='analyze'),
    path('urban/analyze/', UrbanAnalyzeView.as_view(), name='urban-analyze'),

    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    
    path('fields/', FieldListCreateView.as_view(), name='field-list'),
    path('fields/<int:pk>/', FieldDetailView.as_view(), name='field-detail'),
    
    path('crops/', CropTypeListView.as_view(), name='crop-list'),
    path('crops/<int:pk>/', CropTypeDetailView.as_view(), name='crop-detail'),
    path('crops/recommend/', CropPlantingRecommendationView.as_view(), name='crop-planting-recommend'),
    path('rotations/', CropRotationListView.as_view(), name='rotation-list'),
    path('rotations/recommend/<int:field_id>/', CropRotationRecommendationView.as_view(), name='rotation-recommend'),
    
    path('soil-analyses/', SoilAnalysisListView.as_view(), name='soil-analysis-list'),
    path('soil-analyses/timeseries/<int:field_id>/', SoilAnalysisTimeSeriesView.as_view(), name='soil-analysis-timeseries'),
    
    path('growth/', GrowthMonitoringListView.as_view(), name='growth-list'),
    path('growth/analyze/', GrowthAnalyzeView.as_view(), name='growth-analyze'),
    path('growth/timeseries/<int:field_id>/', GrowthTimeSeriesView.as_view(), name='growth-timeseries'),
    
    path('invasive/', InvasiveSpeciesListView.as_view(), name='invasive-list'),
    path('invasive/<int:pk>/', InvasiveSpeciesDetailView.as_view(), name='invasive-detail'),
    path('weeds/detect/', WeedDetectionView.as_view(), name='weed-detect'),
    path('weeds/database/', WeedDatabaseListView.as_view(), name='weed-database'),
    
]
