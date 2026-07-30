import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, transforms, models
from torch.utils.data import DataLoader
import os
from tqdm import tqdm

# 1. Настройка устройства (GPU если доступно, иначе CPU)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Используем устройство: {device}")

# 2. Трансформация изображений (приведение к одному размеру + аугментация)
data_transforms = {
    'train': transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.RandomHorizontalFlip(), # Случайный поворот для разнообразия
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]) # Нормализация ResNet
    ]),
    'val': transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ]),
}

# 3. Загрузка датасета из папок
data_dir = './dataset'
image_datasets = {x: datasets.ImageFolder(os.path.join(data_dir, x), data_transforms[x]) for x in ['train', 'val']}
dataloaders = {x: DataLoader(image_datasets[x], batch_size=16, shuffle=True) for x in ['train', 'val']}

class_names = image_datasets['train'].classes
print(f"Обнаружены классы: {class_names}")

# 4. Загрузка предобученной модели ResNet18
model = models.resnet18(pretrained=True)

# Перестраиваем финальный слой под наше количество классов (например, 3 класса)
num_ftrs = model.fc.in_features
model.fc = nn.Linear(num_ftrs, len(class_names))
model = model.to(device)

# 5. Функция потерь и оптимизатор
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.parameters(), lr=0.001)

# 6. Цикл обучения
epochs = 10
print("Старт обучения...")

for epoch in range(epochs):
    print(f"\nЭпоха {epoch+1}/{epochs}")
    
    # Каждая эпоха имеет фазу обучения и валидации
    for phase in ['train', 'val']:
        if phase == 'train':
            model.train()
        else:
            model.eval()

        running_loss = 0.0
        running_corrects = 0

        # Итерация по данным
        for inputs, labels in tqdm(dataloaders[phase], desc=phase):
            inputs, labels = inputs.to(device), labels.to(device)

            optimizer.zero_grad()

            # Прямой шаг
            with torch.set_grad_enabled(phase == 'train'):
                outputs = model(inputs)
                _, preds = torch.max(outputs, 1)
                loss = criterion(outputs, labels)

                # Обратный шаг + оптимизация только в фазе обучения
                if phase == 'train':
                    loss.backward()
                    optimizer.step()

            running_loss += loss.item() * inputs.size(0)
            running_corrects += torch.sum(preds == labels.data)

        epoch_loss = running_loss / len(image_datasets[phase])
        epoch_acc = running_corrects.double() / len(image_datasets[phase])

        print(f"{phase} Ошибка: {epoch_loss:.4f} Точность: {epoch_acc:.4f}")

# 7. Сохранение обученной модели
torch.save(model.state_dict(), 'soil_model.pth')
print("\nМодель успешно обучена и сохранена в 'soil_model.pth'!")