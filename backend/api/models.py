from django.db import models
from django.utils import timezone
import json

class Field(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название участка")
    description = models.TextField(blank=True, null=True, verbose_name="Описание")
    bounds_json = models.TextField(verbose_name="Границы участка (JSON)")
    center_lat = models.FloatField(verbose_name="Широта центра")
    center_lon = models.FloatField(verbose_name="Долгота центра")
    area_hectares = models.FloatField(default=0, verbose_name="Площадь (га)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Поле"
        verbose_name_plural = "Поля"
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    def get_bounds(self):
        return json.loads(self.bounds_json)
    
    def set_bounds(self, bounds):
        self.bounds_json = json.dumps(bounds)

class CropType(models.Model):
    name = models.CharField(max_length=100, verbose_name="Название культуры")
    name_latin = models.CharField(max_length=100, blank=True, null=True, verbose_name="Латинское название")
    description = models.TextField(blank=True, null=True, verbose_name="Описание")
    icon = models.CharField(max_length=10, default="🌱", verbose_name="Иконка (эмодзи)")
    good_predecessors = models.ManyToManyField(
        'self', 
        blank=True, 
        symmetrical=False, 
        related_name='good_successors',
        verbose_name="Хорошие предшественники"
    )
    bad_predecessors = models.ManyToManyField(
        'self', 
        blank=True, 
        symmetrical=False, 
        related_name='bad_successors',
        verbose_name="Плохие предшественники"
    )
    min_return_interval = models.IntegerField(default=2, verbose_name="Мин. интервал возврата (лет)")
    color = models.CharField(max_length=7, default="#4CAF50", verbose_name="Цвет")
    ph_min = models.FloatField(default=6.0, verbose_name="Мин. pH почвы")
    ph_max = models.FloatField(default=7.5, verbose_name="Макс. pH почвы")
    temp_min = models.FloatField(default=5.0, verbose_name="Мин. температура (°C)")
    temp_optimal = models.FloatField(default=20.0, verbose_name="Оптимальная температура (°C)")
    nitrogen_requirement = models.CharField(max_length=10, choices=[
        ('low', 'Низкая'),
        ('medium', 'Средняя'),
        ('high', 'Высокая'),
    ], default='medium', verbose_name="Потребность в азоте (N)")
    phosphorus_requirement = models.CharField(max_length=10, choices=[
        ('low', 'Низкая'),
        ('medium', 'Средняя'),
        ('high', 'Высокая'),
    ], default='medium', verbose_name="Потребность в фосфоре (P)")
    potassium_requirement = models.CharField(max_length=10, choices=[
        ('low', 'Низкая'),
        ('medium', 'Средняя'),
        ('high', 'Высокая'),
    ], default='medium', verbose_name="Потребность в калии (K)")
    moisture_min = models.IntegerField(default=20, verbose_name="Мин. влажность почвы (%)")
    moisture_max = models.IntegerField(default=60, verbose_name="Макс. влажность почвы (%)")
    planting_season = models.CharField(max_length=20, choices=[
        ('spring', 'Весна'),
        ('summer', 'Лето'),
        ('autumn', 'Осень'),
        ('winter', 'Зима'),
        ('any', 'Любой'),
    ], default='spring', verbose_name="Сезон посадки")
    vegetation_days = models.IntegerField(default=90, verbose_name="Период вегетации (дней)")
    planting_depth_cm = models.FloatField(default=3.0, verbose_name="Глубина посадки (см)")
    spacing_cm = models.IntegerField(default=30, verbose_name="Расстояние между растениями (см)")
    row_spacing_cm = models.IntegerField(default=50, verbose_name="Расстояние между рядами (см)")
    planting_instructions = models.TextField(blank=True, null=True, verbose_name="Инструкции по посадке")
    care_instructions = models.TextField(blank=True, null=True, verbose_name="Уход за культурой")
    harvest_instructions = models.TextField(blank=True, null=True, verbose_name="Инструкции по сбору урожая")
    expected_yield_min = models.FloatField(default=1.0, verbose_name="Мин. урожайность (т/га)")
    expected_yield_max = models.FloatField(default=5.0, verbose_name="Макс. урожайность (т/га)")
    
    class Meta:
        verbose_name = "Тип культуры"
        verbose_name_plural = "Типы культур"
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def check_soil_compatibility(self, ph, nitrogen, phosphorus, potassium, moisture):
        score = 0
        max_score = 5
        issues = []
        recommendations = []
        
        if self.ph_min <= ph <= self.ph_max:
            score += 1
        else:
            if ph < self.ph_min:
                issues.append(f"pH почвы ({ph}) ниже требуемого ({self.ph_min})")
                recommendations.append("Рекомендуется известкование почвы")
            else:
                issues.append(f"pH почвы ({ph}) выше требуемого ({self.ph_max})")
                recommendations.append("Рекомендуется гипсование или добавление серы")
        
        n_thresholds = {'low': 30, 'medium': 45, 'high': 60}
        n_req = n_thresholds.get(self.nitrogen_requirement, 45)
        if nitrogen >= n_req * 0.7:
            score += 1
        else:
            issues.append(f"Недостаточно азота (N): {nitrogen} мг/кг")
            recommendations.append("Внесите азотные удобрения (аммиачная селитра, мочевина)")
        
        p_thresholds = {'low': 15, 'medium': 25, 'high': 40}
        p_req = p_thresholds.get(self.phosphorus_requirement, 25)
        if phosphorus >= p_req * 0.7:
            score += 1
        else:
            issues.append(f"Недостаточно фосфора (P): {phosphorus} мг/кг")
            recommendations.append("Внесите фосфорные удобрения (суперфосфат)")
        
        k_thresholds = {'low': 100, 'medium': 180, 'high': 250}
        k_req = k_thresholds.get(self.potassium_requirement, 180)
        if potassium >= k_req * 0.7:
            score += 1
        else:
            issues.append(f"Недостаточно калия (K): {potassium} мг/кг")
            recommendations.append("Внесите калийные удобрения (хлористый калий)")
        
        if self.moisture_min <= moisture <= self.moisture_max:
            score += 1
        else:
            if moisture < self.moisture_min:
                issues.append(f"Влажность почвы ({moisture}%) ниже требуемой")
                recommendations.append("Необходим полив перед посадкой")
            else:
                issues.append(f"Влажность почвы ({moisture}%) выше требуемой")
                recommendations.append("Обеспечьте дренаж или подождите подсыхания")
        
        compatibility_percent = int((score / max_score) * 100)
        
        return {
            'compatible': score >= 3,
            'score': score,
            'max_score': max_score,
            'compatibility_percent': compatibility_percent,
            'issues': issues,
            'recommendations': recommendations
        }

class CropRotation(models.Model):
    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name='rotations', verbose_name="Поле")
    crop_type = models.ForeignKey(CropType, on_delete=models.CASCADE, verbose_name="Культура")
    year = models.IntegerField(verbose_name="Год")
    season = models.CharField(max_length=20, choices=[
        ('spring', 'Весна'),
        ('summer', 'Лето'),
        ('autumn', 'Осень'),
        ('winter', 'Зима'),
    ], default='spring', verbose_name="Сезон")
    yield_amount = models.FloatField(blank=True, null=True, verbose_name="Урожайность (т/га)")
    notes = models.TextField(blank=True, null=True, verbose_name="Заметки")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Запись севооборота"
        verbose_name_plural = "Записи севооборота"
        ordering = ['-year', '-created_at']
        unique_together = ['field', 'year', 'season']
    
    def __str__(self):
        return f"{self.field.name} - {self.crop_type.name} ({self.year})"

class SoilAnalysis(models.Model):
    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name='analyses', verbose_name="Поле")
    analysis_date = models.DateTimeField(default=timezone.now, verbose_name="Дата анализа")
    bbox_json = models.TextField(verbose_name="BBOX (JSON)")
    very_high_percent = models.FloatField(default=0, verbose_name="Очень высокое (%)")
    high_percent = models.FloatField(default=0, verbose_name="Высокое (%)")
    moderate_percent = models.FloatField(default=0, verbose_name="Умеренное (%)")
    low_percent = models.FloatField(default=0, verbose_name="Низкое (%)")
    non_fertile_percent = models.FloatField(default=0, verbose_name="Неплодородная (%)")
    fertility_index = models.FloatField(default=0, verbose_name="Индекс плодородия")
    overlay_image = models.TextField(blank=True, null=True, verbose_name="Маска плодородия")
    notes = models.TextField(blank=True, null=True, verbose_name="Заметки")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Анализ почвы"
        verbose_name_plural = "Анализы почвы"
        ordering = ['-analysis_date']
    
    def __str__(self):
        return f"{self.field.name} - {self.analysis_date.strftime('%Y-%m-%d')}"
    
    def calculate_fertility_index(self):
        index = (
            self.very_high_percent * 1.0 +
            self.high_percent * 0.75 +
            self.moderate_percent * 0.5 +
            self.low_percent * 0.25 +
            self.non_fertile_percent * 0.0
        )
        self.fertility_index = round(index, 2)
        return self.fertility_index

