"""
工况定义解析器
"""
import csv
from pathlib import Path
from typing import List, Optional

from models.condition import ConditionDefinition, GPSPoint, PathCheckpoint, LoopZone

DEFAULT_SKIP_DISTANCE_M = 200.0
DEFAULT_SKIP_TIME_S = 30.0
MAX_DYNAMIC_POINTS = 20


class ConditionParser:
    """解析CSV文件中的工况定义"""

    @staticmethod
    def parse_csv(file_path: str) -> List[ConditionDefinition]:
        """
        解析工况定义CSV文件

        Args:
            file_path: CSV文件路径

        Returns:
            工况定义列表
        """
        conditions: List[ConditionDefinition] = []
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"工况定义文件不存在: {file_path}")

        # 尝试多种编码打开文件
        encodings = ['utf-8', 'gbk', 'utf-8-sig', 'cp936']
        f = None
        encoding_used = 'utf-8'
        
        for enc in encodings:
            try:
                f = open(file_path, 'r', encoding=enc)
                # 尝试读取并解析 CSV 头，验证编码有效性
                csv.DictReader(f).fieldnames
                f.seek(0)
                encoding_used = enc
                break
            except (UnicodeDecodeError, csv.Error):
                if f: 
                    f.close()
                    f = None
                continue
        
        if not f:
            # 如果所有尝试都失败，回退到忽略错误模式
            print(f"警告: 无法自动检测编码，尝试使用 utf-8 (errors='replace')")
            f = open(file_path, 'r', encoding='utf-8', errors='replace')

        with f:
            reader = csv.DictReader(f)
            
            for row in reader:
                try:
                    condition = ConditionParser._parse_row(row)
                    
                    # 动态处理类似 TW-1, TW-2 这种变体名称，将它们统一归类为 TW
                    # 但是保留它们各自不同的坐标数据，这样程序就能通过 CompositeConditionMonitor
                    # 自动把它们组合起来。
                    raw_name = condition.condition_name
                    
                    # 动态处理类似 TW-1, TW-2, D16-1, D16-2 这种变体名称，将它们统一归类为基础名称
                    # 但是保留它们各自不同的坐标数据，这样程序就能通过 CompositeConditionMonitor
                    # 自动把它们组合起来。
                    # 注意：如果名称中包含多个 '-' (比如 A-B-1)，我们只剥离最后的数字部分
                    # 例如 D16-1 变为 D16, D13-2 变为 D13
                    import re
                    # 匹配以 "-数字" 结尾的名称
                    match = re.search(r'-\d+$', raw_name)
                    if match:
                        base_name = raw_name[:match.start()]
                        # 将名称强制修改为基础名称（如 D16-1 变为 D16）
                        condition.condition_name = base_name
                        # 可以在描述里保留原始名称以供调试区分
                        if not condition.description:
                            condition.description = raw_name
                            
                    conditions.append(condition)
                except (ValueError, KeyError) as exc:
                    print(f"警告: 跳过无效行 {row.get('Condition', 'Unknown')}: {exc}")
                    continue

        return conditions

    @staticmethod
    def _parse_row(row: dict) -> ConditionDefinition:
        """解析单行数据"""
        condition_name = (row.get('Condition') or '').strip()
        if not condition_name:
            raise ValueError("缺少 Condition 列")

        description = (row.get('Description') or '').strip()

        ref_time_min = ConditionParser._to_float(row.get('Ref_Time_Min'), 'Ref_Time_Min')
        ref_time = ConditionParser._to_float(row.get('Ref_Time'), 'Ref_Time')
        ref_time_max = ConditionParser._to_float(row.get('Ref_Time_Max'), 'Ref_Time_Max')

        start = ConditionParser._parse_point(row, 'Start')
        end = ConditionParser._parse_point(row, 'End')

        checkpoints = ConditionParser._parse_checkpoints(row)
        loop_zones = ConditionParser._parse_loop_zones(row)
        forbidden_zones = ConditionParser._parse_forbidden_zones(row)

        skip_distance = ConditionParser._to_float(
            row.get('SkipDistanceThresholdM'),
            'SkipDistanceThresholdM',
            default=DEFAULT_SKIP_DISTANCE_M
        )
        skip_time = ConditionParser._to_float(
            row.get('SkipTimeThresholdS'),
            'SkipTimeThresholdS',
            default=DEFAULT_SKIP_TIME_S
        )
        priority = ConditionParser._to_int(row.get('Priority'), default=0)
        group = (row.get('Group') or '').strip() or None
        required_laps = ConditionParser._to_int(
            row.get('RequiredLaps') or row.get('LapCount'),
            default=1
        )

        return ConditionDefinition(
            condition_name=condition_name,
            description=description,
            ref_time_min=ref_time_min,
            ref_time=ref_time,
            ref_time_max=ref_time_max,
            start=start,
            end=end,
            checkpoints=checkpoints,
            loop_zones=loop_zones,
            forbidden_zones=forbidden_zones,
            required_laps=required_laps,
            skip_distance_threshold_m=skip_distance,
            skip_time_threshold_s=skip_time,
            priority=priority,
            group=group
        )

    @staticmethod
    def _parse_checkpoints(row: dict) -> List[PathCheckpoint]:
        checkpoints: List[PathCheckpoint] = []

        legacy_prefixes = ['Feature1', 'Feature2', 'Feature3']
        for prefix in legacy_prefixes:
            point = ConditionParser._parse_point_optional(row, prefix)
            if point:
                checkpoints.append(PathCheckpoint(name=prefix, zone=point, required=True))

        dynamic_prefixes = []
        dynamic_prefixes += ConditionParser._collect_dynamic_prefixes(row, 'Waypoint')
        dynamic_prefixes += ConditionParser._collect_dynamic_prefixes(row, 'Via')
        dynamic_prefixes += ConditionParser._collect_dynamic_prefixes(row, 'Checkpoint')

        for prefix in dynamic_prefixes:
            point = ConditionParser._parse_point_optional(row, prefix)
            if point:
                required_key = f'{prefix}_Required'
                required = ConditionParser._to_bool(row.get(required_key), default=True)
                checkpoints.append(PathCheckpoint(name=prefix, zone=point, required=required))

        return checkpoints

    @staticmethod
    def _parse_forbidden_zones(row: dict) -> List[GPSPoint]:
        zones: List[GPSPoint] = []

        feature4 = ConditionParser._parse_point_optional(row, 'Feature4')
        if feature4:
            zones.append(feature4)

        for prefix in ConditionParser._collect_dynamic_prefixes(row, 'Forbidden'):
            point = ConditionParser._parse_point_optional(row, prefix)
            if point:
                zones.append(point)

        for prefix in ConditionParser._collect_dynamic_prefixes(row, 'Exclude'):
            point = ConditionParser._parse_point_optional(row, prefix)
            if point:
                zones.append(point)

        return zones

    @staticmethod
    def _parse_loop_zones(row: dict) -> List[LoopZone]:
        loop_zones: List[LoopZone] = []
        for prefix in ConditionParser._collect_dynamic_prefixes(row, 'LoopZone'):
            point = ConditionParser._parse_point_optional(row, prefix)
            if not point:
                continue
            count_value = row.get(f'{prefix}_Count')
            if count_value is None:
                count_value = row.get(f'{prefix}_Entries')
            required_entries = ConditionParser._to_int(count_value, default=1)
            loop_zones.append(
                LoopZone(
                    name=prefix,
                    zone=point,
                    required_entries=max(required_entries, 1)
                )
            )
        return loop_zones

    @staticmethod
    def _collect_dynamic_prefixes(row: dict, base_name: str) -> List[str]:
        prefixes: List[str] = []
        for idx in range(1, MAX_DYNAMIC_POINTS + 1):
            candidates = [f"{base_name}{idx}", f"{base_name}{idx:02d}"]
            found = None
            for candidate in candidates:
                if ConditionParser._has_point_columns(row, candidate):
                    found = candidate
                    break
            if found:
                prefixes.append(found)
        return prefixes

    @staticmethod
    def _parse_point(row: dict, prefix: str) -> GPSPoint:
        """解析必需GPS点"""
        point = ConditionParser._parse_point_optional(row, prefix)
        if not point:
            raise KeyError(f"缺少 {prefix} 的坐标定义")
        return point

    @staticmethod
    def _parse_point_optional(row: dict, prefix: str) -> Optional[GPSPoint]:
        """解析可选GPS点"""
        lon_lb_key = f'{prefix}_LonLB'
        lon_ub_key = f'{prefix}_LonUB'
        lat_lb_key = f'{prefix}_LatLB'
        lat_ub_key = f'{prefix}_LatUB'

        keys = [lon_lb_key, lon_ub_key, lat_lb_key, lat_ub_key]
        if not all(key in row for key in keys):
            return None

        values = []
        for key in keys:
            raw = row.get(key)
            if raw is None:
                return None
            text = str(raw).strip()
            if not text:
                return None
            try:
                values.append(float(text))
            except ValueError as exc:
                raise ValueError(f"{prefix} 的字段 {key} 不是数字: {raw}") from exc

        return GPSPoint(
            lon_lb=values[0],
            lon_ub=values[1],
            lat_lb=values[2],
            lat_ub=values[3]
        )

    @staticmethod
    def _has_point_columns(row: dict, prefix: str) -> bool:
        """判断是否存在完整的坐标列"""
        required_keys = [
            f'{prefix}_LonLB',
            f'{prefix}_LonUB',
            f'{prefix}_LatLB',
            f'{prefix}_LatUB'
        ]
        if not all(key in row for key in required_keys):
            return False

        values = [str(row[key]).strip() for key in required_keys if row.get(key) is not None]
        return any(values)

    @staticmethod
    def _to_float(value, field_name: str, default: Optional[float] = None) -> float:
        if value is None or str(value).strip() == '':
            if default is not None:
                return default
            raise ValueError(f"{field_name} 缺失")
        try:
            return float(str(value).strip())
        except ValueError as exc:
            raise ValueError(f"{field_name} 非法: {value}") from exc

    @staticmethod
    def _to_int(value, default: int = 0) -> int:
        if value is None or str(value).strip() == '':
            return default
        try:
            return int(float(str(value).strip()))
        except ValueError as exc:
            raise ValueError(f"整数值非法: {value}") from exc

    @staticmethod
    def _to_bool(value, default: bool = True) -> bool:
        if value is None:
            return default
        text = str(value).strip().lower()
        if not text:
            return default
        if text in ('false', '0', 'no', 'n'):
            return False
        if text in ('true', '1', 'yes', 'y'):
            return True
        return default

