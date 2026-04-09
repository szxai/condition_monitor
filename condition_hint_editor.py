import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainterPath, QPen, QBrush
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyleFactory,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from utils.condition_parser import ConditionParser


CURRENT_DIR = Path(__file__).resolve().parent
DEFAULT_CONDITION_FILE = CURRENT_DIR / "referencePosition" / "ConditionExtendedTemplate.csv"

TRACK_COLORS = [
    QColor("#1f77b4"),
    QColor("#d62728"),
    QColor("#2ca02c"),
    QColor("#9467bd"),
    QColor("#ff7f0e"),
    QColor("#17becf"),
]
DEFAULT_HALF_SPAN = "0.00005"
BASE_POINT_TABLE_HEADERS = [
    "目标",
    "类型",
    "LonLB",
    "LonUB",
    "LatLB",
    "LatUB",
    "参数",
    "默认提示",
]


@dataclass
class TrackPoint:
    longitude: float
    latitude: float
    timestamp: str


@dataclass
class TrackData:
    file_path: Path
    points: List[TrackPoint]
    color: QColor


@dataclass
class PointEntry:
    prefix: str
    point_type: str
    param_key: str = ""
    param_value: str = ""
    hints_enabled: bool = True


class MapView(QGraphicsView):
    mouse_moved = pyqtSignal(float, float)
    mouse_clicked = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._transformer = None

    def set_transformer(self, transformer):
        self._transformer = transformer

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if not self._transformer:
            return
        scene_pos = self.mapToScene(event.pos())
        lon, lat = self._transformer.scene_to_geo(scene_pos.x(), scene_pos.y())
        self.mouse_moved.emit(lon, lat)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if not self._transformer:
            return
        scene_pos = self.mapToScene(event.pos())
        lon, lat = self._transformer.scene_to_geo(scene_pos.x(), scene_pos.y())
        self.mouse_clicked.emit(lon, lat)


class GeoTransformer:
    def __init__(self):
        self.center_lon = 0.0
        self.center_lat = 0.0
        self.scale_x = 1.0
        self.scale_y = 1.0

    def configure(self, min_lon: float, max_lon: float, min_lat: float, max_lat: float, width: int, height: int):
        self.center_lon = (min_lon + max_lon) / 2.0
        self.center_lat = (min_lat + max_lat) / 2.0
        span_lon = max(0.0001, max_lon - min_lon)
        span_lat = max(0.0001, max_lat - min_lat)
        self.scale_x = (max(width, 1) * 0.85) / span_lon
        self.scale_y = (max(height, 1) * 0.85) / span_lat

    def geo_to_scene(self, lon: float, lat: float) -> Tuple[float, float]:
        x = (lon - self.center_lon) * self.scale_x
        y = (lat - self.center_lat) * (-self.scale_y)
        return x, y

    def scene_to_geo(self, x: float, y: float) -> Tuple[float, float]:
        lon = (x / self.scale_x) + self.center_lon
        lat = self.center_lat - (y / self.scale_y)
        return lon, lat


class ConditionHintEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("工况提示与点位编辑器")
        self.resize(1700, 950)

        self.condition_file = DEFAULT_CONDITION_FILE
        self.condition_encoding = "utf-8"
        self.condition_df = pd.DataFrame()
        self.filtered_row_indices: List[int] = []
        self.selected_row_index: Optional[int] = None
        self.track_data: List[TrackData] = []
        self.selected_track_point: Optional[TrackPoint] = None
        self.selected_track_name: str = ""
        self.box_select_mode = False
        self.box_first_point: Optional[TrackPoint] = None
        self.last_box_points: Optional[Tuple[TrackPoint, TrackPoint]] = None
        self.hover_track_point: Optional[TrackPoint] = None
        self.transformer = GeoTransformer()
        self._populating_table = False
        self.current_lap_hint_suffixes: List[str] = []

        self.init_ui()
        self.load_condition_file(self.condition_file)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)

        toolbar_layout = QHBoxLayout()
        self.lbl_file = QLabel(f"工况文件: {self.condition_file}")
        self.lbl_file.setWordWrap(True)
        toolbar_layout.addWidget(self.lbl_file, 1)

        btn_open_condition = QPushButton("打开工况 CSV")
        btn_open_condition.clicked.connect(self.choose_condition_file)
        toolbar_layout.addWidget(btn_open_condition)

        btn_add_tracks = QPushButton("加载轨迹 CSV")
        btn_add_tracks.clicked.connect(self.add_track_files)
        toolbar_layout.addWidget(btn_add_tracks)

        btn_clear_tracks = QPushButton("清空轨迹")
        btn_clear_tracks.clicked.connect(self.clear_tracks)
        toolbar_layout.addWidget(btn_clear_tracks)

        btn_save = QPushButton("保存到工况 CSV")
        btn_save.setStyleSheet("font-weight: bold; color: blue;")
        btn_save.clicked.connect(self.save_condition_file)
        toolbar_layout.addWidget(btn_save)

        root_layout.addLayout(toolbar_layout)

        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        splitter.addWidget(left_panel)

        search_group = QGroupBox("工况列表")
        search_layout = QVBoxLayout()
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("搜索工况名称或描述")
        self.edit_search.textChanged.connect(self.refresh_condition_list)
        search_layout.addWidget(self.edit_search)

        self.list_conditions = QListWidget()
        self.list_conditions.currentRowChanged.connect(self.on_condition_selected)
        search_layout.addWidget(self.list_conditions)
        search_group.setLayout(search_layout)
        left_layout.addWidget(search_group)

        track_group = QGroupBox("已加载轨迹")
        track_layout = QVBoxLayout()
        self.list_tracks = QListWidget()
        track_layout.addWidget(self.list_tracks)
        track_group.setLayout(track_layout)
        left_layout.addWidget(track_group)

        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        splitter.addWidget(center_panel)

        map_group = QGroupBox("轨迹地图")
        map_layout = QVBoxLayout()
        self.map_scene = QGraphicsScene()
        self.map_view = MapView()
        self.map_view.setScene(self.map_scene)
        self.map_view.set_transformer(self.transformer)
        self.map_view.mouse_moved.connect(self.on_map_mouse_moved)
        self.map_view.mouse_clicked.connect(self.on_map_clicked)
        map_layout.addWidget(self.map_view)

        self.lbl_mouse_geo = QLabel("鼠标位置: --")
        map_layout.addWidget(self.lbl_mouse_geo)
        self.lbl_selected_geo = QLabel("地图选点: --")
        self.lbl_selected_geo.setWordWrap(True)
        map_layout.addWidget(self.lbl_selected_geo)
        map_group.setLayout(map_layout)
        center_layout.addWidget(map_group)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        splitter.addWidget(right_panel)

        info_group = QGroupBox("当前工况")
        info_layout = QVBoxLayout()
        self.lbl_condition_name = QLabel("工况: --")
        self.lbl_condition_name.setFont(QFont("Arial", 12, QFont.Bold))
        info_layout.addWidget(self.lbl_condition_name)
        self.lbl_condition_desc = QLabel("描述: --")
        self.lbl_condition_desc.setWordWrap(True)
        info_layout.addWidget(self.lbl_condition_desc)

        laps_layout = QHBoxLayout()
        laps_layout.addWidget(QLabel("工况圈数:"))
        self.edit_required_laps = QLineEdit("1")
        self.edit_required_laps.setMaximumWidth(80)
        self.edit_required_laps.editingFinished.connect(self.on_required_laps_changed)
        laps_layout.addWidget(self.edit_required_laps)
        laps_layout.addWidget(QLabel("地图框选:"))
        self.btn_box_mode = QPushButton("开启框选")
        self.btn_box_mode.clicked.connect(self.toggle_box_select_mode)
        laps_layout.addWidget(self.btn_box_mode)
        btn_clear_box = QPushButton("清除框选")
        btn_clear_box.clicked.connect(self.clear_box_selection)
        laps_layout.addWidget(btn_clear_box)
        laps_layout.addStretch()
        info_layout.addLayout(laps_layout)
        info_group.setLayout(info_layout)
        right_layout.addWidget(info_group)

        editor_group = QGroupBox("点位与提示编辑")
        editor_layout = QVBoxLayout()

        point_toolbar = QHBoxLayout()
        btn_add_waypoint = QPushButton("新增 Waypoint")
        btn_add_waypoint.clicked.connect(lambda: self.add_dynamic_point("Waypoint"))
        point_toolbar.addWidget(btn_add_waypoint)

        btn_add_loop = QPushButton("新增 LoopZone")
        btn_add_loop.clicked.connect(lambda: self.add_dynamic_point("LoopZone"))
        point_toolbar.addWidget(btn_add_loop)

        btn_delete = QPushButton("清空所选点位")
        btn_delete.clicked.connect(self.clear_selected_point)
        point_toolbar.addWidget(btn_delete)

        point_toolbar.addWidget(QLabel("半宽度:"))
        self.edit_half_span = QLineEdit(DEFAULT_HALF_SPAN)
        self.edit_half_span.setMaximumWidth(90)
        point_toolbar.addWidget(self.edit_half_span)

        btn_apply_map = QPushButton("将地图点写入所选行")
        btn_apply_map.clicked.connect(self.apply_selected_map_point_to_row)
        point_toolbar.addWidget(btn_apply_map)

        btn_apply_box = QPushButton("用两点成框写入所选行")
        btn_apply_box.clicked.connect(self.apply_box_points_to_current_row)
        point_toolbar.addWidget(btn_apply_box)
        editor_layout.addLayout(point_toolbar)

        self.table_hints = QTableWidget()
        self.rebuild_table_columns(1)
        self.table_hints.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_hints.setSelectionMode(QTableWidget.SingleSelection)
        self.table_hints.itemChanged.connect(self.on_table_item_changed)
        self.table_hints.itemSelectionChanged.connect(self.redraw_map)
        editor_layout.addWidget(self.table_hints)
        editor_group.setLayout(editor_layout)
        right_layout.addWidget(editor_group)

        help_group = QGroupBox("使用说明")
        help_layout = QVBoxLayout()
        help_text = QLabel(
            "1. 加载一个或多个 GPS 轨迹 CSV，地图会叠加显示。\n"
            "2. 左侧选择工况，右侧表格可同时编辑起点/终点/Waypoint/LoopZone 的坐标与提示。\n"
            "3. 点地图后会自动吸附到最近轨迹点，再用“将地图点写入所选行”更新区域。\n"
            "4. 开启地图框选后，连续点击两个轨迹点可直接生成矩形区域。\n"
            "5. 工况圈数会控制当前显示的圈次提示列，循环区次数可在参数列中修改。\n"
            "6. 新增 Waypoint / LoopZone 后，可继续扩展更多点位，保存会直接回写工况 CSV。"
        )
        help_text.setWordWrap(True)
        help_layout.addWidget(help_text)
        help_group.setLayout(help_layout)
        right_layout.addWidget(help_group)

        splitter.setSizes([300, 850, 650])

    def choose_condition_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择工况 CSV",
            str(self.condition_file.parent),
            "CSV Files (*.csv)"
        )
        if file_path:
            self.load_condition_file(Path(file_path))

    def load_condition_file(self, file_path: Path):
        try:
            self.condition_df, self.condition_encoding = self.read_csv_safely(file_path)
            self.condition_file = Path(file_path)
            self.lbl_file.setText(f"工况文件: {self.condition_file}")
            self.ensure_required_columns()
            self.refresh_condition_list()
        except Exception as exc:
            QMessageBox.critical(self, "错误", f"加载工况文件失败:\n{exc}")

    def read_csv_safely(self, file_path: Path):
        for encoding in ["utf-8-sig", "gbk", "utf-8", "cp936"]:
            try:
                df = pd.read_csv(file_path, encoding=encoding, dtype=str, keep_default_na=False)
                return df, encoding
            except UnicodeDecodeError:
                continue
        df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
        return df, "utf-8"

    def ensure_required_columns(self):
        base_columns = [
            "Condition", "Description", "Group", "Priority",
            "Ref_Time_Min", "Ref_Time", "Ref_Time_Max", "RequiredLaps",
            "Start_LonLB", "Start_LonUB", "Start_LatLB", "Start_LatUB",
            "End_LonLB", "End_LonUB", "End_LatLB", "End_LatUB",
        ]
        for column in base_columns:
            if column not in self.condition_df.columns:
                self.condition_df[column] = ""

        for prefix in ["Feature1", "Feature2", "Feature3"]:
            self.ensure_prefix_columns(prefix, "checkpoint")

        for prefix in self.collect_existing_prefixes("Waypoint"):
            self.ensure_prefix_columns(prefix, "checkpoint")
        for prefix in self.collect_existing_prefixes("LoopZone"):
            self.ensure_prefix_columns(prefix, "loop")
        if "Prestart_Hint" not in self.condition_df.columns:
            self.condition_df["Prestart_Hint"] = ""

    def rebuild_table_columns(self, lap_count: int):
        self.current_lap_hint_suffixes = [f"Lap{lap:02d}_Hint" for lap in range(1, max(lap_count, 0) + 1)]
        headers = BASE_POINT_TABLE_HEADERS + [f"第{lap}圈" for lap in range(1, len(self.current_lap_hint_suffixes) + 1)]
        self.table_hints.setColumnCount(len(headers))
        self.table_hints.setHorizontalHeaderLabels(headers)
        header = self.table_hints.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        for index in range(2, 7):
            header.setSectionResizeMode(index, QHeaderView.ResizeToContents)
        if self.table_hints.columnCount() > 7:
            header.setSectionResizeMode(7, QHeaderView.Stretch)
        for index in range(8, self.table_hints.columnCount()):
            header.setSectionResizeMode(index, QHeaderView.Stretch)

    def get_visible_lap_count(self, row) -> int:
        required_laps = self.parse_positive_int(row.get("RequiredLaps", "1"), 1)
        max_loop_count = 0
        for prefix in self.collect_row_prefixes(row, "LoopZone"):
            max_loop_count = max(max_loop_count, self.parse_positive_int(row.get(f"{prefix}_Count", "0"), 0))
        return max(required_laps, max_loop_count, self.find_existing_lap_hint_count(row))

    def find_existing_lap_hint_count(self, row) -> int:
        max_lap = 0
        for key, value in row.items():
            if not str(value).strip():
                continue
            match = re.match(r"^.+_Lap(\d+)_Hint$", str(key))
            if match:
                max_lap = max(max_lap, int(match.group(1)))
        return max_lap

    @staticmethod
    def parse_positive_int(value, default: int) -> int:
        try:
            parsed = int(str(value).strip())
            return parsed if parsed > 0 else default
        except (TypeError, ValueError):
            return default

    def refresh_condition_list(self):
        self.list_conditions.clear()
        self.filtered_row_indices = []
        keyword = self.edit_search.text().strip().lower()
        for row_idx, row in self.condition_df.iterrows():
            cond_name = str(row.get("Condition", "")).strip()
            desc = str(row.get("Description", "")).strip()
            searchable = f"{cond_name} {desc}".lower()
            if keyword and keyword not in searchable:
                continue
            item_text = cond_name if not desc else f"{cond_name} | {desc}"
            self.list_conditions.addItem(QListWidgetItem(item_text))
            self.filtered_row_indices.append(row_idx)

        if self.filtered_row_indices:
            self.list_conditions.setCurrentRow(0)
        else:
            self.selected_row_index = None
            self.table_hints.setRowCount(0)
            self.lbl_condition_name.setText("工况: --")
            self.lbl_condition_desc.setText("描述: --")
            self.redraw_map()

    def on_condition_selected(self, list_index: int):
        previous_row_index = self.selected_row_index
        if previous_row_index is not None:
            self.apply_table_to_dataframe(previous_row_index)

        if list_index < 0 or list_index >= len(self.filtered_row_indices):
            self.selected_row_index = None
            self.redraw_map()
            return

        self.selected_row_index = self.filtered_row_indices[list_index]
        row = self.condition_df.iloc[self.selected_row_index]
        self.lbl_condition_name.setText(f"工况: {row.get('Condition', '--')}")
        self.lbl_condition_desc.setText(f"描述: {row.get('Description', '--')}")
        self.edit_required_laps.setText(str(self.parse_positive_int(row.get("RequiredLaps", "1"), 1)))
        self.populate_point_table(row)
        self.redraw_map()

    def populate_point_table(self, row):
        entries = self.collect_point_entries(row)
        visible_lap_count = self.get_visible_lap_count(row)
        self._populating_table = True
        self.rebuild_table_columns(visible_lap_count)
        self.table_hints.setRowCount(len(entries))

        for row_idx, entry in enumerate(entries):
            self.set_readonly_item(row_idx, 0, entry.prefix)
            self.set_readonly_item(row_idx, 1, entry.point_type)
            self.set_edit_item(row_idx, 2, row.get(f"{entry.prefix}_LonLB", ""))
            self.set_edit_item(row_idx, 3, row.get(f"{entry.prefix}_LonUB", ""))
            self.set_edit_item(row_idx, 4, row.get(f"{entry.prefix}_LatLB", ""))
            self.set_edit_item(row_idx, 5, row.get(f"{entry.prefix}_LatUB", ""))
            self.set_edit_item(row_idx, 6, entry.param_value)

            if entry.prefix == "Prestart":
                for col in range(2, 7):
                    item = self.table_hints.item(row_idx, col)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setForeground(QColor("gray"))

            value = row.get(f"{entry.prefix}_Hint", "") if entry.hints_enabled else ""
            self.set_edit_item(row_idx, 7, value if entry.hints_enabled else "")
            if not entry.hints_enabled:
                item = self.table_hints.item(row_idx, 7)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setForeground(QColor("gray"))

            for offset, suffix in enumerate(self.current_lap_hint_suffixes, start=8):
                value = row.get(f"{entry.prefix}_{suffix}", "") if entry.hints_enabled else ""
                self.set_edit_item(row_idx, offset, value if entry.hints_enabled else "")
                if not entry.hints_enabled:
                    item = self.table_hints.item(row_idx, offset)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setForeground(QColor("gray"))

        self._populating_table = False
        if entries:
            self.table_hints.selectRow(0)

    def set_readonly_item(self, row, column, text):
        item = QTableWidgetItem(str(text))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table_hints.setItem(row, column, item)

    def set_edit_item(self, row, column, text):
        self.table_hints.setItem(row, column, QTableWidgetItem(str(text or "")))

    def collect_point_entries(self, row) -> List[PointEntry]:
        entries = [
            PointEntry("Prestart", "开始前提示", hints_enabled=True),
            PointEntry("Start", "起点", hints_enabled=False),
            PointEntry("End", "终点", hints_enabled=False),
        ]

        for prefix in ["Feature1", "Feature2", "Feature3"]:
            if self.row_has_prefix_data(row, prefix, include_hints=True):
                entries.append(
                    PointEntry(
                        prefix=prefix,
                        point_type="关键点",
                        param_key="Required",
                        param_value=row.get(f"{prefix}_Required", "TRUE") or "TRUE",
                        hints_enabled=True
                    )
                )

        for prefix in self.collect_row_prefixes(row, "Waypoint"):
            entries.append(
                PointEntry(
                    prefix=prefix,
                    point_type="Waypoint",
                    param_key="Required",
                    param_value=row.get(f"{prefix}_Required", "TRUE") or "TRUE",
                    hints_enabled=True
                )
            )

        for prefix in self.collect_row_prefixes(row, "LoopZone"):
            entries.append(
                PointEntry(
                    prefix=prefix,
                    point_type="循环区",
                    param_key="Count",
                    param_value=row.get(f"{prefix}_Count", "1") or "1",
                    hints_enabled=True
                )
            )

        return entries

    def collect_existing_prefixes(self, base_name: str) -> List[str]:
        pattern = re.compile(rf"^{re.escape(base_name)}(\d+)_(LonLB|Hint|Lap\d+_Hint)$")
        prefixes = []
        seen = set()
        for column in self.condition_df.columns:
            match = pattern.match(column)
            if not match:
                continue
            prefix = f"{base_name}{match.group(1)}"
            if prefix not in seen:
                seen.add(prefix)
                prefixes.append((int(match.group(1)), prefix))
        return [prefix for _, prefix in sorted(prefixes, key=lambda item: item[0])]

    def collect_row_prefixes(self, row, base_name: str) -> List[str]:
        return [
            prefix for prefix in self.collect_existing_prefixes(base_name)
            if self.row_has_prefix_data(row, prefix, include_hints=True)
        ]

    def row_has_prefix_data(self, row, prefix: str, include_hints: bool) -> bool:
        coord_keys = [f"{prefix}_LonLB", f"{prefix}_LonUB", f"{prefix}_LatLB", f"{prefix}_LatUB"]
        for key in coord_keys:
            if str(row.get(key, "")).strip():
                return True

        for suffix in ["Required", "Count", "Entries"]:
            if str(row.get(f"{prefix}_{suffix}", "")).strip():
                return True

        if include_hints:
            if str(row.get(f"{prefix}_Hint", "")).strip():
                return True
            for key, value in row.items():
                if re.match(rf"^{re.escape(prefix)}_Lap\d+_Hint$", str(key)) and str(value).strip():
                    return True
        return False

    def ensure_prefix_columns(self, prefix: str, point_kind: str):
        for axis in ["LonLB", "LonUB", "LatLB", "LatUB"]:
            column = f"{prefix}_{axis}"
            if column not in self.condition_df.columns:
                self.condition_df[column] = ""

        if point_kind == "checkpoint":
            required_col = f"{prefix}_Required"
            if required_col not in self.condition_df.columns:
                self.condition_df[required_col] = "TRUE"
        elif point_kind == "loop":
            count_col = f"{prefix}_Count"
            if count_col not in self.condition_df.columns:
                self.condition_df[count_col] = "1"

        hint_col = f"{prefix}_Hint"
        if hint_col not in self.condition_df.columns:
            self.condition_df[hint_col] = ""

    def add_dynamic_point(self, base_name: str):
        if self.selected_row_index is None:
            QMessageBox.warning(self, "提示", "请先选择一个工况")
            return

        row = self.condition_df.iloc[self.selected_row_index]
        existing = self.collect_row_prefixes(row, base_name)
        next_index = 1
        if existing:
            last_prefix = existing[-1]
            match = re.search(r"(\d+)$", last_prefix)
            if match:
                next_index = int(match.group(1)) + 1

        prefix = f"{base_name}{next_index:02d}"
        point_kind = "loop" if base_name == "LoopZone" else "checkpoint"
        self.ensure_prefix_columns(prefix, point_kind)

        if self.last_box_points:
            self.fill_prefix_box_from_two_points(self.selected_row_index, prefix, self.last_box_points[0], self.last_box_points[1])
        elif self.selected_track_point:
            self.fill_prefix_box(self.selected_row_index, prefix, self.selected_track_point.longitude, self.selected_track_point.latitude)
        else:
            for axis in ["LonLB", "LonUB", "LatLB", "LatUB"]:
                self.condition_df.at[self.selected_row_index, f"{prefix}_{axis}"] = ""

        self.condition_df.at[self.selected_row_index, f"{prefix}_{'Count' if point_kind == 'loop' else 'Required'}"] = (
            "1" if point_kind == "loop" else "TRUE"
        )
        self.populate_point_table(self.condition_df.iloc[self.selected_row_index])
        self.redraw_map()

    def clear_selected_point(self):
        if self.selected_row_index is None:
            return
        current_row = self.table_hints.currentRow()
        if current_row < 0:
            return
        prefix_item = self.table_hints.item(current_row, 0)
        type_item = self.table_hints.item(current_row, 1)
        if not prefix_item or not type_item:
            return

        prefix = prefix_item.text()
        point_type = type_item.text()
        if prefix in ["Start", "End"]:
            QMessageBox.warning(self, "提示", "起点和终点不建议直接清空，如需调整请修改坐标")
            return

        for axis in ["LonLB", "LonUB", "LatLB", "LatUB"]:
            self.condition_df.at[self.selected_row_index, f"{prefix}_{axis}"] = ""

        if point_type == "循环区":
            self.condition_df.at[self.selected_row_index, f"{prefix}_Count"] = ""
        else:
            self.condition_df.at[self.selected_row_index, f"{prefix}_Required"] = ""

        hint_col = f"{prefix}_Hint"
        if hint_col in self.condition_df.columns:
            self.condition_df.at[self.selected_row_index, hint_col] = ""
        for column in self.condition_df.columns:
            if re.match(rf"^{re.escape(prefix)}_Lap\d+_Hint$", str(column)):
                self.condition_df.at[self.selected_row_index, column] = ""

        self.populate_point_table(self.condition_df.iloc[self.selected_row_index])
        self.redraw_map()

    def on_table_item_changed(self, item):
        if self._populating_table or self.selected_row_index is None:
            return
        self.apply_table_to_dataframe(self.selected_row_index)
        selected_row = self.table_hints.currentRow()
        self.populate_point_table(self.condition_df.iloc[self.selected_row_index])
        if selected_row >= 0 and selected_row < self.table_hints.rowCount():
            self.table_hints.selectRow(selected_row)
        self.redraw_map()

    def on_required_laps_changed(self):
        if self.selected_row_index is None:
            return
        lap_count = self.parse_positive_int(self.edit_required_laps.text(), 1)
        self.condition_df.at[self.selected_row_index, "RequiredLaps"] = str(lap_count)
        self.edit_required_laps.setText(str(lap_count))
        self.populate_point_table(self.condition_df.iloc[self.selected_row_index])
        self.redraw_map()

    def toggle_box_select_mode(self):
        self.box_select_mode = not self.box_select_mode
        self.box_first_point = None
        self.hover_track_point = None
        self.btn_box_mode.setText("关闭框选" if self.box_select_mode else "开启框选")
        self.lbl_selected_geo.setText(
            "框选模式已开启：先点第一个角点，再移动鼠标预览，最后点第二个角点"
            if self.box_select_mode else
            "地图选点: --"
        )
        self.redraw_map()

    def clear_box_selection(self):
        self.box_first_point = None
        self.last_box_points = None
        self.hover_track_point = None
        if self.box_select_mode:
            self.lbl_selected_geo.setText("框选模式已开启：先点第一个角点，再移动鼠标预览，最后点第二个角点")
        self.redraw_map()

    def apply_box_points_to_current_row(self):
        if self.last_box_points:
            self.apply_box_to_current_row(self.last_box_points[0], self.last_box_points[1])
            if self.box_select_mode:
                self.lbl_selected_geo.setText("已使用最近框选区域写入当前点位")
            return
        if self.box_first_point is None or self.selected_track_point is None:
            QMessageBox.warning(self, "提示", "请先在框选模式下点击两个轨迹点")
            return
        self.apply_box_to_current_row(self.box_first_point, self.selected_track_point)
        self.box_first_point = None
        if self.box_select_mode:
            self.lbl_selected_geo.setText("框选完成，可继续点击两个点生成下一个区域")

    def apply_selected_map_point_to_row(self):
        if self.selected_row_index is None:
            QMessageBox.warning(self, "提示", "请先选择一个工况")
            return
        if self.selected_track_point is None:
            QMessageBox.warning(self, "提示", "请先在地图上点击一个轨迹点")
            return
        current_row = self.table_hints.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "提示", "请先在右侧表格中选择一行点位")
            return

        prefix_item = self.table_hints.item(current_row, 0)
        if not prefix_item:
            return
        prefix = prefix_item.text()
        self.fill_prefix_box(
            self.selected_row_index,
            prefix,
            self.selected_track_point.longitude,
            self.selected_track_point.latitude,
        )
        self.populate_point_table(self.condition_df.iloc[self.selected_row_index])
        self.table_hints.selectRow(current_row)
        self.redraw_map()

    def apply_box_to_current_row(self, first_point: TrackPoint, second_point: TrackPoint):
        if self.selected_row_index is None:
            QMessageBox.warning(self, "提示", "请先选择一个工况")
            return
        current_row = self.table_hints.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "提示", "请先在右侧表格中选择一行点位")
            return
        prefix_item = self.table_hints.item(current_row, 0)
        if not prefix_item:
            return
        prefix = prefix_item.text()
        self.last_box_points = (first_point, second_point)
        self.fill_prefix_box_from_two_points(self.selected_row_index, prefix, first_point, second_point)
        self.populate_point_table(self.condition_df.iloc[self.selected_row_index])
        self.table_hints.selectRow(current_row)
        self.redraw_map()

    def get_half_span(self) -> float:
        text = self.edit_half_span.text().strip() or DEFAULT_HALF_SPAN
        try:
            value = abs(float(text))
            return value if value > 0 else float(DEFAULT_HALF_SPAN)
        except ValueError:
            return float(DEFAULT_HALF_SPAN)

    def fill_prefix_box(self, row_index: int, prefix: str, lon: float, lat: float):
        half_span = self.get_half_span()
        self.condition_df.at[row_index, f"{prefix}_LonLB"] = f"{lon - half_span:.6f}"
        self.condition_df.at[row_index, f"{prefix}_LonUB"] = f"{lon + half_span:.6f}"
        self.condition_df.at[row_index, f"{prefix}_LatLB"] = f"{lat - half_span:.6f}"
        self.condition_df.at[row_index, f"{prefix}_LatUB"] = f"{lat + half_span:.6f}"

    def fill_prefix_box_from_two_points(self, row_index: int, prefix: str, first_point: TrackPoint, second_point: TrackPoint):
        self.condition_df.at[row_index, f"{prefix}_LonLB"] = f"{min(first_point.longitude, second_point.longitude):.6f}"
        self.condition_df.at[row_index, f"{prefix}_LonUB"] = f"{max(first_point.longitude, second_point.longitude):.6f}"
        self.condition_df.at[row_index, f"{prefix}_LatLB"] = f"{min(first_point.latitude, second_point.latitude):.6f}"
        self.condition_df.at[row_index, f"{prefix}_LatUB"] = f"{max(first_point.latitude, second_point.latitude):.6f}"

    def add_track_files(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择一个或多个 GPS CSV",
            str(self.condition_file.parent),
            "CSV Files (*.csv)"
        )
        if not file_paths:
            return

        load_errors = []
        for file_path in file_paths:
            try:
                points = self.load_track_points(Path(file_path))
                if not points:
                    load_errors.append(f"{Path(file_path).name}: 没有识别到有效轨迹点")
                    continue
                color = TRACK_COLORS[len(self.track_data) % len(TRACK_COLORS)]
                self.track_data.append(TrackData(Path(file_path), points, color))
            except Exception as exc:
                load_errors.append(f"{Path(file_path).name}: {exc}")

        self.refresh_track_list()
        self.redraw_map()

        if load_errors:
            QMessageBox.warning(self, "部分轨迹加载失败", "\n".join(load_errors))

    def load_track_points(self, file_path: Path) -> List[TrackPoint]:
        df, _ = self.read_csv_safely(file_path)
        lon_col = self.find_first_column(df.columns, [
            "GPS_Longtitude", "GPS_Longitude", "Longitude", "longitude", "Lon", "lon", "Lng", "lng"
        ])
        lat_col = self.find_first_column(df.columns, [
            "GPS_Latitude", "Latitude", "latitude", "Lat", "lat"
        ])
        time_col = self.find_first_column(df.columns, [
            "timestamp", "time", "Time", "gps_time", "GPS_Time"
        ])
        if not lon_col or not lat_col:
            raise ValueError("未找到经纬度列")

        points: List[TrackPoint] = []
        for _, row in df.iterrows():
            lon_text = str(row.get(lon_col, "")).strip()
            lat_text = str(row.get(lat_col, "")).strip()
            if not lon_text or not lat_text:
                continue
            try:
                points.append(
                    TrackPoint(
                        longitude=float(lon_text),
                        latitude=float(lat_text),
                        timestamp=str(row.get(time_col, "")).strip() if time_col else ""
                    )
                )
            except ValueError:
                continue
        return points

    @staticmethod
    def find_first_column(columns, candidates):
        column_set = set(columns)
        for candidate in candidates:
            if candidate in column_set:
                return candidate
        return None

    def refresh_track_list(self):
        self.list_tracks.clear()
        for track in self.track_data:
            item = QListWidgetItem(f"{track.file_path.name} ({len(track.points)} 点)")
            item.setForeground(track.color)
            self.list_tracks.addItem(item)

    def clear_tracks(self):
        self.track_data = []
        self.selected_track_point = None
        self.selected_track_name = ""
        self.refresh_track_list()
        self.redraw_map()

    def redraw_map(self):
        self.map_scene.clear()
        condition = self.get_selected_condition_definition()
        bounds = self.collect_bounds(condition)
        if not bounds:
            return

        min_lon, max_lon, min_lat, max_lat = bounds
        self.transformer.configure(
            min_lon, max_lon, min_lat, max_lat,
            self.map_view.viewport().width(),
            self.map_view.viewport().height()
        )

        self.draw_tracks()
        if condition:
            self.draw_condition(condition)
        self.draw_box_preview()
        self.draw_selected_track_point()
        self.fit_scene_rect(min_lon, max_lon, min_lat, max_lat)

    def get_selected_condition_definition(self):
        if self.selected_row_index is None:
            return None
        row = self.condition_df.iloc[self.selected_row_index].to_dict()
        try:
            return ConditionParser._parse_row(row)
        except Exception:
            return None

    def collect_bounds(self, condition) -> Optional[Tuple[float, float, float, float]]:
        points = []
        for track in self.track_data:
            for point in track.points:
                points.append((point.longitude, point.latitude))

        if condition:
            points.append((condition.start.lon_lb, condition.start.lat_lb))
            points.append((condition.start.lon_ub, condition.start.lat_ub))
            points.append((condition.end.lon_lb, condition.end.lat_lb))
            points.append((condition.end.lon_ub, condition.end.lat_ub))
            for checkpoint in condition.checkpoints:
                points.append((checkpoint.zone.lon_lb, checkpoint.zone.lat_lb))
                points.append((checkpoint.zone.lon_ub, checkpoint.zone.lat_ub))
            for loop_zone in condition.loop_zones:
                points.append((loop_zone.zone.lon_lb, loop_zone.zone.lat_lb))
                points.append((loop_zone.zone.lon_ub, loop_zone.zone.lat_ub))

        if not points:
            return None

        min_lon = min(p[0] for p in points)
        max_lon = max(p[0] for p in points)
        min_lat = min(p[1] for p in points)
        max_lat = max(p[1] for p in points)
        return min_lon, max_lon, min_lat, max_lat

    def fit_scene_rect(self, min_lon, max_lon, min_lat, max_lat):
        x1, y1 = self.transformer.geo_to_scene(min_lon, min_lat)
        x2, y2 = self.transformer.geo_to_scene(max_lon, max_lat)
        margin = 20
        left = min(x1, x2) - margin
        top = min(y1, y2) - margin
        width = abs(x2 - x1) + 2 * margin
        height = abs(y2 - y1) + 2 * margin
        self.map_scene.setSceneRect(left, top, width, height)

    def draw_tracks(self):
        for track in self.track_data:
            if len(track.points) < 2:
                continue
            path = QPainterPath()
            first_x, first_y = self.transformer.geo_to_scene(track.points[0].longitude, track.points[0].latitude)
            path.moveTo(first_x, first_y)
            for point in track.points[1:]:
                x, y = self.transformer.geo_to_scene(point.longitude, point.latitude)
                path.lineTo(x, y)
            pen = QPen(track.color)
            pen.setWidth(2)
            self.map_scene.addPath(path, pen)

    def draw_condition(self, condition):
        selected_prefix = self.get_selected_table_prefix()
        self.draw_zone("Start", "起点", condition.start, QColor("#2ca02c"), selected_prefix == "Start")
        self.draw_zone("End", "终点", condition.end, QColor("#d62728"), selected_prefix == "End")
        for checkpoint in condition.checkpoints:
            self.draw_zone(checkpoint.name, checkpoint.name, checkpoint.zone, QColor("#ff9800"), selected_prefix == checkpoint.name)
        for loop_zone in condition.loop_zones:
            self.draw_zone(loop_zone.name, loop_zone.name, loop_zone.zone, QColor("#9467bd"), selected_prefix == loop_zone.name)

    def draw_zone(self, prefix, label, zone, color, selected=False):
        x1, y1 = self.transformer.geo_to_scene(zone.lon_lb, zone.lat_lb)
        x2, y2 = self.transformer.geo_to_scene(zone.lon_ub, zone.lat_ub)
        left = min(x1, x2)
        top = min(y1, y2)
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        pen = QPen(color)
        pen.setWidth(3 if selected else 1)
        self.map_scene.addRect(left, top, width, height, pen)
        text_item = self.map_scene.addText(label)
        text_item.setDefaultTextColor(color)
        text_item.setPos(left, top - 18)

    def get_selected_table_prefix(self) -> str:
        current_row = self.table_hints.currentRow()
        if current_row < 0:
            return ""
        item = self.table_hints.item(current_row, 0)
        return item.text() if item else ""

    def draw_selected_track_point(self):
        if not self.selected_track_point:
            return
        x, y = self.transformer.geo_to_scene(self.selected_track_point.longitude, self.selected_track_point.latitude)
        radius = 5
        pen = QPen(QColor("#00bcd4"))
        pen.setWidth(2)
        brush = QBrush(QColor(0, 188, 212, 80))
        self.map_scene.addEllipse(x - radius, y - radius, radius * 2, radius * 2, pen, brush)

    def draw_box_preview(self):
        if self.box_first_point and self.hover_track_point and self.box_select_mode:
            first = self.box_first_point
            second = self.hover_track_point
        elif self.last_box_points:
            first, second = self.last_box_points
        else:
            return

        x1, y1 = self.transformer.geo_to_scene(first.longitude, first.latitude)
        x2, y2 = self.transformer.geo_to_scene(second.longitude, second.latitude)
        pen = QPen(QColor("#00bcd4"))
        pen.setStyle(Qt.DashLine)
        pen.setWidth(2)
        brush = QBrush(QColor(0, 188, 212, 35))
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        if width < 2 and height < 2:
            self.map_scene.addEllipse(x1 - 6, y1 - 6, 12, 12, pen, brush)
        else:
            self.map_scene.addRect(min(x1, x2), min(y1, y2), width, height, pen, brush)

    def on_map_mouse_moved(self, lon: float, lat: float):
        self.lbl_mouse_geo.setText(f"鼠标位置: {lat:.6f}, {lon:.6f}")
        if self.box_select_mode and self.box_first_point:
            self.hover_track_point = TrackPoint(lon, lat, "")
            self.redraw_map()

    def on_map_clicked(self, lon: float, lat: float):
        nearest = self.find_nearest_track_point(lon, lat)
        if not nearest:
            self.selected_track_name = "地图点击"
            self.selected_track_point = TrackPoint(lon, lat, "")
        else:
            file_name, point, distance = nearest
            self.selected_track_name = file_name
            self.selected_track_point = point
            time_text = point.timestamp or "--"
            self.lbl_selected_geo.setText(
                f"最近轨迹点: {file_name} | 时间: {time_text} | 坐标: {point.latitude:.6f}, {point.longitude:.6f} | 偏差平方: {distance:.8f}"
            )

        if self.box_select_mode and self.selected_track_point:
            if self.box_first_point is None:
                self.box_first_point = TrackPoint(
                    self.selected_track_point.longitude,
                    self.selected_track_point.latitude,
                    self.selected_track_point.timestamp
                )
                self.last_box_points = None
                self.hover_track_point = TrackPoint(
                    self.selected_track_point.longitude,
                    self.selected_track_point.latitude,
                    self.selected_track_point.timestamp
                )
                self.lbl_selected_geo.setText(
                    f"框选起点已记录: {self.box_first_point.latitude:.6f}, {self.box_first_point.longitude:.6f}"
                )
            else:
                second_point = TrackPoint(
                    self.selected_track_point.longitude,
                    self.selected_track_point.latitude,
                    self.selected_track_point.timestamp
                )
                self.last_box_points = (self.box_first_point, second_point)
                self.apply_box_to_current_row(self.box_first_point, second_point)
                self.box_first_point = None
                self.hover_track_point = None
                self.lbl_selected_geo.setText(
                    f"框选完成: {second_point.latitude:.6f}, {second_point.longitude:.6f}"
                )
        elif not nearest:
            self.lbl_selected_geo.setText(f"地图点: {lat:.6f}, {lon:.6f}")

        self.redraw_map()

    def find_nearest_track_point(self, lon: float, lat: float):
        best = None
        best_dist = None
        for track in self.track_data:
            for point in track.points:
                dist = (point.longitude - lon) ** 2 + (point.latitude - lat) ** 2
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best = (track.file_path.name, point, dist)
        return best

    def save_condition_file(self):
        if self.selected_row_index is not None:
            self.apply_table_to_dataframe(self.selected_row_index)

        try:
            self.condition_df.to_csv(self.condition_file, index=False, encoding=self.condition_encoding)
            QMessageBox.information(self, "成功", f"已保存到:\n{self.condition_file}")
        except Exception as exc:
            QMessageBox.critical(self, "错误", f"保存失败:\n{exc}")

    def apply_table_to_dataframe(self, row_index: int):
        existing_entries = self.collect_point_entries(self.condition_df.iloc[row_index])
        entry_map = {entry.prefix: entry for entry in existing_entries}

        for table_row in range(self.table_hints.rowCount()):
            prefix_item = self.table_hints.item(table_row, 0)
            type_item = self.table_hints.item(table_row, 1)
            if not prefix_item or not type_item:
                continue

            prefix = prefix_item.text()
            point_type = type_item.text()
            if prefix not in entry_map:
                entry_map[prefix] = PointEntry(prefix=prefix, point_type=point_type)

            if prefix not in ["Prestart"]:
                for column_offset, axis in zip(range(2, 6), ["LonLB", "LonUB", "LatLB", "LatUB"]):
                    item = self.table_hints.item(table_row, column_offset)
                    self.condition_df.at[row_index, f"{prefix}_{axis}"] = item.text().strip() if item else ""

            param_item = self.table_hints.item(table_row, 6)
            param_value = param_item.text().strip() if param_item else ""
            if point_type == "循环区":
                self.condition_df.at[row_index, f"{prefix}_Count"] = param_value
            elif prefix not in ["Start", "End", "Prestart"]:
                self.condition_df.at[row_index, f"{prefix}_Required"] = param_value or "TRUE"

            if prefix not in ["Start", "End"]:
                hint_item = self.table_hints.item(table_row, 7)
                self.condition_df.at[row_index, f"{prefix}_Hint"] = hint_item.text().strip() if hint_item else ""
                for col_idx, suffix in enumerate(self.current_lap_hint_suffixes, start=8):
                    item = self.table_hints.item(table_row, col_idx)
                    value = item.text().strip() if item else ""
                    column_name = f"{prefix}_{suffix}"
                    if column_name not in self.condition_df.columns:
                        self.condition_df[column_name] = ""
                    self.condition_df.at[row_index, column_name] = value


def main():
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))
    font = app.font()
    font.setPointSize(10)
    app.setFont(font)
    window = ConditionHintEditor()
    window.showMaximized()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
