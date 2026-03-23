"""
Диагностика проблем с моделью
"""
import torch
import torch.nn as nn
from torchvision import models
import os
import json

print("=" * 50)
print("ДИАГНОСТИКА МОДЕЛИ")
print("=" * 50)

# 1. Проверка файлов
print("\n1. Проверка наличия файлов:")
model_path = "models/soil_classifier_best.pth"
classes_path = "models/classes.json"

if os.path.exists(model_path):
    size_mb = os.path.getsize(model_path) / (1024 * 1024)
    print(f"   ✓ Модель найдена: {model_path} ({size_mb:.2f} MB)")
else:
    print(f"   ✗ Модель НЕ найдена: {model_path}")

if os.path.exists(classes_path):
    print(f"   ✓ Классы найдены: {classes_path}")
    with open(classes_path, 'r') as f:
        classes = json.load(f)
    print(f"   Классы: {classes}")
else:
    print(f"   ✗ Классы НЕ найдены: {classes_path}")
    classes = ["Black_Soil", "Clay", "Loam", "Sand"]

# 2. Проверка загрузки модели
print("\n2. Проверка загрузки модели:")
try:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"   Устройство: {device}")
    
    # Создаём архитектуру модели
    model = models.mobilenet_v2(pretrained=False)
    print(f"   ✓ Архитектура MobileNetV2 создана")
    print(f"   last_channel: {model.last_channel}")
    
    # Модифицируем последний слой
    model.classifier[1] = nn.Linear(model.last_channel, len(classes))
    print(f"   ✓ Последний слой изменён на {len(classes)} классов")
    
    # Загружаем веса
    if os.path.exists(model_path):
        state_dict = torch.load(model_path, map_location=device)
        model.load_state_dict(state_dict)
        print(f"   ✓ Веса модели загружены успешно")
    else:
        print(f"   ✗ Не удалось загрузить веса")
    
    model = model.to(device)
    model.eval()
    print(f"   ✓ Модель переведена в режим оценки")
    
except Exception as e:
    print(f"   ✗ ОШИБКА при загрузке модели: {e}")
    import traceback
    traceback.print_exc()

# 3. Тест инференса
print("\n3. Тест инференса на случайных данных:")
try:
    # Создаём случайный тензор (имитация изображения)
    dummy_input = torch.randn(1, 3, 224, 224).to(device)
    
    with torch.no_grad():
        output = model(dummy_input)
        probabilities = torch.nn.functional.softmax(output[0], dim=0)
        confidence, index = torch.max(probabilities, 0)
        
    predicted_class = classes[index.item()]
    print(f"   ✓ Инференс работает!")
    print(f"   Предсказанный класс: {predicted_class}")
    print(f"   Уверенность: {confidence.item():.4f}")
    print(f"   Все вероятности: {probabilities.tolist()}")
    
except Exception as e:
    print(f"   ✗ ОШИБКА при инференсе: {e}")
    import traceback
    traceback.print_exc()

# 4. Проверка на реальном изображении
print("\n4. Проверка на реальном изображении:")
try:
    from PIL import Image
    from torchvision import transforms
    
    # Ищем любое изображение в data
    test_images = []
    for root, dirs, files in os.walk("data/train"):
        for file in files:
            if file.endswith(('.jpg', '.jpeg', '.png')):
                test_images.append(os.path.join(root, file))
                if len(test_images) >= 3:
                    break
        if len(test_images) >= 3:
            break
    
    if test_images:
        transform = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])
        
        print(f"   Найдено {len(test_images)} тестовых изображений")
        
        for img_path in test_images[:3]:
            image = Image.open(img_path).convert('RGB')
            img_t = transform(image)
            batch_t = torch.unsqueeze(img_t, 0).to(device)
            
            with torch.no_grad():
                output = model(batch_t)
                probabilities = torch.nn.functional.softmax(output[0], dim=0)
                confidence, index = torch.max(probabilities, 0)
            
            predicted = classes[index.item()]
            actual = os.path.basename(os.path.dirname(img_path))
            
            print(f"\n   Файл: {os.path.basename(img_path)}")
            print(f"   Реальный класс: {actual}")
            print(f"   Предсказанный: {predicted}")
            print(f"   Уверенность: {confidence.item():.2%}")
            
            if predicted == actual:
                print(f"   ✓ ПРАВИЛЬНО!")
            else:
                print(f"   ✗ НЕПРАВИЛЬНО!")
    else:
        print("   ⚠ Тестовые изображения не найдены")
        
except Exception as e:
    print(f"   ✗ ОШИБКА при тестировании на изображении: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 50)
print("ДИАГНОСТИКА ЗАВЕРШЕНА")
print("=" * 50)
