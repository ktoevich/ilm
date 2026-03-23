def get_soil_info(soil_type):
    """
    Returns fertility info and crop recommendations based on soil type.
    """
    data = {
        "Black_Soil": {
            "fertility": "Высокое (High)",
            "description": "Темный, рыхлый грунт. Богатый гумусом.",
            "crops": [
                "Пшеница (Wheat)", 
                "Овощи (Vegetables)", 
                "Подсолнечник (Sunflower)",
                "Кукуруза (Corn)"
            ],
            "visual_characteristics": "Темный цвет, рыхлая структура"
        },
        "Sand": {
            "fertility": "Низкое (Low)",
            "description": "Желтый, зернистый. Быстро пропускает воду, беден питательными веществами.",
            "crops": [
                "Дыни (Melons)", 
                "Виноград (Grapes)", 
                "Сосна (Pine)",
                "Арахис (Peanuts)",
                "Картофель (Potatoes)"
            ],
            "visual_characteristics": "Желтый или светлый цвет, крупное зерно"
        },
        "Clay": {
            "fertility": "Среднее (Medium)",
            "description": "Светло-коричневый, плотный. Тяжелый, удерживает влагу.",
            "crops": [
                "Рис (Rice)", 
                "Бобовые (Legumes)", 
                "Капуста (Cabbage)",
                "Плодовые деревья (Fruit trees)"
            ],
            "visual_characteristics": "Плотный, пластичный, часто трескается при высыхании"
        },
        "Loam": { # Added Loam as it's a common classification
            "fertility": "Среднее-Высокое (Medium-High)",
            "description": "Смесь песка, ила и глины. Идеальна для садоводства.",
            "crops": [
                "Большинство овощей (Most vegetables)",
                "Ягодные кустарники (Berry bushes)",
                "Салаты (Lettuce)",
                "Томаты (Tomatoes)"
            ],
            "visual_characteristics": "Рыхлый, влажный, темно-коричневый"
        },
        # Fallbacks or other types if added
        "Yellow_Soil": {
             "fertility": "Низкое-Среднее",
             "description": "Бедная органикой почва.",
             "crops": ["Чай (Tea)", "Кофе (Coffee)"],
             "visual_characteristics": "Желтоватый оттенок"
        },
        "Red_Soil": {
             "fertility": "Низкое-Среднее",
             "description": "Богата железом, часто кислая.",
             "crops": ["Хлопок (Cotton)", "Цитрусовые (Citrus)", "Табак (Tobacco)"],
             "visual_characteristics": "Красноватый цвет"
        }
    }
    
    return data.get(soil_type, {
        "fertility": "Неизвестно",
        "description": "Тип почвы не распознан.",
        "crops": [],
        "visual_characteristics": "-"
    })
