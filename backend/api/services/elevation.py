"""Terrain elevation from Open-Meteo's DEM (Copernicus GLO-90).

Why this exists: the previous relief detection ran a Sobel filter over the
satellite image and called anything with a strong gradient a mountain. In a
city that flags every building -- a test over central Tashkent came back as
79% "mountains". Slope has to come from an elevation model, not from image
contrast.

The API accepts up to 100 coordinates per call, so one request covers a 10x10
sample grid across the bounding box.
"""

import logging

import numpy as np
from django.core.cache import cache

from .http import build_session, get_json

logger = logging.getLogger(__name__)

ELEVATION_URL = 'https://api.open-meteo.com/v1/elevation'
GRID_SIZE = 10                     # 100 points -- the API's per-request maximum
CACHE_TIMEOUT = 60 * 60 * 24 * 90  # terrain does not move
COORD_PRECISION = 3

_session = build_session('FavorableSoil/1.0 (agricultural analysis)')


def _grid_coordinates(bbox, size=GRID_SIZE):
    """Cell-centre coordinates of a ``size x size`` grid over ``bbox``."""
    min_lon, min_lat, max_lon, max_lat = bbox
    lat_step = (max_lat - min_lat) / size
    lon_step = (max_lon - min_lon) / size

    # Row 0 is the northern edge, matching image row order.
    lats = [max_lat - (row + 0.5) * lat_step for row in range(size)]
    lons = [min_lon + (col + 0.5) * lon_step for col in range(size)]
    return lats, lons


def fetch_elevation_grid(bbox, size=GRID_SIZE):
    """Return a ``(size, size)`` array of elevations in metres, or ``None``."""
    min_lon, min_lat, max_lon, max_lat = bbox
    key = 'elevation:{}:{}:{}:{}:{}'.format(
        size,
        *[round(value, COORD_PRECISION) for value in (min_lon, min_lat, max_lon, max_lat)]
    )
    cached = cache.get(key)
    if cached is not None:
        return np.array(cached) if cached else None

    lats, lons = _grid_coordinates(bbox, size)
    points = [(lat, lon) for lat in lats for lon in lons]

    payload = get_json(
        _session,
        ELEVATION_URL,
        params={
            'latitude': ','.join(f'{lat:.5f}' for lat, _ in points),
            'longitude': ','.join(f'{lon:.5f}' for _, lon in points),
        },
        timeout=10,
        service='Open-Meteo Elevation',
    )

    elevations = (payload or {}).get('elevation')
    if not elevations or len(elevations) != size * size:
        logger.info('Elevation grid unavailable for %s', bbox)
        cache.set(key, [], 60 * 10)
        return None

    grid = np.array(elevations, dtype=np.float32).reshape(size, size)
    cache.set(key, grid.tolist(), CACHE_TIMEOUT)
    return grid


def slope_percent(grid, bbox):
    """Per-cell slope in percent (rise / run * 100).

    Uses the real ground distance between neighbouring sample points, so the
    result is comparable across latitudes and bbox sizes.
    """
    if grid is None:
        return None

    size = grid.shape[0]
    min_lon, min_lat, max_lon, max_lat = bbox
    mean_lat = (min_lat + max_lat) / 2.0

    metres_per_degree_lat = 111_320.0
    metres_per_degree_lon = metres_per_degree_lat * np.cos(np.radians(mean_lat))

    cell_height_m = abs(max_lat - min_lat) / size * metres_per_degree_lat
    cell_width_m = abs(max_lon - min_lon) / size * metres_per_degree_lon

    # np.gradient with explicit spacing gives rise-over-run directly.
    d_rows, d_cols = np.gradient(grid, max(cell_height_m, 1.0), max(cell_width_m, 1.0))
    return np.hypot(d_rows, d_cols) * 100.0
