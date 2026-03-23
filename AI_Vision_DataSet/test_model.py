"""
Пример использования обученной модели для анализа почвы
"""
from PIL import Image
from src.inference import SoilClassifier
from src.recommendations import get_soil_info

# Загрузить модель
classifier = SoilClassifier(
    model_path="models/soil_classifier_best.pth",  # Используем лучшую модель
    classes_path="models/classes.json"
)

# Загрузить изображение
image_path = "data/train/Black_Soil/dummy_0.jpg"  # Замените на свой путь
image = Image.open(image_path).convert('RGB')

# Получить предсказание
soil_type, confidence = classifier.predict(image)

print(f"🌍 Тип почвы: {soil_type}")
print(f"📊 Уверенность: {confidence:.2%}")
print()

# Получить рекомендации
info = get_soil_info(soil_type)
print(f"🌱 Плодородность: {info['fertility']}")
print(f"📝 Описание: {info['description']}")
print(f"🚜 Рекомендуемые культуры:")
for crop in info['crops']:
    print(f"   - {crop}")
