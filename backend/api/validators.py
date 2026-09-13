"""Validation helpers for user supplied geographic input.

Every analysis endpoint receives a ``bbox`` straight from the browser. Without
validation a single request can ask the backend to stitch together millions of
satellite tiles, so the parsing here is deliberately strict.
"""

import math

# Web Mercator is undefined beyond these latitudes.
MAX_MERCATOR_LAT = 85.05112878


class BBoxError(ValueError):
    """Raised when a client supplied bounding box cannot be used."""


def parse_bbox(raw):
    """Validate and normalise ``[min_lon, min_lat, max_lon, max_lat]``.

    Returns a tuple of floats. Raises :class:`BBoxError` with a message that is
    safe to show to the user.
    """
    if raw is None:
        raise BBoxError('Не передан параметр bbox')

    if isinstance(raw, str):
        parts = [part for part in raw.replace(' ', '').split(',') if part]
    elif isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        raise BBoxError('bbox должен быть массивом из 4 чисел')

    if len(parts) != 4:
        raise BBoxError('bbox должен содержать ровно 4 значения: [запад, юг, восток, север]')

    try:
        min_lon, min_lat, max_lon, max_lat = (float(value) for value in parts)
    except (TypeError, ValueError) as exc:
        raise BBoxError('Координаты bbox должны быть числами') from exc

    for value in (min_lon, min_lat, max_lon, max_lat):
        if not math.isfinite(value):
            raise BBoxError('Координаты bbox содержат недопустимое значение')

    if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
        raise BBoxError('Долгота должна быть в диапазоне от -180 до 180')

    if not (-MAX_MERCATOR_LAT <= min_lat <= MAX_MERCATOR_LAT
            and -MAX_MERCATOR_LAT <= max_lat <= MAX_MERCATOR_LAT):
        raise BBoxError(
            f'Широта должна быть в диапазоне от -{MAX_MERCATOR_LAT:.2f} до {MAX_MERCATOR_LAT:.2f}'
        )

    if min_lon >= max_lon or min_lat >= max_lat:
        raise BBoxError('Некорректный bbox: запад/юг должны быть меньше востока/севера')

    # A box this large is never a field; it is either a bug on the client or an
    # attempt to make the server download the whole planet.
    if (max_lon - min_lon) > 10.0 or (max_lat - min_lat) > 10.0:
        raise BBoxError('Выбранная область слишком велика. Приблизьте карту и повторите анализ.')

    return (min_lon, min_lat, max_lon, max_lat)


def tile_span(bbox, zoom):
    """How many tiles in x and y a bbox covers at ``zoom``."""
    from utils.tiles import deg2num

    min_lon, min_lat, max_lon, max_lat = bbox
    x_min, y_min = deg2num(max_lat, min_lon, zoom)
    x_max, y_max = deg2num(min_lat, max_lon, zoom)
    return (x_max - x_min + 1), (y_max - y_min + 1)


def choose_zoom(bbox, preferred_zoom, max_tiles):
    """Pick the highest zoom <= ``preferred_zoom`` that stays within the budget.

    Zooming out is far better UX than refusing the request: the user still gets
    an answer, just at a coarser resolution.
    """
    zoom = int(preferred_zoom)
    while zoom > 0:
        cols, rows = tile_span(bbox, zoom)
        if cols * rows <= max_tiles:
            return zoom
        zoom -= 1
    return 0


def metres_per_pixel(latitude, zoom):
    """Ground resolution of one 256px web-mercator tile pixel.

    Scale depends on both zoom and latitude, so a hardcoded constant is wrong
    everywhere except the equator.
    """
    equator_circumference = 40075016.686
    return (equator_circumference * math.cos(math.radians(latitude))) / (256.0 * (2 ** zoom))
