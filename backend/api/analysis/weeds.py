"""Detection of vegetation anomalies that may indicate weed infestation.

Scope, stated plainly: a 10 m satellite pixel cannot identify a plant
species. What it can show is where the vegetation inside a field differs
from the rest of that field -- patches that are markedly greener (weed
flushes, volunteer crop) or paler (stress, bare spots) than the field median.
Those are places to walk to, not diagnoses, and the response says so in
``note`` and ``is_species_identified``.

Primary source: the latest clear Sentinel-2 NDVI scene. Anomalies are pixels
whose NDVI sits more than ``ANOMALY_K`` robust standard deviations (median
absolute deviation) from the median of the vegetated pixels. Fallback when
Sentinel-2 is unavailable: the old texture heuristic on the RGB basemap,
labelled as such.
"""

import logging

import cv2
import numpy as np

from api.services import sentinel, worldcover
from api.services.sentinel import SentinelUnavailable
from api.services.worldcover import WorldCoverUnavailable

from .imagery import encode_overlay, load_imagery, percentage, upsample_grid

logger = logging.getLogger(__name__)

ZOOM = 14
MIN_CONTOUR_AREA_PX = 100
MIN_ANOMALY_AREA_SQM = 400   # four Sentinel-2 pixels

# Vegetated pixels: below this NDVI there is nothing for a weed to hide in.
VEGETATION_NDVI = 0.20
# Anomaly threshold in MAD-scaled standard deviations from the field median.
ANOMALY_K = 2.0

NOTE = ('Вид растения по спутниковому снимку не определяется. Отмечены участки, '
        'где растительность заметно отличается от остального поля; для '
        'идентификации нужен осмотр или фото с земли.')

RECOMMENDATIONS = {
    'low': 'Рекомендуется осмотр участка. Мониторинг каждые 2 недели.',
    'medium': ('Осмотрите участок; при подтверждении сорняков — механическая обработка '
               'или точечное применение гербицидов. Мониторинг каждую неделю.'),
    'high': 'Крупный очаг: осмотр в ближайшие дни, при подтверждении — обработка гербицидами.',
    'critical': ('Очень крупный очаг. Немедленный осмотр всего участка; без вмешательства '
                 'возможна потеря урожая.'),
}


def recommendation_for(severity):
    return RECOMMENDATIONS.get(severity, 'Рекомендуется дополнительный осмотр.')


def _severity_for_area(area_sqm):
    """Thresholds in real square metres, not pixels."""
    if area_sqm > 20000:
        return 'critical'
    if area_sqm > 5000:
        return 'high'
    if area_sqm > 1000:
        return 'medium'
    return 'low'


def _local_variance(gray, kernel=5):
    mean = cv2.blur(gray.astype(np.float32), (kernel, kernel))
    mean_of_squares = cv2.blur(gray.astype(np.float32) ** 2, (kernel, kernel))
    return np.maximum(mean_of_squares - mean ** 2, 0.0)


def _contours_to_detections(mask, bbox, sqm_per_pixel, strength_of):
    """Turn an anomaly mask into ranked detections with real-world areas."""
    height, width = mask.shape
    min_lon, min_lat, max_lon, max_lat = bbox

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    detections = []

    for contour in contours:
        area_px = cv2.contourArea(contour)
        area_sqm = area_px * sqm_per_pixel
        if area_sqm < MIN_ANOMALY_AREA_SQM:
            continue

        moments = cv2.moments(contour)
        if moments['m00'] == 0:
            continue
        cx = moments['m10'] / moments['m00']
        cy = moments['m01'] / moments['m00']

        x, y, w, h = cv2.boundingRect(contour)
        patch_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.drawContours(patch_mask, [contour], -1, 255, -1, offset=(-x, -y))
        strength, direction = strength_of(y, x, h, w, patch_mask > 0)

        severity = _severity_for_area(area_sqm)
        detections.append({
            'name': 'Аномалия растительности',
            'is_species_identified': False,
            'direction': direction,
            'lat': round(max_lat - (cy / height) * (max_lat - min_lat), 6),
            'lon': round(min_lon + (cx / width) * (max_lon - min_lon), 6),
            'area': round(area_sqm, 1),
            'severity': severity,
            'anomaly_strength': round(strength, 2),
            'recommendations': recommendation_for(severity),
        })

    detections.sort(key=lambda item: item['area'], reverse=True)
    return detections


def _farmland_mask(bbox, shape):
    """Cropland, grass and shrub from WorldCover, or ``None`` if unavailable.

    Without it a city park or a tree line reads as an "anomaly" against the
    surrounding roofs. Weeds live in fields; restrict the search to them.
    """
    if not worldcover.is_available():
        return None
    try:
        classes, meta = worldcover.fetch_landcover(bbox, size=shape[0])
    except WorldCoverUnavailable as exc:
        logger.info('WorldCover unavailable for weed mask: %s', exc)
        return None
    if classes.shape != shape:
        classes = upsample_grid(classes, shape).astype(np.uint8)
    return np.isin(classes, (worldcover.CROPLAND, worldcover.GRASS, worldcover.SHRUB)), meta


