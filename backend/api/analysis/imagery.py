"""Shared image primitives for the analysis pipelines."""

import base64
import logging

import cv2
import numpy as np
from utils.tiles import TileFetchError, fetch_satellite_image

logger = logging.getLogger(__name__)


class AnalysisError(RuntimeError):
    """An analysis could not be completed. The message is user-facing."""


def load_imagery(bbox, zoom):
    """Fetch the mosaic for ``bbox``, converting fetch failures into AnalysisError."""
    try:
        return fetch_satellite_image(bbox, zoom=zoom)
    except TileFetchError as exc:
        raise AnalysisError(str(exc)) from exc


def encode_overlay(rgba):
    """Encode an RGBA overlay as a PNG data URI."""
    bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
    ok, buffer = cv2.imencode('.png', bgra)
    if not ok:
        raise AnalysisError('Не удалось сформировать изображение результата')
    return 'data:image/png;base64,' + base64.b64encode(buffer).decode('ascii')


def excess_green_index(rgb):
    """Normalised Excess Green (ExG) in ``[-1, 1]``.

    This is NOT NDVI. NDVI needs a near-infrared band; the basemap here is
    ordinary RGB imagery, so the best available proxy for vegetation vigour is
    the excess-green index. It correlates with green cover but saturates early
    and cannot distinguish healthy from stressed vegetation the way NDVI does.
    Every caller surfaces this distinction to the user.
    """
    red = rgb[:, :, 0].astype(np.float32)
    green = rgb[:, :, 1].astype(np.float32)
    blue = rgb[:, :, 2].astype(np.float32)

    numerator = 2.0 * green - red - blue
    denominator = 2.0 * green + red + blue + 1e-6
    return np.clip(numerator / denominator, -1.0, 1.0)


def local_variance(rgb, kernel=7):
    """Local intensity variance -- a cheap texture measure."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    mean = cv2.blur(gray, (kernel, kernel))
    mean_of_squares = cv2.blur(gray ** 2, (kernel, kernel))
    return np.maximum(mean_of_squares - mean ** 2, 0.0)


def water_mask(rgb):
    """Open water: blue-dominant *and* smooth.

    The colour test alone also catches asphalt, roofs and deep shadow, which is
    how a scene over central Tashkent previously came back 21% "water". Water
    bodies are texturally flat, so requiring low local variance removes most of
    the urban false positives.
    """
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    blue = cv2.inRange(hsv, np.array([90, 40, 40]), np.array([140, 255, 255])) > 0
    very_dark = cv2.inRange(hsv, np.array([0, 0, 0]), np.array([180, 255, 45])) > 0

    smooth = local_variance(rgb) < 80.0
    return (blue | very_dark) & smooth


def paint(rgba, mask, colour):
    rgba[mask] = colour


def percentage(count, total):
    return round(float(count) / total * 100.0, 2) if total else 0.0


def upsample_grid(grid, shape):
    """Expand a coarse per-cell grid to full image resolution."""
    height, width = shape
    return cv2.resize(
        grid.astype(np.float32), (width, height), interpolation=cv2.INTER_NEAREST
    )
