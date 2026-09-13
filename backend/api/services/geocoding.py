"""Reverse geocoding via Nominatim, with an explicitly approximate fallback.

Nominatim's usage policy requires an identifying User-Agent with a contact
address and discourages bulk traffic, so results are cached aggressively and
the contact is configurable (``GEOCODER_CONTACT``).
"""

import logging

from django.conf import settings
from django.core.cache import cache

from .http import build_session, get_json

logger = logging.getLogger(__name__)

NOMINATIM_URL = 'https://nominatim.openstreetmap.org/reverse'
CACHE_TIMEOUT = 60 * 60 * 24 * 30
COORD_PRECISION = 1  # country resolution: ~11 km cells are plenty

# Coarse fallback used only when Nominatim is unreachable. Ordered smallest
# country first, because the boxes overlap and the first match wins -- the
# previous version listed Russia's box before Central Asia's and swallowed it.
_APPROXIMATE_COUNTRY_BOXES = (
    ('Таджикистан', 36.6, 41.1, 67.3, 75.2),
    ('Киргизия', 39.1, 43.3, 69.2, 80.3),
    ('Узбекистан', 37.1, 45.6, 55.9, 73.2),
    ('Туркменистан', 35.1, 42.8, 52.4, 66.7),
    ('Казахстан', 40.5, 55.5, 46.4, 87.4),
    ('Россия', 41.1, 82.0, 19.6, 180.0),
)


def _session():
    contact = getattr(settings, 'GEOCODER_CONTACT', '')
    suffix = f'; +{contact}' if contact else ''
    if not contact:
        logger.debug('GEOCODER_CONTACT is unset; Nominatim asks for a contact address')
    return build_session(f'FavorableSoil/1.0 (agricultural analysis{suffix})')


def approximate_country(lat, lon):
    """Bounding-box guess. Explicitly approximate -- callers must label it."""
    for name, lat_min, lat_max, lon_min, lon_max in _APPROXIMATE_COUNTRY_BOXES:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return name
    return None


def reverse_geocode_country(lat, lon):
    """Return ``(country_name_or_None, is_approximate)``."""
    key = f'geocode:{round(lat, COORD_PRECISION)}:{round(lon, COORD_PRECISION)}'
    cached = cache.get(key)
    if cached is not None:
        return (cached or None), False

    payload = get_json(
        _session(),
        NOMINATIM_URL,
        params={
            'format': 'json',
            'lat': lat,
            'lon': lon,
            'zoom': 5,
            'addressdetails': 1,
            'accept-language': 'ru',
        },
        timeout=5,
        service='Nominatim',
    )

    country = ((payload or {}).get('address') or {}).get('country')
    if country:
        cache.set(key, country, CACHE_TIMEOUT)
        return country, False

    return approximate_country(lat, lon), True