class InvasiveSpeciesReport(models.Model):
    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name='invasive_reports', verbose_name="Поле")
    species_name = models.CharField(max_length=255, verbose_name="Название вида")
    species_type = models.CharField(max_length=50, choices=[
        ('weed', 'Сорняк'),
        ('pest', 'Вредитель'),
        ('disease', 'Болезнь'),
        ('other', 'Другое'),
    ], default='weed', verbose_name="Тип")
    severity = models.CharField(max_length=20, choices=[
        ('low', 'Низкая'),
        ('medium', 'Средняя'),
        ('high', 'Высокая'),
        ('critical', 'Критическая'),
    ], default='low', verbose_name="Степень заражения")
    location_lat = models.FloatField(verbose_name="Широта")
    location_lon = models.FloatField(verbose_name="Долгота")
    affected_area = models.FloatField(default=0, verbose_name="Площадь поражения (м²)")
    image_base64 = models.TextField(blank=True, null=True, verbose_name="Изображение")
    status = models.CharField(max_length=20, choices=[
        ('detected', 'Обнаружено'),
        ('confirmed', 'Подтверждено'),
        ('treating', 'В обработке'),
        ('resolved', 'Устранено'),
    ], default='detected', verbose_name="Статус")
    recommendations = models.TextField(blank=True, null=True, verbose_name="Рекомендации")
    detected_at = models.DateTimeField(default=timezone.now, verbose_name="Дата обнаружения")
    resolved_at = models.DateTimeField(blank=True, null=True, verbose_name="Дата устранения")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Отчёт об инвазивных видах"
        verbose_name_plural = "Отчёты об инвазивных видах"
        ordering = ['-detected_at']
    
    def __str__(self):
        return f"{self.species_name} на {self.field.name}"

