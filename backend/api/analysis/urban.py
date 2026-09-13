"""Urban structure: built-up land, buildings, and how the built-up area changed.

Sources, in order of preference:

* **ESA WorldCover** (10 m, 2020 and 2021) for the built-up class, the
  vegetation classes and water. A published land-cover product with a stated
  accuracy, not a colour threshold.
* **OpenStreetMap building footprints** via Overpass for individual buildings
  and their areas, where people have mapped them.
* The previous Canny/HSV heuristics remain only as a fallback when neither
  source can answer, and the ``method`` field says when that happened.

"Prediction" of development is not something a free official source offers.
What is offered is *change*: built-up land in 2021 versus 2020, and how much
arable or bare ground sits next to existing settlement. That is reported as
dynamics and potential, not as a forecast.
"""

import logging

import cv2
import numpy as np

from api.services import buildings as buildings_service
from api.services import worldcover
from api.services.worldcover import WorldCoverUnavailable

from .imagery import encode_overlay, load_imagery, percentage

logger = logging.getLogger(__name__)

BUILDING_ZOOM = 15
DEVELOPMENT_ZOOM = 14
URBAN_FILTER_ZOOM = 14
GRID_SIZE = 256

# Distance from existing settlement, in pixels of the WorldCover grid, that
# counts as "next to infrastructure" for the development-potential estimate.
EXPANSION_PX = 12


def _bounds(bbox):
    return [[bbox[1], bbox[0]], [bbox[3], bbox[2]]]


def _landcover(bbox, year=worldcover.LATEST_YEAR):
    if not worldcover.is_available():
        return None, None
    try:
        return worldcover.fetch_landcover(bbox, year=year, size=GRID_SIZE)
    except WorldCoverUnavailable as exc:
        logger.info('WorldCover %s unavailable: %s', year, exc)
        return None, None


def _rasterise(rings, bbox, shape):
    """Paint lat/lon rings onto a ``shape`` grid aligned with ``bbox``."""
    height, width = shape
    min_lon, min_lat, max_lon, max_lat = bbox
    mask = np.zeros((height, width), dtype=np.uint8)
    lon_span = max(max_lon - min_lon, 1e-9)
    lat_span = max(max_lat - min_lat, 1e-9)

    for ring in rings:
        points = np.array([
            [(lon - min_lon) / lon_span * width, (max_lat - lat) / lat_span * height]
            for lat, lon in ring
        ], dtype=np.int32)
        cv2.fillPoly(mask, [points], 255)
    return mask


def _district_type(density):
    if density > 40:
        return 'Плотная городская застройка'
    if density > 15:
        return 'Жилой район / Пригород'
    if density > 1:
        return 'Сельская местность / Редкая застройка'
    return 'Незастроенная территория'


