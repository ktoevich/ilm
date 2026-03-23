import json

notebook = {
    "cells": [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# 🌱 Диагностика модели классификации почвы\n",
                "\n",
                "Этот notebook проверяет работоспособность обученной модели и выявляет возможные проблемы."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "import torch\n",
                "import torch.nn as nn\n",
                "from torchvision import models, transforms\n",
                "from PIL import Image\n",
                "import os\n",
                "import json\n",
                "import matplotlib.pyplot as plt\n",
                "import numpy as np\n",
                "\n",
                "print('✓ Библиотеки импортированы')"
            ]
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 1. Проверка наличия файлов модели"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "print(\"=\"*50)\n",
                "print(\"ПРОВЕРКА ФАЙЛОВ\")\n",
                "print(\"=\"*50)\n",
                "\n",
                "model_path = \"models/soil_classifier_best.pth\"\n",
                "classes_path = \"models/classes.json\"\n",
                "\n",
                "if os.path.exists(model_path):\n",
                "    size_mb = os.path.getsize(model_path) / (1024 * 1024)\n",
                "    print(f\"✓ Модель найдена: {model_path} ({size_mb:.2f} MB)\")\n",
                "else:\n",
                "    print(f\"✗ Модель НЕ найдена: {model_path}\")\n",
                "\n",
                "if os.path.exists(classes_path):\n",
                "    print(f\"✓ Классы найдены: {classes_path}\")\n",
                "    with open(classes_path, 'r') as f:\n",
                "        classes = json.load(f)\n",
                "    print(f\"Классы: {classes}\")\n",
                "else:\n",
                "    print(f\"✗ Классы НЕ найдены: {classes_path}\")\n",
                "    classes = [\"Black_Soil\", \"Clay\", \"Loam\", \"Sand\"]"
            ]
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 2. Загрузка модели"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "print(\"=\"*50)\n",
                "print(\"ЗАГРУЗКА МОДЕЛИ\")\n",
                "print(\"=\"*50)\n",
                "\n",
                "device = torch.device(\"cuda\" if torch.cuda.is_available() else \"cpu\")\n",
                "print(f\"Устройство: {device}\")\n",
                "\n",
                "# Создаём архитектуру\n",
                "model = models.mobilenet_v2(pretrained=False)\n",
                "print(f\"✓ Архитектура MobileNetV2 создана\")\n",
                "print(f\"last_channel: {model.last_channel}\")\n",
                "\n",
                "# Модифицируем последний слой\n",
                "model.classifier[1] = nn.Linear(model.last_channel, len(classes))\n",
                "print(f\"✓ Последний слой изменён на {len(classes)} классов\")\n",
                "\n",
                "# Загружаем веса\n",
                "if os.path.exists(model_path):\n",
                "    state_dict = torch.load(model_path, map_location=device)\n",
                "    model.load_state_dict(state_dict)\n",
                "    print(f\"✓ Веса модели загружены успешно\")\n",
                "else:\n",
                "    print(f\"✗ Не удалось загрузить веса\")\n",
                "\n",
                "model = model.to(device)\n",
                "model.eval()\n",
                "print(f\"✓ Модель переведена в режим оценки\")"
            ]
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 3. Тест на случайных данных"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "print(\"=\"*50)\n",
                "print(\"ТЕСТ НА СЛУЧАЙНЫХ ДАННЫХ\")\n",
                "print(\"=\"*50)\n",
                "\n",
                "# Создаём случайный тензор\n",
                "dummy_input = torch.randn(1, 3, 224, 224).to(device)\n",
                "\n",
                "with torch.no_grad():\n",
                "    output = model(dummy_input)\n",
                "    probabilities = torch.nn.functional.softmax(output[0], dim=0)\n",
                "    confidence, index = torch.max(probabilities, 0)\n",
                "\n",
                "predicted_class = classes[index.item()]\n",
                "print(f\"✓ Инференс работает!\")\n",
                "print(f\"Предсказанный класс: {predicted_class}\")\n",
                "print(f\"Уверенность: {confidence.item():.4f}\")\n",
                "print(f\"\\nВсе вероятности:\")\n",
                "for i, (cls, prob) in enumerate(zip(classes, probabilities.tolist())):\n",
                "    print(f\"  {cls}: {prob:.4f}\")"
            ]
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 4. Тест на реальных изображениях"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "print(\"=\"*50)\n",
                "print(\"ТЕСТ НА РЕАЛЬНЫХ ИЗОБРАЖЕНИЯХ\")\n",
                "print(\"=\"*50)\n",
                "\n",
                "# Ищем тестовые изображения\n",
                "test_images = []\n",
                "for root, dirs, files in os.walk(\"data/train\"):\n",
                "    for file in files:\n",
                "        if file.endswith(('.jpg', '.jpeg', '.png')):\n",
                "            test_images.append(os.path.join(root, file))\n",
                "            if len(test_images) >= 6:\n",
                "                break\n",
                "    if len(test_images) >= 6:\n",
                "        break\n",
                "\n",
                "print(f\"Найдено {len(test_images)} тестовых изображений\\n\")\n",
                "\n",
                "# Трансформации\n",
                "transform = transforms.Compose([\n",
                "    transforms.Resize(256),\n",
                "    transforms.CenterCrop(224),\n",
                "    transforms.ToTensor(),\n",
                "    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])\n",
                "])\n",
                "\n",
                "# Тестируем\n",
                "results = []\n",
                "for img_path in test_images[:6]:\n",
                "    image = Image.open(img_path).convert('RGB')\n",
                "    img_t = transform(image)\n",
                "    batch_t = torch.unsqueeze(img_t, 0).to(device)\n",
                "    \n",
                "    with torch.no_grad():\n",
                "        output = model(batch_t)\n",
                "        probabilities = torch.nn.functional.softmax(output[0], dim=0)\n",
                "        confidence, index = torch.max(probabilities, 0)\n",
                "    \n",
                "    predicted = classes[index.item()]\n",
                "    actual = os.path.basename(os.path.dirname(img_path))\n",
                "    correct = predicted == actual\n",
                "    \n",
                "    results.append({\n",
                "        'image': image,\n",
                "        'path': img_path,\n",
                "        'actual': actual,\n",
                "        'predicted': predicted,\n",
                "        'confidence': confidence.item(),\n",
                "        'correct': correct,\n",
                "        'probabilities': probabilities.cpu().numpy()\n",
                "    })\n",
                "    \n",
                "    status = \"✓ ПРАВИЛЬНО\" if correct else \"✗ НЕПРАВИЛЬНО\"\n",
                "    print(f\"Файл: {os.path.basename(img_path)}\")\n",
                "    print(f\"  Реальный: {actual}\")\n",
                "    print(f\"  Предсказанный: {predicted}\")\n",
                "    print(f\"  Уверенность: {confidence.item():.2%}\")\n",
                "    print(f\"  {status}\\n\")"
            ]
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 5. Визуализация результатов"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# Визуализируем результаты\n",
                "fig, axes = plt.subplots(2, 3, figsize=(15, 10))\n",
                "axes = axes.flatten()\n",
                "\n",
                "for idx, result in enumerate(results[:6]):\n",
                "    ax = axes[idx]\n",
                "    ax.imshow(result['image'])\n",
                "    \n",
                "    color = 'green' if result['correct'] else 'red'\n",
                "    title = f\"Реальный: {result['actual']}\\n\"\n",
                "    title += f\"Предсказан: {result['predicted']}\\n\"\n",
                "    title += f\"Уверенность: {result['confidence']:.2%}\"\n",
                "    \n",
                "    ax.set_title(title, color=color, fontsize=10, weight='bold')\n",
                "    ax.axis('off')\n",
                "\n",
                "plt.tight_layout()\n",
                "plt.show()\n",
                "\n",
                "# Статистика\n",
                "correct_count = sum(1 for r in results if r['correct'])\n",
                "total_count = len(results)\n",
                "accuracy = correct_count / total_count if total_count > 0 else 0\n",
                "\n",
                "print(f\"\\n{'='*50}\")\n",
                "print(f\"СТАТИСТИКА\")\n",
                "print(f\"{'='*50}\")\n",
                "print(f\"Правильных предсказаний: {correct_count}/{total_count}\")\n",
                "print(f\"Точность: {accuracy:.2%}\")"
            ]
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 6. Анализ вероятностей"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# График вероятностей для каждого изображения\n",
                "fig, axes = plt.subplots(2, 3, figsize=(15, 8))\n",
                "axes = axes.flatten()\n",
                "\n",
                "for idx, result in enumerate(results[:6]):\n",
                "    ax = axes[idx]\n",
                "    probs = result['probabilities']\n",
                "    \n",
                "    colors = ['green' if cls == result['actual'] else 'blue' for cls in classes]\n",
                "    bars = ax.bar(classes, probs, color=colors, alpha=0.7)\n",
                "    \n",
                "    # Подсвечиваем предсказанный класс\n",
                "    predicted_idx = classes.index(result['predicted'])\n",
                "    bars[predicted_idx].set_edgecolor('red')\n",
                "    bars[predicted_idx].set_linewidth(3)\n",
                "    \n",
                "    ax.set_title(f\"Файл: {os.path.basename(result['path'])}\\nРеальный: {result['actual']}\", fontsize=9)\n",
                "    ax.set_ylabel('Вероятность')\n",
                "    ax.set_ylim([0, 1])\n",
                "    ax.tick_params(axis='x', rotation=45, labelsize=8)\n",
                "    ax.grid(axis='y', alpha=0.3)\n",
                "\n",
                "plt.tight_layout()\n",
                "plt.show()"
            ]
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 7. Тест через класс SoilClassifier"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "print(\"=\"*50)\n",
                "print(\"ТЕСТ ЧЕРЕЗ КЛАСС SoilClassifier\")\n",
                "print(\"=\"*50)\n",
                "\n",
                "import sys\n",
                "sys.path.append('..')\n",
                "\n",
                "from src.inference import SoilClassifier\n",
                "from src.recommendations import get_soil_info\n",
                "\n",
                "# Загружаем классификатор\n",
                "classifier = SoilClassifier(\n",
                "    model_path=\"models/soil_classifier_best.pth\",\n",
                "    classes_path=\"models/classes.json\"\n",
                ")\n",
                "\n",
                "print(\"✓ Классификатор загружен\\n\")\n",
                "\n",
                "# Тестируем на первом изображении\n",
                "if test_images:\n",
                "    test_img = Image.open(test_images[0]).convert('RGB')\n",
                "    soil_type, confidence = classifier.predict(test_img)\n",
                "    \n",
                "    print(f\"Предсказание: {soil_type}\")\n",
                "    print(f\"Уверенность: {confidence:.2%}\\n\")\n",
                "    \n",
                "    # Получаем рекомендации\n",
                "    info = get_soil_info(soil_type)\n",
                "    print(f\"Плодородность: {info['fertility']}\")\n",
                "    print(f\"Описание: {info['description']}\")\n",
                "    print(f\"Визуальные характеристики: {info['visual_characteristics']}\")\n",
                "    print(f\"\\nРекомендуемые культуры:\")\n",
                "    for crop in info['crops']:\n",
                "        print(f\"  - {crop}\")\n",
                "    \n",
                "    # Визуализация\n",
                "    plt.figure(figsize=(8, 6))\n",
                "    plt.imshow(test_img)\n",
                "    plt.title(f\"Тип почвы: {soil_type}\\nУверенность: {confidence:.2%}\", fontsize=14, weight='bold')\n",
                "    plt.axis('off')\n",
                "    plt.show()"
            ]
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 8. Выводы\n",
                "\n",
                "После выполнения всех тестов вы можете сделать выводы:\n",
                "\n",
                "1. **Модель загружается?** - Проверьте раздел 2\n",
                "2. **Инференс работает?** - Проверьте раздел 3\n",
                "3. **Точность на реальных данных?** - Проверьте раздел 5\n",
                "4. **Уверенность модели?** - Проверьте раздел 6\n",
                "5. **API работает?** - Проверьте раздел 7\n",
                "\n",
                "### Возможные проблемы:\n",
                "\n",
                "- **Низкая точность**: Модель нужно дообучить или использовать больше данных\n",
                "- **Низкая уверенность**: Модель не уверена в предсказаниях (все вероятности близки)\n",
                "- **Ошибки загрузки**: Проверьте пути к файлам модели\n",
                "- **Всегда один класс**: Модель переобучена или данные несбалансированы"
            ]
        }
    ],
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3"
        },
        "language_info": {
            "codemirror_mode": {
                "name": "ipython",
                "version": 3
            },
            "file_extension": ".py",
            "mimetype": "text/x-python",
            "name": "python",
            "nbconvert_exporter": "python",
            "pygments_lexer": "ipython3",
            "version": "3.8.0"
        }
    },
    "nbformat": 4,
    "nbformat_minor": 4
}

with open('diagnose_model.ipynb', 'w', encoding='utf-8') as f:
    json.dump(notebook, f, indent=2, ensure_ascii=False)

print('✓ Notebook создан: diagnose_model.ipynb')
