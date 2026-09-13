"""ESA WorldCover land cover via the Microsoft Planetary Computer.

A global 10 m land-cover map produced by ESA from Sentinel-1 and Sentinel-2,
available for 2020 (v100) and 2021 (v200). Free, keyless, and on the same
data API the Sentinel-2 client already uses.

It replaces three heuristics that mistook the world for what they were
looking for: the HSV "blue and smooth" water mask, the Canny-edge building
detector, and the HSV vegetation mask. Each of those was a guess about
colour; WorldCover is a published classification with a documented accuracy
(~75% overall), and it says so in the response.
"""

import logging
import os

import numpy as np
from django.core.cache import cache

from .sentinel import DATA_URL, STAC_URL, _pack, _session, _unpack, resolution_for

logger = logging.getLogger(__name__)

COLLECTION = 'esa-worldcover'
DEFAULT_SIZE = 256
CACHE_TIMEOUT = 60 * 60 * 24 * 30
SEARCH_TIMEOUT = 30
RASTER_TIMEOUT = 60

# Product versions by reference year.
VERSIONS = {2020: '1.0.0', 2021: '2.0.0'}
LATEST_YEAR = 2021

TREES, SHRUB, GRASS, CROPLAND, BUILT_UP, BARE, SNOW, WATER, WETLAND, MANGROVE, MOSS = (
    10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100
)
NODATA = 0

LABELS = {
    TREES: 'Деревья',
    SHRUB: 'Кустарник',
    GRASS: 'Травяной покров',
    CROPLAND: 'Пашня',
    BUILT_UP: 'Застройка',
    BARE: 'Голая земля',
    SNOW: 'Снег и лёд',
    WATER: 'Вода',
    WETLAND: 'Болото',
    MANGROVE: 'Мангры',
    MOSS: 'Мох и лишайник',
}

# Official WorldCover legend colours, as RGBA.
COLOURS = {
    TREES: (0, 100, 0, 200),
    SHRUB: (255, 187, 34, 200),
    GRASS: (255, 255, 76, 200),
    CROPLAND: (240, 150, 255, 200),
    BUILT_UP: (250, 0, 0, 200),
    BARE: (180, 180, 180, 200),
    SNOW: (240, 240, 240, 200),
    WATER: (0, 100, 200, 200),
    WETLAND: (0, 150, 160, 200),
    MANGROVE: (0, 207, 117, 200),
    MOSS: (250, 230, 160, 200),
}

WATER_CLASSES = (WATER, WETLAND, MANGROVE)
VEGETATION_CLASSES = (TREES, SHRUB, GRASS, CROPLAND, MANGROVE)
# Ground that can, in principle, be farmed.
ARABLE_CLASSES = (GRASS, CROPLAND, BARE, SHRUB)


class WorldCoverUnavailable(RuntimeError):
    """No land cover for this area. The message is safe to show the user."""


def is_available():
    return os.environ.get('DISABLE_WORLDCOVER', '').strip().lower() not in ('1', 'true', 'yes')


def _find_item(bbox, year):
    """The WorldCover tile covering the centre of ``bbox`` for ``year``."""
    version = VERSIONS.get(year)
    if version is None:
        raise WorldCoverUnavailable(f'WorldCover за {year} год не существует')

    min_lon, min_lat, max_lon, max_lat = bbox
    centre = [(min_lon + max_lon) / 2.0, (min_lat + max_lat) / 2.0]

    try:
        response = _session.post(STAC_URL, json={
            'collections': [COLLECTION],
            'intersects': {'type': 'Point', 'coordinates': centre},
            'query': {'esa_worldcover:product_version': {'eq': version}},
            'limit': 2,
        }, timeout=SEARCH_TIMEOUT)
    except Exception as exc:
        raise WorldCoverUnavailable(f'Каталог WorldCover недоступен: {exc}') from exc

    if response.status_code != 200:
        raise WorldCoverUnavailable(f'Каталог WorldCover вернул HTTP {response.status_code}')

    try:
        features = response.json().get('features') or []
    except ValueError as exc:
        raise WorldCoverUnavailable('Каталог WorldCover вернул некорректный ответ') from exc

    if not features:
        raise WorldCoverUnavailable('WorldCover не покрывает эту точку')
    return features[0]


def fetch_landcover(bbox, year=LATEST_YEAR, size=DEFAULT_SIZE):
    """Land-cover class per pixel over ``bbox``.

    Returns ``(classes, metadata)`` where ``classes`` is a ``size x size``
    ``uint8`` array of WorldCover codes (0 where the tile has no data).
    Raises :class:`WorldCoverUnavailable` when the service cannot answer.
    """
    if not is_available():
        raise WorldCoverUnavailable('Источник WorldCover отключён')

    cache_key = 'worldcover:v1:{}:{}:{}'.format(
        year, size, ':'.join(f'{value:.4f}' for value in bbox)
    )
    cached = cache.get(cache_key)
    if cached is not None:
        blob, metadata = cached
        (classes,) = _unpack(blob)
        return classes, metadata

    item = _find_item(bbox, year)
    url = f"{DATA_URL}/{','.join(f'{value}' for value in bbox)}/{size}x{size}.npy"

    try:
        response = _session.get(url, params={
            'collection': COLLECTION,
            'item': item['id'],
            'assets': 'map',
            'resampling': 'nearest',
        }, timeout=RASTER_TIMEOUT)
    except Exception as exc:
        raise WorldCoverUnavailable(f'Не удалось получить карту покрова: {exc}') from exc

    if response.status_code != 200:
        raise WorldCoverUnavailable(f'Сервис WorldCover вернул HTTP {response.status_code}')

    import io
    try:
        raw = np.load(io.BytesIO(response.content))
    except ValueError as exc:
        raise WorldCoverUnavailable('Сервис WorldCover вернул нечитаемые данные') from exc

    classes = np.asarray(raw[0], dtype=np.uint8)
    coverage = float((classes != NODATA).mean())
    if coverage < 0.5:
        # The bbox straddles a tile edge and most of it fell outside this tile.
        raise WorldCoverUnavailable('Область на границе тайлов WorldCover')

    metadata = {
        'source': f'ESA WorldCover {year} v{VERSIONS[year]}',
        'provider': 'Microsoft Planetary Computer',
        'year': year,
        'metres_per_pixel': resolution_for(bbox, size),
        'native_resolution_m': 10,
        'valid_coverage': round(coverage, 3),
        'accuracy_note': 'Заявленная ESA общая точность около 75%',
    }

    cache.set(cache_key, (_pack(classes), metadata), CACHE_TIMEOUT)
    return classes, metadata


def class_percentages(classes):
    """Share of each class in percent, keyed by class code."""
    total = classes.size
    if total == 0:
        return {}
    codes, counts = np.unique(classes, return_counts=True)
    return {int(code): round(float(count) / total * 100.0, 2)
            for code, count in zip(codes, counts, strict=True) if code != NODATA}


def paint(classes):
    """RGBA overlay in the official legend colours."""
    height, width = classes.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    for code, colour in COLOURS.items():
        rgba[classes == code] = colour
    return rgba


def legend(codes=None):
    return {
        LABELS[code]: 'rgba({}, {}, {}, {:.2f})'.format(*COLOURS[code][:3], COLOURS[code][3] / 255)
        for code in (codes or LABELS)
        if code in LABELS
    }
