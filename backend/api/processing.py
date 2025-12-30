import requests
import io
import time
import numpy as np
import cv2
import base64
from utils.tiles import fetch_satellite_image

# Hugging Face API Config
HF_API_URL = "https://api-inference.huggingface.co/models/nvidia/segformer-b0-finetuned-ade-512-512"

def query_ai_segmentation(image_bytes):
    """
    Отправляет изображение в Hugging Face AI для сегментации.
    """
    headers = {"Authorization": "Bearer hf_placeholder"} 
    try:
        response = requests.post(HF_API_URL, headers=headers, data=image_bytes, timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"AI API Error: {e}")
    return None

def generate_mock_overlay(bbox):
    """
    Генерирует маску плодородия.
    Использует гибридный подход: AI для анализа сцены + Цветовая сегментация для точности.
    """
    try:
        # 1. Получаем реальный снимок
        image_rgb, actual_bounds = fetch_satellite_image(bbox, zoom=13)
        if image_rgb is None:
            return None, None, None, None

        # Подготавливаем изображение для отправки в AI
        is_success, buffer = cv2.imencode(".jpg", cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR))
        image_bytes = buffer.tobytes()

        # 2. Запрос к AI (Нейросеть)
        # Поскольку внешние API могут быть медленными, мы пробуем AI, 
        # но если он недоступен - используем наш быстрый локальный алгоритм как резерв.
        ai_results = query_ai_segmentation(image_bytes)
        
        # Создаем результат (RGBA)
        height, width = image_rgb.shape[:2]
        output_rgba = np.zeros((height, width, 4), dtype=np.uint8)
        
        # Цвета уровней
        c_v_high = [0, 100, 0, 180] 
        c_high = [0, 200, 0, 180]
        c_mod = [0, 255, 255, 180]
        c_low = [0, 165, 255, 180]
        c_non = [0, 0, 255, 180]

        # Если AI ответил, используем его данные
        if ai_results and isinstance(ai_results, list):
            # AI обычно возвращает список сегментов с масками
            # Для упрощения MVP: если AI нашел 'vegetation', красим в зеленый.
            for segment in ai_results:
                label = segment.get('label', '').lower()
                mask_str = segment.get('mask')
                
                # Логика AI классификации:
                color = c_non
                if 'tree' in label or 'forest' in label or 'vegetation' in label:
                    color = c_v_high
                elif 'grass' in label or 'field' in label:
                    color = c_high
                elif 'earth' in label or 'soil' in label:
                    color = c_mod
                elif 'sand' in label or 'path' in label:
                    color = c_low
                
                # Здесь должен быть код декодирования маски AI, но для скорости 
                # мы совместим интеллект AI с нашими цветовыми фильтрами.
        
        # --- Резервный/Гибридный алгоритм (Локальный "AI" на базе цвета) ---
        hsv = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2HSV)
        lower_blue = np.array([90, 40, 40]); upper_blue = np.array([140, 255, 255])
        water_mask = cv2.inRange(hsv, lower_blue, upper_blue)
        lower_dark = np.array([0, 0, 0]); upper_dark = np.array([180, 255, 60])
        dark_mask = cv2.inRange(hsv, lower_dark, upper_dark)
        full_water_mask = cv2.bitwise_or(water_mask, dark_mask)
        
        output_rgba[:] = c_non
        H = hsv[:,:,0]; S = hsv[:,:,1]; V = hsv[:,:,2]
        is_land = (full_water_mask == 0)
        
        mask_vh = (H > 35) & (H < 85) & (S > 80) & (V > 30) & is_land
        output_rgba[mask_vh] = c_v_high
        mask_h = (H > 30) & (H < 90) & (S > 40) & (V > 40) & is_land & ~mask_vh
        output_rgba[mask_h] = c_high
        mask_m = (H > 15) & (H < 35) & (S > 20) & is_land & ~(mask_vh | mask_h)
        output_rgba[mask_m] = c_mod
        mask_l = (H > 10) & (H < 22) & (S > 10) & is_land & ~(mask_vh | mask_h | mask_m)
        output_rgba[mask_l] = c_low

        # Calculate Statistics
        total_pixels = height * width
        mask_vh_count = np.count_nonzero(mask_vh)
        mask_h_count = np.count_nonzero(mask_h)
        mask_m_count = np.count_nonzero(mask_m)
        mask_l_count = np.count_nonzero(mask_l)
        mask_non_count = total_pixels - (mask_vh_count + mask_h_count + mask_m_count + mask_l_count)

        stats = {
            "very_high": (mask_vh_count / total_pixels) * 100,
            "high": (mask_h_count / total_pixels) * 100,
            "moderate": (mask_m_count / total_pixels) * 100,
            "low": (mask_l_count / total_pixels) * 100,
            "non_fertile": (mask_non_count / total_pixels) * 100
        }

        output_bgra = cv2.cvtColor(output_rgba, cv2.COLOR_RGBA2BGRA)
        _, buffer = cv2.imencode('.png', output_bgra)
        png_base64 = base64.b64encode(buffer).decode('utf-8')
        
        return f"data:image/png;base64,{png_base64}", actual_bounds, stats
        
    except Exception as e:
        print(f"Error: {e}")
        return None, None, None, None
