"""
工况状态监控核心逻辑
"""
from enum import Enum
from datetime import datetime
from typing import Dict, List, Optional

from models.condition import ConditionDefinition
from models.gps_data import GPSData
from utils.geo import haversine_distance_m
from utils.logger import logger


class ConditionState(Enum):
    """工况状态枚举"""
    NOT_STARTED = "未开始"
    IN_PROGRESS = "进行中"
    COMPLETING = "完成确认中"
    COMPLETED = "已完成"
    MANUAL_COMPLETED = "人工完成"
    FAILED = "失败"
    SKIPPED = "已跳过"


class ConditionMonitor:
    """单个工况监控器"""

    def __init__(self, condition: ConditionDefinition, task_id: Optional[str] = None):
        self.condition = condition
        self.task_id = task_id  # 任务号
        self.state = ConditionState.NOT_STARTED
        self.start_time: Optional[datetime] = None  # 整体开始时间
        self.end_time: Optional[datetime] = None  # 整体结束时间
        self.last_gps: Optional[GPSData] = None
        self.end_candidate_time: Optional[datetime] = None

        self.required_indices: List[int] = [
            idx for idx, cp in enumerate(condition.checkpoints) if cp.required
        ]
        self._reset_checkpoint_states()
        self._reset_loop_states()

        self.completed_laps = 0
        self.required_laps = condition.required_laps

        self.speed_sum = 0.0
        self.speed_count = 0
        self.speed_max: Optional[float] = None
        self.speed_min: Optional[float] = None
        self.total_distance_m = 0.0
        self.skip_reason: Optional[str] = None
        self.failure_reason: Optional[str] = None
        self.completion_reason: Optional[str] = None

    def restore_state(self, state_data: dict):
        """从保存的数据恢复状态"""
        if not state_data:
            return

        state_str = state_data.get('state')
        state_display = state_data.get('state_display')
        if state_str:
            state_map = {
                'pending': ConditionState.NOT_STARTED,
                'in_progress': ConditionState.IN_PROGRESS,
                'completing': ConditionState.COMPLETING,
                'completed': ConditionState.COMPLETED,
                'manual_completed': ConditionState.MANUAL_COMPLETED,
                'failed': ConditionState.FAILED,
                'skipped': ConditionState.SKIPPED
            }
            if state_str in state_map:
                self.state = state_map[state_str]
        if state_display:
            for s in ConditionState:
                if s.value == state_display:
                    self.state = s
                    break
        
        # 恢复时间
        if state_data.get('start_time'):
            try:
                self.start_time = datetime.fromisoformat(state_data.get('start_time'))
            except: pass
            
        if state_data.get('end_time'):
            try:
                self.end_time = datetime.fromisoformat(state_data.get('end_time'))
            except: pass

        # 恢复圈数
        self.completed_laps = state_data.get('laps_completed', 0)
        
        # 恢复检查点
        saved_checkpoints = state_data.get('checkpoints', [])
        if saved_checkpoints:
            for saved_cp in saved_checkpoints:
                name = saved_cp.get('name')
                if not name:
                    continue
                if saved_cp.get('passed'):
                    self.checkpoint_status[name] = True
                    if saved_cp.get('passed_at'):
                        try:
                            self.checkpoint_pass_time[name] = datetime.fromisoformat(saved_cp.get('passed_at'))
                        except:
                            pass
            self.next_required_pointer = 0
            self._advance_required_pointer()

        # 恢复循环区
        saved_loops = state_data.get('loop_zones', [])
        if saved_loops:
            for saved_loop in saved_loops:
                name = saved_loop.get('name')
                if name in self.loop_zone_counts:
                    self.loop_zone_counts[name] = saved_loop.get('current_entries', self.loop_zone_counts.get(name, 0))
                if name in self.loop_zone_inside and 'is_inside' in saved_loop:
                    self.loop_zone_inside[name] = bool(saved_loop.get('is_inside'))
        
        # 如果状态是进行中，但数据不完整，可能需要重置为NOT_STARTED
        if self.state == ConditionState.IN_PROGRESS and not self.start_time:
             self.state = ConditionState.NOT_STARTED

        # 如果状态是未开始且没有任何圈数，确保所有进度被清除（防止从持久化数据恢复错误的进度）
        if self.state == ConditionState.NOT_STARTED and self.completed_laps == 0:
            self._reset_checkpoint_states()
            self._reset_loop_states()
            self.completed_laps = 0
            self.total_distance_m = 0.0
            self.speed_sum = 0.0
            self.speed_count = 0

    def update(self, gps: GPSData) -> ConditionState:
        """更新工况状态"""
        if self.state in (ConditionState.COMPLETED, ConditionState.SKIPPED, ConditionState.MANUAL_COMPLETED):
            self.last_gps = gps
            return self.state

        # 禁用禁行区域判定
        # if self._violated_forbidden_zone(gps):
        #     self.state = ConditionState.FAILED
        #     self.failure_reason = "进入禁行区域"
        #     self.end_time = gps.timestamp
        #     self.last_gps = gps
        #     return self.state

        if self.state == ConditionState.NOT_STARTED:
            if self.completed_laps >= self.required_laps:
                self.state = ConditionState.COMPLETED
                self.end_time = self.end_time or gps.timestamp
                self.last_gps = gps
                return self.state
            
            # 使用包含稍微放大一点的宽容度来判断，或者至少增加日志以便调试
            if self.condition.start.contains(gps.longitude, gps.latitude):
                # 记录一下触发点，方便调试
                logger.info(f"[{self.condition.condition_name}] 进入起点，触发坐标: {gps.longitude}, {gps.latitude}")
                self.state = ConditionState.IN_PROGRESS
                if not self.start_time:
                    self.start_time = gps.timestamp

        self._update_speed_stats(gps)

        if self.state == ConditionState.IN_PROGRESS:
            self._update_loop_zones(gps)
            self._update_checkpoints(gps)
            if (self._all_required_checkpoints_passed() and
                    self._loop_requirements_met() and
                    self.condition.end.contains(gps.longitude, gps.latitude)):
                self.state = ConditionState.COMPLETING
                self.end_candidate_time = gps.timestamp
                print(self.end_candidate_time)

        elif self.state == ConditionState.COMPLETING:
            # 检查是否已满足时间阈值，不再因为下一帧GPS离开就回退状态
            if self.end_candidate_time and \
                    (gps.timestamp - self.end_candidate_time).total_seconds() >= 0.05:
                self._handle_lap_completion(gps)
            # 如果仍在终点区域，保持COMPLETING状态
            elif self.condition.end.contains(gps.longitude, gps.latitude):
                print(f"调试: 车辆仍在终点区域，保持COMPLETING状态")
                # 不做任何操作，继续保持COMPLETING状态
            # 如果离开终点区域但时间还未达到阈值，仍然保持COMPLETING状态
            # 只有在时间达到阈值后才会处理完成

        self.last_gps = gps
        return self.state

    def mark_skipped(self, reason: str, timestamp: Optional[datetime] = None):
        """标记当前工况被跳过"""
        self.state = ConditionState.SKIPPED
        self.skip_reason = reason
        self.end_time = timestamp or datetime.utcnow()
    
    def mark_completed(self, reason: str, timestamp: Optional[datetime] = None, manual: bool = False):
        """标记当前工况已完成"""
        self.state = ConditionState.MANUAL_COMPLETED if manual else ConditionState.COMPLETED
        self.completion_reason = reason
        self.end_time = timestamp or datetime.utcnow()

    def get_progress_info(self) -> dict:
        """获取工况实时信息"""
        checkpoints_info = [
            {
                'name': cp.name,
                'required': cp.required,
                'hint_text': cp.hint_text,
                'lap_hints': cp.lap_hints,
                'passed': self.checkpoint_status.get(cp.name, False),
                'passed_at': (self.checkpoint_pass_time[cp.name].isoformat()
                              if cp.name in self.checkpoint_pass_time else None)
            }
            for cp in self.condition.checkpoints
        ]

        current_lap = self._get_current_lap_number()
        active_checkpoint = self._get_latest_passed_required_checkpoint()
        next_checkpoint = self._get_next_required_checkpoint()
        next_loop_zone = self._get_next_incomplete_loop_zone()
        operation_hint = ""
        operation_source = ""
        operation_target = ""

        if self.state == ConditionState.NOT_STARTED:
            operation_hint = self._resolve_hint_text(
                self.condition.prestart_hint,
                self.condition.prestart_lap_hints
            )
            operation_source = 'prestart'
            operation_target = 'Start'
        elif next_loop_zone and not next_checkpoint:
            operation_hint = self._resolve_hint_text(next_loop_zone.hint_text, next_loop_zone.lap_hints)
            operation_source = 'loop_zone'
            operation_target = next_loop_zone.name
        elif active_checkpoint:
            operation_hint = self._resolve_hint_text(active_checkpoint.hint_text, active_checkpoint.lap_hints)
            operation_source = 'checkpoint'
            operation_target = active_checkpoint.name
        elif next_checkpoint:
            operation_hint = self._resolve_hint_text(next_checkpoint.hint_text, next_checkpoint.lap_hints)
            operation_source = 'upcoming_checkpoint'
            operation_target = next_checkpoint.name

        info = {
            'condition': self.condition.condition_name,
            'description': self.condition.description,
            'task_id': self.task_id,
            'state': self.state.value,
            'checkpoints': checkpoints_info,
            'laps_completed': self.completed_laps,
            'required_laps': self.required_laps,
            'current_lap': current_lap,
            'operation_hint': operation_hint,
            'operation_hint_source': operation_source,
            'operation_hint_target': operation_target,
            'skip_reason': self.skip_reason,
            'failure_reason': self.failure_reason
        }

        if self.start_time:
            info['start_time'] = self.start_time.isoformat()
        if self.end_time:
            info['end_time'] = self.end_time.isoformat()
        duration = self._get_duration_seconds()
        info['duration_seconds'] = duration
        info['completion_score'] = self._calculate_completion_score(duration)
        if self.last_gps:
            info['last_gps'] = {
                'longitude': self.last_gps.longitude,
                'latitude': self.last_gps.latitude,
                'timestamp': self.last_gps.timestamp.isoformat()
            }

        if self.condition.loop_zones:
            info['loop_zones'] = [
                {
                    'name': zone.name,
                    'required_entries': zone.required_entries,
                    'current_entries': self.loop_zone_counts.get(zone.name, 0),
                    'hint_text': zone.hint_text,
                    'lap_hints': zone.lap_hints
                }
                for zone in self.condition.loop_zones
            ]

        return info

    def get_summary(self) -> dict:
        """返回工况执行总结"""
        duration = self._get_duration_seconds()
        completion_score = self._calculate_completion_score(duration)

        avg_speed = (self.speed_sum / self.speed_count) if self.speed_count else None

        return {
            'condition': self.condition.condition_name,
            'description': self.condition.description,
            'task_id': self.task_id,
            'state': self.state.value,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_seconds': duration,
            'ref_time_min': self.condition.ref_time_min,
            'ref_time_max': self.condition.ref_time_max,
            'completion_score': completion_score,
            'avg_speed_kmh': avg_speed,
            'max_speed_kmh': self.speed_max,
            'min_speed_kmh': self.speed_min,
            'distance_m': self.total_distance_m,
            'checkpoints': self.get_progress_info().get('checkpoints', []),
            'loop_zones': self.get_progress_info().get('loop_zones'),
            'laps_completed': self.completed_laps,
            'required_laps': self.required_laps,
            'skip_reason': self.skip_reason,
            'failure_reason': self.failure_reason
        }

    def _get_duration_seconds(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None

    def _calculate_completion_score(self, duration_seconds: Optional[float]) -> Optional[float]:
        if duration_seconds is None:
            return None

        min_ref = float(self.condition.ref_time_min)
        max_ref = float(self.condition.ref_time_max)
        if min_ref <= duration_seconds <= max_ref:
            return 100.0

        # 超出范围按超出比例扣分，最低0分
        if duration_seconds < min_ref:
            base = max(min_ref, 1e-6)
            ratio = (min_ref - duration_seconds) / base
        else:
            base = max(max_ref, 1e-6)
            ratio = (duration_seconds - max_ref) / base

        score = max(0.0, 100.0 * (1.0 - ratio))
        return round(score, 2)

    def reset(self):
        """重置状态（保留任务ID）"""
        self.state = ConditionState.NOT_STARTED
        self.start_time = None
        self.end_time = None
        self.last_gps = None
        self.end_candidate_time = None
        self._reset_checkpoint_states()
        self._reset_loop_states()
        self.completed_laps = 0
        self.speed_sum = 0.0
        self.speed_count = 0
        self.speed_max = None
        self.speed_min = None
        self.total_distance_m = 0.0
        self.skip_reason = None
        self.failure_reason = None
        self.completion_reason = None
        # task_id 不重置，保留任务标识

    def _update_checkpoints(self, gps: GPSData):
        """检测所有途径点"""
        for idx, checkpoint in enumerate(self.condition.checkpoints):
            if self.checkpoint_status.get(checkpoint.name):
                continue

            if checkpoint.zone.contains(gps.longitude, gps.latitude):
                self.checkpoint_status[checkpoint.name] = True
                self.checkpoint_pass_time[checkpoint.name] = gps.timestamp
                logger.info(f"Task {self.condition.condition_name}: Checkpoint passed - {checkpoint.name} at {gps.timestamp}")
                self._advance_required_pointer()

    def _advance_required_pointer(self):
        while self.next_required_pointer < len(self.required_indices):
            idx = self.required_indices[self.next_required_pointer]
            cp = self.condition.checkpoints[idx]
            if self.checkpoint_status.get(cp.name):
                self.next_required_pointer += 1
            else:
                break

    def _all_required_checkpoints_passed(self) -> bool:
        return self.next_required_pointer >= len(self.required_indices)

    def _violated_forbidden_zone(self, gps: GPSData) -> bool:
        for zone in self.condition.forbidden_zones:
            if zone.contains(gps.longitude, gps.latitude):
                return True
        return False

    def _update_speed_stats(self, gps: GPSData):
        if not self.start_time:
            return

        if not self.last_gps:
            self.last_gps = gps
            return

        time_diff = (gps.timestamp - self.last_gps.timestamp).total_seconds()
        if time_diff <= 0:
            return

        distance = haversine_distance_m(
            self.last_gps.longitude,
            self.last_gps.latitude,
            gps.longitude,
            gps.latitude
        )

        if self.last_gps.timestamp >= self.start_time:
            self.total_distance_m += distance

        speed_kmh = gps.speed
        if speed_kmh is None:
            speed_kmh = (distance / time_diff) * 3.6

        if speed_kmh is not None:
            self.speed_sum += speed_kmh
            self.speed_count += 1
            self.speed_max = speed_kmh if self.speed_max is None else max(self.speed_max, speed_kmh)
            self.speed_min = speed_kmh if self.speed_min is None else min(self.speed_min, speed_kmh)

    def _update_loop_zones(self, gps: GPSData):
        if not self.condition.loop_zones:
            return
        for zone in self.condition.loop_zones:
            inside = zone.zone.contains(gps.longitude, gps.latitude)
            prev_inside = self.loop_zone_inside.get(zone.name, False)
            if inside and not prev_inside:
                self.loop_zone_counts[zone.name] = self.loop_zone_counts.get(zone.name, 0) + 1
            self.loop_zone_inside[zone.name] = inside

    def _loop_requirements_met(self) -> bool:
        for zone in self.condition.loop_zones:
            if self.loop_zone_counts.get(zone.name, 0) < zone.required_entries:
                return False
        return True

    def _handle_lap_completion(self, gps: GPSData):
        self.completed_laps += 1
        if self.completed_laps >= self.required_laps:
            self.state = ConditionState.COMPLETED
            self.end_time = gps.timestamp
        else:
            self._reset_lap_state()
            self.state = ConditionState.NOT_STARTED
        self.end_candidate_time = None

    def _reset_lap_state(self):
        """准备下一圈"""
        self._reset_checkpoint_states()
        self._reset_loop_states()

    def _reset_checkpoint_states(self):
        self.checkpoint_status = {cp.name: False for cp in self.condition.checkpoints}
        self.checkpoint_pass_time = {}
        self.next_required_pointer = 0

    def _reset_loop_states(self):
        self.loop_zone_counts = {zone.name: 0 for zone in self.condition.loop_zones}
        self.loop_zone_inside = {zone.name: False for zone in self.condition.loop_zones}

    def _get_current_lap_number(self) -> int:
        if self.state in (ConditionState.COMPLETED, ConditionState.MANUAL_COMPLETED):
            return max(self.completed_laps, 1)
        return min(self.completed_laps + 1, self.required_laps)

    def _get_next_required_checkpoint(self):
        if self.next_required_pointer >= len(self.required_indices):
            return None
        idx = self.required_indices[self.next_required_pointer]
        return self.condition.checkpoints[idx]

    def _get_latest_passed_required_checkpoint(self):
        if self.next_required_pointer <= 0:
            return None
        idx = self.required_indices[self.next_required_pointer - 1]
        return self.condition.checkpoints[idx]

    def _get_next_incomplete_loop_zone(self):
        for zone in self.condition.loop_zones:
            if self.loop_zone_counts.get(zone.name, 0) < zone.required_entries:
                return zone
        return None

    def _resolve_hint_text(self, default_hint: str, lap_hints: Dict[int, str]) -> str:
        current_lap = self._get_current_lap_number()
        if lap_hints and current_lap in lap_hints and lap_hints[current_lap]:
            return lap_hints[current_lap]
        return default_hint or ""


class CompositeConditionMonitor:
    """组合工况监控器（用于处理同名但不同区域的工况，如TW-1/TW-2统称为TW）"""

    def __init__(self, conditions: List[ConditionDefinition], task_id: Optional[str] = None):
        if not conditions:
            raise ValueError("必须提供至少一个工况定义")
        
        # 创建子监控器
        self.monitors = [ConditionMonitor(cond, task_id) for cond in conditions]
        self.active_monitor: Optional[ConditionMonitor] = None
        
        # 使用第一个工况作为默认信息源
        self.primary_condition = conditions[0]
        self.task_id = task_id
        self.state = ConditionState.NOT_STARTED
        
    @property
    def condition(self):
        """返回当前活动的或主要工况定义"""
        return self.active_monitor.condition if self.active_monitor else self.primary_condition

    @property
    def start_time(self):
        return self.active_monitor.start_time if self.active_monitor else None

    @property
    def end_time(self):
        return self.active_monitor.end_time if self.active_monitor else None

    @property
    def completed_laps(self):
        return self.active_monitor.completed_laps if self.active_monitor else 0
        
    @property
    def required_laps(self):
        return self.primary_condition.required_laps

    @property
    def skip_reason(self):
        return self.active_monitor.skip_reason if self.active_monitor else None

    @property
    def failure_reason(self):
        return self.active_monitor.failure_reason if self.active_monitor else None

    @property
    def completion_reason(self):
        return getattr(self.active_monitor, 'completion_reason', None) if self.active_monitor else None

    def restore_state(self, state_data: dict):
        """恢复状态"""
        if not state_data:
            return
            
        # 根据缓存的描述或名称，尝试精确恢复对应的子监控器
        cached_desc = state_data.get('description', '')
        cached_name = state_data.get('name', '')
        
        target_monitor = None
        for monitor in self.monitors:
            # 如果缓存中的描述匹配了特定的子工况，或者是名称匹配了
            if (cached_desc and monitor.condition.description == cached_desc) or \
               (cached_name and monitor.condition.condition_name == cached_name):
                target_monitor = monitor
                break
                
        # 如果找不到精确匹配，使用第一个
        if not target_monitor and self.monitors:
            target_monitor = self.monitors[0]
            
        if target_monitor:
            target_monitor.restore_state(state_data)
            if target_monitor.state != ConditionState.NOT_STARTED:
                self.active_monitor = target_monitor
                self.state = target_monitor.state
                return
        
        # 如果所有都是未开始，重置
        self.state = ConditionState.NOT_STARTED
        self.active_monitor = None

    def update(self, gps: GPSData) -> ConditionState:
        """更新状态"""
        # 如果当前有活动监控器，一直使用它直到完成或失败
        if self.active_monitor:
            new_state = self.active_monitor.update(gps)
            # 如果活动监控器被重置（回退到 NOT_STARTED 且没有任何圈数进度），我们需要解除锁定，允许重新选择
            if new_state == ConditionState.NOT_STARTED and self.active_monitor.completed_laps == 0:
                self.active_monitor = None
                self.state = ConditionState.NOT_STARTED
            else:
                self.state = new_state
                return new_state
            
        # 如果没有活动的监控器，检查所有
        # 特别是对于 TW 这样的组合工况，需要让子 monitor 能处理进入起点的逻辑
        # 只要有任何一个 monitor 触发了开始，就立即锁定并返回
        for monitor in self.monitors:
            state = monitor.update(gps)
            if state != ConditionState.NOT_STARTED:
                self.active_monitor = monitor
                self.state = state
                return state
                
        self.state = ConditionState.NOT_STARTED
        return ConditionState.NOT_STARTED

    def mark_skipped(self, reason: str, timestamp: Optional[datetime] = None):
        if self.active_monitor:
            self.active_monitor.mark_skipped(reason, timestamp)
        else:
            self.monitors[0].mark_skipped(reason, timestamp)
            self.active_monitor = self.monitors[0]
        self.state = ConditionState.SKIPPED

    def mark_completed(self, reason: str, timestamp: Optional[datetime] = None, manual: bool = False):
        if self.active_monitor:
            self.active_monitor.mark_completed(reason, timestamp, manual)
        else:
            self.monitors[0].mark_completed(reason, timestamp, manual)
            self.active_monitor = self.monitors[0]
        self.state = ConditionState.MANUAL_COMPLETED if manual else ConditionState.COMPLETED

    def get_progress_info(self) -> dict:
        if self.active_monitor:
            return self.active_monitor.get_progress_info()
        return self.monitors[0].get_progress_info()

    def get_summary(self) -> dict:
        if self.active_monitor:
            return self.active_monitor.get_summary()
        return self.monitors[0].get_summary()

    def reset(self):
        self.active_monitor = None
        self.state = ConditionState.NOT_STARTED
        for monitor in self.monitors:
            monitor.reset()