class GrowthMonitoring(models.Model):
    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name='growth_records', verbose_name="Поле")
    observation_date = models.DateField(verbose_name="Дата наблюдения")
    ndvi_mean = models.FloatField(blank=True, null=True, verbose_name="Средний NDVI")
    ndvi_min = models.FloatField(blank=True, null=True, verbose_name="Минимальный NDVI")
    ndvi_max = models.FloatField(blank=True, null=True, verbose_name="Максимальный NDVI")
    moisture_index = models.FloatField(blank=True, null=True, verbose_name="Индекс влажности")
    health_score = models.FloatField(blank=True, null=True, verbose_name="Оценка здоровья")
    growth_stage = models.CharField(max_length=50, choices=[
        ('bare_soil', 'Голая почва'),
        ('emergence', 'Всходы'),
        ('vegetative', 'Вегетация'),
        ('flowering', 'Цветение'),
        ('maturation', 'Созревание'),
        ('harvest', 'Уборка'),
    ], blank=True, null=True, verbose_name="Стадия роста")
    ndvi_overlay = models.TextField(blank=True, null=True, verbose_name="Маска NDVI")
    data_source = models.CharField(max_length=50, choices=[
        ('sentinel2', 'Sentinel-2'),
        ('landsat8', 'Landsat-8'),
        ('local_analysis', 'Локальный анализ'),
        ('manual', 'Ручной ввод'),
    ], default='local_analysis', verbose_name="Источник данных")
    notes = models.TextField(blank=True, null=True, verbose_name="Заметки")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Запись мониторинга роста"
        verbose_name_plural = "Записи мониторинга роста"
        ordering = ['-observation_date']
        unique_together = ['field', 'observation_date']
    
    def __str__(self):
        return f"{self.field.name} - {self.observation_date}"


class WeedDatabase(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название")
    name_latin = models.CharField(max_length=255, blank=True, null=True, verbose_name="Латинское название")
    description = models.TextField(blank=True, null=True, verbose_name="Описание")
    color_signature = models.TextField(blank=True, null=True, verbose_name="Цветовая сигнатура (JSON)")
    texture_features = models.TextField(blank=True, null=True, verbose_name="Текстурные признаки (JSON)")
    reference_images_json = models.TextField(blank=True, null=True, verbose_name="Референсные изображения (JSON)")
    control_methods = models.TextField(blank=True, null=True, verbose_name="Методы борьбы")
    danger_level = models.CharField(max_length=20, choices=[
        ('low', 'Низкая'),
        ('medium', 'Средняя'),
        ('high', 'Высокая'),
    ], default='medium', verbose_name="Уровень опасности")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Сорняк (база)"
        verbose_name_plural = "Сорняки (база)"
        ordering = ['name']
    
    def __str__(self):
        return self.name
