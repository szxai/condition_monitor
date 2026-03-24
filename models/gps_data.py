"""
GPS数据模型
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class GPSData:
    """GPS数据点"""
    timestamp: datetime  # 时间戳
    longitude: float  # 经度
    latitude: float  # 纬度
    altitude: Optional[float] = None  # 海拔（可选）
    speed: Optional[float] = None  # 速度（可选）
    heading: Optional[float] = None  # 航向（可选）
    
    def __post_init__(self):
        """验证GPS数据有效性"""
        if not (-180 <= self.longitude <= 180):
            raise ValueError(f"经度值无效: {self.longitude}")
        if not (-90 <= self.latitude <= 90):
            raise ValueError(f"纬度值无效: {self.latitude}")

