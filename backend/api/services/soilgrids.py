"""ISRIC SoilGrids v2.0 client.

Replaces the previous ``random.uniform`` soil chemistry. Every value returned
from here carries a ``source`` marker so the UI can distinguish a measured
property from a derived estimate, and an unreachable service yields ``None``
instead of a plausible-looking invention.

What SoilGrids actually provides, and what it does not
-----------------------------------------------------
Measured (global 250 m rasters, modelled from ~240k soil profiles):
  * ``phh2o``    -- pH in water
  * ``nitrogen`` -- total nitrogen
  * ``soc``      -- soil organic carbon
  * ``cec``      -- cation exchange capacity
  * ``clay`` / ``sand`` -- texture
  * ``wv0033``   -- volumetric water content at field capacity (33 kPa)

Not provided: plant-available phosphorus and exchangeable potassium. Those two
are derived below from CEC and organic carbon using standard agronomic
rules-of-thumb, and are reported with ``source='derived'``. They are good
enough to rank crops against each other; they are not a substitute for a
laboratory test, and the API says so.
"""

import logging

from django.core.cache import cache

from .http import build_session, get_json

logger = logging.getLogger(__name__)

SOILGRIDS_URL = 'https://rest.isric.org/soilgrids/v2.0/properties/query'
DEPTH = '0-5cm'
CACHE_TIMEOUT = 60 * 60 * 24 * 30  # soil properties are effectively static
# ~110 m at the equator: finer than the 250 m source raster, so rounding to
# three decimals never merges cells that SoilGrids itself distinguishes.
COORD_PRECISION = 3

PROPERTIES = ('phh2o', 'nitrogen', 'soc', 'cec', 'clay', 'sand', 'wv0033')

# SoilGrids ships integers; each layer declares the divisor that converts them
# back to the conventional unit.
_FALLBACK_D_FACTOR = {
    'phh2o': 10,     # -> pH
    'nitrogen': 100,  # -> g/kg
    'soc': 10,       # -> g/kg
    'cec': 10,       # -> cmol(c)/kg
    'clay': 10,      # -> %
    'sand': 10,      # -> %
    'wv0033': 10,    # -> volumetric %
}

_session = build_session('FavorableSoil/1.0 (agricultural analysis)')


def _cache_key(lat, lon):
    return f'soilgrids:v2:{round(lat, COORD_PRECISION)}:{round(lon, COORD_PRECISION)}'


QUANTILES = ('mean', 'Q0.05', 'Q0.95')


def _extract_layers(payload):
    """Flatten the SoilGrids response into ``{property: value_in_real_units}``.

    Also collects the 5th and 95th percentiles SoilGrids publishes for every
    property into ``_ranges``: ``{property: (low, high)}``. A number without
    its uncertainty looks like a measurement; with it, it looks like what it
    is -- a model prediction at 250 m.
    """
    values = {}
    ranges = {}
    layers = (payload or {}).get('properties', {}).get('layers', []) or []

    for layer in layers:
        name = layer.get('name')
        if name not in PROPERTIES:
            continue

        d_factor = (layer.get('unit_measure') or {}).get('d_factor')
        if not d_factor:
            d_factor = _FALLBACK_D_FACTOR.get(name, 1)

        for depth in layer.get('depths', []) or []:
            if depth.get('label') != DEPTH:
                continue
            quantiles = depth.get('values') or {}
            raw = quantiles.get('mean')
            if raw is None:
                continue
            values[name] = raw / d_factor

            low, high = quantiles.get('Q0.05'), quantiles.get('Q0.95')
            if low is not None and high is not None:
                ranges[name] = (low / d_factor, high / d_factor)

    values['_ranges'] = ranges
    return values


def _range(ranges, name, digits=1):
    span = ranges.get(name)
    if span is None:
        return None
    return [round(span[0], digits), round(span[1], digits)]


def _available_nitrogen_mg_per_kg(total_n_g_per_kg):
    """Total N (g/kg) -> plant-available mineral N (mg/kg).

    Mineral nitrogen is typically 1-3% of total N in the topsoil; 2% is the
    usual working figure. The crop thresholds in ``CropType`` are expressed in
    available N, so the conversion has to happen somewhere -- doing it here
    keeps the units honest.
    """
    return round(total_n_g_per_kg * 1000.0 * 0.02, 1)


