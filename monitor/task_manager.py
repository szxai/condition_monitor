"""
任务列表管理器
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
import json
import os
from pathlib import Path

from models.condition import ConditionDefinition
from models.gps_data import GPSData
from monitor.condition_monitor import ConditionMonitor, ConditionState, CompositeConditionMonitor
from utils.geo import haversine_distance_m
from utils.json_output import output_task_status
from utils.task_list_parser import get_task_for_condition
from utils.logger import logger

DEFAULT_AUTO_SKIP = {
    'enabled': True,
    'distance_threshold_m': 200.0,
    'time_threshold_s': 30.0
}


class TaskManager:
    """工况任务列表管理器"""

    def __init__(
        self,
        conditions: List[ConditionDefinition],
        scheduler_mode: str = 'sequential',
        preferred_conditions: Optional[List[str]] = None,
        auto_skip: Optional[Dict] = None,
        task_list_data: Optional[Dict] = None,
        status_output_file: Optional[str] = None
    ):
        logger.info(f"Initializing TaskManager. Mode: {scheduler_mode}, Tasks: {len(task_list_data.get('execution_order', [])) if task_list_data else len(conditions)}")
        self.conditions_map = {}
        for cond in conditions:
            if cond.condition_name not in self.conditions_map:
                self.conditions_map[cond.condition_name] = []
            self.conditions_map[cond.condition_name].append(cond)
        
        self.current_monitor: Optional[ConditionMonitor] = None
        self.completed_task_names: List[str] = []
        self.completed_task_ids: List[str] = []
        self.execution_log: List[dict] = []
        self.scheduler_mode = scheduler_mode
        self.preferred_queue = preferred_conditions[:] if preferred_conditions else []
        self.auto_skip_config = {**DEFAULT_AUTO_SKIP, **(auto_skip or {})}
        self.auto_skip_state = {'timer_start': None, 'last_distance': None, 'increasing_streak': 0}
        self.last_gps = None
        self.last_event_summary: Optional[dict] = None
        self.task_list_data = task_list_data  # 外部任务列表数据
        self.status_output_file = status_output_file  # 状态输出文件路径
        
        # 任务状态文件路径
        if status_output_file:
            self.task_status_file = status_output_file
        else:
            self.task_status_file = 'output/task_status.json'
            
        # 确保目录存在
        os.makedirs(os.path.dirname(self.task_status_file), exist_ok=True)
            
        self.task_status_data = {}
        self._load_task_status()
        
        # 初始化待执行任务队列
        self.pending_tasks = []
        
        if task_list_data:
            # 使用外部任务列表
            self.execution_order = task_list_data.get('execution_order', [])
            # 创建任务映射的副本，避免修改原始数据，并确保状态重置
            original_map = task_list_data.get('task_map', {})
            self.task_map = {}
            for tid, tdata in original_map.items():
                self.task_map[tid] = tdata.copy()
                # 默认重置为pending，忽略tasks_list.json中的状态
                self.task_map[tid]['state'] = 'pending'
                self.task_map[tid].pop('completion_reason', None)
                self.task_map[tid].pop('manual_completion', None)
            
            # 合并状态数据到任务映射
            for task_id in self.task_map:
                if task_id in self.task_status_data:
                    self.task_map[task_id].update(self.task_status_data[task_id])
            
            # 根据任务状态过滤待执行任务
            self.pending_tasks = []
            self.completed_task_ids = []
            
            for task_id in self.execution_order:
                task_info = self.task_map.get(task_id)
                task_state = task_info.get('state', 'pending') if task_info else 'pending'
                
                # 跳过的任务（skipped）现在被视为未完成，放入队列末尾
                if task_state in ['completed', 'failed', 'manual_completed']:
                    self.completed_task_ids.append(task_id)
                else:
                    self.pending_tasks.append(task_id)

            # 将skipped状态的任务移动到队列末尾，并重置为pending状态
            skipped_tasks = []
            for task_id in list(self.pending_tasks):
                task_info = self.task_map.get(task_id)
                if task_info and task_info.get('state') == 'skipped':
                    # 重置状态为pending，以便重新执行
                    task_info['state'] = 'pending'
                    skipped_tasks.append(task_id)
                    self.pending_tasks.remove(task_id)
            self.pending_tasks.extend(skipped_tasks)
            
            self.total_tasks = len(self.execution_order)
        else:
            # 使用传统方式，基于工况列表
            self.pending_monitors = []
            for name, cond_list in self.conditions_map.items():
                if len(cond_list) == 1:
                    self.pending_monitors.append(ConditionMonitor(cond_list[0]))
                else:
                    self.pending_monitors.append(CompositeConditionMonitor(cond_list))
            self.total_tasks = len(self.pending_monitors)

    def _load_task_status(self):
        """加载任务状态文件"""
        if os.path.exists(self.task_status_file):
            try:
                with open(self.task_status_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.task_status_data = {}
                
                # 情况1: Report格式 (包含 all_tasks_status 列表)
                if isinstance(data, dict) and 'all_tasks_status' in data and isinstance(data['all_tasks_status'], list):
                    for task_entry in data['all_tasks_status']:
                        task_id = task_entry.get('task_id')
                        if task_id:
                            self.task_status_data[task_id] = task_entry
                            
                # 情况2: KV格式 (直接是 task_id -> status)
                elif isinstance(data, dict):
                    for k, v in data.items():
                        # 排除非任务ID的键
                        if k not in ['timestamp', 'event_type', 'summary', 'current_task'] and isinstance(v, dict):
                            self.task_status_data[k] = v

                print(f"✓ 已加载任务状态: {self.task_status_file} (包含 {len(self.task_status_data)} 个任务记录)")
                
                display_to_code = {
                    ConditionState.NOT_STARTED.value: 'pending',
                    ConditionState.IN_PROGRESS.value: 'in_progress',
                    ConditionState.COMPLETING.value: 'completing',
                    ConditionState.COMPLETED.value: 'completed',
                    ConditionState.MANUAL_COMPLETED.value: 'manual_completed',
                    ConditionState.FAILED.value: 'failed',
                    ConditionState.SKIPPED.value: 'skipped'
                }
                
                for task_id, entry in self.task_status_data.items():
                    if not isinstance(entry, dict):
                        continue
                    state = entry.get('state')
                    state_display = entry.get('state_display')
                    
                    # 尝试标准化状态字段
                    if state in display_to_code.values():
                        # 已经是代码 (pending, completed 等)
                        if not state_display:
                            # 如果缺少display，补全它
                            for k, v in display_to_code.items():
                                if v == state:
                                    entry['state_display'] = k
                                    break
                    elif state in display_to_code:
                        # 是中文显示名，转换为代码
                        entry['state_display'] = state
                        entry['state'] = display_to_code[state]
                    elif state_display in display_to_code:
                         # 有中文显示名，用它来设置代码
                        entry['state'] = display_to_code[state_display]
                        
            except Exception as e:
                print(f"Error loading task status: {e}")
                self.task_status_data = {}
        else:
            self.task_status_data = {}

    def _save_task_status(self, task_id: str, status_data: dict):
        """保存任务状态到文件"""
        # 更新内存数据
        if task_id not in self.task_status_data:
            self.task_status_data[task_id] = {}
        self.task_status_data[task_id].update(status_data)
        
        # 写入文件
        try:
            with open(self.task_status_file, 'w', encoding='utf-8') as f:
                json.dump(self.task_status_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving task status: {e}")

    def _state_to_code(self, state: ConditionState) -> str:
        if state == ConditionState.NOT_STARTED:
            return 'pending'
        if state == ConditionState.IN_PROGRESS:
            return 'in_progress'
        if state == ConditionState.COMPLETING:
            return 'completing'
        if state == ConditionState.COMPLETED:
            return 'completed'
        if state == ConditionState.MANUAL_COMPLETED:
            return 'manual_completed'
        if state == ConditionState.FAILED:
            return 'failed'
        if state == ConditionState.SKIPPED:
            return 'skipped'
        return 'pending'

    def update(self, gps: GPSData) -> dict:
        """更新当前任务状态"""
        self.last_gps = gps

        if not self.current_monitor:
            self._select_next_monitor(gps)

        if not self.current_monitor:
            logger.debug("No current monitor selected, all tasks completed.")
            return {
                'all_completed': True,
                'current_task': None,
                'message': '所有任务已完成',
                'state_changed': False
            }

        monitor = self.current_monitor
        old_state = monitor.state
        new_state = monitor.update(gps)
        
        # 保护：确保新状态是枚举值而不是字符串
        if isinstance(new_state, str):
             logger.error(f"Error: new_state is a string ({new_state}) instead of ConditionState")
             # 如果它返回了字符串，我们强行把它当做未改变或者尝试转回枚举
             # 因为后面对 new_state 的操作（比如判断是否等于某个枚举）都会报错
             # 为了保险，我们把它转回原来的状态对象
             new_state = old_state
             
        if old_state != new_state:
            old_val = old_state.value if hasattr(old_state, 'value') else old_state
            new_val = new_state.value if hasattr(new_state, 'value') else new_state
            logger.info(f"Task {monitor.condition.condition_name} state changed: {old_val} -> {new_val}")
        
        # 实时保存状态变化
        if monitor.task_id:
            progress_info = monitor.get_progress_info()
            # 仅保存关键字段
            status_update = {
                'state': self._state_to_code(monitor.state),
                'state_display': monitor.state.value,
                'laps_completed': monitor.completed_laps,
                'checkpoints': progress_info.get('checkpoints', []),
                'loop_zones': progress_info.get('loop_zones', []),
                'last_update': datetime.now().isoformat()
            }
            if monitor.start_time:
                status_update['start_time'] = monitor.start_time.isoformat()
            if monitor.end_time:
                status_update['end_time'] = monitor.end_time.isoformat()
            if monitor.skip_reason:
                status_update['skip_reason'] = monitor.skip_reason
            if monitor.failure_reason:
                status_update['failure_reason'] = monitor.failure_reason
            if getattr(monitor, 'completion_reason', None):
                status_update['completion_reason'] = monitor.completion_reason
            
            self._save_task_status(monitor.task_id, status_update)

        if self.auto_skip_config.get('enabled', True):
            self._maybe_auto_skip(monitor, gps)

        result = {
            'all_completed': False,
            'current_task': monitor.get_progress_info(),
            'state_changed': old_state != new_state,
            'old_state': old_state.value if hasattr(old_state, 'value') else old_state,
            'new_state': new_state.value if hasattr(new_state, 'value') else new_state,
            'task_id': getattr(monitor, 'task_id', None),
            'message': ''
        }

        if new_state == ConditionState.COMPLETED or new_state == ConditionState.MANUAL_COMPLETED:
            result_flag = 'manual_completed' if new_state == ConditionState.MANUAL_COMPLETED else 'completed'
            summary = self._finalize_current_monitor(result_flag)
            result['last_summary'] = summary
            result['message'] = f"工况 {summary['condition']} 已完成{' (人工)' if new_state == ConditionState.MANUAL_COMPLETED else ''}"
            if summary['avg_speed_kmh'] is not None:
                result['message'] += f"，平均车速 {summary['avg_speed_kmh']:.1f} km/h"

        elif new_state == ConditionState.FAILED:
            summary = self._finalize_current_monitor('failed')
            result['last_summary'] = summary
            result['message'] = f"工况 {summary['condition']} 执行失败"

        elif new_state == ConditionState.IN_PROGRESS:
            result['message'] = f"工况 {monitor.condition.condition_name} 进行中"

        elif new_state == ConditionState.COMPLETING:
            result['message'] = f"工况 {monitor.condition.condition_name} 进入完成确认"

        else:
            if monitor.completed_laps > 0:
                result['message'] = f"工况 {monitor.condition.condition_name} 等待开始下一圈"
            else:
                result['message'] = f"工况 {monitor.condition.condition_name} 等待开始"

        if self.last_event_summary and 'last_summary' not in result:
            result['last_summary'] = self.last_event_summary
            self.last_event_summary = None

        if not self.current_monitor and (self.task_list_data and not self.pending_tasks or not hasattr(self, 'pending_monitors') or not self.pending_monitors):
            result['all_completed'] = True

        if self.task_list_data and self.pending_tasks:
            result['next_task'] = self.pending_tasks[0]
        else:
            result['next_task'] = None

        return result

    def get_status(self) -> dict:
        """获取当前任务状态摘要"""
        if self.task_list_data:
            # 基于外部任务列表的状态
            remaining = len(self.pending_tasks)
            status = {
                'total_tasks': self.total_tasks,
                'completed_tasks': self.completed_task_ids[:],
                'remaining_tasks': remaining,
                'current_task': self.current_monitor.get_progress_info() if self.current_monitor else None,
                'pending_tasks': self.pending_tasks[:],
                'execution_log': self.execution_log[-20:]
            }
        else:
            # 传统方式的状态
            remaining = len(self.pending_monitors) + (1 if self.current_monitor else 0) if hasattr(self, 'pending_monitors') else 0
            status = {
                'total_tasks': self.total_tasks,
                'completed_tasks': self.completed_task_names[:],
                'remaining_tasks': remaining,
                'current_task': self.current_monitor.get_progress_info() if self.current_monitor else None,
                'pending_tasks': [m.condition.condition_name for m in self.pending_monitors] if hasattr(self, 'pending_monitors') else [],
                'execution_log': self.execution_log[-20:]
            }
        return status
    
    def get_all_tasks_status(self) -> List[Dict[str, any]]:
        """获取所有任务的状态信息"""
        all_status = []
        
        if self.task_list_data:
            # 使用外部任务列表时的处理
            
            # 首先添加已完成任务的状态
            completed_task_status = {}
            for log_entry in self.execution_log:
                if log_entry.get('task_id'):
                    completed_task_status[log_entry['task_id']] = log_entry
            
            # 然后按照执行顺序添加所有任务的状态
            for task_id in self.execution_order:
                if task_id in completed_task_status:
                    all_status.append(completed_task_status[task_id])
                elif self.current_monitor and hasattr(self.current_monitor, 'task_id') and self.current_monitor.task_id == task_id:
                    # 当前正在执行的任务
                    all_status.append(self.current_monitor.get_summary())
                elif task_id in self.pending_tasks:
                    # 待执行任务（包括skipped后重新排队的）
                    task_info = self.task_map.get(task_id)
                    if task_info:
                        condition_id = task_info.get('condition_id')
                        cond_list = self.conditions_map.get(condition_id)
                        condition = cond_list[0] if cond_list else None
                        if condition:
                            skip_reason = task_info.get('skip_reason')
                            # 如果有skip_reason，说明是被跳过重试的任务
                            state_val = ConditionState.NOT_STARTED.value
                            state_display = "等待重试" if skip_reason else ConditionState.NOT_STARTED.value
                            
                            status = {
                                'condition': condition.condition_name,
                                'description': task_info.get('description', condition.description),
                                'task_id': task_id,
                                'state': state_val,
                                'state_display': state_display,
                                'start_time': None,
                                'end_time': None,
                                'duration_seconds': None,
                                'avg_speed_kmh': None,
                                'max_speed_kmh': None,
                                'min_speed_kmh': None,
                                'distance_m': 0.0,
                                'checkpoints': [],
                                'loop_zones': None,
                                'laps_completed': task_info.get('laps_completed', 0),
                                'required_laps': condition.required_laps,
                                'skip_reason': skip_reason,
                                'failure_reason': None
                            }
                            
                            # 尝试从持久化数据中恢复圈数状态，防止显示"未开始"但圈数为0/3
                            persisted_data = self.task_status_data.get(task_id) if hasattr(self, 'task_status_data') else None
                            if persisted_data and 'laps_completed' in persisted_data:
                                status['laps_completed'] = persisted_data['laps_completed']
                                if status['laps_completed'] > 0:
                                    status['state_display'] = 'waiting_next_lap'
                                    status['state'] = 'waiting_next_lap'
                                
                            all_status.append(status)
                else:
                    # 已完成或跳过的任务（从持久化状态恢复，但不在本次运行的日志中）
                    task_info = self.task_map.get(task_id)
                    if task_info:
                        condition_id = task_info.get('condition_id')
                        cond_list = self.conditions_map.get(condition_id)
                        condition = cond_list[0] if cond_list else None
                        
                        status = {
                            'condition': condition.condition_name if condition else task_info.get('name', 'Unknown'),
                            'description': task_info.get('description', ''),
                            'task_id': task_id,
                            'state': task_info.get('state', 'unknown'),
                            'state_display': task_info.get('state_display', task_info.get('state', 'unknown')),
                            'start_time': task_info.get('start_time'),
                            'end_time': task_info.get('end_time'),
                            'duration_seconds': task_info.get('duration_seconds'),
                            'avg_speed_kmh': task_info.get('avg_speed_kmh'),
                            'max_speed_kmh': task_info.get('max_speed_kmh'),
                            'min_speed_kmh': task_info.get('min_speed_kmh'),
                            'distance_m': task_info.get('distance_m', 0.0),
                            'checkpoints': task_info.get('checkpoints', []),
                            'loop_zones': task_info.get('loop_zones', []),
                            'laps_completed': task_info.get('laps_completed', 0),
                            'required_laps': condition.required_laps if condition else 1,
                            'skip_reason': task_info.get('skip_reason'),
                            'failure_reason': task_info.get('failure_reason'),
                            'completion_reason': task_info.get('completion_reason')
                        }
                        all_status.append(status)
        else:
            # 传统方式的处理
            # 获取已完成任务的状态
            for task_name in self.completed_task_names:
                # 从执行日志中查找该任务的摘要
                for log_entry in reversed(self.execution_log):
                    if log_entry.get('condition') == task_name:
                        all_status.append(log_entry)
                        break
            
            # 获取当前任务的状态
            if self.current_monitor:
                all_status.append(self.current_monitor.get_summary())
            
            # 获取待执行任务的状态
            if hasattr(self, 'pending_monitors'):
                for monitor in self.pending_monitors:
                    all_status.append(monitor.get_summary())
        
        return all_status
    
    def output_final_summary(self, output_file: Optional[str] = None) -> Dict[str, Any]:
        """输出程序结束时的工况状态总结"""
        all_tasks_status = self.get_all_tasks_status()
        
        # 如果有当前任务，使用它作为summary，否则使用最后一个执行的任务
        if self.current_monitor:
            summary_task = self.current_monitor.get_summary()
        elif self.last_event_summary:
            summary_task = self.last_event_summary
        elif all_tasks_status:
            summary_task = all_tasks_status[0]
        else:
            summary_task = {}
        
        # 使用程序结束事件类型输出JSON
        from utils.json_output import generate_task_status_json, save_json_output, print_json_output
        
        json_data = generate_task_status_json(
            summary_task, 
            all_tasks_status, 
            event_type="program_end"
        )
        
        # 保存到文件
        file_path = output_file or self.status_output_file
        if file_path:
            save_json_output(file_path, json_data)
        
        # 打印到控制台
        print_json_output(json_data)
        
        return json_data

    def reset(self):
        """重置所有任务"""
        if hasattr(self, 'pending_monitors'):
            for monitor in self.pending_monitors:
                monitor.reset()
        if self.current_monitor:
            self.current_monitor.reset()
        self.completed_task_names = []
        self.completed_task_ids = []
        self.execution_log = []
        self.current_monitor = None
        self.auto_skip_state = {'timer_start': None, 'last_distance': None, 'increasing_streak': 0}
        
        # 重置待执行任务队列
        if self.task_list_data:
            self.pending_tasks = self.execution_order.copy()
        elif hasattr(self, 'pending_monitors'):
            # 重新初始化传统方式的监控器列表
            self.pending_monitors = []
            for name, cond_list in self.conditions_map.items():
                if len(cond_list) == 1:
                    self.pending_monitors.append(ConditionMonitor(cond_list[0]))
                else:
                    self.pending_monitors.append(CompositeConditionMonitor(cond_list))
        
        # task_list_data 和 status_output_file 不重置

    def reset_all_tasks_status(self):
        """重置所有任务状态（包括持久化文件）"""
        self.reset()
        
        # 重置状态文件
        self.task_status_data = {}
        try:
            with open(self.task_status_file, 'w', encoding='utf-8') as f:
                json.dump({}, f)
        except:
            pass
            
        if self.task_list_data:
            # 清除内存中的任务状态
            for task_id in self.task_map:
                task = self.task_map[task_id]
                task['state'] = 'pending'
                
                # 清除其他执行相关字段
                if 'start_time' in task:
                    del task['start_time']
                if 'end_time' in task:
                    del task['end_time']
                if 'completion_reason' in task:
                    del task['completion_reason']
                if 'manual_completion' in task:
                    del task['manual_completion']
            
    # ---------------- Internal helpers ---------------- #

    def ensure_monitor_selected(self, gps: Optional[GPSData] = None):
        """确保已选择当前监控器（用于初始化显示）"""
        if not self.current_monitor:
            self._select_next_monitor(gps)

    def _select_next_monitor(self, gps):
        if self.task_list_data and self.pending_tasks:
            # 使用外部任务列表选择下一个任务
            task_id = self.pending_tasks.pop(0)
            task_info = self.task_map.get(task_id)
            
            if task_info:
                condition_id = task_info.get('condition_id')
                cond_list = self.conditions_map.get(condition_id)
                
                if cond_list:
                    # 创建带有任务ID的监控器
                    if len(cond_list) == 1:
                        monitor = ConditionMonitor(cond_list[0], task_id=task_id)
                    else:
                        monitor = CompositeConditionMonitor(cond_list, task_id=task_id)
                    
                    # 恢复监控器状态（如果有）
                    if task_id in self.task_status_data:
                        monitor.restore_state(self.task_status_data[task_id])
                        
                    self.current_monitor = monitor
                    self.auto_skip_state = {'timer_start': None, 'last_distance': None, 'increasing_streak': 0}
                    return
        elif not hasattr(self, 'pending_monitors') or not self.pending_monitors:
            # 如果没有待执行任务，设置current_monitor为None
            self.current_monitor = None
            return
        
        # 回退到传统方式选择下一个监控器
        monitor = self._pop_preferred_monitor()
        if not monitor:
            if hasattr(self, 'pending_monitors'):
                if self.scheduler_mode == 'priority':
                    self.pending_monitors.sort(
                        key=lambda m: (-m.condition.priority, m.condition.condition_name)
                    )
                    monitor = self.pending_monitors.pop(0)
                elif self.scheduler_mode == 'nearest' and gps:
                    idx = self._find_nearest_monitor_index(gps)
                    monitor = self.pending_monitors.pop(idx)
                else:
                    monitor = self.pending_monitors.pop(0)
        
        if monitor:
            self.current_monitor = monitor
            self.auto_skip_state = {'timer_start': None, 'last_distance': None, 'increasing_streak': 0}

    def _pop_preferred_monitor(self) -> Optional[ConditionMonitor]:
        if not self.preferred_queue:
            return None
        for preferred in list(self.preferred_queue):
            for idx, monitor in enumerate(self.pending_monitors):
                if monitor.condition.condition_name == preferred:
                    self.preferred_queue.remove(preferred)
                    return self.pending_monitors.pop(idx)
        return None

    def _find_nearest_monitor_index(self, gps) -> int:
        best_idx = 0
        best_distance = float('inf')
        for idx, monitor in enumerate(self.pending_monitors):
            start_center = monitor.condition.start.center
            distance = haversine_distance_m(
                gps.longitude, gps.latitude, start_center[0], start_center[1]
            )
            if distance < best_distance:
                best_distance = distance
                best_idx = idx
        return best_idx

    def skip_current(self, reason: str = "人工跳过", requeue: bool = True) -> Optional[dict]:
        """人工跳过当前工况"""
        if not self.current_monitor:
            logger.warning("Attempted to skip, but no current task active.")
            return None
        logger.info(f"Skipping current task: {self.current_monitor.condition.condition_name}, Reason: {reason}")
        summary = self._skip_current(reason, requeue=requeue)
        return summary

    def complete_current(self, reason: str = "手动完成") -> Optional[dict]:
        """手动完成当前任务"""
        if not self.current_monitor:
            logger.warning("Attempted to manual complete, but no current task active.")
            return None
        
        logger.info(f"Manually completing current task: {self.current_monitor.condition.condition_name}, Reason: {reason}")
        self.current_monitor.mark_completed(
            reason,
            self.last_gps.timestamp if self.last_gps else None,
            manual=True
        )
        summary = self._finalize_current_monitor('manual_completed')
        return summary

    def _update_task_list_file(self):
        """更新任务列表文件(仅状态)"""
        if not self.task_list_data:
            return

        # 此处不再直接修改task_list.json文件，因为状态已经保存在 task_status.json 中
        # 但是为了兼容性，如果需要，可以仅更新内存中的状态
        pass
            
    def _maybe_auto_skip(self, monitor: ConditionMonitor, gps):
        if not self.current_monitor or monitor is not self.current_monitor:
            return
        if monitor.state in (ConditionState.COMPLETED, ConditionState.SKIPPED):
            return

        threshold = monitor.condition.skip_distance_threshold_m or \
            self.auto_skip_config.get('distance_threshold_m', 200.0)
        time_threshold = monitor.condition.skip_time_threshold_s or \
            self.auto_skip_config.get('time_threshold_s', 30.0)

        start_center = monitor.condition.start.center
        distance = haversine_distance_m(
            gps.longitude, gps.latitude, start_center[0], start_center[1]
        )

        state = self.auto_skip_state
        last_distance = state.get('last_distance')
        if last_distance is not None and distance > last_distance + 5:
            state['increasing_streak'] = state.get('increasing_streak', 0) + 1
        else:
            state['increasing_streak'] = 0
        state['last_distance'] = distance

        if distance > threshold:
            if not state['timer_start']:
                state['timer_start'] = gps.timestamp
                logger.info(f"Auto-skip timer started for {monitor.condition.condition_name}. Distance {distance:.1f}m > {threshold}m")
            elif (gps.timestamp - state['timer_start']).total_seconds() >= time_threshold and \
                    state.get('increasing_streak', 0) >= 3:
                logger.warning(f"Auto-skipping {monitor.condition.condition_name}. Distance: {distance:.1f}m, Time: {(gps.timestamp - state['timer_start']).total_seconds():.1f}s")
                self._skip_current(
                    f"距离起点超过{int(distance)}m，自动跳过",
                    requeue=True
                )
        else:
            if state['timer_start']:
                logger.info(f"Auto-skip timer reset for {monitor.condition.condition_name}. Back within range.")
            state['timer_start'] = None

    def _skip_current(self, reason: str, requeue: bool = True) -> Optional[dict]:
        if not self.current_monitor:
            return None

        monitor = self.current_monitor
        monitor.mark_skipped(reason, self.last_gps.timestamp if self.last_gps else None)
        summary = monitor.get_summary()
        summary['result'] = 'skipped'
        summary['reason'] = reason
        self.execution_log.append(summary)

        monitor.reset()
        if requeue:
            if self.task_list_data and hasattr(self.current_monitor, 'task_id'):
                # 使用外部任务列表时，将任务ID重新加入待执行队列
                self.pending_tasks.append(self.current_monitor.task_id)
                
                # 更新任务映射中的任务状态为 pending (重试)，但保留跳过原因
                task_id = self.current_monitor.task_id
                if task_id in self.task_map:
                    self.task_map[task_id]['state'] = 'pending'
                    self._save_task_status(task_id, {
                        'state': 'pending',
                        'state_display': '等待重试',
                        'skip_reason': reason,
                        'end_time': summary.get('end_time'),
                        'checkpoints': [],  # 清除途径点状态
                        'loop_zones': [],   # 清除循环区状态
                        'laps_completed': 0, # 清除圈数
                        'distance_m': 0.0,   # 清除距离
                        'avg_speed_kmh': None # 清除速度
                    })
            elif hasattr(self, 'pending_monitors'):
                # 传统方式，将监控器重新加入待执行队列
                self.pending_monitors.append(monitor)
        else:
            if self.task_list_data and hasattr(self.current_monitor, 'task_id'):
                # 使用外部任务列表时，记录已完成的任务ID
                task_id = self.current_monitor.task_id
                self.completed_task_ids.append(task_id)
                
                end_time_str = ""
                if hasattr(self.current_monitor, 'end_time') and self.current_monitor.end_time:
                    end_time_str = self.current_monitor.end_time.isoformat()
                else:
                    end_time_str = datetime.now().isoformat()
                    
                # 更新任务映射中的任务状态
                if task_id in self.task_map:
                    self.task_map[task_id]['state'] = 'skipped'
                    self.task_map[task_id]['end_time'] = end_time_str
                    self.task_map[task_id]['completion_reason'] = reason
                    self._save_task_status(task_id, {
                        'state': 'skipped',
                        'state_display': '已跳过',
                        'end_time': self.task_map[task_id]['end_time'],
                        'completion_reason': reason,
                        'last_update': end_time_str
                    })
            else:
                # 传统方式，记录已完成的工况名称
                self.completed_task_names.append(monitor.condition.condition_name)

        self.current_monitor = None
        self.auto_skip_state = {'timer_start': None, 'last_distance': None, 'increasing_streak': 0}
        self._select_next_monitor(self.last_gps)
        return summary

    def _finalize_current_monitor(self, result_flag: str) -> dict:
        """处理当前任务完成后的清理工作"""
        if not self.current_monitor:
            return {}

        summary = self.current_monitor.get_summary()
        summary['result'] = result_flag
        
        # 根据是否使用外部任务列表进行不同处理
        if self.task_list_data and hasattr(self.current_monitor, 'task_id') and self.current_monitor.task_id:
            # 使用外部任务列表时，记录任务ID
            task_id = self.current_monitor.task_id
            self.completed_task_ids.append(task_id)
            
            # 优先使用 monitor 中的 end_time（通常来源于 GPS 时间戳）
            end_time_str = ""
            if hasattr(self.current_monitor, 'end_time') and self.current_monitor.end_time:
                end_time_str = self.current_monitor.end_time.isoformat()
            else:
                end_time_str = datetime.now().isoformat()
            
            # 更新任务映射中的任务状态
            if task_id in self.task_map:
                self.task_map[task_id]['state'] = result_flag
                self.task_map[task_id]['end_time'] = end_time_str
                completion_reason = getattr(self.current_monitor, 'completion_reason', None) or \
                    summary.get('completion_reason') or summary.get('reason') or '自动完成'
                self.task_map[task_id]['completion_reason'] = completion_reason
                self._save_task_status(task_id, {
                    'state': result_flag,
                    'state_display': self.current_monitor.state.value,
                    'end_time': self.task_map[task_id]['end_time'],
                    'completion_reason': self.task_map[task_id]['completion_reason'],
                    'laps_completed': self.current_monitor.completed_laps,
                    'checkpoints': summary.get('checkpoints', []),
                    'loop_zones': summary.get('loop_zones', []),
                    'last_update': end_time_str
                })
        elif result_flag in ['completed', 'manual_completed']:
            # 传统方式，记录工况名称
            self.completed_task_names.append(summary['condition'])
        
        self.execution_log.append(summary)
        self.last_event_summary = summary
        
        # 获取所有任务状态并输出JSON
        all_tasks_status = self.get_all_tasks_status()
        output_task_status(summary, all_tasks_status, self.status_output_file)
        
        self.current_monitor = None
        self.auto_skip_state = {'timer_start': None, 'last_distance': None, 'increasing_streak': 0}
        self._select_next_monitor(self.last_gps)
        return summary



