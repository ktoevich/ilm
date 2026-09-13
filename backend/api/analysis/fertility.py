"""Soil fertility mapping.

A single NDVI scene measures how green the ground is on one day, which is not
fertility: a fertile field under fallow reads as bare. The map here is built
from sources that each say something about the ground itself, and every one
of them is named in the response:

1. **Productivity** -- per-pixel peak and mean NDVI across the growing seasons
   of the last three years (Sentinel-2, 10 m). Ground that is consistently
   productive is the standard precision-agriculture definition of a
   high-potential zone.
2. **Soil** -- pH, organic carbon, cation exchange capacity and texture from
   ISRIC SoilGrids (250 m), combined by documented agronomic rules into a
   score in [0, 1] (see :func:`api.services.soilgrids.soil_quality_score`).
3. **Land cover** -- ESA WorldCover (10 m) excludes water, built-up land, snow
   and dense forest so that a lake or a housing estate never lands in a
   fertility class.
4. **Slope** -- Copernicus GLO-90 through Open-Meteo; ground steeper than 15%
   is not workable cropland.

Fallbacks, in order, when the multi-season data cannot be assembled: the
latest single Sentinel-2 scene (labelled as such), then the Excess Green
index over the RGB basemap (no date, no infrared, labelled as such).

The bundled ResNet-18 (``ai model/soil_model.pth``) was trained on close-up
ground photographs of soil, so applying it to satellite imagery is an
unvalidated domain shift. It stays behind ``ENABLE_SOIL_MODEL_ON_TILES=true``
and is off by default; ``method`` always names what actually ran.
"""

import logging
import os

import numpy as np

from api.services import elevation as elevation_service
from api.services import sentinel, soilgrids, worldcover
from api.services.sentinel import SentinelUnavailable
from api.services.worldcover import WorldCoverUnavailable

from .imagery import (
    encode_overlay,
    excess_green_index,
    load_imagery,
    percentage,
    upsample_grid,
    water_mask,
)

logger = logging.getLogger(__name__)

ZOOM = 13

# Label ids for the classification raster. Counting labels is both faster and
# more reliable than comparing RGBA tuples pixel by pixel.
L_BARE, L_WATER, L_STEEP, L_LOW, L_MODERATE, L_HIGH, L_VERY_HIGH, L_BUILT = range(8)

# Slopes above this are not workable cropland. 15% ~= 8.5 degrees, the usual
# limit for mechanised agriculture.
STEEP_SLOPE_PERCENT = 15.0

COLOURS = {
    L_VERY_HIGH: (0, 100, 0, 180),
    L_HIGH: (0, 200, 0, 180),
    L_MODERATE: (0, 255, 255, 180),
    L_LOW: (0, 165, 255, 180),
    L_STEEP: (100, 70, 50, 180),
    L_BARE: (150, 150, 150, 180),
    L_WATER: (0, 0, 255, 180),
    L_BUILT: (200, 0, 0, 180),
}

LEGEND = {
    'Очень высокое плодородие': 'rgba(0, 100, 0, 0.7)',
    'Высокое плодородие': 'rgba(0, 200, 0, 0.7)',
    'Умеренное плодородие': 'rgba(0, 255, 255, 0.7)',
    'Низкое плодородие': 'rgba(0, 165, 255, 0.7)',
    'Крутой склон (>15%)': 'rgba(100, 70, 50, 0.7)',
    'Без растительного покрова': 'rgba(150, 150, 150, 0.7)',
    'Вода': 'rgba(0, 0, 255, 0.7)',
    'Застройка': 'rgba(200, 0, 0, 0.7)',
}

# Excess-green thresholds separating the fertility bands.
#
# Calibrated against the actual distribution of the ArcGIS World Imagery
# basemap rather than picked from theory: over this basemap the median ExG is
# ~0.035 in a dense city, ~0.07 over irrigated cropland, and the 90th
# percentile of cropland reaches ~0.21. Bands are (lower_bound, label), read
# from the top down -- the first threshold a pixel clears wins.
_EXG_BANDS = (
    (0.16, L_VERY_HIGH),
    (0.10, L_HIGH),
    (0.06, L_MODERATE),
    (0.025, L_LOW),
)

