"""
工况定义数据模型
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class GPSPoint:
    """GPS坐标点（带边界范围）"""
    lon_lb: float  # 经度下限
    lon_ub: float  # 经度上限
    lat_lb: float  # 纬度下限
    lat_ub: float  # 纬度上限

    def contains(self, lon: float, lat: float) -> bool:
        """判断GPS坐标是否在此范围内，增加极小的容差处理浮点数精度问题"""
        # 添加一个微小的容差(约5米左右)，避免浮点数在边界上的跳动，并降低精度要求
        tol = 0.00005
        return (self.lon_lb - tol <= lon <= self.lon_ub + tol and
                self.lat_lb - tol <= lat <= self.lat_ub + tol)

    @property
    def center(self) -> Tuple[float, float]:
        """获取范围中心点"""
        return ((self.lon_lb + self.lon_ub) / 2.0,
                (self.lat_lb + self.lat_ub) / 2.0)


@dataclass
class PathCheckpoint:
    """路径关键点（可按顺序经过）"""
    name: str
    zone: GPSPoint
    required: bool = True  # 是否必须经过
    hint_text: str = ""  # 默认操作提示
    lap_hints: Dict[int, str] = field(default_factory=dict)  # 分圈操作提示


@dataclass
class LoopZone:
    """需要在指定区域内重复进入的区域"""
    name: str
    zone: GPSPoint
    required_entries: int = 1  # 需要进入的次数（计圈）
    hint_text: str = ""  # 默认操作提示
    lap_hints: Dict[int, str] = field(default_factory=dict)  # 分圈操作提示


@dataclass
class ConditionDefinition:
    """工况定义"""
    condition_name: str  # 工况名称
    description: str
    ref_time_min: float  # 参考时间最小值（秒）
    ref_time: float  # 参考时间（秒）
    ref_time_max: float  # 参考时间最大值（秒）
    start: GPSPoint  # 开始点
    end: GPSPoint  # 结束点
    checkpoints: List[PathCheckpoint] = field(default_factory=list)  # 按顺序必经点
    loop_zones: List[LoopZone] = field(default_factory=list)  # 需要重复进入的区域
    forbidden_zones: List[GPSPoint] = field(default_factory=list)  # 必不经过区域
    prestart_hint: str = ""  # 起点前提示
    prestart_lap_hints: Dict[int, str] = field(default_factory=dict)  # 起点前分圈提示
    required_laps: int = 1  # 完成所需的进出次数（整条路线圈数）
    skip_distance_threshold_m: float = 200.0  # 自动跳过的距离阈值
    skip_time_threshold_s: float = 30.0  # 自动跳过的时间阈值
    priority: int = 0  # 调度优先级（越大越优先）
    group: Optional[str] = None  # 工况分组标签，可用于调度

    def __post_init__(self):
        """验证数据有效性"""
        if self.ref_time_min > self.ref_time or self.ref_time > self.ref_time_max:
            raise ValueError(f"工况 {self.condition_name} 的时间参数无效")

        self._validate_point("Start", self.start)
        self._validate_point("End", self.end)

        for checkpoint in self.checkpoints:
            self._validate_point(checkpoint.name, checkpoint.zone)

        for loop_zone in self.loop_zones:
            if loop_zone.required_entries <= 0:
                raise ValueError(f"工况 {self.condition_name} 的循环区域 {loop_zone.name} 的次数必须为正数")
            self._validate_point(loop_zone.name, loop_zone.zone)

        for idx, zone in enumerate(self.forbidden_zones, start=1):
            self._validate_point(f"ForbiddenZone{idx}", zone)

        if self.required_laps <= 0:
            raise ValueError(f"工况 {self.condition_name} 的圈数必须为正数")
        if self.skip_distance_threshold_m <= 0:
            raise ValueError(f"工况 {self.condition_name} 的跳过距离阈值必须为正数")
        if self.skip_time_threshold_s <= 0:
            raise ValueError(f"工况 {self.condition_name} 的跳过时间阈值必须为正数")

    @staticmethod
    def _validate_point(name: str, point: GPSPoint):
        if point.lon_lb > point.lon_ub or point.lat_lb > point.lat_ub:
            raise ValueError(f"{name} 点范围无效")

