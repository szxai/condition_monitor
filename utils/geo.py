"""
地理计算工具
"""
import math
from typing import Tuple


EARTH_RADIUS_M = 6371000.0


def haversine_distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """计算两点之间的大圆距离（单位：米）"""
    lon1_rad, lat1_rad = math.radians(lon1), math.radians(lat1)
    lon2_rad, lat2_rad = math.radians(lon2), math.radians(lat2)

    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad

    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_M * c


def midpoint(point_a: Tuple[float, float], point_b: Tuple[float, float]) -> Tuple[float, float]:
    """计算两个经纬度点的中点"""
    return ((point_a[0] + point_b[0]) / 2.0, (point_a[1] + point_b[1]) / 2.0)

