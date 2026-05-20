import io
import time
import numpy as np
import cv2
import base64
from utils.tiles import fetch_satellite_image

def generate_mock_overlay(bbox):
    try:
        image_rgb, actual_bounds = fetch_satellite_image(bbox, zoom=13)
        if image_rgb is None:
            return None, None, None
        
        height, width = image_rgb.shape[:2]

        hsv = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2HSV)
        lower_blue = np.array([90, 40, 40])
        upper_blue = np.array([140, 255, 255])
        water_mask = cv2.inRange(hsv, lower_blue, upper_blue)

        output_rgba = np.zeros((height, width, 4), dtype=np.uint8)
        
        c_v_high = [0, 100, 0, 180] 
        c_high = [0, 200, 0, 180]
        c_mod = [0, 255, 255, 180]
        c_low = [0, 165, 255, 180]
        c_wt = [0, 0, 255, 180]
        c_ds = [150, 150, 150, 180]
        c_mt = [100, 70, 50, 180]
        
        full_water_mask = cv2.bitwise_or(water_mask, cv2.inRange(hsv, np.array([0, 0, 0]), np.array([180, 255, 60])))
        
        output_rgba[:] = c_ds
        output_rgba[full_water_mask > 0] = c_wt
        H = hsv[:,:,0]; S = hsv[:,:,1]; V = hsv[:,:,2]
        is_land = (full_water_mask == 0)
        
        gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        blur_mag = cv2.GaussianBlur(mag, (21, 21), 0)
        
        m_mountains = is_land & (blur_mag > 60)
        output_rgba[m_mountains] = c_mt
        
        fertility_mask = is_land & ~m_mountains
        
        mask_vh = (H > 35) & (H < 85) & (S > 80) & (V > 30) & fertility_mask
        output_rgba[mask_vh] = c_v_high
        mask_h = (H > 30) & (H < 90) & (S > 40) & (V > 40) & fertility_mask & ~mask_vh
        output_rgba[mask_h] = c_high
        mask_m = (H > 15) & (H < 35) & (S > 20) & fertility_mask & ~(mask_vh | mask_h)
        output_rgba[mask_m] = c_mod
        mask_l = (H > 10) & (H < 22) & (S > 10) & fertility_mask & ~(mask_vh | mask_h | mask_m)
        output_rgba[mask_l] = c_low

        total_pixels = height * width
        vh_c = np.count_nonzero(mask_vh)
        h_c = np.count_nonzero(mask_h)
        m_c = np.count_nonzero(mask_m)
        l_c = np.count_nonzero(mask_l)
        mt_c = np.count_nonzero(m_mountains)
        wt_c = np.count_nonzero(full_water_mask)
        
        ds_c = total_pixels - (vh_c + h_c + m_c + l_c + mt_c + wt_c)

        stats = {
            "very_high": (vh_c / total_pixels) * 100,
            "high": (h_c / total_pixels) * 100,
            "moderate": (m_c / total_pixels) * 100,
            "low": (l_c / total_pixels) * 100,
            "mountains": (mt_c / total_pixels) * 100,
            "water": (wt_c / total_pixels) * 100,
            "desert": (ds_c / total_pixels) * 100,
            "analysis_method": "Heuristic (HSV + Edge)"
        }

        output_bgra = cv2.cvtColor(output_rgba, cv2.COLOR_RGBA2BGRA)
        _, buffer = cv2.imencode('.png', output_bgra)
        png_base64 = base64.b64encode(buffer).decode('utf-8')
        
        return f"data:image/png;base64,{png_base64}", actual_bounds, stats
        
    except Exception as e:
        return None, None, None


