"""
Пример использования API
"""
import requests

# URL вашего API
API_URL = "http://localhost:8000"

def test_health():
    """Проверка работоспособности"""
    response = requests.get(f"{API_URL}/health")
    print("Health Check:", response.json())

def analyze_image(image_path):
    """Анализ изображения"""
    with open(image_path, 'rb') as f:
        files = {'file': f}
        response = requests.post(f"{API_URL}/analyze", files=files)
    
    if response.status_code == 200:
        result = response.json()
        print("\n🌍 Результат анализа:")
        print(f"Тип почвы: {result['soil_type']}")
        print(f"Уверенность: {result['confidence']*100:.2f}%")
        print(f"Плодородность: {result['fertility']}")
        print(f"Описание: {result['description']}")
        print(f"\n🚜 Рекомендуемые культуры:")
        for crop in result['recommended_crops']:
            print(f"  - {crop}")
    else:
        print(f"Ошибка: {response.status_code}")
        print(response.json())

if __name__ == "__main__":
    # Проверяем работоспособность
    test_health()
    
    # Анализируем изображение
    # Замените путь на свой файл
    analyze_image("data/train/Black_Soil/dummy_0.jpg")
