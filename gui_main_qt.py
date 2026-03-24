import sys
import json
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QFrame, 
                             QMessageBox, QDialog, QFormLayout, QComboBox, QLineEdit, 
                             QScrollArea, QSplitter, QGroupBox, QAction, QFileDialog, QStyleFactory, QHeaderView, QGraphicsView, QGraphicsScene)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPointF, QRectF
from PyQt5.QtGui import QFont, QColor, QIcon, QPen, QBrush, QPolygonF

# Import existing system
from main import ConditionMonitorSystem
from models.gps_data import GPSData
from monitor.condition_monitor import CompositeConditionMonitor
from utils.logger import setup_logger

# Initialize logger
logger = setup_logger("ConditionMonitor")

class ConfigDialog(QDialog):
    def __init__(self, config_path, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.setWindowTitle("系统配置 (System Configuration)")
        self.resize(500, 300)
        
        self.config_data = {}
        self.load_config()
        
        layout = QFormLayout(self)
        
        # GPS Mode
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["csv", "usb"])
        
        current_mode = self.config_data.get('gps', {}).get('mode', 'csv')
        if current_mode == 'serial':
            current_mode = 'usb'
            
        self.combo_mode.setCurrentText(current_mode)
        self.combo_mode.currentTextChanged.connect(self.on_mode_change)
        layout.addRow("GPS 模式 (Mode):", self.combo_mode)
        
        # CSV File
        self.edit_csv = QLineEdit()
        self.edit_csv.setText(self.config_data.get('gps', {}).get('csv_file', ''))
        self.btn_csv = QPushButton("选择文件...")
        self.btn_csv.clicked.connect(self.browse_csv)
        csv_layout = QHBoxLayout()
        csv_layout.addWidget(self.edit_csv)
        csv_layout.addWidget(self.btn_csv)
        layout.addRow("CSV 文件路径:", csv_layout)
        
        # Serial Port
        self.edit_port = QLineEdit()
        self.edit_port.setText(self.config_data.get('gps', {}).get('port', '/dev/ttyACM0'))
        layout.addRow("串口号 (Port):", self.edit_port)
        
        # Baudrate
        self.edit_baud = QLineEdit()
        self.edit_baud.setText(str(self.config_data.get('gps', {}).get('baudrate', 115200)))
        layout.addRow("波特率 (Baudrate):", self.edit_baud)
        
        # Auto Skip
        self.edit_skip_dist = QLineEdit()
        self.edit_skip_dist.setText(str(self.config_data.get('task_options', {}).get('auto_skip', {}).get('distance_threshold_m', 200.0)))
        layout.addRow("自动跳过距离 (m):", self.edit_skip_dist)
        
        self.edit_skip_time = QLineEdit()
        self.edit_skip_time.setText(str(self.config_data.get('task_options', {}).get('auto_skip', {}).get('time_threshold_s', 30.0)))
        layout.addRow("自动跳过时间 (s):", self.edit_skip_time)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("保存并重启")
        btn_save.clicked.connect(self.save_config)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addRow(btn_layout)
        
        self.on_mode_change(self.combo_mode.currentText())

    def load_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config_data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法读取配置文件: {e}")
            self.reject()

    def on_mode_change(self, mode):
        is_csv = (mode == 'csv')
        self.edit_csv.setEnabled(is_csv)
        self.btn_csv.setEnabled(is_csv)
        self.edit_port.setEnabled(not is_csv)
        self.edit_baud.setEnabled(not is_csv)

    def browse_csv(self):
        filename, _ = QFileDialog.getOpenFileName(self, "选择 CSV 文件", "", "CSV Files (*.csv);;All Files (*)")
        if filename:
            self.edit_csv.setText(filename)

    def save_config(self):
        try:
            gps = self.config_data.setdefault('gps', {})
            gps['mode'] = self.combo_mode.currentText()
            gps['csv_file'] = self.edit_csv.text()
            gps['port'] = self.edit_port.text()
            gps['baudrate'] = int(self.edit_baud.text())
            
            opts = self.config_data.setdefault('task_options', {})
            skip = opts.setdefault('auto_skip', {})
            skip['distance_threshold_m'] = float(self.edit_skip_dist.text())
            skip['time_threshold_s'] = float(self.edit_skip_time.text())
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
                
            logger.info("Configuration saved")
            QMessageBox.information(self, "成功", "配置已保存，请重启程序以生效。")
            self.accept()
        except Exception as e:
            logger.error(f"Failed to save config: {e}", exc_info=True)
            QMessageBox.critical(self, "错误", f"保存配置失败: {e}")

