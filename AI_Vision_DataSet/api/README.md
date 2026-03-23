# 🚀 REST API для анализа почвы

Готовый REST API сервер для анализа почвы по фотографиям.

## Установка зависимостей

```bash
pip install fastapi uvicorn python-multipart requests
```

## Запуск сервера

```bash
python api/server.py
```

Или через uvicorn:
```bash
uvicorn api.server:app --reload --host 0.0.0.0 --port 8000
```

Сервер запустится на `http://localhost:8000`

## API Endpoints

### GET `/`
Информация об API

### GET `/health`
Проверка работоспособности
```bash
curl http://localhost:8000/health
```

### POST `/analyze`
Анализ почвы по изображению

**Пример с curl:**
```bash
curl -X POST "http://localhost:8000/analyze" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@path/to/your/image.jpg"
```

**Пример с Python:**
```python
import requests

with open("soil_image.jpg", "rb") as f:
    response = requests.post(
        "http://localhost:8000/analyze",
        files={"file": f}
    )
    
result = response.json()
print(result)
```

**Ответ:**
```json
{
  "success": true,
  "soil_type": "Black_Soil",
  "confidence": 0.9876,
  "fertility": "Высокое (High)",
  "description": "Темный, рыхлый грунт. Богатый гумусом.",
  "visual_characteristics": "Темный цвет, рыхлая структура",
  "recommended_crops": [
    "Пшеница (Wheat)",
    "Овощи (Vegetables)",
    "Подсолнечник (Sunflower)",
    "Кукуруза (Corn)"
  ]
}
```

## Тестирование

### 1. Python скрипт
```bash
python api/test_api.py
```

### 2. HTML интерфейс
Откройте `api/test_client.html` в браузере (после запуска сервера).
Красивый интерфейс с drag-and-drop для загрузки фото.

### 3. Swagger UI
Откройте в браузере: `http://localhost:8000/docs`
Интерактивная документация API.

## Интеграция

Вы можете использовать этот API из любого приложения:
- Мобильное приложение
- Веб-сайт
- Telegram бот
- Desktop приложение

Просто отправляйте POST запрос с изображением на `/analyze`.
