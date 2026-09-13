"""Sentinel-2 via the Microsoft Planetary Computer.

Free, keyless, and no account: the Planetary Computer serves a public STAC
catalogue plus a raster data API that evaluates band maths server-side. That
gives a real NDVI -- from the near-infrared band -- without the paid tiers,
service accounts or registration that the commercial platforms require.

    NDVI = (NIR - Red) / (NIR + Red)          bands B08 and B04, 10 m
    NDMI = (NIR - SWIR) / (NIR + SWIR)        bands B08 and B11, 10/20 m

Three things this module provides:

* ``fetch_ndvi_array`` / ``fetch_ndvi_stats`` -- the latest clear scene, with
  a cloud mask from the scene classification layer. ``fetch_ndvi_stats`` also
  attaches NDMI (a moisture proxy) and the NDVI of the same calendar window in
  previous years, so a reading can be compared with what is normal here.
* ``fetch_seasonal_productivity`` -- per-pixel peak and mean NDVI across the
  growing seasons of the last few years. One scene says how green a field is
  today; several seasons say how productive the ground is. This is the
  standard "management zones" input in precision agriculture and it is what
  the fertility map is built on.
* the reflectance offset handling below, which is easy to get wrong.

The reflectance offset
----------------------
Since processing baseline 04.00 (January 2022) Sentinel-2 L2A products carry
``BOA_ADD_OFFSET = -1000``: true reflectance is ``(DN - 1000) / 10000``. The
offset does not cancel in a normalised difference -- it cancels in the
numerator but not the denominator -- so ignoring it is not harmless:

    raw DN over a Tashkent field:  NDVI = 0.333
    with the offset applied:       NDVI = 0.494

That is a whole fertility band and one growth stage of error. The expression
below applies the offset, and only for scenes whose baseline calls for it.
"""

import io
import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

STAC_URL = 'https://planetarycomputer.microsoft.com/api/stac/v1/search'
DATA_URL = 'https://planetarycomputer.microsoft.com/api/data/v1/item/bbox'
COLLECTION = 'sentinel-2-l2a'

RED_ASSET = 'B04'
NIR_ASSET = 'B08'
SWIR_ASSET = 'B11'
SCL_ASSET = 'SCL'
NATIVE_SCALE_M = 10

# Sentinel-2 revisits every ~5 days; 90 days survives a cloudy season without
# silently returning something stale.
DEFAULT_LOOKBACK_DAYS = 90
MAX_CLOUD_PERCENT = 40
DEFAULT_SIZE = 512

# Multi-season productivity: growing season months, seasons back, raster size.
SEASON_MONTHS = (4, 5, 6, 7, 8, 9)
SEASON_YEARS = 3
SEASON_SIZE = 256
SEASON_MAX_CLOUD = 25
MIN_SEASON_SCENES = 3

# Anomaly reference: same calendar window in previous years.
REFERENCE_YEARS = 2
REFERENCE_WINDOW_DAYS = 20

# Baselines at or above this add the -1000 reflectance offset.
OFFSET_BASELINE = 4.0
REFLECTANCE_OFFSET = 1000

# Scene classification values that carry usable ground information.
# Excluded: 0 no-data, 1 saturated, 2 dark area, 3 cloud shadow,
# 8 cloud medium probability, 9 cloud high probability, 10 thin cirrus.
VALID_SCL_CLASSES = (4, 5, 6, 7, 11)

CACHE_TIMEOUT = 60 * 60 * 6
SEASON_CACHE_TIMEOUT = 60 * 60 * 24 * 7
SEARCH_TIMEOUT = 30
RASTER_TIMEOUT = 90
_MAX_PARALLEL = 8

# Below this share of usable pixels the scene is not worth reporting on.
MIN_VALID_COVERAGE = 0.5

_session = requests.Session()
_session.headers.update({'User-Agent': 'FavorableSoil/1.0 (agricultural analysis)'})


class SentinelUnavailable(RuntimeError):
    """No usable Sentinel-2 scene. The message is safe to show the user."""