# ---------------------------------------------------------------------------
# Buildings / infrastructure
# ---------------------------------------------------------------------------
def detect_buildings(bbox):
    classes, cover_meta = _landcover(bbox)
    footprints = buildings_service.lookup_buildings(bbox)

    if classes is None and footprints is None:
        return _detect_buildings_heuristic(bbox)

    shape = (GRID_SIZE, GRID_SIZE)
    overlay = np.zeros((*shape, 4), dtype=np.uint8)
    sources = []

    built_up_percent = None
    if classes is not None:
        built = classes == worldcover.BUILT_UP
        built_up_percent = percentage(np.count_nonzero(built), classes.size)
        overlay[built] = (255, 120, 60, 120)
        sources.append(cover_meta['source'])

    buildings = []
    footprint_area = 0.0
    if footprints is not None:
        mask = _rasterise([f['ring'] for f in footprints], bbox, shape)
        overlay[mask > 0] = (255, 69, 0, 200)
        footprint_area = sum(f['area_sqm'] for f in footprints)
        buildings = [{
            'type': f['type'] or 'building',
            'name': f['name'],
            'levels': f['levels'],
            'lat': f['lat'], 'lon': f['lon'],
            'area_sqm': f['area_sqm'],
        } for f in footprints]
        sources.append('OpenStreetMap')

    bbox_area = buildings_service.bbox_area_km2(bbox) * 1e6
    footprint_percent = round(footprint_area / bbox_area * 100.0, 2) if bbox_area else 0.0
    density = built_up_percent if built_up_percent is not None else footprint_percent

    method = 'Класс «застройка» WorldCover' if classes is not None else 'Контуры зданий OpenStreetMap'
    if classes is not None and footprints is not None:
        method = 'Класс «застройка» WorldCover + контуры зданий OpenStreetMap'

    notes = []
    if footprints is None:
        notes.append('Контуры зданий не запрашивались: область больше '
                     f'{buildings_service.MAX_AREA_KM2:.0f} км² или Overpass недоступен.')
    elif not footprints:
        notes.append('В OpenStreetMap здания здесь не размечены; плотность взята из WorldCover.')
    if classes is None:
        notes.append('WorldCover недоступен; плотность взята по контурам OSM.')

    return {
        'building_density': density,
        'built_up_percent': built_up_percent,
        'footprint_percent': footprint_percent,
        'district_type': _district_type(density),
        'buildings_detected': len(buildings),
        'buildings_total_area_sqm': round(footprint_area, 1),
        'buildings': buildings[:200],
        'overlay': encode_overlay(overlay),
        'bounds': _bounds(bbox),
        'legend': {
            'Здания (OpenStreetMap)': 'rgba(255, 69, 0, 0.8)',
            'Застройка (WorldCover)': 'rgba(255, 120, 60, 0.5)',
        },
        'method': method,
        'sources': sources,
        'notes': notes,
        'imagery': {
            'source': ' + '.join(sources),
            'metres_per_pixel': cover_meta['metres_per_pixel'] if cover_meta else None,
            'land_cover_year': cover_meta['year'] if cover_meta else None,
        },
    }


def _detect_buildings_heuristic(bbox):
    imagery = load_imagery(bbox, BUILDING_ZOOM)
    image = imagery.pixels
    height, width = image.shape[:2]

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)

    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_lon, min_lat, max_lon, max_lat = bbox
    building_mask = np.zeros((height, width), dtype=np.uint8)
    buildings = []
    building_pixels = 0

    for contour in contours:
        area_px = cv2.contourArea(contour)
        if area_px < 50:
            continue

        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
        if not 3 <= len(approx) <= 6:
            continue

        x, y, w, h = cv2.boundingRect(approx)
        if h == 0 or not 0.2 < (w / h) < 5:
            continue

        cv2.drawContours(building_mask, [contour], -1, 255, -1)
        building_pixels += area_px

        moments = cv2.moments(contour)
        if moments['m00'] == 0:
            continue
        cx = moments['m10'] / moments['m00']
        cy = moments['m01'] / moments['m00']
        buildings.append({
            'type': 'candidate',
            'lat': round(max_lat - (cy / height) * (max_lat - min_lat), 6),
            'lon': round(min_lon + (cx / width) * (max_lon - min_lon), 6),
            'area_sqm': round(imagery.pixels_to_area_sqm(area_px), 1),
        })

    density = percentage(building_pixels, height * width)
    overlay = np.zeros((height, width, 4), dtype=np.uint8)
    overlay[building_mask > 0] = (255, 69, 0, 180)

    return {
        'building_density': density,
        'built_up_percent': None,
        'footprint_percent': None,
        'district_type': _district_type(density),
        'buildings_detected': len(buildings),
        'buildings': buildings[:200],
        'overlay': encode_overlay(overlay),
        'bounds': imagery.bounds,
        'method': 'Эвристика: контуры Canny по RGB-подложке (WorldCover и OSM недоступны)',
        'sources': ['ArcGIS World Imagery'],
        'notes': ['Это грубая текстурная оценка, а не кадастровые данные.'],
        'imagery': {
            'source': 'ArcGIS World Imagery',
            'zoom': imagery.zoom,
            'metres_per_pixel': round(imagery.metres_per_pixel, 2),
        },
    }