def _exchangeable_potassium_mg_per_kg(cec_cmol_per_kg):
    """Estimate exchangeable K (mg/kg) from CEC.

    Potassium usually occupies 2-5% of exchange sites; 3% is used here.
    1 cmol(c)/kg of K equals 391 mg/kg (39.1 g/mol, one charge).
    """
    return round(cec_cmol_per_kg * 0.03 * 391.0, 1)


def _available_phosphorus_mg_per_kg(soc_g_per_kg, clay_percent):
    """Rough Olsen-P estimate from organic carbon and texture.

    Phosphorus is the weakest of the three: it depends heavily on fertiliser
    history, which no global raster knows. Organic matter mineralisation is the
    dominant natural source, and heavy clays fix more P, so both terms appear.
    Clamped to a sane agronomic range.
    """
    estimate = 4.0 + soc_g_per_kg * 1.1 - max(0.0, clay_percent - 30.0) * 0.15
    return round(min(60.0, max(3.0, estimate)), 1)


def _texture_label(clay, sand):
    if clay is None or sand is None:
        return None
    if clay >= 40:
        return 'Глинистая'
    if sand >= 70:
        return 'Песчаная'
    if clay >= 27:
        return 'Суглинок тяжёлый'
    if sand >= 52:
        return 'Супесь'
    return 'Суглинок'


def fetch_soil_properties(lat, lon):
    """Return soil properties for a point, or ``None`` if unavailable.

    The result is a dict of ``{name: {'value': float, 'unit': str,
    'source': 'measured'|'derived'}}`` plus provider metadata.
    """
    key = _cache_key(lat, lon)
    cached = cache.get(key)
    if cached is not None:
        return cached or None  # empty dict is a cached failure

    params = [('lon', lon), ('lat', lat), ('depth', DEPTH)]
    params += [('value', quantile) for quantile in QUANTILES]
    params += [('property', name) for name in PROPERTIES]

    payload = get_json(_session, SOILGRIDS_URL, params=params,
                       timeout=15, service='SoilGrids')
    layers = _extract_layers(payload)
    ranges = layers.get('_ranges', {})

    if 'phh2o' not in layers:
        # Oceans, ice sheets and service outages all land here.
        logger.info('SoilGrids has no topsoil data for %.4f, %.4f', lat, lon)
        cache.set(key, {}, 60 * 60)  # short negative cache
        return None

    ph = round(layers['phh2o'], 1)
    soc = layers.get('soc')
    cec = layers.get('cec')
    clay = layers.get('clay')
    sand = layers.get('sand')

    result = {
        'ph': {'value': ph, 'unit': 'pH', 'source': 'measured',
               'range': _range(ranges, 'phh2o')},
        'texture': {'value': _texture_label(clay, sand), 'unit': None, 'source': 'measured'},
        'organic_carbon': {
            'value': round(soc, 1) if soc is not None else None,
            'unit': 'г/кг', 'source': 'measured', 'range': _range(ranges, 'soc'),
        },
        'cec': {
            'value': round(cec, 1) if cec is not None else None,
            'unit': 'cmol(c)/кг', 'source': 'measured', 'range': _range(ranges, 'cec'),
        },
        'clay_percent': {
            'value': round(clay, 1) if clay is not None else None,
            'unit': '%', 'source': 'measured', 'range': _range(ranges, 'clay'),
        },
        'sand_percent': {
            'value': round(sand, 1) if sand is not None else None,
            'unit': '%', 'source': 'measured', 'range': _range(ranges, 'sand'),
        },
        'water_holding_capacity': {
            'value': round(layers['wv0033'], 1) if 'wv0033' in layers else None,
            'unit': '% объёма', 'source': 'measured', 'range': _range(ranges, 'wv0033'),
        },
        'provider': 'ISRIC SoilGrids v2.0',
        'depth': DEPTH,
        'resolution_m': 250,
    }

    if 'nitrogen' in layers:
        result['nitrogen'] = {
            'value': _available_nitrogen_mg_per_kg(layers['nitrogen']),
            'unit': 'мг/кг', 'source': 'derived',
            'note': 'Доступный азот, оценён как 2% от общего N по SoilGrids',
        }
    else:
        result['nitrogen'] = {'value': None, 'unit': 'мг/кг', 'source': 'unavailable'}

    if cec is not None:
        result['potassium'] = {
            'value': _exchangeable_potassium_mg_per_kg(cec),
            'unit': 'мг/кг', 'source': 'derived',
            'note': 'Обменный калий, оценён как 3% от ёмкости катионного обмена',
        }
    else:
        result['potassium'] = {'value': None, 'unit': 'мг/кг', 'source': 'unavailable'}

    if soc is not None:
        result['phosphorus'] = {
            'value': _available_phosphorus_mg_per_kg(soc, clay or 0.0),
            'unit': 'мг/кг', 'source': 'derived',
            'note': 'Грубая оценка по органическому углероду и текстуре; '
                    'фактическое значение зависит от истории удобрений',
        }
    else:
        result['phosphorus'] = {'value': None, 'unit': 'мг/кг', 'source': 'unavailable'}

    cache.set(key, result, CACHE_TIMEOUT)
    return result


