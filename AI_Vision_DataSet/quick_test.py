"""
Быстрая проверка модели
"""
import torch
from src.inference import SoilClassifier
from PIL import Image
import os

print("🔍 БЫСТРАЯ ДИАГНОСТИКА МОДЕЛИ")
print("="*60)

# 1. Проверка загрузки
print("\n1️⃣ Загрузка модели...")
try:
    classifier = SoilClassifier(
        model_path="models/soil_classifier_best.pth",
        classes_path="models/classes.json"
    )
    print("   ✓ Модель загружена успешно")
    print(f"   Классы: {classifier.classes}")
except Exception as e:
    print(f"   ✗ ОШИБКА: {e}")
    exit(1)

# 2. Поиск тестового изображения
print("\n2️⃣ Поиск тестового изображения...")
test_image_path = None
for root, dirs, files in os.walk("data/train"):
    for file in files:
        if file.endswith(('.jpg', '.jpeg', '.png')):
            test_image_path = os.path.join(root, file)
            break
    if test_image_path:
        break

if not test_image_path:
    print("   ✗ Тестовые изображения не найдены!")
    exit(1)

print(f"   ✓ Найдено: {test_image_path}")
actual_class = os.path.basename(os.path.dirname(test_image_path))
print(f"   Реальный класс: {actual_class}")

# 3. Тест предсказания
print("\n3️⃣ Тест предсказания...")
try:
    image = Image.open(test_image_path).convert('RGB')
    soil_type, confidence = classifier.predict(image)
    
    print(f"   Предсказанный класс: {soil_type}")
    print(f"   Уверенность: {confidence:.2%}")
    
    if soil_type == actual_class:
        print("   ✓ ПРАВИЛЬНО!")
    else:
        print(f"   ✗ НЕПРАВИЛЬНО! (ожидалось: {actual_class})")
        
except Exception as e:
    print(f"   ✗ ОШИБКА при предсказании: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

# 4. Тест на нескольких изображениях
print("\n4️⃣ Тест на нескольких изображениях...")
test_images = []
for root, dirs, files in os.walk("data/train"):
    for file in files:
        if file.endswith(('.jpg', '.jpeg', '.png')):
            test_images.append(os.path.join(root, file))
            if len(test_images) >= 10:
                break
    if len(test_images) >= 10:
        break

correct = 0
total = len(test_images)

for img_path in test_images:
    image = Image.open(img_path).convert('RGB')
    soil_type, confidence = classifier.predict(image)
    actual = os.path.basename(os.path.dirname(img_path))
    
    if soil_type == actual:
        correct += 1

accuracy = correct / total if total > 0 else 0
print(f"   Протестировано: {total} изображений")
print(f"   Правильных: {correct}")
print(f"   Точность: {accuracy:.2%}")

# 5. Выводы
print("\n" + "="*60)
print("📊 ВЫВОДЫ:")
print("="*60)

if accuracy >= 0.8:
    print("✓ Модель работает ХОРОШО!")
    print("  Точность выше 80%, модель готова к использованию.")
elif accuracy >= 0.5:
    print("⚠ Модель работает СРЕДНЕ")
    print("  Точность 50-80%, рекомендуется дообучение.")
else:
    print("✗ Модель работает ПЛОХО")
    print("  Точность ниже 50%, требуется переобучение.")
    print("\nВозможные причины:")
    print("  - Недостаточно данных для обучения")
    print("  - Мало эпох обучения")
    print("  - Данные плохого качества")
    print("  - Несбалансированные классы")

print("\n💡 Рекомендации:")
if accuracy < 0.8:
    print("  1. Увеличьте количество эпох обучения (сейчас 5)")
    print("  2. Добавьте больше изображений в датасет")
    print("  3. Проверьте качество изображений")
    print("  4. Используйте data augmentation")

print("\n🚀 Для запуска приложения:")
print("  - Streamlit: streamlit run app/main.py")
print("  - API: python api/server.py")
