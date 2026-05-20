import math
import requests
import cv2
import numpy as np
from io import BytesIO
from PIL import Image

def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)

def download_tile(x, y, z):
    url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        if response.status_code == 200:
            return Image.open(BytesIO(response.content))
    except Exception as e:
        pass
    return None

def num2deg(xtile, ytile, zoom):
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return (lat_deg, lon_deg)

def fetch_satellite_image(bbox, zoom=14):
    min_lon, min_lat, max_lon, max_lat = bbox
    
    xtile_min, ytile_min = deg2num(max_lat, min_lon, zoom)
    xtile_max, ytile_max = deg2num(min_lat, max_lon, zoom)
    
    xs = range(xtile_min, xtile_max + 1)
    ys = range(ytile_min, ytile_max + 1)
    
    tile_width, tile_height = 256, 256
    full_width = len(xs) * tile_width
    full_height = len(ys) * tile_height
    
    full_image = Image.new('RGB', (full_width, full_height))
    
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            tile = download_tile(x, y, zoom)
            if tile:
                full_image.paste(tile, (i * tile_width, j * tile_height))
    
    lat_max_final, lon_min_final = num2deg(xtile_min, ytile_min, zoom)
    lat_min_final, lon_max_final = num2deg(xtile_max + 1, ytile_max + 1, zoom)
    
    actual_bounds = [[lat_min_final, lon_min_final], [lat_max_final, lon_max_final]]
                
    return np.array(full_image), actual_bounds