def _from_sentinel(bbox):
    ndvi, valid, meta = sentinel.fetch_ndvi_array(bbox)
    height, width = ndvi.shape
    sqm_per_pixel = meta['metres_per_pixel'] ** 2

    vegetated = valid & (ndvi > VEGETATION_NDVI)
    farmland = _farmland_mask(bbox, ndvi.shape)
    if farmland is not None:
        vegetated &= farmland[0]
        meta = {**meta, 'land_cover': farmland[1]['source']}
    empty = {
        'detections': [],
        'weed_coverage_percent': 0.0,
        'total_weed_area_sqm': 0.0,
        'overlay': encode_overlay(np.zeros((height, width, 4), dtype=np.uint8)),
        'bounds': [[bbox[1], bbox[0]], [bbox[3], bbox[2]]],
        'method': 'Отклонение NDVI от медианы поля (Sentinel-2)',
        'is_species_identified': False,
        'note': NOTE,
        'imagery': _imagery_meta(meta),
    }
    if vegetated.sum() < 50:
        empty['note'] = 'Растительность в выбранной области не обнаружена. ' + NOTE
        return empty

    values = ndvi[vegetated]
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median))) * 1.4826  # MAD -> sigma
    if mad < 0.01:
        mad = 0.01

    deviation = (ndvi - median) / mad
    anomalies = vegetated & (np.abs(deviation) > ANOMALY_K)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(anomalies.astype(np.uint8) * 255, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    def strength_of(y, x, h, w, patch):
        patch_dev = deviation[y:y + h, x:x + w][patch]
        signed = float(patch_dev.mean())
        strength = min(1.0, abs(signed) / (ANOMALY_K * 2))
        return strength, ('greener' if signed > 0 else 'paler')

    detections = _contours_to_detections(mask, bbox, sqm_per_pixel, strength_of)

    overlay = np.zeros((height, width, 4), dtype=np.uint8)
    greener = (mask > 0) & (deviation > 0)
    paler = (mask > 0) & (deviation <= 0)
    overlay[greener] = (255, 0, 0, 200)
    overlay[paler] = (255, 165, 0, 200)

    return {
        'detections': detections,
        'weed_coverage_percent': percentage(np.count_nonzero(mask), int(vegetated.sum())),
        'total_weed_area_sqm': round(sum(item['area'] for item in detections), 1),
        'field_median_ndvi': round(median, 3),
        'overlay': encode_overlay(overlay),
        'bounds': [[bbox[1], bbox[0]], [bbox[3], bbox[2]]],
        'legend': {
            'Заметно зеленее поля': 'rgba(255, 0, 0, 0.8)',
            'Заметно бледнее поля': 'rgba(255, 165, 0, 0.8)',
            'Обычная растительность': 'rgba(0, 0, 0, 0)',
        },
        'method': 'Отклонение NDVI от медианы поля (Sentinel-2)',
        'is_species_identified': False,
        'note': NOTE,
        'imagery': _imagery_meta(meta),
    }


def _imagery_meta(meta):
    return {
        'source': meta['source'],
        'provider': meta['provider'],
        'capture_date': meta['capture_date'],
        'cloud_percent': meta['cloud_percent'],
        'metres_per_pixel': meta['metres_per_pixel'],
        'land_cover': meta.get('land_cover'),
    }


def _from_basemap(bbox):
    """Texture heuristic on the RGB basemap: the fallback, labelled as such."""
    imagery = load_imagery(bbox, ZOOM)
    image = imagery.pixels
    height, width = image.shape[:2]

    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    hue, saturation, value = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    vegetation = (hue > 25) & (hue < 95) & (saturation > 30) & (value > 30)

    base = {
        'bounds': imagery.bounds,
        'method': 'Текстурный анализ RGB-подложки (Sentinel-2 недоступен)',
        'is_species_identified': False,
        'note': NOTE,
        'imagery': {
            'source': 'ArcGIS World Imagery',
            'capture_date': None,
            'zoom': imagery.zoom,
            'metres_per_pixel': round(imagery.metres_per_pixel, 2),
        },
    }

    if not vegetation.any():
        return {
            **base,
            'detections': [],
            'weed_coverage_percent': 0.0,
            'total_weed_area_sqm': 0.0,
            'overlay': encode_overlay(np.zeros((height, width, 4), dtype=np.uint8)),
            'note': 'Растительность в выбранной области не обнаружена. ' + NOTE,
        }

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    variance = _local_variance(gray)
    threshold = float(np.percentile(variance[vegetation], 75))
    anomalies = (variance > threshold) & vegetation

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(anomalies.astype(np.uint8) * 255, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    def strength_of(y, x, h, w, patch):
        patch_var = variance[y:y + h, x:x + w][patch]
        return float(np.clip((patch_var.mean() - threshold) / (threshold + 1e-6), 0.0, 1.0)), 'texture'

    detections = _contours_to_detections(
        mask, bbox, imagery.square_metres_per_pixel, strength_of
    )

    overlay = np.zeros((height, width, 4), dtype=np.uint8)
    overlay[mask > 0] = (255, 0, 0, 200)

    return {
        **base,
        'detections': detections,
        'weed_coverage_percent': percentage(np.count_nonzero(mask), height * width),
        'total_weed_area_sqm': round(sum(item['area'] for item in detections), 1),
        'overlay': encode_overlay(overlay),
    }


def detect_weeds(bbox):
    if sentinel.is_available():
        try:
            return _from_sentinel(bbox)
        except SentinelUnavailable as exc:
            logger.info('Weed anomalies falling back to the basemap: %s', exc)
    return _from_basemap(bbox)
