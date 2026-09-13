"""Vegetation vigour.

Two sources, in order of preference:

1. **Sentinel-2 via the Planetary Computer** -- a real NDVI from the
   near-infrared band, at 10 m, from a scene with a known acquisition date and
   a cloud mask. Free and keyless.
2. **The RGB basemap** -- the Excess Green index, used when the Sentinel-2
   service is unreachable or every recent scene is clouded out.

The two indices are *not* interchangeable, so each carries its own growth-stage
thresholds and its own health scale. ``index_type`` in the response says which
one produced the numbers, which is what makes a stored time series
interpretable later.
"""

import logging

import numpy as np

from api.services import sentinel
from api.services.sentinel import SentinelUnavailable

from .imagery import encode_overlay, excess_green_index, load_imagery

logger = logging.getLogger(__name__)

ZOOM = 13


class IndexProfile:
    """Thresholds and scaling for one vegetation index."""

    def __init__(self, code, label, stages, health_floor, health_ceiling, palette):
        self.code = code
        self.label = label
        self.stages = stages
        self.health_floor = health_floor
        self.health_ceiling = health_ceiling
        self.palette = palette

    def growth_stage(self, mean):
        for threshold, stage in self.stages:
            if mean < threshold:
                return stage
        return 'maturation'

    def health_score(self, mean):
        span = self.health_ceiling - self.health_floor
        return float(np.clip((mean - self.health_floor) / span * 100.0, 0.0, 100.0))


# Standard NDVI breakpoints from the remote-sensing literature. These are the
# thresholds the growth stages were always meant to use; they only became
# applicable once a real NIR band was available.
NDVI = IndexProfile(
    code='NDVI',
    label='NDVI (Sentinel-2)',
    stages=((0.10, 'bare_soil'), (0.20, 'emergence'), (0.40, 'vegetative'), (0.60, 'flowering')),
    health_floor=0.0,
    health_ceiling=0.85,
    palette=((0.60, (0, 128, 0, 180)), (0.40, (144, 238, 144, 180)),
             (0.20, (255, 255, 0, 180)), (0.10, (139, 69, 19, 180))),
)

# ExG breakpoints, calibrated against the actual distribution of the RGB
# basemap rather than borrowed from NDVI.
EXG = IndexProfile(
    code='ExG',
    label='Индекс зелёности (ExG)',
    stages=((0.02, 'bare_soil'), (0.06, 'emergence'), (0.12, 'vegetative'), (0.18, 'flowering')),
    health_floor=-0.10,
    health_ceiling=0.25,
    palette=((0.18, (0, 128, 0, 180)), (0.10, (144, 238, 144, 180)),
             (0.03, (255, 255, 0, 180)), (-0.05, (139, 69, 19, 180))),
)

_WATER_COLOUR = (0, 0, 139, 180)


def _paint(index, profile, shape):
    """Colour the index. NaN marks masked pixels and stays transparent."""
    rgba = np.zeros((*shape, 4), dtype=np.uint8)
    finite = np.isfinite(index)

    rgba[finite & (index <= profile.palette[-1][0])] = _WATER_COLOUR
    for threshold, colour in reversed(profile.palette):
        rgba[finite & (index > threshold)] = colour
    return rgba


def analyze_vegetation(bbox):
    """NDVI from Sentinel-2 when available, otherwise ExG from the basemap."""
    if sentinel.is_available():
        try:
            return _from_sentinel(bbox)
        except SentinelUnavailable as exc:
            logger.info('Falling back to ExG: %s', exc)

    return _from_basemap(bbox)