# ---------------------------------------------------------------------------
# Development dynamics
# ---------------------------------------------------------------------------
def predict_development(bbox):
    """Built-up change 2020 -> 2021 plus arable land next to settlement."""
    current, current_meta = _landcover(bbox, year=2021)
    if current is None:
        return _predict_development_heuristic(bbox)

    previous, _ = _landcover(bbox, year=2020)

    built_now = current == worldcover.BUILT_UP
    built_percent_now = percentage(np.count_nonzero(built_now), current.size)

    change = None
    new_built = np.zeros_like(built_now)
    if previous is not None:
        built_before = previous == worldcover.BUILT_UP
        built_percent_before = percentage(np.count_nonzero(built_before), previous.size)
        change = round(built_percent_now - built_percent_before, 2)
        new_built = built_now & ~built_before

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * EXPANSION_PX + 1,) * 2)
    near_settlement = cv2.dilate(built_now.astype(np.uint8), kernel) > 0
    available = np.isin(current, worldcover.ARABLE_CLASSES) & near_settlement & ~built_now

    potential = percentage(np.count_nonzero(available), current.size)
    metres_per_pixel = current_meta['metres_per_pixel']
    available_sqm = float(np.count_nonzero(available)) * metres_per_pixel ** 2

    if potential > 30:
        status = 'Много свободной земли рядом с застройкой'
        recommendations = ['Рядом с существующей застройкой много пашни, луга или пустоши.',
                           'Такие участки застраиваются первыми, если растёт спрос.']
    elif potential > 10:
        status = 'Умеренный запас свободной земли'
        recommendations = ['Возможна точечная застройка на свободных участках.']
    else:
        status = 'Свободной земли рядом с застройкой мало'
        recommendations = ['Район плотно застроен или ограничен рельефом, водой и лесом.']

    if change is not None:
        if change > 1.0:
            recommendations.insert(0, f'Застройка выросла на {change:.1f} п.п. между 2020 и 2021 годами.')
        elif change < -1.0:
            recommendations.insert(0, f'Класс «застройка» сократился на {abs(change):.1f} п.п. между 2020 и 2021 годами.')
        else:
            recommendations.insert(0, 'Между 2020 и 2021 годами площадь застройки почти не изменилась.')

    overlay = np.zeros((*current.shape, 4), dtype=np.uint8)
    overlay[available] = (0, 215, 255, 150)
    overlay[built_now] = (120, 120, 120, 120)
    overlay[new_built] = (255, 0, 0, 220)

    return {
        'growth_status': status,
        'growth_potential_percent': potential,
        'available_area_sqm': round(available_sqm, 1),
        'built_up_percent_2021': built_percent_now,
        'built_up_change_pp': change,
        'recommendations': recommendations,
        'overlay': encode_overlay(overlay),
        'bounds': _bounds(bbox),
        'legend': {
            'Свободная земля у застройки': 'rgba(0, 215, 255, 0.6)',
            'Застройка 2021': 'rgba(120, 120, 120, 0.5)',
            'Новая застройка 2020→2021': 'rgba(255, 0, 0, 0.9)',
        },
        'method': 'Динамика класса «застройка» WorldCover 2020→2021 + свободная земля рядом',
        'sources': [current_meta['source']] + (['ESA WorldCover 2020 v1.0.0'] if previous is not None else []),
        'notes': [] if previous is not None else ['WorldCover 2020 недоступен: изменение не рассчитано.'],
        'imagery': {
            'source': current_meta['source'],
            'metres_per_pixel': metres_per_pixel,
            'land_cover_year': current_meta['year'],
        },
    }