# NDVI bands, from the standard remote-sensing breakpoints for vegetation
# density. Unlike the ExG ones above these are not basemap-specific: NDVI is a
# physical quantity, so the same thresholds hold anywhere.
_NDVI_BANDS = (
    (0.60, L_VERY_HIGH),
    (0.45, L_HIGH),
    (0.30, L_MODERATE),
    (0.15, L_LOW),
)

# Composite score bands. The score is in [0, 1]; see ``_fertility_score``.
_SCORE_BANDS = (
    (0.70, L_VERY_HIGH),
    (0.50, L_HIGH),
    (0.30, L_MODERATE),
    (0.12, L_LOW),
)

# NDVI below this is open water rather than bare ground.
NDVI_WATER_THRESHOLD = -0.05

# Peak NDVI of 0.15 is bare ground, 0.75 is dense healthy crop; season mean of
# 0.10 is bare, 0.50 is a field that stays green all season.
PEAK_RANGE = (0.15, 0.75)
MEAN_RANGE = (0.10, 0.50)

# Weights of the two halves of the composite when soil data is present.
PRODUCTIVITY_WEIGHT = 0.65
SOIL_WEIGHT = 0.35

_soil_model = None
_soil_model_device = None
_soil_model_state = 'not-loaded'


def model_enabled():
    return os.environ.get('ENABLE_SOIL_MODEL_ON_TILES', '').strip().lower() in ('1', 'true', 'yes')


def load_soil_model():
    """Load the ResNet once. Returns ``(model, device)`` or ``(None, None)``."""
    global _soil_model, _soil_model_device, _soil_model_state

    if _soil_model is not None:
        return _soil_model, _soil_model_device
    if _soil_model_state == 'unavailable':
        return None, None

    try:
        import torch
        import torch.nn as nn
        from torchvision import models
    except ImportError:
        logger.info('PyTorch is not installed; fertility falls back to the heuristic')
        _soil_model_state = 'unavailable'
        return None, None

    from django.conf import settings

    model_path = settings.SOIL_MODEL_PATH
    if not os.path.exists(model_path):
        logger.warning('Soil model weights not found at %s', model_path)
        _soil_model_state = 'unavailable'
        return None, None

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = models.resnet18()
    model.fc = nn.Linear(model.fc.in_features, 3)

    try:
        state_dict = torch.load(model_path, map_location=device, weights_only=True)
        model.load_state_dict(state_dict)
    except Exception:
        logger.exception('Failed to load soil model weights from %s', model_path)
        _soil_model_state = 'unavailable'
        return None, None

    model.to(device).eval()
    _soil_model, _soil_model_device, _soil_model_state = model, device, 'ready'
    logger.info('Soil model loaded on %s', device)
    return _soil_model, _soil_model_device


def _classify_by_vegetation(index, land_mask, bands=_EXG_BANDS):
    """Assign a fertility band to every land pixel from its index value.

    ``np.select`` picks the first matching condition, so the bands cannot
    overwrite one another -- an earlier loop-and-assign version applied them in
    descending order and left every pixel in the last (lowest) band.
    """
    conditions = [index > threshold for threshold, _ in bands]
    choices = [label for _, label in bands]

    labels = np.select(conditions, choices, default=L_BARE).astype(np.uint8)
    labels[~land_mask] = L_BARE
    return labels


def _steep_terrain_mask(bbox, shape):
    """Pixels on slopes too steep to farm, from the elevation model.

    Returns ``(mask, available)``. When the DEM is unreachable the mask is
    empty and the caller adds a caveat -- guessing relief from image contrast
    is what produced the "79% mountains over a city" result.
    """
    grid = elevation_service.fetch_elevation_grid(bbox)
    slopes = elevation_service.slope_percent(grid, bbox)
    if slopes is None:
        return np.zeros(shape, dtype=bool), False

    return upsample_grid(slopes, shape) > STEEP_SLOPE_PERCENT, True


