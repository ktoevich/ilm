"""Building footprints from OpenStreetMap via the Overpass API.

Replaces the Canny-edge "building detector", which found rectangles in
texture and called them houses. OSM footprints are drawn by people from
imagery and surveys; where they exist they are real outlines with real
areas. Where they do not exist the caller gets ``None`` and falls back to the
WorldCover built-up class, which is coarser but still a published product.

Why not Microsoft's Global Building Footprints: they are also free (ODbL) and
cover Central Asia, but ship as region-sized GeoParquet files of hundreds of
megabytes. Pulling one per request is not workable; loading them into
PostGIS is the right way and is a deployment task, not a code change.

Overpass is volunteer-run: the query is bounded by area and result count,
results are cached for a week, and the User-Agent identifies the app.
"""

import logging
import math

from django.core.cache import cache

from .http import build_session
from .osm_fields import OVERPASS_URL, _ring_area_sqm

logger = logging.getLogger(__name__)

CACHE_TIMEOUT = 60 * 60 * 24 * 7
QUERY_TIMEOUT_S = 25
MAX_RESULTS = 3000
# A dense city returns ~1000 buildings per km²; beyond this the payload is
# tens of megabytes and WorldCover's built-up class is the better answer.
MAX_AREA_KM2 = 12.0
COORD_PRECISION = 4

_session = build_session('FavorableSoil/1.0 (agricultural analysis)')


def is_available():
    return True  # no key, no account


def bbox_area_km2(bbox):
    min_lon, min_lat, max_lon, max_lat = bbox
    mean_lat = (min_lat + max_lat) / 2.0
    height_km = (max_lat - min_lat) * 111.32
    width_km = (max_lon - min_lon) * 111.32 * math.cos(math.radians(mean_lat))
    return height_km * width_km


def _build_query(bbox):
    min_lon, min_lat, max_lon, max_lat = bbox
    return f"""
[out:json][timeout:{QUERY_TIMEOUT_S}];
(
  way["building"]({min_lat},{min_lon},{max_lat},{max_lon});
);
out geom {MAX_RESULTS};
"""


def _element_to_feature(element):
    geometry = element.get('geometry') or []
    if len(geometry) < 3:
        return None

    ring = [[point['lat'], point['lon']] for point in geometry]
    tags = element.get('tags') or {}
    area = _ring_area_sqm(ring)

    levels = tags.get('building:levels')
    try:
        levels = int(levels) if levels else None
    except ValueError:
        levels = None

    return {
        'id': f"way/{element.get('id')}",
        'type': tags.get('building'),
        'name': tags.get('name'),
        'levels': levels,
        'area_sqm': round(area, 1),
        'lat': round(sum(p[0] for p in ring) / len(ring), 6),
        'lon': round(sum(p[1] for p in ring) / len(ring), 6),
        'ring': ring,
        'source': 'OpenStreetMap',
    }


def lookup_buildings(bbox):
    """Mapped building footprints inside ``bbox``, largest first.

    Returns a list (possibly empty) or ``None`` when the area is too large to
    ask for or Overpass could not answer.
    """
    if bbox_area_km2(bbox) > MAX_AREA_KM2:
        logger.info('Building lookup skipped: bbox is %.1f km²', bbox_area_km2(bbox))
        return None

    key = 'osm-buildings:v1:' + ':'.join(f'{round(v, COORD_PRECISION)}' for v in bbox)
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        response = _session.post(
            OVERPASS_URL,
            data={'data': _build_query(bbox)},
            timeout=QUERY_TIMEOUT_S + 15,
        )
    except Exception as exc:
        logger.warning('Overpass building request failed: %s', exc)
        return None

    if response.status_code != 200:
        logger.warning('Overpass returned HTTP %s for buildings', response.status_code)
        return None

    try:
        elements = response.json().get('elements') or []
    except ValueError:
        logger.warning('Overpass returned a non-JSON body for buildings')
        return None

    features = [feature for feature in map(_element_to_feature, elements) if feature]
    features.sort(key=lambda item: item['area_sqm'], reverse=True)

    cache.set(key, features, CACHE_TIMEOUT if features else 60 * 60 * 6)
    return features
