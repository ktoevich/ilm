"""
REST API для анализа почвы
Отправляйте изображение и получайте результат анализа
"""
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
import io
import sys
import os

# Добавляем путь к src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.inference import SoilClassifier
from src.recommendations import get_soil_info

app = FastAPI(
    title="Soil Analysis API",
    description="API для анализа плодородности почвы по фотографии",
    version="1.0.0"
)

# CORS для доступа из браузера
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Загружаем модель при старте
classifier = SoilClassifier(
    model_path="models/soil_classifier_best.pth",
    classes_path="models/classes.json"
)

@app.get("/")
async def root():
    """Информация об API"""
    return {
        "message": "Soil Analysis API",
        "version": "1.0.0",
        "endpoints": {
            "POST /analyze": "Анализ почвы по фото",
            "GET /health": "Проверка работоспособности"
        }
    }

@app.get("/health")
async def health():
    """Проверка работоспособности API"""
    return {"status": "ok", "model_loaded": classifier.model is not None}

@app.post("/analyze")
async def analyze_soil(file: UploadFile = File(...)):
    """
    Анализ почвы по загруженному изображению
    
    Args:
        file: Изображение почвы (JPG, PNG)
    
    Returns:
        JSON с результатами анализа:
        - soil_type: тип почвы
        - confidence: уверенность модели (0-1)
        - fertility: уровень плодородности
        - description: описание почвы
        - visual_characteristics: визуальные характеристики
        - recommended_crops: рекомендуемые культуры
    """
    try:
        # Проверяем формат файла
        if not file.content_type.startswith("image/"):
            raise HTTPException(
                status_code=400,
                detail="Файл должен быть изображением (JPG, PNG)"
            )
        
        # Читаем изображение
        contents = await file.read()
        image = Image.open(io.BytesIO(contents)).convert('RGB')
        
        # Анализируем
        soil_type, confidence = classifier.predict(image)
        
        # Получаем рекомендации
        info = get_soil_info(soil_type)
        
        # Формируем ответ
        return {
            "success": True,
            "soil_type": soil_type,
            "confidence": round(confidence, 4),
            "fertility": info["fertility"],
            "description": info["description"],
            "visual_characteristics": info["visual_characteristics"],
            "recommended_crops": info["crops"]
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при анализе изображения: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