def _from_sentinel(bbox):
    stats = sentinel.fetch_ndvi_stats(bbox)
    meta = stats['metadata']
    mean = stats['index_mean']

    ndvi, valid = stats['ndvi'], stats['valid']
    overlay = _paint(np.where(valid, ndvi, np.nan), NDVI, ndvi.shape)

    # Context that a single number lacks: moisture from the SWIR band, and how
    # this reading compares with the same calendar window in previous years.
    ndmi = stats.get('ndmi_mean')
    reference = stats.get('reference_ndvi')
    anomaly = round(mean - reference, 4) if reference is not None else None

    return {
        'index_type': NDVI.code,
        'index_label': NDVI.label,
        'index_mean': mean,
        'index_min': stats['index_min'],
        'index_max': stats['index_max'],
        'index_stddev': stats['index_stddev'],
        'health_score': round(NDVI.health_score(mean), 2),
        'growth_stage': NDVI.growth_stage(mean),
        'moisture_index': ndmi,
        'moisture_label': describe_moisture(ndmi),
        'reference_ndvi': reference,
        'reference_years': stats.get('reference_years') or [],
        'ndvi_anomaly': anomaly,
        'anomaly_label': describe_anomaly(anomaly),
        'overlay': encode_overlay(overlay),
        'bounds': [[bbox[1], bbox[0]], [bbox[3], bbox[2]]],
        'method': 'NDVI по Sentinel-2 (ближний ИК)',
        'imagery': {
            'source': meta['source'],
            'provider': meta['provider'],
            'capture_date': meta['capture_date'],
            'cloud_percent': meta['cloud_percent'],
            'metres_per_pixel': meta['metres_per_pixel'],
            'valid_coverage': meta['valid_coverage'],
        },
    }


def describe_moisture(ndmi):
    """Plain-language reading of NDMI (Gao 1996 breakpoints, approximately)."""
    if ndmi is None:
        return None
    if ndmi < -0.2:
        return 'Сухая растительность или голая почва'
    if ndmi < 0.0:
        return 'Низкая влажность растительного покрова'
    if ndmi < 0.2:
        return 'Умеренная влажность'
    if ndmi < 0.4:
        return 'Высокая влажность'
    return 'Очень влажно (возможен застой воды)'


def describe_anomaly(anomaly):
    """NDVI now minus the same window in previous years."""
    if anomaly is None:
        return None
    if anomaly > 0.10:
        return 'Заметно зеленее обычного для этого времени года'
    if anomaly > 0.03:
        return 'Немного зеленее обычного'
    if anomaly < -0.10:
        return 'Заметно хуже обычного: проверьте полив, вредителей и сроки сева'
    if anomaly < -0.03:
        return 'Немного ниже обычного'
    return 'В пределах нормы для этого времени года'


def _from_basemap(bbox):
    imagery = load_imagery(bbox, ZOOM)
    index = excess_green_index(imagery.pixels)
    mean = float(np.mean(index))

    return {
        'index_type': EXG.code,
        'index_label': EXG.label,
        'index_mean': round(mean, 4),
        'index_min': round(float(np.min(index)), 4),
        'index_max': round(float(np.max(index)), 4),
        'index_stddev': round(float(np.std(index)), 4),
        'health_score': round(EXG.health_score(mean), 2),
        'growth_stage': EXG.growth_stage(mean),
        'overlay': encode_overlay(_paint(index, EXG, index.shape)),
        'bounds': imagery.bounds,
        'method': f'{EXG.label} по RGB-подложке',
        'imagery': {
            'source': 'ArcGIS World Imagery',
            'capture_date': None,
            'metres_per_pixel': round(imagery.metres_per_pixel, 2),
            'zoom': imagery.zoom,
        },
    }


def summarise_history(growth_records):
    """Trend across stored observations for one field."""
    records = sorted(growth_records, key=lambda record: record.observation_date)
    values = [record.ndvi_mean for record in records if record.ndvi_mean is not None]

    if len(values) < 2:
        return {
            'trend': 'insufficient_data',
            'recommendation': 'Недостаточно данных для анализа',
            'data_points': len(values),
        }

    midpoint = len(values) // 2
    change = float(np.mean(values[midpoint:]) - np.mean(values[:midpoint]))

    # Threshold sits between the two indices' scales: ExG moves in a narrower
    # range than NDVI, and a stored series may span a switch between them.
    if change > 0.03:
        trend = 'improving'
        recommendation = 'Растительность активно развивается. Продолжайте текущий уход.'
    elif change < -0.03:
        trend = 'declining'
        recommendation = ('Замечено снижение растительного покрова. Проверьте полив, '
                          'удобрения и наличие вредителей.')
    else:
        trend = 'stable'
        recommendation = 'Состояние растений стабильное.'

    return {
        'trend': trend,
        'index_change': round(change, 4),
        'recommendation': recommendation,
        'data_points': len(values),
    }
