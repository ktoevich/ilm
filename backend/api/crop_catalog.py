"""Static catalogue of crops used for planting recommendations.

Separate from the ``CropType`` database model on purpose: this list drives the
quick "what could grow here" suggestion shown right after an analysis, and must
work before the user has populated any data of their own.
"""

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


# NOTE: this is a coarse regional filter, not an agronomic authority. It exists
# so the suggestion list does not propose cotton in Siberia. Countries not
# listed here get the unfiltered catalogue.
def get_allowed_crops_for_country(country_name):
    c = country_name.lower().strip()
    # 1. Uzbekistan / Central Asia
    if any(x in c for x in ["uzbek", "узбек", "tadj", "тадж", "turkm", "туркм", "kyrgy", "кирг", "таджик", "киргиз"]):
        return [
            "Хлопок", "Пшеница", "Виноград", "Томаты", "Люцерна", "Кукуруза", "Рис",
            "Дыня", "Арбуз", "Персик", "Абрикос", "Гранат", "Грецкий орех", "Тыква",
            "Нут", "Арахис", "Перец", "Баклажаны", "Огурцы", "Слива", "Черешня"
        ]
    # 2. Kazakhstan
    elif "kazakh" in c or "казах" in c:
        return [
            "Пшеница", "Ячмень", "Подсолнечник", "Лен", "Кукуруза", "Соя", "Сахарная свекла",
            "Картофель", "Капуста", "Морковь", "Гречиха", "Овес", "Рожь", "Фасоль", "Тыква"
        ]
    # 3. Russia / Belarus / Ukraine
    elif any(x in c for x in ["russia", "росси", "belarus", "беларус", "ukrain", "украин"]):
        return [
            "Пшеница", "Картофель", "Подсолнечник", "Кукуруза", "Соя", "Лен", "Капуста",
            "Морковь", "Яблоня", "Сахарная свекла", "Гречиха", "Овес", "Рожь", "Клубника",
            "Лук", "Чеснок", "Груша", "Слива", "Вишня", "Черешня", "Тыква", "Кабачок", "Фасоль"
        ]
    return None
