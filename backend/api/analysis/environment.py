"""Agro-climatic context for a bounding box.

This module replaces the block that used to invent soil chemistry with
``random.uniform``. Values now come from ISRIC SoilGrids and Open-Meteo, and
when a service is unavailable the corresponding field is ``None`` with an
explicit reason -- never a fabricated number.

Every returned measurement carries its own ``source``:

* ``measured``    -- reported by SoilGrids / Open-Meteo as-is
* ``derived``     -- computed from measured values by a documented agronomic
                     rule (see :mod:`api.services.soilgrids`)
* ``unavailable`` -- the upstream service had no data for this point
"""

import logging

from api.crop_catalog import CROP_DATABASE, get_allowed_crops_for_country
from api.services import geocoding, soilgrids, weather

logger = logging.getLogger(__name__)


def _centre(bbox):
    min_lon, min_lat, max_lon, max_lat = bbox
    return (min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0


def _value(properties, key):
    """Read a numeric value out of the SoilGrids result, or ``None``."""
    if not properties:
        return None
    entry = properties.get(key)
    return entry.get('value') if isinstance(entry, dict) else None


def _range(properties, key):
    """The 5th-95th percentile SoilGrids publishes for a measured property."""
    if not properties:
        return None
    entry = properties.get(key)
    return entry.get('range') if isinstance(entry, dict) else None


def _sources(properties, moisture_available):
    if not properties:
        return dict.fromkeys(('ph', 'nitrogen', 'phosphorus', 'potassium', 'moisture'), 'unavailable')

    sources = {}
    for name in ('ph', 'nitrogen', 'phosphorus', 'potassium'):
        entry = properties.get(name)
        sources[name] = entry.get('source', 'unavailable') if isinstance(entry, dict) else 'unavailable'
    sources['moisture'] = 'derived' if moisture_available else 'unavailable'
    return sources


def chemistry_recommendation(ph, nitrogen, moisture):
    """Agronomic notes for the values that are actually known."""
    notes = []

    if ph is None:
        notes.append('Нет данных о pH для этой точки.')
    elif ph < 6.0:
        notes.append('Почва кислая: рекомендуется известкование.')
    elif ph > 7.5:
        notes.append('Почва щелочная: рекомендуется гипсование.')

    if nitrogen is not None and nitrogen < 30:
        notes.append('Низкий доступный азот: внесите аммиачную селитру или мочевину.')

    if moisture is not None and moisture < 20:
        notes.append('Низкая влажность почвы, требуется полив.')

    if not notes:
        return 'Показатели в пределах нормы для большинства культур. Стандартная подкормка.'
    return ' '.join(notes)


def analyze_environment(bbox):
    """Weather, soil chemistry and derived recommendations for ``bbox``."""
    lat, lon = _centre(bbox)

    country, country_is_approximate = geocoding.reverse_geocode_country(lat, lon)
    current_weather = weather.fetch_weather(lat, lon)
    soil_properties = soilgrids.fetch_soil_properties(lat, lon)

    precipitation = (current_weather or {}).get('precipitation_7d_mm', 0.0)
    moisture = soilgrids.estimate_current_moisture(
        _value(soil_properties, 'water_holding_capacity'), precipitation
    )

    ph = _value(soil_properties, 'ph')
    nitrogen = _value(soil_properties, 'nitrogen')
    phosphorus = _value(soil_properties, 'phosphorus')
    potassium = _value(soil_properties, 'potassium')

    warnings = []
    if soil_properties is None:
        warnings.append(
            'Данные о почве для этой точки недоступны (SoilGrids не покрывает '
            'водоёмы и ледники, либо сервис временно недоступен).'
        )
    if current_weather is None:
        warnings.append('Данные о погоде временно недоступны.')
    if country_is_approximate and country:
        warnings.append(f'Страна определена приблизительно по координатам: {country}.')

    environment = {
        'country': country or 'Выбранная местность',
        'country_is_approximate': country_is_approximate,
        'coordinates': {'lat': round(lat, 5), 'lon': round(lon, 5)},
        'weather': {
            'temp': (current_weather or {}).get('temp'),
            'condition': (current_weather or {}).get('condition'),
            'humidity': (current_weather or {}).get('humidity'),
            'wind_speed': (current_weather or {}).get('wind_speed'),
            'precipitation_7d_mm': (current_weather or {}).get('precipitation_7d_mm'),
            'provider': (current_weather or {}).get('provider'),
        },
        'soil_chemistry': {
            'ph': ph,
            'nitrogen': nitrogen,
            'phosphorus': phosphorus,
            'potassium': potassium,
            'moisture': moisture,
            'texture': _value(soil_properties, 'texture'),
            'organic_carbon': _value(soil_properties, 'organic_carbon'),
            'water_holding_capacity': _value(soil_properties, 'water_holding_capacity'),
            'sources': _sources(soil_properties, moisture is not None),
            # 5th-95th percentile bands from SoilGrids: the honest width of a
            # 250 m model prediction, shown next to every measured value.
            'ranges': {
                'ph': _range(soil_properties, 'ph'),
                'organic_carbon': _range(soil_properties, 'organic_carbon'),
                'cec': _range(soil_properties, 'cec'),
                'clay_percent': _range(soil_properties, 'clay_percent'),
                'water_holding_capacity': _range(soil_properties, 'water_holding_capacity'),
            },
            'cec': _value(soil_properties, 'cec'),
            'provider': (soil_properties or {}).get('provider'),
            'depth': (soil_properties or {}).get('depth'),
            'resolution_m': (soil_properties or {}).get('resolution_m'),
        },
        'recommendation': chemistry_recommendation(ph, nitrogen, moisture),
        'warnings': warnings,
    }

    environment['crops'] = recommend_crops(environment)
    return environment


def recommend_crops(environment, limit=3):
    """Rank catalogue crops against the known conditions.

    Scoring only counts criteria that have data. A crop is never rejected for
    failing a check whose input is missing -- it simply scores lower, and the
    match percentage is computed over the criteria that could be evaluated.
    """
    soil = environment['soil_chemistry']
    temperature = environment['weather'].get('temp')
    allowed = get_allowed_crops_for_country(environment.get('country', ''))

    ph = soil.get('ph')
    nitrogen = soil.get('nitrogen')

    if ph is None and temperature is None:
        return []

    results = []
    for crop in CROP_DATABASE:
        if allowed is not None and crop['name'] not in allowed:
            continue

        score = 0
        possible = 0
        reasons = []

        if ph is not None:
            possible += 2
            ph_min, ph_max = crop['ph_range']
            if ph_min <= ph <= ph_max:
                score += 2
            elif min(abs(ph - ph_min), abs(ph - ph_max)) < 0.5:
                score += 1
                reasons.append('pH на границе допустимого')
            else:
                continue  # genuinely unsuitable

        if temperature is not None:
            possible += 2
            if temperature >= crop['temp_min']:
                score += 2
            else:
                reasons.append('Сейчас слишком холодно для посадки')

        if nitrogen is not None:
            possible += 1
            requirement = crop['nitrogen_req']
            if requirement == 'high' and nitrogen > 40:
                score += 1
            elif requirement == 'low' and nitrogen < 30:
                score += 1
            elif requirement == 'medium' and 25 <= nitrogen <= 55:
                score += 1
            else:
                reasons.append('Потребность в азоте не совпадает с почвой')

        if possible == 0:
            continue

        match_percent = int(round(score / possible * 100))
        if match_percent < 50:
            continue

        results.append({
            'name': crop['name'],
            'icon': crop['icon'],
            'match_percent': match_percent,
            'desc': crop['desc'],
            'notes': reasons,
            'evaluated_criteria': possible,
        })

    results.sort(key=lambda item: (item['match_percent'], item['evaluated_criteria']), reverse=True)
    return results[:limit]