def _predict_development_heuristic(bbox):
    imagery = load_imagery(bbox, DEVELOPMENT_ZOOM)
    image = imagery.pixels
    height, width = image.shape[:2]

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    built_up = cv2.dilate(cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel), kernel, iterations=2)

    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    water = cv2.inRange(hsv, np.array([90, 40, 40]), np.array([140, 255, 255]))
    forest = cv2.inRange(hsv, np.array([35, 100, 20]), np.array([85, 255, 150]))
    unsuitable = cv2.bitwise_or(water, forest)

    available = cv2.bitwise_and(cv2.bitwise_not(built_up), cv2.bitwise_not(unsuitable))
    expansion_zone = cv2.dilate(built_up, kernel, iterations=5)
    predicted = cv2.morphologyEx(cv2.bitwise_and(expansion_zone, available), cv2.MORPH_OPEN, kernel)

    growth_percent = percentage(np.count_nonzero(predicted), height * width)
    if growth_percent > 30:
        status = 'Много свободной земли рядом с застройкой'
    elif growth_percent > 10:
        status = 'Умеренный запас свободной земли'
    else:
        status = 'Свободной земли рядом с застройкой мало'

    overlay = np.zeros((height, width, 4), dtype=np.uint8)
    overlay[predicted > 0] = (0, 215, 255, 150)

    return {
        'growth_status': status,
        'growth_potential_percent': growth_percent,
        'available_area_sqm': round(imagery.pixels_to_area_sqm(np.count_nonzero(predicted)), 1),
        'built_up_percent_2021': None,
        'built_up_change_pp': None,
        'recommendations': ['Оценка по текстуре RGB-подложки: WorldCover недоступен.'],
        'overlay': encode_overlay(overlay),
        'bounds': imagery.bounds,
        'method': 'Эвристика: морфология по RGB-подложке (WorldCover недоступен)',
        'sources': ['ArcGIS World Imagery'],
        'notes': ['Это грубая текстурная оценка.'],
        'imagery': {
            'source': 'ArcGIS World Imagery',
            'zoom': imagery.zoom,
            'metres_per_pixel': round(imagery.metres_per_pixel, 2),
        },
    }


# ---------------------------------------------------------------------------
# Urban filter / land cover
# ---------------------------------------------------------------------------
def filter_urban_areas(bbox):
    classes, meta = _landcover(bbox)
    if classes is None:
        return _filter_urban_areas_heuristic(bbox)

    shares = worldcover.class_percentages(classes)
    urban = shares.get(worldcover.BUILT_UP, 0.0)
    vegetation = round(sum(shares.get(code, 0.0) for code in worldcover.VEGETATION_CLASSES), 2)
    water = round(sum(shares.get(code, 0.0) for code in worldcover.WATER_CLASSES), 2)

    present = [code for code in worldcover.LABELS if code in shares]

    return {
        'stats': {
            'urban_percent': urban,
            'veg_percent': vegetation,
            'water_percent': water,
            'classes': {worldcover.LABELS[code]: shares[code] for code in present},
        },
        'legend': worldcover.legend(present),
        'overlay': encode_overlay(worldcover.paint(classes)),
        'bounds': _bounds(bbox),
        'method': f"Классы покрова {meta['source']}",
        'sources': [meta['source']],
        'notes': [meta['accuracy_note']],
        'imagery': {
            'source': meta['source'],
            'metres_per_pixel': meta['metres_per_pixel'],
            'land_cover_year': meta['year'],
        },
    }


def _filter_urban_areas_heuristic(bbox):
    imagery = load_imagery(bbox, URBAN_FILTER_ZOOM)
    image = imagery.pixels
    height, width = image.shape[:2]

    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    vegetation = cv2.inRange(hsv, np.array([25, 40, 20]), np.array([95, 255, 255]))
    water = cv2.inRange(hsv, np.array([95, 40, 40]), np.array([140, 255, 255]))

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 200)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    texture = cv2.dilate(cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel), kernel, iterations=2)

    natural = cv2.bitwise_or(vegetation, water)
    urban = cv2.morphologyEx(cv2.bitwise_and(texture, cv2.bitwise_not(natural)), cv2.MORPH_OPEN, kernel)

    total = height * width
    overlay = np.zeros((height, width, 4), dtype=np.uint8)
    overlay[urban > 0] = (80, 70, 70, 200)

    return {
        'stats': {
            'urban_percent': percentage(np.count_nonzero(urban), total),
            'veg_percent': percentage(np.count_nonzero(vegetation), total),
            'water_percent': percentage(np.count_nonzero(water), total),
        },
        'legend': {
            'Городская застройка': 'rgba(80, 70, 70, 0.8)',
            'Природный ландшафт': 'rgba(0, 0, 0, 0)',
        },
        'overlay': encode_overlay(overlay),
        'bounds': imagery.bounds,
        'method': 'Эвристика: текстура и цвет RGB-подложки (WorldCover недоступен)',
        'sources': ['ArcGIS World Imagery'],
        'notes': ['Это грубая текстурная оценка.'],
        'imagery': {
            'source': 'ArcGIS World Imagery',
            'zoom': imagery.zoom,
            'metres_per_pixel': round(imagery.metres_per_pixel, 2),
        },
    }