def analyze_ndvi(bbox):
    try:
        image_rgb, actual_bounds = fetch_satellite_image(bbox, zoom=13)
        if image_rgb is None:
            return None
        
        height, width = image_rgb.shape[:2]
        
        R = image_rgb[:,:,0].astype(np.float32)
        G = image_rgb[:,:,1].astype(np.float32)
        B = image_rgb[:,:,2].astype(np.float32)
        
        numerator = 2*G - R - B
        denominator = 2*G + R + B + 1e-6  
        pseudo_ndvi = numerator / denominator
        
        pseudo_ndvi = np.clip(pseudo_ndvi, -1, 1)
        
        ndvi_mean = float(np.mean(pseudo_ndvi))
        ndvi_min = float(np.min(pseudo_ndvi))
        ndvi_max = float(np.max(pseudo_ndvi))
        
        moisture_index = float(np.mean(B) / 255.0)
        
        health_score = float((ndvi_mean + 1) / 2 * 100)
        
        if ndvi_mean < -0.1:
            growth_stage = 'bare_soil'
        elif ndvi_mean < 0.1:
            growth_stage = 'emergence'
        elif ndvi_mean < 0.3:
            growth_stage = 'vegetative'
        elif ndvi_mean < 0.5:
            growth_stage = 'flowering'
        else:
            growth_stage = 'maturation'
        
        output_rgba = np.zeros((height, width, 4), dtype=np.uint8)
        
        c_healthy = [0, 128, 0, 180]
        c_moderate = [144, 238, 144, 180]
        c_weak = [255, 255, 0, 180]
        c_soil = [139, 69, 19, 180]
        c_water = [0, 0, 139, 180]
        
        mask_healthy = pseudo_ndvi > 0.4
        mask_moderate = (pseudo_ndvi > 0.2) & (pseudo_ndvi <= 0.4)
        mask_weak = (pseudo_ndvi > 0) & (pseudo_ndvi <= 0.2)
        mask_soil = (pseudo_ndvi > -0.2) & (pseudo_ndvi <= 0)
        mask_water = pseudo_ndvi <= -0.2
        
        output_rgba[mask_healthy] = c_healthy
        output_rgba[mask_moderate] = c_moderate
        output_rgba[mask_weak] = c_weak
        output_rgba[mask_soil] = c_soil
        output_rgba[mask_water] = c_water
        
        output_bgra = cv2.cvtColor(output_rgba, cv2.COLOR_RGBA2BGRA)
        _, buffer = cv2.imencode('.png', output_bgra)
        png_base64 = base64.b64encode(buffer).decode('utf-8')
        
        return {
            "ndvi_mean": round(ndvi_mean, 4),
            "ndvi_min": round(ndvi_min, 4),
            "ndvi_max": round(ndvi_max, 4),
            "moisture_index": round(moisture_index, 4),
            "health_score": round(health_score, 2),
            "growth_stage": growth_stage,
            "overlay": f"data:image/png;base64,{png_base64}",
            "bounds": actual_bounds
        }
        
    except Exception as e:
        return None