def _classify_with_model(image, labels, land_mask, grid_size=10):
    """Overwrite land labels with per-cell ResNet predictions. Best effort."""
    import torch
    from PIL import Image as PILImage
    from torchvision import transforms

    model, device = load_soil_model()
    if model is None:
        return False

    preprocess = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])

    # ImageFolder sorts class directories alphabetically.
    class_names = ['high_fertility', 'low_fertility', 'medium_fertility']
    height, width = labels.shape

    crops, cells = [], []
    for row in range(grid_size):
        for col in range(grid_size):
            y1, y2 = int(row * height / grid_size), int((row + 1) * height / grid_size)
            x1, x2 = int(col * width / grid_size), int((col + 1) * width / grid_size)
            if y2 <= y1 or x2 <= x1:
                continue
            cell_land = land_mask[y1:y2, x1:x2]
            if cell_land.mean() < 0.5:
                continue
            crops.append(preprocess(PILImage.fromarray(image[y1:y2, x1:x2])))
            cells.append((y1, y2, x1, x2))

    if not crops:
        return False

    with torch.no_grad():
        outputs = model(torch.stack(crops).to(device))
        probabilities = torch.nn.functional.softmax(outputs, dim=1)
        confidences, indices = torch.max(probabilities, dim=1)

    for position, (y1, y2, x1, x2) in enumerate(cells):
        predicted = class_names[indices[position].item()]
        confidence = confidences[position].item()

        if predicted == 'high_fertility':
            label = L_VERY_HIGH if confidence > 0.75 else L_HIGH
        elif predicted == 'medium_fertility':
            label = L_MODERATE
        else:
            label = L_LOW if confidence >= 0.7 else L_BARE

        cell = labels[y1:y2, x1:x2]
        cell[land_mask[y1:y2, x1:x2]] = label

    return True


def _build_result(labels, bbox, method, imagery_meta, components=None):
    """Shared tail: paint the overlay and count the classes."""
    height, width = labels.shape

    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    for label, colour in COLOURS.items():
        rgba[labels == label] = colour

    total = height * width
    counts = np.bincount(labels.ravel(), minlength=8)

    stats = {
        'very_high': percentage(counts[L_VERY_HIGH], total),
        'high': percentage(counts[L_HIGH], total),
        'moderate': percentage(counts[L_MODERATE], total),
        'low': percentage(counts[L_LOW], total),
        # Key names are kept for the stored SoilAnalysis columns.
        'mountains': percentage(counts[L_STEEP], total),
        'water': percentage(counts[L_WATER], total),
        'desert': percentage(counts[L_BARE], total),
        'built_up': percentage(counts[L_BUILT], total),
        'analysis_method': method,
    }

    return {
        'stats': stats,
        'legend': LEGEND,
        'overlay': encode_overlay(rgba),
        'method': method,
        'imagery': imagery_meta,
        'components': components or {},
    }


def _normalise(values, span):
    low, high = span
    return np.clip((values - low) / (high - low), 0.0, 1.0)


def _fertility_score(peak, mean, soil_score):
    """Composite fertility in [0, 1] per pixel.

    Productivity is 60% peak NDVI (how much the ground can grow) and 40%
    season mean (how long it stays green). With a soil score the two halves
    are blended by ``PRODUCTIVITY_WEIGHT`` / ``SOIL_WEIGHT``; without one the
    result is productivity alone, and the response says so.
    """
    productivity = 0.6 * _normalise(peak, PEAK_RANGE) + 0.4 * _normalise(mean, MEAN_RANGE)
    if soil_score is None:
        return productivity, productivity
    score = PRODUCTIVITY_WEIGHT * productivity + SOIL_WEIGHT * soil_score
    return score, productivity


def _landcover_masks(bbox, shape):
    """Water / built / excluded masks from WorldCover, or ``None`` if unavailable."""
    if not worldcover.is_available():
        return None
    try:
        classes, meta = worldcover.fetch_landcover(bbox, size=shape[0])
    except WorldCoverUnavailable as exc:
        logger.info('WorldCover unavailable, using NDVI water mask: %s', exc)
        return None

    if classes.shape != shape:
        classes = upsample_grid(classes, shape).astype(np.uint8)

    return {
        'water': np.isin(classes, worldcover.WATER_CLASSES),
        'built': classes == worldcover.BUILT_UP,
        'excluded': np.isin(classes, (worldcover.SNOW, worldcover.NODATA)),
        'meta': meta,
        'percentages': worldcover.class_percentages(classes),
    }