class TaskDetailDialog(QDialog):
    def __init__(self, task_info, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"任务详情: {task_info.get('name', 'Unknown')}")
        self.resize(400, 300)
        layout = QFormLayout(self)
        
        layout.addRow("任务ID:", QLabel(task_info.get('task_id', '--')))
        layout.addRow("工况ID:", QLabel(task_info.get('condition_id', '--')))
        layout.addRow("名称:", QLabel(task_info.get('name', '--')))
        layout.addRow("描述:", QLabel(task_info.get('description', '无')))
        layout.addRow("状态:", QLabel(task_info.get('state', 'pending')))
        
        if 'start_time' in task_info:
            layout.addRow("开始时间:", QLabel(task_info['start_time']))
        if 'end_time' in task_info:
            layout.addRow("结束时间:", QLabel(task_info['end_time']))
        if 'completion_reason' in task_info:
            layout.addRow("完成原因:", QLabel(task_info['completion_reason']))

# Global Exception Hook
def exception_hook(exctype, value, traceback):
    logger.critical("Uncaught exception", exc_info=(exctype, value, traceback))
    sys.__excepthook__(exctype, value, traceback)

sys.excepthook = exception_hook

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        logger.info("Initializing MainWindow")
        self.setWindowTitle("工况监控系统 (Condition Monitor) - PyQt Edition")
        self.resize(1200, 800)
        
        # Initialize System
        self.config_path = 'config/config.json'
        
        # GPS State for UI stability
        self.last_valid_gps = None
        self.last_gps_time = 0
        self.gps_grace_period = 2.0 # seconds to hold GPS data before showing "Waiting..."
        self.last_log_time = 0
        self.gps_connected = False
        
        # Increase timer frequency for smoother GPS (was 100ms)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_loop)
        self.timer.start(50) # 50ms update rate (20Hz)

        logger.info(f"Using config file: {self.config_path}")
        self.system = ConditionMonitorSystem(config_path=self.config_path)
        try:
            self.system.initialize()
            logger.info("System initialized successfully")
            self.system.running = True
            
            # Ensure a monitor is selected if possible (for initial display)
            self.system.task_manager.ensure_monitor_selected()
        except Exception as e:
            logger.critical(f"System initialization failed: {e}", exc_info=True)
            QMessageBox.critical(self, "初始化错误", f"无法启动系统: {e}")
            sys.exit(1)
            
        self.init_ui()

    def init_ui(self):
        # Central Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # Splitter for Left (Execution) and Right (Queue)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        
        # --- Left Panel: Execution Status ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        splitter.addWidget(left_panel)
        
        # 1. Header (GPS & Status)
        header_group = QGroupBox("系统状态")
        header_layout = QHBoxLayout()
        self.lbl_gps = QLabel("GPS: --, --")
        self.lbl_gps.setFont(QFont("Arial", 10, QFont.Bold))
        header_layout.addWidget(self.lbl_gps)
        
        # Speed and Altitude
        self.lbl_speed_alt = QLabel("Speed: -- km/h | Alt: -- m")
        self.lbl_speed_alt.setFont(QFont("Arial", 10))
        header_layout.addWidget(self.lbl_speed_alt)
        
        header_layout.addStretch()
        self.lbl_message = QLabel("系统就绪")
        self.lbl_message.setStyleSheet("color: gray; font-style: italic;")
        header_layout.addWidget(self.lbl_message)
        header_group.setLayout(header_layout)
        left_layout.addWidget(header_group)
        
        # 2. Current Task (Big Display)
        current_group = QGroupBox("正在执行 (Current Task)")
        current_layout = QVBoxLayout()
        
        self.lbl_current_task = QLabel("等待开始...")
        self.lbl_current_task.setFont(QFont("Arial", 20, QFont.Bold))
        self.lbl_current_task.setStyleSheet("color: blue;")
        self.lbl_current_task.setAlignment(Qt.AlignCenter)
        current_layout.addWidget(self.lbl_current_task)
        
        # Current Task Description
        self.lbl_current_desc = QLabel("")
        self.lbl_current_desc.setFont(QFont("Arial", 14))
        self.lbl_current_desc.setStyleSheet("color: darkblue;")
        self.lbl_current_desc.setAlignment(Qt.AlignCenter)
        current_layout.addWidget(self.lbl_current_desc)
        
        # Next Task Indicator
        self.lbl_next_task = QLabel("下个任务: --")
        self.lbl_next_task.setFont(QFont("Arial", 12))
        self.lbl_next_task.setStyleSheet("color: gray;")
        self.lbl_next_task.setAlignment(Qt.AlignCenter)
        current_layout.addWidget(self.lbl_next_task)
        
        # Progress Info
        progress_layout = QHBoxLayout()
        self.lbl_laps = QLabel("圈数: -- / --")
        self.lbl_laps.setFont(QFont("Arial", 12))
        progress_layout.addWidget(self.lbl_laps)
        self.lbl_start_flag = QLabel("起点: 未到达")
        self.lbl_start_flag.setFont(QFont("Arial", 12))
        progress_layout.addWidget(self.lbl_start_flag)
        self.lbl_end_flag = QLabel("终点: 未到达")
        self.lbl_end_flag.setFont(QFont("Arial", 12))
        progress_layout.addWidget(self.lbl_end_flag)
        current_layout.addLayout(progress_layout)
        
        # Loop Zones Text
        self.lbl_loops = QLabel("循环区: --")
        self.lbl_loops.setWordWrap(True)
        current_layout.addWidget(self.lbl_loops)
        
        current_group.setLayout(current_layout)
        left_layout.addWidget(current_group)
        
        # Map under Current Task (left panel)
        map_group = QGroupBox("坐标地图（当前任务）")
        map_layout = QVBoxLayout()
        self.map_view = QGraphicsView()
        self.map_scene = QGraphicsScene()
        self.map_view.setScene(self.map_scene)
        self.map_view.setMinimumHeight(240)
        # Hide scroll bars to avoid unintended panning UI
        self.map_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.map_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        map_layout.addWidget(self.map_view)
        map_group.setLayout(map_layout)
        left_layout.addWidget(map_group)
        
        # 4. Controls
        control_layout = QHBoxLayout()
        
        btn_skip = QPushButton("⏭ 跳过当前")
        btn_skip.clicked.connect(self.skip_current)
        control_layout.addWidget(btn_skip)
        
        btn_complete = QPushButton("✅ 人工完成")
        btn_complete.clicked.connect(self.manual_complete)
        control_layout.addWidget(btn_complete)
        
        btn_reset = QPushButton("🔄 重置任务")
        btn_reset.clicked.connect(self.reset_tasks)
        control_layout.addWidget(btn_reset)
        
        left_layout.addLayout(control_layout)
        
        # --- Right Panel: Task Queue ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        splitter.addWidget(right_panel)
        
        queue_group = QGroupBox("任务队列 (点击查看详情)")
        queue_layout = QVBoxLayout()
        
        self.tree_queue = QTreeWidget()
        self.tree_queue.setHeaderLabels(["状态", "任务名称", "Task ID"])
        # Set column widths - adaptive and wider status
        self.tree_queue.setColumnWidth(0, 150) # Status (Wider for visibility)
        self.tree_queue.header().setSectionResizeMode(1, QHeaderView.Stretch) # Name stretches
        self.tree_queue.setColumnWidth(2, 100) # ID
        self.tree_queue.itemClicked.connect(self.show_task_details)
        queue_layout.addWidget(self.tree_queue)
        
        queue_group.setLayout(queue_layout)
        right_layout.addWidget(queue_group)
        
        # Checkpoints list under queue (right panel, narrow)
        cp_group = QGroupBox("途经点状态 (Checkpoints)")
        cp_layout = QVBoxLayout()
        self.tree_checkpoints = QTreeWidget()
        self.tree_checkpoints.setHeaderLabels(["名称", "类型", "状态", "通过时间"])
        self.tree_checkpoints.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree_checkpoints.setColumnWidth(1, 70)
        self.tree_checkpoints.setColumnWidth(2, 120)
        self.tree_checkpoints.setColumnWidth(3, 100)
        cp_layout.addWidget(self.tree_checkpoints)
        cp_group.setLayout(cp_layout)
        right_layout.addWidget(cp_group)
        
        # Set Splitter Sizes (60% Left, 40% Right) and Stretch Factors
        splitter.setSizes([800, 400])
        splitter.setStretchFactor(0, 2) # Left panel takes more space
        splitter.setStretchFactor(1, 1)
        
        # --- Menu Bar / Toolbar ---
        toolbar = self.addToolBar("Main")
        
        action_config = QAction("⚙ 参数设置", self)
        action_config.triggered.connect(self.open_settings)
        toolbar.addAction(action_config)
        
        toolbar.addSeparator()
        
        action_import = QAction("📥 接收任务文件", self)
        action_import.triggered.connect(self.import_task)
        toolbar.addAction(action_import)
        
        action_export = QAction("📤 发送工况文件", self)
        action_export.triggered.connect(self.export_status)
        toolbar.addAction(action_export)

        # Initialize Queue
        self.update_queue()
        self._queue_initialized = True

    def update_loop(self):
        if not self.system.running:
            return
            
        try:
            current_time = datetime.now().timestamp()
            gps = self.system.gps_reader.read()
            
            # Periodic logging (every 60s)
            if current_time - self.last_log_time > 60:
                self.last_log_time = current_time
                status = "GPS Connected" if gps else "GPS Waiting"
                task_name = self.system.task_manager.current_monitor.condition.condition_name if self.system.task_manager.current_monitor else "No Task"
                logger.info(f"System Heartbeat: Status={status}, Current Task={task_name}")

            display_gps = gps
            
            if gps:
                if not self.gps_connected:
                    logger.info("GPS Signal Connected/Restored")
                    self.gps_connected = True
                self.last_valid_gps = gps
                self.last_gps_time = current_time
            else:
                # Use cached GPS if within grace period
                if self.last_valid_gps and (current_time - self.last_gps_time < self.gps_grace_period):
                    display_gps = self.last_valid_gps
                elif self.gps_connected:
                    logger.warning("GPS Signal Lost (Timeout)")
                    self.gps_connected = False
            
            if display_gps:
                update_info = self.system.task_manager.update(display_gps)
                self.update_ui(display_gps, update_info)
            else:
                # No GPS yet, but we might want to update UI for initial task state
                if self.system.task_manager.current_monitor:
                     info = self.system.task_manager.current_monitor.get_progress_info()
                     update_info = {'current_task': info}
                     self.update_ui(None, update_info)
        except Exception as e:
            logger.error(f"Error in update loop: {e}", exc_info=True)
            # print(f"Update error: {e}")

    def update_ui(self, gps: Optional[GPSData], update_info: dict):
        # GPS
        if gps:
            self.lbl_gps.setText(f"GPS: {gps.latitude:.6f}, {gps.longitude:.6f}")
            speed = f"{gps.speed:.1f}" if gps.speed is not None else "--"
            alt = f"{gps.altitude:.1f}" if gps.altitude is not None else "--"
            self.lbl_speed_alt.setText(f"Speed: {speed} km/h | Alt: {alt} m")
        else:
            self.lbl_gps.setText("GPS: 等待信号...")
            self.lbl_speed_alt.setText("Speed: -- km/h | Alt: -- m")
        
        # Message
        if update_info.get('message'):
            self.lbl_message.setText(update_info['message'])
            
        # Current Task
        current_task = update_info.get('current_task')
        
        # Next Task
        next_task_id = update_info.get('next_task')
        next_task_name = "--"
        if next_task_id and self.system.task_manager.task_map:
            task_info = self.system.task_manager.task_map.get(next_task_id)
            if task_info:
                next_task_name = task_info.get('name', next_task_id)
        
        self.lbl_next_task.setText(f"下个任务: {next_task_name}")
        
        # Determine if we need to refresh queue/checkpoints
        # Refresh if task changed or explicitly requested via state_changed
        state_changed = update_info.get('state_changed', False)
        
        # Check if current task ID changed
        current_task_id = current_task.get('task_id') if current_task else None
        task_changed = (getattr(self, '_last_task_id', None) != current_task_id)
        self._last_task_id = current_task_id
        
        if current_task:
            self.lbl_current_task.setText(current_task.get('condition', 'Unknown'))
            self.lbl_current_desc.setText(current_task.get('description', ''))
            
            completed = current_task.get('laps_completed', 0)
            required = current_task.get('required_laps', 1)
            self.lbl_laps.setText(f"圈数: {completed} / {required}")
            
            # Update condition access
            cond_list = self.system.task_manager.conditions_map.get(current_task.get('condition'))
            cond_obj = cond_list[0] if cond_list and isinstance(cond_list, list) else cond_list
            
            if cond_obj and gps:
                at_start = cond_obj.start.contains(gps.longitude, gps.latitude)
                at_end = cond_obj.end.contains(gps.longitude, gps.latitude)
                
                # 如果状态是进行中或更高，即使不在起点框内，逻辑上也已经“经过起点”了
                state_code = current_task.get('state', 'pending')
                laps_completed = current_task.get('laps_completed', 0)
                is_waiting_lap = (state_code in ['not_started', 'pending'] and laps_completed > 0)
                
                if state_code in ['in_progress', 'completing', 'completed', 'manual_completed']:
                    self.lbl_start_flag.setText("起点: 已通过")
                elif is_waiting_lap:
                    self.lbl_start_flag.setText("起点: 等待进入(下一圈)")
                else:
                    self.lbl_start_flag.setText("起点: 已到达" if at_start else "起点: 未到达")
                    
                self.lbl_end_flag.setText("终点: 已到达" if at_end else "终点: 未到达")
            else:
                self.lbl_start_flag.setText("起点: --")
                self.lbl_end_flag.setText("终点: --")
            
            # Loops
            loops_text = []
            if current_task.get('loop_zones'):
                for zone in current_task['loop_zones']:
                    loops_text.append(f"{zone['name']}: {zone['current_entries']}/{zone['required_entries']}")
                self.lbl_loops.setText(" | ".join(loops_text))
            else:
                self.lbl_loops.setText("无循环区")
                
            if task_changed or not hasattr(self, '_map_scale_ready'):
                self._compute_map_scale(current_task, gps)
            self._update_map(gps, current_task)
            self.update_checkpoints(current_task.get('checkpoints', []))
        else:
            self.lbl_current_task.setText("无任务正在执行")
            self.lbl_current_desc.setText("")
            self.lbl_laps.setText("圈数: -- / --")
            self.lbl_start_flag.setText("起点: --")
            self.lbl_end_flag.setText("终点: --")
            self.lbl_loops.setText("循环区: --")
            self.map_scene.clear()
            self.tree_checkpoints.clear()
            
        # Task Queue (Refresh only on significant changes)
        if state_changed or task_changed or not hasattr(self, '_queue_initialized'):
            self.update_queue()
            self._queue_initialized = True

    def _compute_map_scale(self, current_task: dict, gps: Optional[GPSData]):
        cond_id = current_task.get('condition')
        cond_list = self.system.task_manager.conditions_map.get(cond_id)
        
        # 优先使用 active_monitor 对应的工况（如果存在），否则使用所有候选工况来计算边界
        tm = self.system.task_manager
        active_cond = None
        if tm.current_monitor and isinstance(tm.current_monitor, CompositeConditionMonitor):
            # 获取内部实际正在执行的子监控器（包含 TW-1, TW-2 等）
            inner_monitor = tm.current_monitor.active_monitor
            # 修改锁定判定：只要 active_monitor 存在（即使状态是 NOT_STARTED 并且刚初始化），也应被视为当前焦点，但这会导致没选时就锁定
            # 所以正确的逻辑是：只有当状态明确为进行中/完成等，或者已经有圈数时，才锁定
            has_laps = inner_monitor and inner_monitor.completed_laps > 0
            if inner_monitor and (inner_monitor.state != ConditionState.NOT_STARTED or has_laps):
                active_cond = inner_monitor.condition
        
        # 如果已经锁定了某个区域，就只聚焦那个区域
        if active_cond:
             target_conditions = [active_cond]
        else:
             # 否则，考虑所有候选区域
             target_conditions = []
             seen_coords = set()
             if cond_list:
                 for c in (cond_list if isinstance(cond_list, list) else [cond_list]):
                     if c:
                         # 同样使用简化坐标去重
                         coord_key = (round(c.start.lon_lb, 3), round(c.start.lat_lb, 3))
                         if coord_key not in seen_coords:
                             seen_coords.add(coord_key)
                             target_conditions.append(c)

        if not target_conditions and cond_list:
            target_conditions = cond_list if isinstance(cond_list, list) else [cond_list]

        if not target_conditions:
            self._map_scale_ready = False
            return

        points = []
        for cond in target_conditions:
            if not cond: continue
            points.append((cond.start.lon_lb, cond.start.lat_lb))
            points.append((cond.start.lon_ub, cond.start.lat_ub))
            points.append((cond.end.lon_lb, cond.end.lat_lb))
            points.append((cond.end.lon_ub, cond.end.lat_ub))
            for cp in cond.checkpoints:
                points.append((cp.zone.lon_lb, cp.zone.lat_lb))
                points.append((cp.zone.lon_ub, cp.zone.lat_ub))
        
        # Include current GPS
        if gps:
            points.append((gps.longitude, gps.latitude))
        
        # ... (rest of calculation)
        min_lon = min(p[0] for p in points)
        max_lon = max(p[0] for p in points)
        min_lat = min(p[1] for p in points)
        max_lat = max(p[1] for p in points)
        self._map_center_lon = (min_lon + max_lon) / 2.0
        self._map_center_lat = (min_lat + max_lat) / 2.0
        span_lon = max(0.0001, max_lon - min_lon)
        span_lat = max(0.0001, max_lat - min_lat)
        vw = max(1, int(self.map_view.viewport().width()))
        vh = max(1, int(self.map_view.viewport().height()))
        self._map_scale_x = (vw * 0.8) / span_lon
        self._map_scale_y = (vh * 0.8) / span_lat
        
        # Precompute scene rect bounds in scene coordinates (to keep items visible)
        min_x = (min_lon - self._map_center_lon) * self._map_scale_x
        max_x = (max_lon - self._map_center_lon) * self._map_scale_x
        min_y = (min_lat - self._map_center_lat) * (-self._map_scale_y)
        max_y = (max_lat - self._map_center_lat) * (-self._map_scale_y)
        self._scene_margin = 20
        rx = min(min_x, max_x) - self._scene_margin
        ry = min(min_y, max_y) - self._scene_margin
        rw = abs(max_x - min_x) + 2 * self._scene_margin
        rh = abs(max_y - min_y) + 2 * self._scene_margin
        self._scene_rect = QRectF(rx, ry, rw, rh)
        
        self._map_scale_ready = True

    def _update_map(self, gps: Optional[GPSData], current_task: dict):
        self.map_scene.clear()
        cond_id = current_task.get('condition')
        cond_list = self.system.task_manager.conditions_map.get(cond_id)
        
        # 确定需要绘制的区域
        tm = self.system.task_manager
        active_cond = None
        if tm.current_monitor and isinstance(tm.current_monitor, CompositeConditionMonitor):
            # 获取内部实际正在执行的子监控器（包含 TW-1, TW-2 等）
            inner_monitor = tm.current_monitor.active_monitor
            # 修改锁定判定：只要 active_monitor 存在（即使状态是 NOT_STARTED 并且刚初始化），也应被视为当前焦点，但这会导致没选时就锁定
            # 所以正确的逻辑是：只有当状态明确为进行中/完成等，或者已经有圈数时，才锁定
            has_laps = inner_monitor and inner_monitor.completed_laps > 0
            if inner_monitor and (inner_monitor.state != ConditionState.NOT_STARTED or has_laps):
                active_cond = inner_monitor.condition
                
        # 强制重算地图边界和比例尺
        self._compute_map_scale(current_task, gps)

        if active_cond:
             target_conditions = [active_cond]
        else:
             # 如果未锁定，绘制所有候选区域，必须去除重复坐标
             target_conditions = []
             seen_coords = set()
             if cond_list:
                 for c in (cond_list if isinstance(cond_list, list) else [cond_list]):
                     if c:
                         # 只用起点的下限做简单哈希去重，防止浮点微小差异影响去重
                         # 降低精度到小数点后3位（约百米级别）以确保相似坐标被视为同一个
                         coord_key = (round(c.start.lon_lb, 3), round(c.start.lat_lb, 3))
                         if coord_key not in seen_coords:
                             seen_coords.add(coord_key)
                             target_conditions.append(c)

        if not target_conditions:
            # 去重和兜底都失败时，才尝试恢复为全部
            if cond_list:
                target_conditions = cond_list if isinstance(cond_list, list) else [cond_list]

        # 计算地图比例尺，如果还没有的话，或者强制重算
        self._compute_map_scale(current_task, gps)
        
        if not target_conditions or not getattr(self, '_map_scale_ready', False):
            # 强制重新计算比例尺
            self._map_scale_ready = False
            return

        zones = []
        for i, cond in enumerate(target_conditions):
            if not cond: continue
            
            # 使用条件名称区分区域 (例如 TW (Area 1), TW (Area 2))
            suffix = ""
            if len(target_conditions) > 1:
                suffix = f" (路线{i+1})"

            zones.append((f'起点{suffix}', cond.start, QColor(0, 200, 0)))
            zones.append((f'终点{suffix}', cond.end, QColor(200, 0, 0)))
            for cp in cond.checkpoints:
                zones.append((f'{cp.name}{suffix}', cp.zone, QColor(255, 165, 0)))

        # Draw zones
        for name, z, clr in zones:
            x1 = (z.lon_lb - self._map_center_lon) * self._map_scale_x
            x2 = (z.lon_ub - self._map_center_lon) * self._map_scale_x
            y1 = (z.lat_lb - self._map_center_lat) * (-self._map_scale_y)
            y2 = (z.lat_ub - self._map_center_lat) * (-self._map_scale_y)
            rx = min(x1, x2)
            ry = min(y1, y2)
            rw = abs(x2 - x1)
            rh = abs(y2 - y1)
            pen = QPen(clr)
            brush = QBrush(QColor(clr.red(), clr.green(), clr.blue(), 40))
            self.map_scene.addRect(rx, ry, rw, rh, pen, brush)
            self.map_scene.addText(name).setPos(rx, ry - 14)
        # Draw GPS arrow
        if gps:
            gx = (gps.longitude - self._map_center_lon) * self._map_scale_x
            gy = (gps.latitude - self._map_center_lat) * (-self._map_scale_y)
            arrow_pen = QPen(QColor(0, 0, 255))
            arrow_pen.setWidth(2)
            arrow_brush = QBrush(QColor(0, 0, 255))
            # Up-pointing triangle as arrow; rotate if heading exists
            poly = QPolygonF([QPointF(-10, 6), QPointF(0, -16), QPointF(10, 6)])
            item = self.map_scene.addPolygon(poly, arrow_pen, arrow_brush)
            item.setPos(gx, gy)
            item.setZValue(1000)
            heading = getattr(gps, 'heading', None)
            if heading is not None:
                item.setRotation(-heading)
            # Lock scene rect and center on current GPS arrow to ensure visibility
            if hasattr(self, '_scene_rect'):
                self.map_scene.setSceneRect(self._scene_rect)
            self.map_view.centerOn(gx, gy)
        elif hasattr(self, '_scene_rect'):
            self.map_scene.setSceneRect(self._scene_rect)

    def update_checkpoints(self, checkpoints):
        current_count = self.tree_checkpoints.topLevelItemCount()
        new_count = len(checkpoints)
        if current_count != new_count:
            self.tree_checkpoints.clear()
            for cp in checkpoints:
                item = QTreeWidgetItem(self.tree_checkpoints)
                self._set_checkpoint_item(item, cp)
        else:
            for i in range(new_count):
                item = self.tree_checkpoints.topLevelItem(i)
                self._set_checkpoint_item(item, checkpoints[i])

    def _set_checkpoint_item(self, item, cp):
        item.setText(0, cp.get('name', 'Unknown'))
        item.setText(1, "必经" if cp.get('required') else "参考")
        passed = cp.get('passed', False)
        item.setText(2, "✔ 已通过" if passed else "...")
        if passed:
            item.setForeground(2, QColor("green"))
        else:
            item.setForeground(2, QColor("black"))
        time_str = cp.get('passed_at', "")
        if time_str:
            try:
                if 'T' in time_str:
                    dt = datetime.fromisoformat(time_str)
                    time_str = dt.strftime("%H:%M:%S")
            except:
                pass
        item.setText(3, time_str)

    def update_queue(self):
        # This can be optimized to not clear every time
        # Get all tasks from task manager
        tm = self.system.task_manager
        
        self.tree_queue.clear()
        
        # 使用统一的方法获取所有任务状态
        all_tasks = tm.get_all_tasks_status()
        
        for task in all_tasks:
            item = QTreeWidgetItem(self.tree_queue)
            
            task_id = task.get('task_id', '')
            state = task.get('state', 'pending')
            name = task.get('name', task.get('condition', 'Unknown'))
            
            # Translate state for display if needed
            display_state = state
            if state == 'pending': display_state = '等待开始'
            elif state == 'in_progress': display_state = '进行中'
            elif state == 'completed' or state == '已完成': display_state = '已完成'
            elif state == 'skipped': display_state = '已跳过'
            elif state == 'manual_completed' or state == '人工完成': display_state = '人工完成'
            elif state == 'not_started': display_state = '未开始'
            
            laps_comp = task.get('laps_completed', 0)
            req_laps = task.get('required_laps', 1)
            
            if 'laps_completed' in task and 'required_laps' in task:
                lap_display = f" | 圈数: {laps_comp} / {req_laps}"
                name = f"{name}{lap_display}"
                
            # 修正状态文字：如果圈数>0且当前显示为未开始或等待开始，修正显示为“等待开始下一圈”
            if display_state in ['未开始', '等待开始'] and laps_comp > 0:
                display_state = '等待开始下一圈'
                state = 'waiting_next_lap'  # Adjust state code for UI logic
            
            item.setText(0, display_state)
            item.setText(1, name)
            item.setText(2, task_id)
            
            # Colors
            if state in ['pending', 'waiting_next_lap']:
                # User requested blue for pending "等待开始"
                for col in range(3):
                    item.setForeground(col, QColor("blue"))
            elif state == 'in_progress':
                 # Highlight background for running task
                 for col in range(3):
                     item.setBackground(col, QColor("#e6f3ff"))
                     item.setForeground(col, QColor("blue"))
                     item.setFont(col, QFont("Arial", 10, QFont.Bold))
            elif state == 'completed' or state == 'manual_completed' or state == '已完成' or state == '人工完成':
                for col in range(3):
                    item.setForeground(col, QColor("green"))
            elif state == 'skipped':
                for col in range(3):
                    item.setForeground(col, QColor("gray"))
                    
    def show_task_details(self, item, column):
        task_id = item.text(2)
        tm = self.system.task_manager
        
        # Try finding in task_map first
        task_info = tm.task_map.get(task_id)
        
        # If not found (e.g. traditional mode), search in pending/completed
        if not task_info:
            all_tasks = tm.get_all_tasks_status()
            for t in all_tasks:
                if t.get('task_id') == task_id:
                    task_info = t
                    break
        
        if task_info:
            dialog = TaskDetailDialog(task_info, self)
            dialog.exec_()

    def open_settings(self):
        dialog = ConfigDialog(self.config_path, self)
        dialog.exec_()

    def reset_tasks(self):
        reply = QMessageBox.question(self, "确认", "确定要重置所有任务状态吗？\n这将清除所有已完成的记录。",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            logger.info("User requested task reset")
            self.system.task_manager.reset_all_tasks_status()
            
            # Ensure UI is updated immediately
            self.system.task_manager.ensure_monitor_selected()
            self.update_queue()
            
            # Reset UI displays
            if self.system.task_manager.current_monitor:
                 info = self.system.task_manager.current_monitor.get_progress_info()
                 self.update_ui(None, {'current_task': info})
            else:
                 # Fallback clear
                 self.lbl_current_task.setText("等待开始...")
                 self.lbl_current_desc.setText("")
                 self.lbl_laps.setText("圈数: -- / --")
                 self.map_scene.clear()
                 self.tree_checkpoints.clear()
            
            QMessageBox.information(self, "成功", "任务已重置")

    def skip_current(self):
        if not self.system.task_manager.current_monitor:
            return
        reply = QMessageBox.question(self, "确认", "确定要跳过当前工况吗？",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            logger.info("User requested skip current task")
            self.system.task_manager.skip_current(reason="用户手动跳过", requeue=True)

    def manual_complete(self):
        if not self.system.task_manager.current_monitor:
            return
        reply = QMessageBox.question(self, "确认", "确定要手动完成当前工况吗？",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            logger.info("User requested manual completion")
            self.system.task_manager.complete_current(reason="用户手动完成")

    def import_task(self):
        QMessageBox.information(self, "提示", "功能预留: 接收任务文件")

    def export_status(self):
        QMessageBox.information(self, "提示", "功能预留: 发送工况文件")

    def closeEvent(self, event):
        reply = QMessageBox.question(self, "退出", "确定要退出程序吗？",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            logger.info("Application closing by user request")
            self.system.cleanup()
            event.accept()
        else:
            event.ignore()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion")) # Modern look
    
    # Increase font size globally
    font = QFont("Arial", 10)
    app.setFont(font)
    
    window = MainWindow()
    # Default to maximized (fullscreen)
    window.showMaximized()
    sys.exit(app.exec_())