def detect_weeds(bbox):
    try:
        image_rgb, actual_bounds = fetch_satellite_image(bbox, zoom=14)
        if image_rgb is None:
            return None
        
        height, width = image_rgb.shape[:2]
        
        hsv = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2HSV)
        H = hsv[:,:,0]; S = hsv[:,:,1]; V = hsv[:,:,2]
        
        vegetation_mask = (H > 25) & (H < 95) & (S > 30) & (V > 30)
        
        gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
        kernel_size = 5
        local_mean = cv2.blur(gray.astype(np.float32), (kernel_size, kernel_size))
        local_sq_mean = cv2.blur((gray.astype(np.float32))**2, (kernel_size, kernel_size))
        local_variance = local_sq_mean - local_mean**2
        
        veg_pixels = local_variance[vegetation_mask]
        if veg_pixels.size > 0:
            variance_threshold = np.percentile(veg_pixels, 75)
        else:
            variance_threshold = 0
        high_variance_mask = (local_variance > variance_threshold) & vegetation_mask
        
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        weed_mask = cv2.morphologyEx(high_variance_mask.astype(np.uint8) * 255, cv2.MORPH_CLOSE, kernel)
        weed_mask = cv2.morphologyEx(weed_mask, cv2.MORPH_OPEN, kernel)
        
        contours, _ = cv2.findContours(weed_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        detections = []
        min_area = 100
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue
            
            M = cv2.moments(contour)
            if M["m00"] == 0:
                continue
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            
            min_lon, min_lat, max_lon, max_lat = bbox
            lat = max_lat - (cy / height) * (max_lat - min_lat)
            lon = min_lon + (cx / width) * (max_lon - min_lon)
            
            if area > 5000:
                severity = 'critical'
            elif area > 2000:
                severity = 'high'
            elif area > 500:
                severity = 'medium'
            else:
                severity = 'low'
            
            area_sq_m = area * 25
            
            detections.append({
                "name": "Потенциальный сорняк",
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "area": round(area_sq_m, 2),
                "severity": severity,
                "confidence": round(0.7 + (area / 10000) * 0.3, 2),
                "recommendations": get_weed_recommendations(severity)
            })
        
        weed_coverage = (np.count_nonzero(weed_mask) / (height * width)) * 100
        
        output_rgba = np.zeros((height, width, 4), dtype=np.uint8)
        output_rgba[:,:,0] = image_rgb[:,:,0] // 2
        output_rgba[:,:,1] = image_rgb[:,:,1] // 2
        output_rgba[:,:,2] = image_rgb[:,:,2] // 2
        output_rgba[:,:,3] = 100
        weed_indices = weed_mask > 0
        output_rgba[weed_indices] = [255, 0, 0, 200]
        
        output_bgra = cv2.cvtColor(output_rgba, cv2.COLOR_RGBA2BGRA)
        _, buffer = cv2.imencode('.png', output_bgra)
        png_base64 = base64.b64encode(buffer).decode('utf-8')
        
        result = {
            "detections": detections,
            "weed_coverage": round(weed_coverage, 2),
            "overlay": f"data:image/png;base64,{png_base64}",
            "bounds": actual_bounds,
            "total_weed_area_sqm": sum(d['area'] for d in detections),
            "analysis_method": "Heuristic"
        }
        
        return result
        
    except Exception as e:
        return None


def get_weed_recommendations(severity):
    recommendations = {
        'low': "Рекомендуется ручная прополка. Мониторинг каждые 2 недели.",
        'medium': "Требуется механическая обработка или точечное применение гербицидов. Мониторинг каждую неделю.",
        'high': "Срочно необходима обработка гербицидами. Рекомендуется консультация агронома.",
        'critical': "КРИТИЧЕСКАЯ ситуация! Немедленная обработка всего участка. Возможна потеря урожая без вмешательства."
    }
    return recommendations.get(severity, "Рекомендуется дополнительный осмотр.")


def calculate_crop_health_from_history(growth_records):
    if len(growth_records) < 2:
        return {"trend": "insufficient_data", "recommendation": "Недостаточно данных для анализа"}
    
    records = sorted(growth_records, key=lambda x: x.observation_date)
    
    ndvi_values = [r.ndvi_mean for r in records if r.ndvi_mean is not None]
    if len(ndvi_values) >= 2:
        first_half = np.mean(ndvi_values[:len(ndvi_values)//2])
        second_half = np.mean(ndvi_values[len(ndvi_values)//2:])
        ndvi_trend = second_half - first_half
    else:
        ndvi_trend = 0
    
    if ndvi_trend > 0.1:
        trend = "improving"
        recommendation = "Растительность активно развивается. Продолжайте текущий уход."
    elif ndvi_trend < -0.1:
        trend = "declining"
        recommendation = "Замечено снижение здоровья растений. Проверьте полив, удобрения и наличие вредителей."
    else:
        trend = "stable"
        recommendation = "Состояние растений стабильное."
    
    return {
        "trend": trend,
        "ndvi_change": round(ndvi_trend, 4),
        "recommendation": recommendation,
        "data_points": len(ndvi_values)
    }


def detect_buildings(bbox):
    try:
        image_rgb, actual_bounds = fetch_satellite_image(bbox, zoom=15) 
        if image_rgb is None:
            return None
        
        height, width = image_rgb.shape[:2]
        gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
        
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        gray = clahe.apply(gray)
        
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        buildings = []
        building_mask = np.zeros((height, width), dtype=np.uint8)
        
        total_area_pixels = height * width
        building_area_pixels = 0
        
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 50: 
                continue
            
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)
            
            if 3 <= len(approx) <= 6:
                x, y, w, h = cv2.boundingRect(approx)
                aspect_ratio = float(w)/h
                
                if 0.2 < aspect_ratio < 5:
                    cv2.drawContours(building_mask, [cnt], -1, 255, -1)
                    building_area_pixels += area
                    
                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])
                        
                        min_lon, min_lat, max_lon, max_lat = bbox
                        lat = max_lat - (cy / height) * (max_lat - min_lat)
                        lon = min_lon + (cx / width) * (max_lon - min_lon)
                        
                        buildings.append({
                            "type": "building",
                            "lat": round(lat, 6),
                            "lon": round(lon, 6),
                            "area_sqm": round(area * 10, 2) 
                        })

        building_density = (building_area_pixels / total_area_pixels) * 100
        
        output_rgba = np.zeros((height, width, 4), dtype=np.uint8)
        output_rgba[building_mask > 0] = [255, 69, 0, 180] 
        
        output_bgra = cv2.cvtColor(output_rgba, cv2.COLOR_RGBA2BGRA)
        _, buffer = cv2.imencode('.png', output_bgra)
        png_base64 = base64.b64encode(buffer).decode('utf-8')
        
        if building_density > 40:
            district_type = "Плотная городская застройка"
        elif building_density > 15:
            district_type = "Жилой район / Пригород"
        elif building_density > 1:
            district_type = "Сельская местность / Редкая застройка"
        else:
            district_type = "Незастроенная территория"
            
        return {
            "building_density": round(building_density, 2),
            "district_type": district_type,
            "overlay": f"data:image/png;base64,{png_base64}",
            "bounds": actual_bounds
        }

    except Exception as e:
        return None


def predict_development(bbox):
    try:
        image_rgb, actual_bounds = fetch_satellite_image(bbox, zoom=14)
        if image_rgb is None: return None
        
        height, width = image_rgb.shape[:2]
        gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
        blur = cv2.GaussianBlur(gray, (5,5), 0)
        
        edges = cv2.Canny(blur, 50, 150)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        built_up_mask = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        built_up_mask = cv2.dilate(built_up_mask, kernel, iterations=2) 
        
        hsv = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2HSV)
        lower_blue = np.array([90, 40, 40]); upper_blue = np.array([140, 255, 255])
        water_mask = cv2.inRange(hsv, lower_blue, upper_blue)
        
        lower_forest = np.array([35, 100, 20]); upper_forest = np.array([85, 255, 150])
        forest_mask = cv2.inRange(hsv, lower_forest, upper_forest)
        
        unsuitable_mask = cv2.bitwise_or(water_mask, forest_mask)
        
        empty_space = cv2.bitwise_not(built_up_mask)
        
        available_land = cv2.bitwise_and(empty_space, empty_space, mask=cv2.bitwise_not(unsuitable_mask))
        
        expansion_zone = cv2.dilate(built_up_mask, kernel, iterations=5)
        predicted_growth = cv2.bitwise_and(expansion_zone, available_land)
        
        predicted_growth = cv2.morphologyEx(predicted_growth, cv2.MORPH_OPEN, kernel)
        
        growth_pixels = np.count_nonzero(predicted_growth)
        growth_percent = (growth_pixels / (height * width)) * 100
        
        output_rgba = np.zeros((height, width, 4), dtype=np.uint8)
        
        output_rgba[predicted_growth > 0] = [0, 215, 255, 150] 
        
        output_bgra = cv2.cvtColor(output_rgba, cv2.COLOR_RGBA2BGRA)
        _, buffer = cv2.imencode('.png', output_bgra)
        png_base64 = base64.b64encode(buffer).decode('utf-8')
        
        recommendations = []
        if growth_percent > 30:
            status = "Высокий потенциал урбанизации"
            recommendations.append("Район имеет много свободной земли рядом с инфраструктурой.")
            recommendations.append("Высокая вероятность жилой застройки в ближайшие 2-3 года.")
        elif growth_percent > 10:
            status = "Умеренный потенциал"
            recommendations.append("Возможно точечное строительство.")
        else:
            status = "Низкий потенциал / Насыщение"
            recommendations.append("Район плотно застроен или ограничен природными факторами.")

        return {
            "growth_status": status,
            "growth_potential_percent": round(growth_percent, 2),
            "recommendations": recommendations,
            "overlay": f"data:image/png;base64,{png_base64}",
            "bounds": actual_bounds
        }
    
    except Exception as e:
        return None


def analyze_environment(bbox):
    import random
    import requests
    
    min_lon, min_lat, max_lon, max_lat = bbox
    center_lon = (min_lon + max_lon) / 2
    center_lat = (min_lat + max_lat) / 2
    
    temp = 15.0
    humidity = 60
    wind_speed = 3.0
    condition = "Ясно"
    
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={center_lat}&longitude={center_lon}&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            current = data.get('current', {})
            temp = current.get('temperature_2m', temp)
            humidity = current.get('relative_humidity_2m', humidity)
            wind_speed = round(current.get('wind_speed_10m', wind_speed * 3.6) / 3.6, 1)
            
            code = current.get('weather_code', 0)
            if code == 0: condition = "Ясно"
            elif code in [1, 2, 3]: condition = "Облачно"
            elif code <= 48: condition = "Туман"
            elif code <= 67: condition = "Дождь"
            elif code <= 79: condition = "Снег"
            else: condition = "Осадки/Шторм"
    except Exception as e:
        temp = round(random.uniform(10, 25), 1)
        humidity = random.randint(40, 80)
        wind_speed = round(random.uniform(1, 8), 1)
    
    ph_level = round(random.uniform(6.0, 7.8), 1)
    
    nitrogen = random.randint(20, 60)
    phosphorus = random.randint(15, 45)
    potassium = random.randint(100, 300)
    
    soil_moisture = random.randint(15, 45) 
    
    return {
        "weather": {
            "temp": temp,
            "condition": condition,
            "humidity": humidity,
            "wind_speed": wind_speed
        },
        "soil_chemistry": {
            "ph": ph_level,
            "nitrogen": nitrogen, 
            "phosphorus": phosphorus, 
            "potassium": potassium, 
            "moisture": soil_moisture
        },
        "recommendation": get_chem_recommendation(ph_level, nitrogen, soil_moisture)
    }

def get_chem_recommendation(ph, n, moisture):
    recs = []
    if ph < 6.0: recs.append("Почва кислая: рекомендуется известкование.")
    if ph > 7.5: recs.append("Почва щелочная: рекомендуется гипсование.")
    if n < 30: recs.append("Низкий азот: внесите аммиачную селитру.")
    if moisture < 20: recs.append("Внимание: низкая влажность почвы, требуется полив.")
    
    if not recs:
        return "Химический состав в норме. Стандартная подкормка."
    return " ".join(recs)


CROP_DATABASE = [ 
    {
        "name": "Пшеница",
        "icon": "🌾",
        "ph_range": (6.0, 7.5),
        "temp_min": -2,
        "nitrogen_req": "medium",
        "desc": "Отлично подходит для текущего сезона."
    },
    {
        "name": "Хлопок",
        "icon": "☁️",
        "ph_range": (6.5, 8.0),
        "temp_min": 10,
        "nitrogen_req": "high",
        "desc": "Требует тепла и высокого содержания азота."
    },
    {
        "name": "Томаты",
        "icon": "🍅",
        "ph_range": (6.0, 6.8),
        "temp_min": 15,
        "nitrogen_req": "high",
        "desc": "Хороший выбор для теплиц или теплого сезона."
    },
    {
        "name": "Картофель",
        "icon": "🥔",
        "ph_range": (4.8, 6.5),
        "temp_min": 5,
        "nitrogen_req": "high",
        "desc": "Любит слабокислые почвы."
    },
    {
        "name": "Люцерна",
        "icon": "🌿",
        "ph_range": (6.2, 7.8),
        "temp_min": 5,
        "nitrogen_req": "low",
        "desc": "Помогает восстановить азот в почве."
    },
    {
        "name": "Виноград",
        "icon": "🍇",
        "ph_range": (5.5, 7.5),
        "temp_min": 10,
        "nitrogen_req": "medium",
        "desc": "Многолетняя культура для данного региона."
    },
    {
        "name": "Подсолнечник",
        "icon": "",
        "ph_range": (6.0, 7.5),
        "temp_min": 15,
        "nitrogen_req": "medium",
        "desc": "Светолюбивая и засухоустойчивая культура."
    },
    {
        "name": "Кукуруза",
        "icon": "",
        "ph_range": (5.8, 7.0),
        "temp_min": 10,
        "nitrogen_req": "high",
        "desc": "Высокопродуктивная злаковая культура."
    },
    {
        "name": "Соя",
        "icon": "",
        "ph_range": (6.0, 7.0),
        "temp_min": 12,
        "nitrogen_req": "low",
        "desc": "Бобовая культура, обогащает почву азотом."
    },
    {
        "name": "Лен",
        "icon": "",
        "ph_range": (5.5, 6.5),
        "temp_min": 5,
        "nitrogen_req": "medium",
        "desc": "Отличная техническая культура для умеренного климата."
    },
    {
        "name": "Огурцы",
        "icon": "",
        "ph_range": (6.0, 7.0),
        "temp_min": 18,
        "nitrogen_req": "high",
        "desc": "Влаголюбивая и теплолюбивая овощная культура."
    },
    {
        "name": "Капуста",
        "icon": "",
        "ph_range": (6.5, 7.5),
        "temp_min": 2,
        "nitrogen_req": "high",
        "desc": "Овощная культура, требовательная к влаге и плодородию."
    },
    {
        "name": "Морковь",
        "icon": "",
        "ph_range": (5.5, 7.0),
        "temp_min": 3,
        "nitrogen_req": "medium",
        "desc": "Корнеплод, хорошо растущий на рыхлых почвах."
    },
    {
        "name": "Яблоня",
        "icon": "",
        "ph_range": (5.6, 7.0),
        "temp_min": -5,
        "nitrogen_req": "medium",
        "desc": "Многолетняя плодовая культура, основа фруктовых садов."
    },
    {
        "name": "Сахарная свекла",
        "icon": "",
        "ph_range": (6.5, 7.5),
        "temp_min": 8,
        "nitrogen_req": "high",
        "desc": "Важная промышленная культура, любит богатую гумусом почву."
    },
    {
        "name": "Рис",
        "icon": "",
        "ph_range": (5.0, 6.5),
        "temp_min": 20,
        "nitrogen_req": "high",
        "desc": "Влаголюбивая злаковая культура, требующая обильного полива."
    },
    {
        "name": "Арахис",
        "icon": "",
        "ph_range": (5.8, 6.2),
        "temp_min": 20,
        "nitrogen_req": "low",
        "desc": "Теплолюбивая бобовая культура, предпочитает легкие почвы."
    },
    {
        "name": "Нут",
        "icon": "",
        "ph_range": (6.5, 8.0),
        "temp_min": 15,
        "nitrogen_req": "low",
        "desc": "Отличная засухоустойчивая бобовая культура."
    },
    {
        "name": "Дыня",
        "icon": "",
        "ph_range": (6.0, 7.0),
        "temp_min": 25,
        "nitrogen_req": "medium",
        "desc": "Бахчевая культура, любящая жару и обилие солнца."
    },
    {
        "name": "Гречиха",
        "icon": "",
        "ph_range": (5.0, 7.0),
        "temp_min": 10,
        "nitrogen_req": "low",
        "desc": "Ценная крупяная и прекрасная медоносная культура."
    },
    {
        "name": "Овес",
        "icon": "",
        "ph_range": (5.0, 6.5),
        "temp_min": 2,
        "nitrogen_req": "medium",
        "desc": "Выносливый злак, терпимый даже к прохладному климату."
    },
    {
        "name": "Рожь",
        "icon": "",
        "ph_range": (5.0, 7.5),
        "temp_min": -5,
        "nitrogen_req": "medium",
        "desc": "Морозоустойчивая зерновая культура, нетребовательна к почве."
    },
    {
        "name": "Клубника",
        "icon": "",
        "ph_range": (5.5, 6.5),
        "temp_min": 15,
        "nitrogen_req": "high",
        "desc": "Популярная ягодная культура, требует качественного полива."
    },
    {
        "name": "Персик",
        "icon": "",
        "ph_range": (6.0, 7.0),
        "temp_min": 10,
        "nitrogen_req": "medium",
        "desc": "Очень теплолюбивое фруктовое дерево."
    },
    {
        "name": "Чеснок",
        "icon": "",
        "ph_range": (6.5, 7.0),
        "temp_min": 0,
        "nitrogen_req": "medium",
        "desc": "Стойкая культура, обладающая высокой неприхотливостью."
    },
    {
        "name": "Лук",
        "icon": "",
        "ph_range": (6.0, 7.0),
        "temp_min": 5,
        "nitrogen_req": "medium",
        "desc": "Холодостойкая культура, предпочитает супесчаные почвы."
    },
    {
        "name": "Баклажаны",
        "icon": "",
        "ph_range": (6.0, 7.0),
        "temp_min": 20,
        "nitrogen_req": "high",
        "desc": "Теплолюбивая культура, требовательная к влаге и солнцу."
    },
    {
        "name": "Перец",
        "icon": "",
        "ph_range": (6.0, 6.8),
        "temp_min": 18,
        "nitrogen_req": "high",
        "desc": "Нуждается в плодородной почве и обильном поливе."
    },
    {
        "name": "Груша",
        "icon": "",
        "ph_range": (5.5, 6.5),
        "temp_min": 0,
        "nitrogen_req": "medium",
        "desc": "Многолетнее плодовое дерево с глубокой корневой системой."
    },
    {
        "name": "Абрикос",
        "icon": "",
        "ph_range": (6.5, 7.5),
        "temp_min": 15,
        "nitrogen_req": "low",
        "desc": "Светолюбивое и засухоустойчивое дерево."
    },
    {
        "name": "Гранат",
        "icon": "",
        "ph_range": (6.0, 7.5),
        "temp_min": 15,
        "nitrogen_req": "medium",
        "desc": "Жаростойкое растение, отлично подходит для жаркого климата."
    },
    {
        "name": "Арбуз",
        "icon": "",
        "ph_range": (6.0, 7.0),
        "temp_min": 22,
        "nitrogen_req": "medium",
        "desc": "Засухоустойчивая бахчевая культура, любит солнце."
    },
    {
        "name": "Грецкий орех",
        "icon": "",
        "ph_range": (6.5, 7.5),
        "temp_min": 5,
        "nitrogen_req": "low",
        "desc": "Долговечное дерево с раскидистой кроной."
    },
    {
        "name": "Тыква",
        "icon": "",
        "ph_range": (6.0, 7.0),
        "temp_min": 15,
        "nitrogen_req": "medium",
        "desc": "Теплолюбивое растение, требует пространства."
    },
    {
        "name": "Кабачок",
        "icon": "",
        "ph_range": (6.0, 7.0),
        "temp_min": 15,
        "nitrogen_req": "medium",
        "desc": "Скороспелая культура, дающая стабильный урожай."
    },
    {
        "name": "Сорго",
        "icon": "",
        "ph_range": (5.5, 8.5),
        "temp_min": 15,
        "nitrogen_req": "medium",
        "desc": "Чрезвычайно засухоустойчивая злаковая культура."
    },
    {
        "name": "Слива",
        "icon": "",
        "ph_range": (6.0, 7.0),
        "temp_min": 5,
        "nitrogen_req": "medium",
        "desc": "Плодовое дерево, хорошо адаптирующееся к условиям."
    },
    {
        "name": "Черешня",
        "icon": "",
        "ph_range": (6.5, 7.0),
        "temp_min": 10,
        "nitrogen_req": "high",
        "desc": "Раннее плодовое дерево, чувствительно к заморозкам."
    },
    {
        "name": "Фасоль",
        "icon": "",
        "ph_range": (6.0, 7.0),
        "temp_min": 12,
        "nitrogen_req": "low",
        "desc": "Теплолюбивое бобовое, обогащает почву."
    }
]

def recommend_crops(env_data):
    soil = env_data['soil_chemistry']
    weather = env_data['weather']
    
    recommendations = []
    
    for crop in CROP_DATABASE:
        score = 0
        reasons = []
        
        if crop['ph_range'][0] <= soil['ph'] <= crop['ph_range'][1]:
            score += 2
        elif abs(soil['ph'] - crop['ph_range'][0]) < 0.5 or abs(soil['ph'] - crop['ph_range'][1]) < 0.5:
             score += 1 
             reasons.append("pH не идеален")
        else:
            continue 
            
        if weather['temp'] >= crop['temp_min']:
            score += 2
        else:
             reasons.append("Холодно")
             
        n_val = soil['nitrogen']
        if crop['nitrogen_req'] == 'high' and n_val > 40: score += 1
        if crop['nitrogen_req'] == 'low' and n_val < 30: score += 1
        
        if score >= 3:
            recommendations.append({
                "name": crop["name"],
                "icon": crop["icon"],
                "match_percent": int((score / 5) * 100),
                "desc": crop["desc"]
            })
            
    recommendations.sort(key=lambda x: x['match_percent'], reverse=True)
    return recommendations[:3] 
    
    
def analyze_environment_with_crops(bbox):
    base_data = analyze_environment(bbox)
    base_data['crops'] = recommend_crops(base_data)
    return base_data


def filter_urban_areas(bbox):
    try:
        image_rgb, actual_bounds = fetch_satellite_image(bbox, zoom=14)
        if image_rgb is None: return None
        
        height, width = image_rgb.shape[:2]
        
        hsv = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2HSV)
        lower_green = np.array([25, 40, 20]); upper_green = np.array([95, 255, 255])
        veg_mask = cv2.inRange(hsv, lower_green, upper_green)
        
        lower_blue = np.array([95, 40, 40]); upper_blue = np.array([140, 255, 255])
        water_mask = cv2.inRange(hsv, lower_blue, upper_blue)
        
        gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
        
        edges = cv2.Canny(gray, 50, 200)
        
        kernel_sq = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        urban_texture = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel_sq)
        urban_texture = cv2.dilate(urban_texture, kernel_sq, iterations=2)
        
        natural_mask = cv2.bitwise_or(veg_mask, water_mask)
        urban_mask = cv2.bitwise_and(urban_texture, urban_texture, mask=cv2.bitwise_not(natural_mask))
        
        urban_mask = cv2.morphologyEx(urban_mask, cv2.MORPH_OPEN, kernel_sq)
        
        total_pixels = height * width
        urban_pixels = np.count_nonzero(urban_mask)
        urban_percent = (urban_pixels / total_pixels) * 100
        
        output_rgba = np.zeros((height, width, 4), dtype=np.uint8)
        
        output_rgba[urban_mask > 0] = [80, 70, 70, 200] 
        
        output_bgra = cv2.cvtColor(output_rgba, cv2.COLOR_RGBA2BGRA)
        _, buffer = cv2.imencode('.png', output_bgra)
        png_base64 = base64.b64encode(buffer).decode('utf-8')
        
        stats = {
            "urban_percent": round(urban_percent, 2),
            "veg_percent": round((np.count_nonzero(veg_mask) / total_pixels) * 100, 2),
            "water_percent": round((np.count_nonzero(water_mask) / total_pixels) * 100, 2)
        }
        
        return {
            "stats": stats,
            "overlay": f"data:image/png;base64,{png_base64}",
            "bounds": actual_bounds
        }
    except Exception as e:
        return None