def _from_composite(bbox):
    """Multi-season productivity + soil + land cover + slope."""
    season = sentinel.fetch_seasonal_productivity(bbox)
    peak, mean, observations = season['peak'], season['mean'], season['observations']
    shape = peak.shape
    observed = observations > 0

    lat = (bbox[1] + bbox[3]) / 2.0
    lon = (bbox[0] + bbox[2]) / 2.0
    soil = soilgrids.fetch_soil_properties(lat, lon)
    soil_score, soil_factors = soilgrids.soil_quality_score(soil)

    cover = _landcover_masks(bbox, shape)
    if cover is not None:
        water = cover['water'] & observed
        built = cover['built'] & observed
        excluded = cover['excluded']
    else:
        water = (np.nan_to_num(peak, nan=1.0) < NDVI_WATER_THRESHOLD) & observed
        built = np.zeros(shape, dtype=bool)
        excluded = np.zeros(shape, dtype=bool)

    steep, elevation_available = _steep_terrain_mask(bbox, shape)
    steep &= ~water & ~built
    land = observed & ~water & ~built & ~steep & ~excluded

    score, productivity = _fertility_score(
        np.nan_to_num(peak, nan=0.0), np.nan_to_num(mean, nan=0.0), soil_score
    )

    labels = _classify_by_vegetation(score, land, bands=_SCORE_BANDS)
    labels[water] = L_WATER
    labels[built] = L_BUILT
    labels[steep] = L_STEEP
    labels[~observed | excluded] = L_BARE

    method_parts = [f"NDVI Sentinel-2 за {len(season['years'])} сезона"]
    if soil_score is not None:
        method_parts.append('почва SoilGrids')
    if cover is not None:
        method_parts.append('покров WorldCover')
    if elevation_available:
        method_parts.append('уклон DEM')
    method = ' + '.join(method_parts)

    land_pixels = land.sum()
    components = {
        'productivity': {
            'source': f"{season['source']} ({season['provider']})",
            'years': season['years'],
            'scenes_used': season['scenes_used'],
            'scene_dates': season['scene_dates'],
            'peak_ndvi_mean': round(float(np.nanmean(peak[land])), 3) if land_pixels else None,
            'season_ndvi_mean': round(float(np.nanmean(mean[land])), 3) if land_pixels else None,
            'score_mean': round(float(productivity[land].mean()), 3) if land_pixels else None,
            'weight': PRODUCTIVITY_WEIGHT if soil_score is not None else 1.0,
        },
        'soil': {
            'source': (soil or {}).get('provider'),
            'resolution_m': (soil or {}).get('resolution_m'),
            'score': soil_score,
            'factors': soil_factors,
            'weight': SOIL_WEIGHT if soil_score is not None else 0.0,
            'note': None if soil_score is not None else
                    'Данные SoilGrids для этой точки недоступны; индекс построен только по продуктивности',
        },
        'land_cover': {
            'source': cover['meta']['source'] if cover else None,
            'percentages': {
                worldcover.LABELS.get(code, str(code)): share
                for code, share in (cover['percentages'] if cover else {}).items()
            },
            'note': None if cover else 'WorldCover недоступен; вода определена по NDVI',
        },
        'elevation': {
            'source': 'Copernicus GLO-90 (Open-Meteo)' if elevation_available else None,
            'steep_threshold_percent': STEEP_SLOPE_PERCENT,
        },
    }

    result = _build_result(
        labels, bbox, method,
        {
            'source': season['source'],
            'provider': season['provider'],
            'capture_date': season['scene_dates'][-1] if season['scene_dates'] else None,
            'scenes_used': season['scenes_used'],
            'years': season['years'],
            'metres_per_pixel': season['metres_per_pixel'],
            'valid_coverage': season['valid_coverage'],
            'elevation_model': 'Copernicus GLO-90' if elevation_available else None,
            'land_cover': cover['meta']['source'] if cover else None,
        },
        components,
    )
    result['bounds'] = [[bbox[1], bbox[0]], [bbox[3], bbox[2]]]
    return result


