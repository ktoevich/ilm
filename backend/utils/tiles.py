"""Satellite tile fetching.

Responsibilities kept here on purpose: everything that talks to the tile
server, so the analysis code never issues raw HTTP calls of its own.

Three properties this module guarantees to its callers:

* the number of tiles downloaded for one request is bounded
  (``settings.MAX_TILES_PER_REQUEST``);
* every HTTP call has a timeout, so a hung tile server cannot pin a worker;
* tiles are cached, so panning around the same area does not re-download.
"""

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO

import numpy as np
import requests
from api.validators import choose_zoom, metres_per_pixel
from django.conf import settings
from django.core.cache import cache
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

TILE_SIZE = 256
TILE_CACHE_TIMEOUT = 60 * 60 * 24 * 7  # imagery changes on the order of months
_MAX_PARALLEL_DOWNLOADS = 8

_session = requests.Session()
_session.headers.update({
    'User-Agent': 'FavorableSoil/1.0 (agricultural analysis; +https://github.com/ktoevich/ilm)',
    'Accept': 'image/png,image/jpeg,*/*',
})


class TileFetchError(RuntimeError):
    """Raised when too little imagery could be retrieved to analyse."""


@dataclass(frozen=True)
class SatelliteImage:
    """A stitched RGB mosaic plus the metadata needed to interpret it."""

    pixels: np.ndarray            # (H, W, 3) uint8
    bounds: list                  # [[min_lat, min_lon], [max_lat, max_lon]]
    zoom: int
    metres_per_pixel: float
    tiles_requested: int
    tiles_retrieved: int

    @property
    def square_metres_per_pixel(self):
        return self.metres_per_pixel ** 2

    def pixels_to_area_sqm(self, pixel_count):
        """Convert a pixel count into ground area, honouring zoom and latitude."""
        return pixel_count * self.square_metres_per_pixel


def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)


def num2deg(xtile, ytile, zoom):
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    return (math.degrees(lat_rad), lon_deg)


def _tile_url(x, y, z):
    return settings.TILE_SERVER_URL.format(x=x, y=y, z=z)


def download_tile(x, y, z):
    """Fetch one tile, using the cache. Returns a PIL image or ``None``."""
    cache_key = f'tile:{z}:{x}:{y}'
    cached = cache.get(cache_key)
    if cached is not None:
        if cached == b'':  # negative cache: this tile does not exist
            return None
        try:
            return Image.open(BytesIO(cached)).convert('RGB')
        except UnidentifiedImageError:
            cache.delete(cache_key)

    try:
        response = _session.get(_tile_url(x, y, z), timeout=settings.HTTP_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        logger.warning('Tile %s/%s/%s request failed: %s', z, x, y, exc)
        return None

    if response.status_code == 404:
        cache.set(cache_key, b'', TILE_CACHE_TIMEOUT)
        return None

    if response.status_code != 200:
        logger.warning('Tile %s/%s/%s returned HTTP %s', z, x, y, response.status_code)
        return None

    try:
        image = Image.open(BytesIO(response.content)).convert('RGB')
    except UnidentifiedImageError:
        logger.warning('Tile %s/%s/%s is not a decodable image', z, x, y)
        return None

    cache.set(cache_key, response.content, TILE_CACHE_TIMEOUT)
    return image


def fetch_satellite_image(bbox, zoom=13):
    """Stitch the tiles covering ``bbox`` into a single RGB mosaic.

    ``bbox`` must already have passed :func:`api.validators.parse_bbox`.
    The requested ``zoom`` is reduced automatically if the area would exceed
    the per-request tile budget, so a large selection returns a coarser image
    instead of an error.
    """
    min_lon, min_lat, max_lon, max_lat = bbox

    effective_zoom = choose_zoom(bbox, zoom, settings.MAX_TILES_PER_REQUEST)
    if effective_zoom < zoom:
        logger.info('Reduced zoom %s -> %s to stay within the tile budget', zoom, effective_zoom)

    x_min, y_min = deg2num(max_lat, min_lon, effective_zoom)
    x_max, y_max = deg2num(min_lat, max_lon, effective_zoom)

    xs = range(x_min, x_max + 1)
    ys = range(y_min, y_max + 1)
    coordinates = [(i, j, x, y) for i, x in enumerate(xs) for j, y in enumerate(ys)]

    mosaic = Image.new('RGB', (len(xs) * TILE_SIZE, len(ys) * TILE_SIZE))

    retrieved = 0
    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_DOWNLOADS) as pool:
        futures = {
            pool.submit(download_tile, x, y, effective_zoom): (i, j)
            for i, j, x, y in coordinates
        }
        for future, (i, j) in futures.items():
            tile = future.result()
            if tile is not None:
                mosaic.paste(tile, (i * TILE_SIZE, j * TILE_SIZE))
                retrieved += 1

    requested = len(coordinates)
    if retrieved == 0:
        raise TileFetchError('Не удалось загрузить ни одного спутникового снимка для этой области')
    if retrieved < requested / 2:
        raise TileFetchError(
            f'Загружено только {retrieved} из {requested} снимков — результат был бы недостоверным'
        )

    top_lat, left_lon = num2deg(x_min, y_min, effective_zoom)
    bottom_lat, right_lon = num2deg(x_max + 1, y_max + 1, effective_zoom)
    bounds = [[bottom_lat, left_lon], [top_lat, right_lon]]

    centre_lat = (bottom_lat + top_lat) / 2.0

    return SatelliteImage(
        pixels=np.array(mosaic),
        bounds=bounds,
        zoom=effective_zoom,
        metres_per_pixel=metres_per_pixel(centre_lat, effective_zoom),
        tiles_requested=requested,
        tiles_retrieved=retrieved,
    )
