import os
import sys
import argparse
import torch
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image

# Hardcoded class list ordered alphabetically (same as PyTorch's ImageFolder)
CLASS_NAMES = ['high_fertility', 'low_fertility', 'medium_fertility']

# Descriptions and crop recommendations for each fertility level
FERTILITY_DETAILS = {
    'high_fertility': {
        'title': 'Высокое плодородие / High Fertility 🌟',
        'desc': 'Почва богата питательными веществами, имеет отличную структуру и хорошо удерживает влагу.',
        'recommendation': 'Подходит для большинства культур с высокой потребностью в питании: пшеница, хлопчатник, рис, овощи.'
    },
    'medium_fertility': {
        'title': 'Среднее плодородие / Medium Fertility 🌱',
        'desc': 'Умеренное содержание органики и минералов. Требует поддерживающего ухода.',
        'recommendation': 'Хорошо подходит для кукурузы, подсолнечника, бобовых. Рекомендуется внесение органических и комплексных удобрений.'
    },
    'low_fertility': {
        'title': 'Низкое плодородие / Low Fertility ⚠️',
        'desc': 'Бедная почва (песчаная, каменистая или сильно выщелоченная). Мало органики.',
        'recommendation': 'Подходит для неприхотливых культур (просо, ячмень) или требует интенсивного внесения сидератов, навоза и капельного орошения.'
    }
}

def get_device():
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")

def load_model(model_path, device):
    """Loads the ResNet-18 model with trained weights."""
    model = models.resnet18()
    num_ftrs = model.fc.in_features
    # 3 classes: high_fertility, low_fertility, medium_fertility
    model.fc = nn.Linear(num_ftrs, len(CLASS_NAMES))
    
    if not os.path.exists(model_path):
        print(f"\nОшибка: Файл весов модели '{model_path}' не найден!")
        print("Пожалуйста, сначала обучите модель с помощью команды: python train.py")
        sys.exit(1)
        
    print(f"Загрузка весов модели из {model_path}...")
    state_dict = torch.load(model_path, map_location=device)
    model.load_state_dict(state_dict)
    model = model.to(device)
    model.eval()
    return model

def predict_image(image_path, model, device):
    """Processes the image and predicts its fertility class."""
    if not os.path.exists(image_path):
        print(f"Ошибка: Изображение '{image_path}' не найдено!")
        sys.exit(1)
        
    # Same transforms as validation set in train.py
    preprocess = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])
    
    try:
        image = Image.open(image_path).convert('RGB')
    except Exception as e:
        print(f"Ошибка при чтении изображения: {e}")
        sys.exit(1)
        
    img_tensor = preprocess(image).unsqueeze(0).to(device)
    
    with torch.no_grad():
        outputs = model(img_tensor)
        probabilities = torch.nn.functional.softmax(outputs[0], dim=0)
        confidence, class_idx = torch.max(probabilities, 0)
        
    predicted_class = CLASS_NAMES[class_idx.item()]
    return predicted_class, confidence.item()

def main():
    parser = argparse.ArgumentParser(description="Скрипт предсказания плодородия почвы по снимку")
    parser.add_argument('--image', '-i', type=str, required=True, help="Путь к снимку почвы")
    parser.add_argument('--model', '-m', type=str, default='soil_model.pth', help="Путь к обученной модели (по умолчанию: soil_model.pth)")
    
    args = parser.parse_args()
    
    device = get_device()
    print(f"Используем устройство: {device}")
    
    model = load_model(args.model, device)
    
    print(f"Анализ снимка: {args.image}...")
    pred_class, conf = predict_image(args.image, model, device)
    
    details = FERTILITY_DETAILS[pred_class]
    
    print("\n" + "="*50)
    print("РЕЗУЛЬТАТ АНАЛИЗА ПОЧВЫ")
    print("="*50)
    print(f"Класс: {details['title']}")
    print(f"Уверенность нейросети: {conf * 100:.2f}%")
    print(f"Описание: {details['desc']}")
    print(f"Рекомендации: {details['recommendation']}")
    print("="*50)

if __name__ == "__main__":
    main()