def _from_sentinel(bbox):
    """Fertility from one NDVI scene: the fallback when seasons are unavailable."""
    ndvi, valid, meta = sentinel.fetch_ndvi_array(bbox)

    cover = _landcover_masks(bbox, ndvi.shape)
    if cover is not None:
        water = cover['water'] & valid
        built = cover['built'] & valid
    else:
        water = (ndvi < NDVI_WATER_THRESHOLD) & valid
        built = np.zeros(ndvi.shape, dtype=bool)

    steep, elevation_available = _steep_terrain_mask(bbox, ndvi.shape)
    steep &= ~water & ~built
    land = valid & ~water & ~built & ~steep

    labels = _classify_by_vegetation(ndvi, land, bands=_NDVI_BANDS)
    labels[water] = L_WATER
    labels[built] = L_BUILT
    labels[steep] = L_STEEP
    # Cloud-masked pixels carry no information; they are not bare ground.
    labels[~valid] = L_BARE

    result = _build_result(
        labels, bbox,
        'NDVI по одному снимку Sentinel-2 + уклон по DEM',
        {
            'source': meta['source'],
            'provider': meta['provider'],
            'capture_date': meta['capture_date'],
            'cloud_percent': meta['cloud_percent'],
            'metres_per_pixel': meta['metres_per_pixel'],
            'valid_coverage': meta['valid_coverage'],
            'elevation_model': 'Copernicus GLO-90' if elevation_available else None,
            'land_cover': cover['meta']['source'] if cover else None,
        },
        {'note': 'Оценка по одному снимку: показывает состояние на дату, а не многолетнюю продуктивность'},
    )
    result['bounds'] = [[bbox[1], bbox[0]], [bbox[3], bbox[2]]]
    return result


def _from_basemap(bbox):
    """Fertility from the RGB basemap, used when Sentinel-2 is unavailable."""
    imagery = load_imagery(bbox, ZOOM)
    image = imagery.pixels
    height, width = image.shape[:2]

    water = water_mask(image)
    steep, elevation_available = _steep_terrain_mask(bbox, (height, width))
    steep &= ~water
    land = ~water & ~steep

    exg = excess_green_index(image)
    labels = _classify_by_vegetation(exg, land, bands=_EXG_BANDS)
    labels[water] = L_WATER
    labels[steep] = L_STEEP

    method = 'Индекс ExG по RGB-подложке + уклон по DEM'

    if model_enabled():
        try:
            if _classify_with_model(image, labels, land):
                method = 'ResNet-18 по сетке 10×10 (экспериментально)'
        except Exception:
            logger.exception('Soil model inference failed; falling back to the heuristic')

    result = _build_result(
        labels, bbox, method,
        {
            'source': 'ArcGIS World Imagery',
            'capture_date': None,
            'zoom': imagery.zoom,
            'metres_per_pixel': round(imagery.metres_per_pixel, 2),
            'tiles': f'{imagery.tiles_retrieved}/{imagery.tiles_requested}',
            'elevation_model': 'Copernicus GLO-90' if elevation_available else None,
        },
        {'note': 'Оценка по видимому спектру без даты съёмки; Sentinel-2 был недоступен'},
    )
    result['bounds'] = imagery.bounds
    return result


def analyze_fertility(bbox):
    """Classify fertility across ``bbox`` and return stats plus an overlay.

    Order of preference: multi-season composite, single Sentinel-2 scene,
    RGB basemap. Each step down is labelled in ``method`` and ``components``.
    """
    if sentinel.is_available():
        try:
            return _from_composite(bbox)
        except SentinelUnavailable as exc:
            logger.info('Composite fertility unavailable, trying one scene: %s', exc)
        try:
            return _from_sentinel(bbox)
        except SentinelUnavailable as exc:
            logger.info('Fertility falling back to the basemap: %s', exc)

    return _from_basemap(bbox)