def estimate_current_moisture(water_holding_capacity, precipitation_7d_mm):
    """Estimate topsoil moisture (% of volume) from capacity and recent rain.

    Neither input alone is enough: field capacity says how much water the soil
    *can* hold, recent precipitation says how much arrived. The blend below is
    a coarse bucket model -- 25 mm over a week is treated as enough to reach
    field capacity, and a floor of 40% of capacity represents residual moisture
    after a dry week.

    Returns ``None`` when capacity is unknown, so the caller can say "нет
    данных" instead of guessing.
    """
    if water_holding_capacity is None:
        return None

    rain = max(0.0, precipitation_7d_mm or 0.0)
    wetness = min(1.0, rain / 25.0)
    return round(water_holding_capacity * (0.4 + 0.6 * wetness), 1)


# ---------------------------------------------------------------------------
# Soil quality score
# ---------------------------------------------------------------------------
# Each factor maps a measured property onto [0, 1] with a documented agronomic
# rule; the score is the weighted mean over the factors that have data. This
# is the "soil" half of the fertility map -- the vegetation half comes from
# multi-season NDVI -- and every factor is returned so the UI can show what
# went into the number.
_FACTOR_WEIGHTS = {'ph': 0.30, 'organic_carbon': 0.30, 'cec': 0.25, 'texture': 0.15}


def _ph_factor(ph):
    """1.0 across the 6.0-7.5 optimum, falling linearly to 0 at 4.5 and 9.0."""
    if ph is None:
        return None
    if 6.0 <= ph <= 7.5:
        return 1.0
    if ph < 6.0:
        return max(0.0, (ph - 4.5) / 1.5)
    return max(0.0, (9.0 - ph) / 1.5)


def _carbon_factor(soc_g_per_kg):
    """20 g/kg organic carbon (~3.4% organic matter) counts as fully supplied."""
    if soc_g_per_kg is None:
        return None
    return max(0.0, min(1.0, soc_g_per_kg / 20.0))


def _cec_factor(cec_cmol_per_kg):
    """25 cmol(c)/kg is a good nutrient-retention capacity for cropland."""
    if cec_cmol_per_kg is None:
        return None
    return max(0.0, min(1.0, cec_cmol_per_kg / 25.0))


def _texture_factor(clay, sand):
    """Loams score 1; very sandy soils drain and leach, very heavy clays waterlog."""
    if clay is None or sand is None:
        return None
    if sand >= 70:
        return 0.4
    if clay >= 60:
        return 0.6
    if sand >= 52 or clay >= 40:
        return 0.8
    return 1.0


def soil_quality_score(properties):
    """Score in [0, 1] from SoilGrids properties, plus the factors behind it.

    Returns ``(score_or_None, factors)`` where ``factors`` is a dict of
    ``{name: {'value': ..., 'factor': ..., 'weight': ...}}``. ``None`` when no
    factor could be evaluated.
    """
    if not properties:
        return None, {}

    def value(name):
        entry = properties.get(name)
        return entry.get('value') if isinstance(entry, dict) else None

    clay = value('clay_percent')
    sand = value('sand_percent')
    raw = {
        'ph': (value('ph'), _ph_factor(value('ph'))),
        'organic_carbon': (value('organic_carbon'), _carbon_factor(value('organic_carbon'))),
        'cec': (value('cec'), _cec_factor(value('cec'))),
        'texture': (value('texture'), _texture_factor(clay, sand)),
    }

    factors = {}
    weighted = 0.0
    weight_sum = 0.0
    for name, (measured, factor) in raw.items():
        if factor is None:
            continue
        weight = _FACTOR_WEIGHTS[name]
        factors[name] = {'value': measured, 'factor': round(factor, 2), 'weight': weight}
        weighted += factor * weight
        weight_sum += weight

    if weight_sum == 0:
        return None, {}
    return round(weighted / weight_sum, 3), factors
