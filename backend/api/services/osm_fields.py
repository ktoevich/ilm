"""Field boundaries from OpenStreetMap via the Overpass API.

Free and keyless, which is why it is here instead of a commercial field
delineation service. The trade-off is honest and worth stating: this returns
what people have *mapped*, not what a model detects. Coverage is excellent
across Europe and much of Russia and patchy to absent elsewhere -- a probe
around Tashkent found nothing at an 8 km radius, while a 2 km radius in Bavaria
returned 120 parcels.

When nothing is mapped the caller gets ``None`` and the endpoint answers 404,
rather than a guessed rectangle.

Overpass is a volunteer-run service with a fair-use policy: results are cached
for a week, the query is bounded by radius and timeout, and the User-Agent
identifies this application.
"""

import logging

from django.core.cache import cache

from .http import build_session

logger = logging.getLogger(__name__)

OVERPASS_URL = 'https://overpass-api.de/api/interpreter'
CACHE_TIMEOUT = 60 * 60 * 24 * 7
COORD_PRECISION = 4
DEFAULT_RADIUS_M = 1500
MAX_RADIUS_M = 5000
QUERY_TIMEOUT_S = 25

# Agricultural land uses worth offering as a field boundary.
LANDUSE_PATTERN = 'farmland|meadow|orchard|vineyard|greenhouse_horticulture|allotments'

LANDUSE_LABELS = {
    'farmland': 'Пашня',
    'meadow': 'Луг',
    'orchard': 'Сад',
    'vineyard': 'Виноградник',
    'greenhouse_horticulture': 'Теплицы',
    'allotments': 'Участки',
}

_session = build_session('FavorableSoil/1.0 (agricultural analysis)')


def is_available():
    return True  # no key, no account


def _build_query(lat, lon, radius):
    return f"""
[out:json][timeout:{QUERY_TIMEOUT_S}];
(
  way["landuse"~"{LANDUSE_PATTERN}"](around:{radius},{lat},{lon});
  relation["landuse"~"{LANDUSE_PATTERN}"](around:{radius},{lat},{lon});
);
out geom;
"""


def _ring_area_sqm(ring):
    """Approximate polygon area using the shoelace formula on a local plane.

    Good to a fraction of a percent for parcels of this size, and avoids
    pulling in a projection library for one number.
    """
    import math

    if len(ring) < 3:
        return 0.0

    mean_lat = sum(point[0] for point in ring) / len(ring)
    metres_per_deg_lat = 111_320.0
    metres_per_deg_lon = metres_per_deg_lat * math.cos(math.radians(mean_lat))

    points = [(point[1] * metres_per_deg_lon, point[0] * metres_per_deg_lat) for point in ring]

    total = 0.0
    for index in range(len(points)):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1

    return abs(total) / 2.0


def _element_to_feature(element):
    geometry = element.get('geometry') or []
    if len(geometry) < 3:
        return None

    # Overpass gives {lat, lon}; Leaflet wants [lat, lon].
    ring = [[point['lat'], point['lon']] for point in geometry]
    lats = [point[0] for point in ring]
    lons = [point[1] for point in ring]

    tags = element.get('tags') or {}
    landuse = tags.get('landuse')
    area = _ring_area_sqm(ring)

    return {
        'id': f"{element.get('type')}/{element.get('id')}",
        'type': landuse,
        'type_label': LANDUSE_LABELS.get(landuse, landuse),
        'name': tags.get('name'),
        'crop': tags.get('crop'),
        'area_sqm': round(area, 1),
        'area_hectares': round(area / 10000.0, 3),
        'bounds': ring,
        'bbox': [min(lons), min(lats), max(lons), max(lats)],
        'source': 'OpenStreetMap',
    }


def lookup_fields(lat, lon, radius=DEFAULT_RADIUS_M):
    """Mapped agricultural parcels near a point, largest first.

    Returns ``None`` when OpenStreetMap has nothing here.
    """
    radius = max(100, min(int(radius), MAX_RADIUS_M))
    key = f'osm-fields:{round(lat, COORD_PRECISION)}:{round(lon, COORD_PRECISION)}:{radius}'

    cached = cache.get(key)
    if cached is not None:
        return cached or None

    try:
        response = _session.post(
            OVERPASS_URL,
            data={'data': _build_query(lat, lon, radius)},
            timeout=QUERY_TIMEOUT_S + 15,
        )
    except Exception as exc:
        logger.warning('Overpass request failed: %s', exc)
        return None

    if response.status_code != 200:
        logger.warning('Overpass returned HTTP %s', response.status_code)
        return None

    try:
        elements = response.json().get('elements') or []
    except ValueError:
        logger.warning('Overpass returned a non-JSON body')
        return None

    features = [feature for feature in map(_element_to_feature, elements) if feature]

    if not features:
        # Short negative cache: mapping improves over time.
        cache.set(key, [], 60 * 60 * 6)
        return None

    features.sort(key=lambda item: item['area_sqm'], reverse=True)
    cache.set(key, features, CACHE_TIMEOUT)
    return features


def nearest_field(lat, lon, radius=DEFAULT_RADIUS_M):
    """The parcel containing the point, else the largest one nearby."""
    features = lookup_fields(lat, lon, radius)
    if not features:
        return None

    for feature in features:
        min_lon, min_lat, max_lon, max_lat = feature['bbox']
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return feature

    return features[0]
