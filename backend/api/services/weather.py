"""Open-Meteo client: current conditions plus recent rainfall."""

import logging

from django.core.cache import cache

from .http import build_session, get_json

logger = logging.getLogger(__name__)

FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
CACHE_TIMEOUT = 60 * 30  # weather does not change meaningfully within half an hour
COORD_PRECISION = 2      # ~1 km grid

_session = build_session('FavorableSoil/1.0 (agricultural analysis)')

# https://open-meteo.com/en/docs -- WMO weather interpretation codes
_WEATHER_CODES = (
    (0, 'Ясно'),
    (3, 'Облачно'),
    (48, 'Туман'),
    (67, 'Дождь'),
    (77, 'Снег'),
    (82, 'Ливень'),
    (99, 'Гроза'),
)


def describe_weather_code(code):
    if code is None:
        return None
    for threshold, label in _WEATHER_CODES:
        if code <= threshold:
            return label
    return 'Осадки'


def fetch_weather(lat, lon):
    """Current weather and 7-day precipitation total, or ``None`` if unavailable."""
    key = f'weather:{round(lat, COORD_PRECISION)}:{round(lon, COORD_PRECISION)}'
    cached = cache.get(key)
    if cached is not None:
        return cached or None

    payload = get_json(
        _session,
        FORECAST_URL,
        params={
            'latitude': lat,
            'longitude': lon,
            'current': 'temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code',
            'daily': 'precipitation_sum',
            'past_days': 7,
            'forecast_days': 1,
            'timezone': 'auto',
            'wind_speed_unit': 'ms',
        },
        service='Open-Meteo',
    )

    if not payload or 'current' not in payload:
        cache.set(key, {}, 60 * 5)
        return None

    current = payload['current']
    daily_precip = (payload.get('daily') or {}).get('precipitation_sum') or []
    # past_days=7 puts the seven completed days first, today last.
    past_week = [value for value in daily_precip[:7] if value is not None]

    result = {
        'temp': current.get('temperature_2m'),
        'humidity': current.get('relative_humidity_2m'),
        # wind_speed_unit=ms is requested explicitly, so no conversion here.
        'wind_speed': current.get('wind_speed_10m'),
        'condition': describe_weather_code(current.get('weather_code')),
        'precipitation_7d_mm': round(sum(past_week), 1) if past_week else 0.0,
        'provider': 'Open-Meteo',
    }

    cache.set(key, result, CACHE_TIMEOUT)
    return result
