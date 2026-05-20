from django.contrib import admin
from .models import (
    Field, CropType, CropRotation, SoilAnalysis,
    InvasiveSpeciesReport, GrowthMonitoring, WeedDatabase
)

@admin.register(Field)
class FieldAdmin(admin.ModelAdmin):
    list_display = ['name', 'area_hectares', 'center_lat', 'center_lon', 'created_at']
    list_filter = ['created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'description', 'area_hectares')
        }),
        ('Местоположение', {
            'fields': ('bounds_json', 'center_lat', 'center_lon')
        }),
        ('Метаданные', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(CropType)
class CropTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'name_latin', 'min_return_interval', 'color']
    list_filter = ['min_return_interval']
    search_fields = ['name', 'name_latin']
    filter_horizontal = ['good_predecessors', 'bad_predecessors']

@admin.register(CropRotation)
class CropRotationAdmin(admin.ModelAdmin):
    list_display = ['field', 'crop_type', 'year', 'season', 'yield_amount', 'created_at']
    list_filter = ['year', 'season', 'crop_type']
    search_fields = ['field__name', 'crop_type__name']
    autocomplete_fields = ['field', 'crop_type']

@admin.register(SoilAnalysis)
class SoilAnalysisAdmin(admin.ModelAdmin):
    list_display = ['field', 'analysis_date', 'fertility_index', 'very_high_percent', 'high_percent', 'moderate_percent']
    list_filter = ['analysis_date', 'field']
    search_fields = ['field__name']
    readonly_fields = ['created_at', 'fertility_index']
    date_hierarchy = 'analysis_date'
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('field', 'analysis_date', 'bbox_json')
        }),
        ('Статистика плодородия', {
            'fields': ('very_high_percent', 'high_percent', 'moderate_percent', 'low_percent', 'non_fertile_percent', 'fertility_index')
        }),
        ('Дополнительно', {
            'fields': ('overlay_image', 'notes', 'created_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(InvasiveSpeciesReport)
class InvasiveSpeciesReportAdmin(admin.ModelAdmin):
    list_display = ['species_name', 'field', 'species_type', 'severity', 'status', 'detected_at']
    list_filter = ['species_type', 'severity', 'status', 'detected_at']
    search_fields = ['species_name', 'field__name']
    readonly_fields = ['created_at', 'detected_at']
    date_hierarchy = 'detected_at'
    list_editable = ['status']
    
    fieldsets = (
        ('Обнаружение', {
            'fields': ('field', 'species_name', 'species_type', 'severity', 'status')
        }),
        ('Местоположение', {
            'fields': ('location_lat', 'location_lon', 'affected_area')
        }),
        ('Данные', {
            'fields': ('image_base64', 'recommendations'),
            'classes': ('collapse',)
        }),
        ('Даты', {
            'fields': ('detected_at', 'resolved_at', 'created_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(GrowthMonitoring)
class GrowthMonitoringAdmin(admin.ModelAdmin):
    list_display = ['field', 'observation_date', 'ndvi_mean', 'health_score', 'growth_stage', 'data_source']
    list_filter = ['observation_date', 'growth_stage', 'data_source']
    search_fields = ['field__name']
    readonly_fields = ['created_at']
    date_hierarchy = 'observation_date'
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('field', 'observation_date', 'data_source')
        }),
        ('NDVI показатели', {
            'fields': ('ndvi_mean', 'ndvi_min', 'ndvi_max')
        }),
        ('Состояние', {
            'fields': ('moisture_index', 'health_score', 'growth_stage')
        }),
        ('Дополнительно', {
            'fields': ('ndvi_overlay', 'notes', 'created_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(WeedDatabase)
class WeedDatabaseAdmin(admin.ModelAdmin):
    list_display = ['name', 'name_latin', 'danger_level', 'created_at']
    list_filter = ['danger_level']
    search_fields = ['name', 'name_latin']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'name_latin', 'description', 'danger_level')
        }),
        ('Идентификация', {
            'fields': ('color_signature', 'texture_features', 'reference_images_json'),
            'classes': ('collapse',)
        }),
        ('Методы борьбы', {
            'fields': ('control_methods',)
        }),
        ('Метаданные', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