def is_available():
    """Sentinel-2 needs no credentials; this only honours an explicit opt-out."""
    return os.environ.get('DISABLE_SENTINEL', '').strip().lower() not in ('1', 'true', 'yes')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _needs_offset(baseline):
    try:
        return float(baseline) >= OFFSET_BASELINE
    except (TypeError, ValueError):
        # Unknown baseline: current data is all post-04.00, so assume the offset.
        return True


def _difference_expression(baseline, first, second):
    """Normalised difference ``(first - second) / (first + second)`` with the offset."""
    if _needs_offset(baseline):
        # ((a-o) - (b-o)) / ((a-o) + (b-o)) == (a-b) / (a+b-2o)
        return f'({first}-{second})/({first}+{second}-{2 * REFLECTANCE_OFFSET})'
    return f'({first}-{second})/({first}+{second})'


def _ndvi_expression(baseline):
    """NDVI expression, with the reflectance offset when the baseline needs it."""
    return _difference_expression(baseline, NIR_ASSET, RED_ASSET)


def _ndmi_expression(baseline):
    return _difference_expression(baseline, NIR_ASSET, SWIR_ASSET)


def resolution_for(bbox, size):
    """Ground metres per pixel of a ``size x size`` raster stretched over ``bbox``.

    The data API resamples to the requested size, so a 20 km box at 512 px is
    ~40 m/pixel, not the native 10 m. Reporting 10 m regardless was wrong.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    mean_lat = (min_lat + max_lat) / 2.0
    height_m = (max_lat - min_lat) * 111_320.0
    width_m = (max_lon - min_lon) * 111_320.0 * math.cos(math.radians(mean_lat))
    return round(max(NATIVE_SCALE_M, max(height_m, width_m) / size), 1)


def _bbox_key(bbox):
    return ':'.join(f'{value:.4f}' for value in bbox)


def _pack(*arrays):
    """Serialise numpy arrays compactly for the cache.

    Python lists of floats pickle to ~10x the size of the raw array; a 512x512
    NDVI plus mask came to 2.6 MB per cache entry that way.
    """
    buffer = io.BytesIO()
    np.savez_compressed(buffer, *arrays)
    return buffer.getvalue()


def _unpack(blob):
    with np.load(io.BytesIO(blob)) as data:
        return [data[key] for key in sorted(data.files, key=lambda name: int(name[4:]))]


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
def search_scenes(bbox, start, end, max_cloud=MAX_CLOUD_PERCENT, limit=100):
    """Scenes over ``bbox`` between two dates, newest first."""
    min_lon, min_lat, max_lon, max_lat = bbox

    try:
        response = _session.post(STAC_URL, json={
            'collections': [COLLECTION],
            'bbox': [min_lon, min_lat, max_lon, max_lat],
            'datetime': f'{start}/{end}',
            'query': {'eo:cloud_cover': {'lt': max_cloud}},
            'sortby': [{'field': 'properties.datetime', 'direction': 'desc'}],
            'limit': limit,
        }, timeout=SEARCH_TIMEOUT)
    except requests.RequestException as exc:
        raise SentinelUnavailable(f'Каталог Sentinel-2 недоступен: {exc}') from exc

    if response.status_code != 200:
        raise SentinelUnavailable(f'Каталог Sentinel-2 вернул HTTP {response.status_code}')

    try:
        return response.json().get('features') or []
    except ValueError as exc:
        raise SentinelUnavailable('Каталог Sentinel-2 вернул некорректный ответ') from exc


def search_scene(bbox, lookback_days=DEFAULT_LOOKBACK_DAYS, max_cloud=MAX_CLOUD_PERCENT):
    """Most recent scene over ``bbox`` under the cloud limit."""
    end = date.today()
    start = end - timedelta(days=lookback_days)
    features = search_scenes(bbox, start, end, max_cloud=max_cloud, limit=1)

    if not features:
        raise SentinelUnavailable(
            f'Нет снимков Sentinel-2 с облачностью ниже {max_cloud}% '
            f'за последние {lookback_days} дней'
        )
    return features[0]


# ---------------------------------------------------------------------------
# Rasters
# ---------------------------------------------------------------------------
def _fetch_raster(bbox, size, params):
    """Fetch one raster from the data API as a numpy array."""
    url = f"{DATA_URL}/{','.join(f'{value}' for value in bbox)}/{size}x{size}.npy"

    try:
        response = _session.get(url, params=params, timeout=RASTER_TIMEOUT)
    except requests.RequestException as exc:
        raise SentinelUnavailable(f'Не удалось получить снимок Sentinel-2: {exc}') from exc

    if response.status_code != 200:
        raise SentinelUnavailable(f'Сервис снимков вернул HTTP {response.status_code}')

    try:
        array = np.load(io.BytesIO(response.content))
    except ValueError as exc:
        raise SentinelUnavailable('Сервис снимков вернул нечитаемые данные') from exc

    # titiler returns (bands + mask, height, width).
    return array


def _scene_params(item_id, assets, expression=None, nearest=False):
    params = {'collection': COLLECTION, 'item': item_id, 'asset_as_band': 'true',
              'assets': list(assets)}
    if expression:
        params['expression'] = expression
    if nearest:
        params['resampling'] = 'nearest'
    return params


def _fetch_scene_ndvi(bbox, size, item):
    """NDVI and validity mask for one catalogue item."""
    item_id = item['id']
    baseline = item.get('properties', {}).get('s2:processing_baseline')

    ndvi_params = _scene_params(item_id, (RED_ASSET, NIR_ASSET), _ndvi_expression(baseline))
    scl_params = _scene_params(item_id, (SCL_ASSET,), nearest=True)

    # The two rasters are independent; fetching them in parallel halves the wait.
    with ThreadPoolExecutor(max_workers=2) as pool:
        ndvi_future = pool.submit(_fetch_raster, bbox, size, ndvi_params)
        scl_future = pool.submit(_fetch_raster, bbox, size, scl_params)
        ndvi_raw = ndvi_future.result()
        scl_raw = scl_future.result()

    ndvi = np.asarray(ndvi_raw[0], dtype=np.float32)
    scl = np.asarray(scl_raw[0], dtype=np.uint8)

    valid = np.isin(scl, VALID_SCL_CLASSES) & np.isfinite(ndvi)
    ndvi = np.clip(np.nan_to_num(ndvi, nan=0.0, posinf=1.0, neginf=-1.0), -1.0, 1.0)
    return ndvi, valid


def fetch_ndvi_array(bbox, size=DEFAULT_SIZE, lookback_days=DEFAULT_LOOKBACK_DAYS):
    """NDVI of the latest clear scene as a per-pixel array plus a validity mask.

    Returns ``(ndvi, valid_mask, metadata)``. Cloud, shadow and saturated
    pixels are marked invalid via the scene classification layer rather than
    silently counted as bare ground.
    """
    if not is_available():
        raise SentinelUnavailable('Источник Sentinel-2 отключён')

    cache_key = f'sentinel-ndvi:v2:{size}:{_bbox_key(bbox)}'
    cached = cache.get(cache_key)
    if cached is not None:
        blob, metadata = cached
        ndvi, valid = _unpack(blob)
        return ndvi, valid.astype(bool), metadata

    item = search_scene(bbox, lookback_days)
    properties = item.get('properties', {})

    ndvi, valid = _fetch_scene_ndvi(bbox, size, item)

    coverage = float(valid.mean())
    if coverage < MIN_VALID_COVERAGE:
        raise SentinelUnavailable(
            f'Облака закрывают {(1 - coverage) * 100:.0f}% выбранной области'
        )

    metadata = {
        'source': 'Sentinel-2 L2A',
        'provider': 'Microsoft Planetary Computer',
        'scene_id': item['id'],
        'capture_date': (properties.get('datetime') or '')[:10] or None,
        'cloud_percent': properties.get('eo:cloud_cover'),
        'processing_baseline': properties.get('s2:processing_baseline'),
        'metres_per_pixel': resolution_for(bbox, size),
        'valid_coverage': round(coverage, 3),
    }

    cache.set(cache_key, (_pack(ndvi, valid), metadata), CACHE_TIMEOUT)
    return ndvi, valid, metadata


def fetch_ndmi_mean(bbox, scene_id, baseline, size=DEFAULT_SIZE, valid=None):
    """Mean NDMI over ``valid`` pixels for one scene, or ``None`` on failure.

    Best effort: moisture context is useful but never worth failing the
    analysis over.
    """
    cache_key = f'sentinel-ndmi:v1:{size}:{scene_id}:{_bbox_key(bbox)}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached or None

    try:
        raw = _fetch_raster(
            bbox, size,
            _scene_params(scene_id, (NIR_ASSET, SWIR_ASSET), _ndmi_expression(baseline)),
        )
    except SentinelUnavailable as exc:
        logger.info('NDMI unavailable for %s: %s', scene_id, exc)
        cache.set(cache_key, 0.0, 60 * 30)
        return None

    ndmi = np.clip(np.nan_to_num(np.asarray(raw[0], dtype=np.float32)), -1.0, 1.0)
    values = ndmi[valid] if valid is not None else ndmi
    if values.size == 0:
        return None

    mean = round(float(values.mean()), 4)
    cache.set(cache_key, mean, CACHE_TIMEOUT)
    return mean


def fetch_reference_ndvi(bbox, capture_date, years=REFERENCE_YEARS,
                         window_days=REFERENCE_WINDOW_DAYS, size=SEASON_SIZE):
    """Mean NDVI of the same calendar window in previous years.

    Answers "is this field greener or paler than it usually is at this time of
    year", which is far more informative than an absolute reading. Returns
    ``(mean_or_None, years_used)``.
    """
    cache_key = f'sentinel-ref:v1:{size}:{years}:{capture_date}:{_bbox_key(bbox)}'
    cached = cache.get(cache_key)
    if cached is not None:
        return tuple(cached)

    try:
        anchor = date.fromisoformat(capture_date)
    except (TypeError, ValueError):
        return None, []

    means, used = [], []
    for back in range(1, years + 1):
        try:
            centre = anchor.replace(year=anchor.year - back)
        except ValueError:  # 29 February
            centre = anchor.replace(year=anchor.year - back, day=28)
        start = centre - timedelta(days=window_days)
        end = centre + timedelta(days=window_days)

        try:
            scenes = search_scenes(bbox, start, end, max_cloud=SEASON_MAX_CLOUD, limit=20)
            if not scenes:
                continue
            best = min(scenes, key=lambda item: item['properties'].get('eo:cloud_cover', 100))
            ndvi, valid = _fetch_scene_ndvi(bbox, size, best)
        except SentinelUnavailable as exc:
            logger.info('Reference scene for %s unavailable: %s', centre, exc)
            continue

        if valid.mean() < MIN_VALID_COVERAGE:
            continue
        means.append(float(ndvi[valid].mean()))
        used.append(centre.year)

    result = (round(sum(means) / len(means), 4) if means else None, used)
    cache.set(cache_key, result, SEASON_CACHE_TIMEOUT)
    return result


def fetch_ndvi_stats(bbox, size=DEFAULT_SIZE, with_context=True):
    """Summary statistics over the valid pixels, plus the raw array.

    With ``with_context`` the result also carries ``ndmi_mean`` (moisture
    proxy) and ``reference_ndvi`` (the same window in previous years). Both are
    best effort and ``None`` when unavailable.
    """
    ndvi, valid, metadata = fetch_ndvi_array(bbox, size)
    values = ndvi[valid]

    if values.size == 0:
        raise SentinelUnavailable('В выбранной области нет пригодных пикселей')

    stats = {
        'index_mean': round(float(values.mean()), 4),
        'index_min': round(float(values.min()), 4),
        'index_max': round(float(values.max()), 4),
        'index_stddev': round(float(values.std()), 4),
        'ndvi': ndvi,
        'valid': valid,
        'metadata': metadata,
        'ndmi_mean': None,
        'reference_ndvi': None,
        'reference_years': [],
    }

    if with_context:
        stats['ndmi_mean'] = fetch_ndmi_mean(
            bbox, metadata['scene_id'], metadata['processing_baseline'], size, valid
        )
        reference, years = fetch_reference_ndvi(bbox, metadata['capture_date'])
        stats['reference_ndvi'] = reference
        stats['reference_years'] = years

    return stats


# ---------------------------------------------------------------------------
# Multi-season productivity
# ---------------------------------------------------------------------------
def season_years(today=None, years=SEASON_YEARS):
    """The last ``years`` growing seasons that are complete enough to use.

    The current year counts once August has passed; before that the season is
    still under way and its peak is not in yet.
    """
    today = today or date.today()
    latest = today.year if today.month >= 9 else today.year - 1
    return [latest - offset for offset in range(years)]


def _best_scene_per_month(scenes):
    """One scene per calendar month: the least cloudy."""
    best = {}
    for item in scenes:
        stamp = item.get('properties', {}).get('datetime') or ''
        cloud = item.get('properties', {}).get('eo:cloud_cover', 100)
        month = stamp[:7]
        if not month:
            continue
        if month not in best or cloud < best[month]['properties'].get('eo:cloud_cover', 100):
            best[month] = item
    return list(best.values())


def fetch_seasonal_productivity(bbox, years=SEASON_YEARS, size=SEASON_SIZE):
    """Per-pixel peak and mean NDVI over the growing seasons of recent years.

    Returns a dict with ``peak`` and ``mean`` arrays (``size x size``), an
    ``observations`` count per pixel, the ``years`` and ``scene_dates`` used and
    ``metres_per_pixel``. Raises :class:`SentinelUnavailable` when fewer than
    ``MIN_SEASON_SCENES`` usable scenes exist.
    """
    if not is_available():
        raise SentinelUnavailable('Источник Sentinel-2 отключён')

    year_list = season_years(years=years)
    cache_key = f'sentinel-season:v1:{size}:{year_list[0]}-{year_list[-1]}:{_bbox_key(bbox)}'
    cached = cache.get(cache_key)
    if cached is not None:
        blob, meta = cached
        peak, mean, observations = _unpack(blob)
        return {'peak': peak, 'mean': mean, 'observations': observations, **meta}

    candidates = []
    for year in year_list:
        start = date(year, SEASON_MONTHS[0], 1)
        end = date(year, SEASON_MONTHS[-1], 30)
        scenes = search_scenes(bbox, start, end, max_cloud=SEASON_MAX_CLOUD, limit=100)
        candidates.extend(_best_scene_per_month(scenes))

    if len(candidates) < MIN_SEASON_SCENES:
        raise SentinelUnavailable(
            f'За сезоны {year_list[-1]}–{year_list[0]} найдено только '
            f'{len(candidates)} ясных снимков Sentinel-2'
        )

    def fetch(item):
        try:
            return item, _fetch_scene_ndvi(bbox, size, item)
        except SentinelUnavailable as exc:
            logger.info('Season scene %s skipped: %s', item.get('id'), exc)
            return item, None

    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL) as pool:
        fetched = list(pool.map(fetch, candidates))

    peak = np.full((size, size), -1.0, dtype=np.float32)
    total = np.zeros((size, size), dtype=np.float32)
    observations = np.zeros((size, size), dtype=np.uint16)
    dates = []

    for item, payload in fetched:
        if payload is None:
            continue
        ndvi, valid = payload
        if valid.mean() < 0.2:
            continue
        np.maximum(peak, np.where(valid, ndvi, -1.0), out=peak)
        total += np.where(valid, ndvi, 0.0)
        observations += valid.astype(np.uint16)
        dates.append((item['properties'].get('datetime') or '')[:10])

    if len(dates) < MIN_SEASON_SCENES:
        raise SentinelUnavailable(
            f'Удалось загрузить только {len(dates)} сезонных снимков Sentinel-2'
        )

    with np.errstate(divide='ignore', invalid='ignore'):
        mean = np.where(observations > 0, total / np.maximum(observations, 1), np.nan)
    peak = np.where(observations > 0, peak, np.nan).astype(np.float32)
    mean = mean.astype(np.float32)

    meta = {
        'source': 'Sentinel-2 L2A',
        'provider': 'Microsoft Planetary Computer',
        'years': year_list,
        'scene_dates': sorted(dates),
        'scenes_used': len(dates),
        'metres_per_pixel': resolution_for(bbox, size),
        'valid_coverage': round(float((observations > 0).mean()), 3),
    }

    cache.set(cache_key, (_pack(peak, mean, observations), meta), SEASON_CACHE_TIMEOUT)
    return {'peak': peak, 'mean': mean, 'observations': observations, **meta}
