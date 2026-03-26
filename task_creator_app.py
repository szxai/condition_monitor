import sys
import os
import json
import csv
import pandas as pd
from datetime import datetime
from pathlib import Path

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, 
                             QMessageBox, QFileDialog, QGroupBox, QFormLayout, QLineEdit, 
                             QComboBox, QTextEdit, QSplitter, QStyleFactory)
from PyQt5.QtCore import Qt

# --- Configuration Paths ---
# Determine paths relative to this script
CURRENT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = CURRENT_DIR / "config"
REF_POS_DIR = CURRENT_DIR / "referencePosition"

# Target Files
TASKS_LIST_FILE = CONFIG_DIR / "tasks_list.json"
CONDITIONS_FILE = REF_POS_DIR / "ConditionExtendedTemplate.csv"

class TaskCreatorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("工况任务列表生成器 (Task List Generator)")
        self.resize(1200, 800)
        
        self.conditions = {}  # {condition_id: description}
        self.tasks = []       # List of dicts
        
        self.load_conditions()
        self.init_ui()
        self.load_existing_tasks()

    def read_csv_safely(self, file_path):
        """尝试使用多种编码（utf-8, gbk, utf-8-sig）读取 CSV 文件"""
        for encoding in ['utf-8', 'gbk', 'utf-8-sig', 'cp936']:
            try:
                return pd.read_csv(file_path, encoding=encoding)
            except (UnicodeDecodeError, Exception):
                continue
        # 如果都失败，尝试使用系统默认编码
        return pd.read_csv(file_path)

    def load_conditions(self):
        """Load available conditions from CSV template"""
        if not CONDITIONS_FILE.exists():
            QMessageBox.warning(self, "警告", f"找不到工况定义文件:\n{CONDITIONS_FILE}")
            return
            
        try:
            import re
            # Try reading with pandas for robustness
            df = self.read_csv_safely(CONDITIONS_FILE)
            
            # Check for required columns
            if 'Condition' in df.columns:
                for _, row in df.iterrows():
                    raw_id = str(row['Condition']).strip()
                    desc = str(row['Description']).strip() if 'Description' in df.columns else ""
                    
                    # 使用与主程序相同的正则剥离逻辑，将 TW-1, D16-2 统一为基础名称
                    match = re.search(r'-\d+$', raw_id)
                    if match:
                        cond_id = raw_id[:match.start()]
                        # 如果没有描述，可以保留原始名称作为描述
                        if not desc:
                            desc = raw_id
                    else:
                        cond_id = raw_id
                        
                    # 由于剥离了后缀，多个 TW-1, TW-2 都会变成 TW。
                    # 为了防止描述被后来的覆盖为空，我们只在尚未存在或者已有描述较短时才更新描述
                    if cond_id not in self.conditions or len(self.conditions[cond_id]) < len(desc):
                        self.conditions[cond_id] = desc
            else:
                QMessageBox.warning(self, "警告", "工况定义文件缺少 'Condition' 列")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载工况定义失败:\n{e}")

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        
        # --- Left Panel: Task List ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        splitter.addWidget(left_panel)
        
        # Toolbar
        toolbar_layout = QHBoxLayout()
        btn_new = QPushButton("➕ 新建任务")
        btn_new.clicked.connect(self.add_task)
        btn_del = QPushButton("➖ 删除任务")
        btn_del.clicked.connect(self.delete_task)
        btn_up = QPushButton("⬆ 上移")
        btn_up.clicked.connect(self.move_up)
        btn_down = QPushButton("⬇ 下移")
        btn_down.clicked.connect(self.move_down)
        
        toolbar_layout.addWidget(btn_new)
        toolbar_layout.addWidget(btn_del)
        toolbar_layout.addWidget(btn_up)
        toolbar_layout.addWidget(btn_down)
        toolbar_layout.addStretch()
        left_layout.addLayout(toolbar_layout)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Task ID", "Condition ID", "任务名称", "描述"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        left_layout.addWidget(self.table)
        
        # File Operations
        file_ops_layout = QHBoxLayout()
        btn_import = QPushButton("📥 导入模板 (Excel/CSV)")
        btn_import.clicked.connect(self.import_template)
        btn_save = QPushButton("💾 保存到配置文件")
        btn_save.setStyleSheet("font-weight: bold; color: blue;")
        btn_save.clicked.connect(self.save_to_json)
        
        file_ops_layout.addWidget(btn_import)
        file_ops_layout.addStretch()
        file_ops_layout.addWidget(btn_save)
        left_layout.addLayout(file_ops_layout)
        
        # --- Right Panel: Task Editor ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        splitter.addWidget(right_panel)
        
        editor_group = QGroupBox("任务编辑 (Task Editor)")
        form_layout = QFormLayout()
        
        self.edit_task_id = QLineEdit()
        self.edit_task_id.setPlaceholderText("例如: TASK-001")
        self.edit_task_id.editingFinished.connect(self.update_current_task)
        
        self.combo_condition = QComboBox()
        self.combo_condition.addItems(sorted(self.conditions.keys()))
        self.combo_condition.currentTextChanged.connect(self.on_condition_changed)
        
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("任务显示名称")
        self.edit_name.editingFinished.connect(self.update_current_task)
        
        self.edit_desc = QTextEdit()
        self.edit_desc.setPlaceholderText("任务详细描述")
        self.edit_desc.setMaximumHeight(100)
        self.edit_desc.textChanged.connect(self.update_current_task_desc)
        
        form_layout.addRow("Task ID:", self.edit_task_id)
        form_layout.addRow("工况 (Condition):", self.combo_condition)
        form_layout.addRow("名称 (Name):", self.edit_name)
        form_layout.addRow("描述 (Description):", self.edit_desc)
        
        editor_group.setLayout(form_layout)
        right_layout.addWidget(editor_group)
        right_layout.addStretch()
        
        # Set Splitter Ratio
        splitter.setSizes([800, 400])

    def load_existing_tasks(self):
        if not TASKS_LIST_FILE.exists():
            return
            
        try:
            with open(TASKS_LIST_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            tasks_map = {t['task_id']: t for t in data.get('tasks', [])}
            execution_order = data.get('execution_order', [])
            
            self.tasks = []
            # Add tasks in order
            for tid in execution_order:
                if tid in tasks_map:
                    self.tasks.append(tasks_map[tid])
            
            # Add any tasks not in execution order (just in case)
            for tid, t in tasks_map.items():
                if tid not in execution_order:
                    self.tasks.append(t)
                    
            self.refresh_table()
            
        except Exception as e:
            QMessageBox.warning(self, "警告", f"读取现有任务列表失败:\n{e}")

    def refresh_table(self):
        current_row = self.table.currentRow()
        self.table.setRowCount(0)
        for row, task in enumerate(self.tasks):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(task.get('task_id', '')))
            self.table.setItem(row, 1, QTableWidgetItem(task.get('condition_id', '')))
            self.table.setItem(row, 2, QTableWidgetItem(task.get('name', '')))
            self.table.setItem(row, 3, QTableWidgetItem(task.get('description', '')))
        
        # Restore selection if possible
        if self.tasks:
            if current_row >= 0 and current_row < len(self.tasks):
                self.table.selectRow(current_row)
            else:
                self.table.selectRow(len(self.tasks)-1)

    def add_task(self):
        # Generate new ID
        idx = 1
        while True:
            new_id = f"TASK-{idx:03d}"
            if not any(t['task_id'] == new_id for t in self.tasks):
                break
            idx += 1
            
        new_task = {
            "task_id": new_id,
            "condition_id": self.combo_condition.currentText() if self.combo_condition.count() > 0 else "",
            "name": "新任务",
            "description": ""
        }
        self.tasks.append(new_task)
        self.refresh_table()
        self.table.selectRow(len(self.tasks)-1)

    def delete_task(self):
        row = self.table.currentRow()
        if row >= 0:
            del self.tasks[row]
            self.refresh_table()

    def move_up(self):
        row = self.table.currentRow()
        if row > 0:
            self.tasks[row], self.tasks[row-1] = self.tasks[row-1], self.tasks[row]
            self.refresh_table()
            self.table.selectRow(row-1)

    def move_down(self):
        row = self.table.currentRow()
        if row < len(self.tasks) - 1 and row >= 0:
            self.tasks[row], self.tasks[row+1] = self.tasks[row+1], self.tasks[row]
            self.refresh_table()
            self.table.selectRow(row+1)

    def on_selection_changed(self):
        row = self.table.currentRow()
        if row >= 0 and row < len(self.tasks):
            task = self.tasks[row]
            self.block_signals(True)
            
            self.edit_task_id.setText(task.get('task_id', ''))
            
            cond_id = task.get('condition_id', '')
            idx = self.combo_condition.findText(cond_id)
            if idx >= 0:
                self.combo_condition.setCurrentIndex(idx)
                
            self.edit_name.setText(task.get('name', ''))
            self.edit_desc.setText(task.get('description', ''))
            
            self.block_signals(False)

    def block_signals(self, block):
        self.edit_task_id.blockSignals(block)
        self.combo_condition.blockSignals(block)
        self.edit_name.blockSignals(block)
        self.edit_desc.blockSignals(block)

    def update_current_task(self):
        row = self.table.currentRow()
        if row >= 0 and row < len(self.tasks):
            self.tasks[row]['task_id'] = self.edit_task_id.text()
            self.tasks[row]['name'] = self.edit_name.text()
            self.tasks[row]['description'] = self.edit_desc.toPlainText()
            
            self.table.setItem(row, 0, QTableWidgetItem(self.tasks[row]['task_id']))
            self.table.setItem(row, 2, QTableWidgetItem(self.tasks[row]['name']))
            self.table.setItem(row, 3, QTableWidgetItem(self.tasks[row]['description']))

    def update_current_task_desc(self):
        # Separate slot for text changed to avoid lag or focus issues if needed
        self.update_current_task()

    def on_condition_changed(self, text):
        row = self.table.currentRow()
        if row >= 0 and row < len(self.tasks):
            self.tasks[row]['condition_id'] = text
            
            # 获取工况描述
            desc = self.conditions.get(text, "")
            
            # 自动填充描述 (如果描述为空)
            if not self.tasks[row].get('description'):
                self.tasks[row]['description'] = desc
                self.edit_desc.setText(desc)
                self.table.setItem(row, 3, QTableWidgetItem(desc))
            
            # 强制更新名称 (Name) 为工况描述 (Description)，实现绑定关系
            self.tasks[row]['name'] = desc
            self.edit_name.setText(desc)
            self.table.setItem(row, 2, QTableWidgetItem(desc))
            
            self.table.setItem(row, 1, QTableWidgetItem(text))

    def import_template(self):
        filename, _ = QFileDialog.getOpenFileName(self, "导入模板", "", "Excel/CSV Files (*.xlsx *.xls *.csv)")
        if not filename:
            return
            
        try:
            if filename.lower().endswith('.csv'):
                df = self.read_csv_safely(filename)
            else:
                df = pd.read_excel(filename)
            
            new_tasks = []
            # Find max current ID to continue numbering
            max_idx = 0
            for t in self.tasks:
                try:
                    idx = int(t['task_id'].split('-')[1])
                    if idx > max_idx: max_idx = idx
                except: pass
            
            current_idx = max_idx + 1
            
            for _, row in df.iterrows():
                # Flexible column mapping
                cond_id = None
                for col in ['Condition', 'ConditionID', 'Condition_ID', '工况', '工况ID']:
                    if col in df.columns and pd.notna(row[col]):
                        cond_id = str(row[col]).strip()
                        break
                
                if not cond_id:
                    continue
                    
                name = ""
                for col in ['Name', 'TaskName', '名称', '任务名称']:
                    if col in df.columns and pd.notna(row[col]):
                        name = str(row[col]).strip()
                        break
                if not name:
                    name = f"{cond_id} 任务"
                    
                desc = ""
                for col in ['Description', 'Desc', '描述', '说明']:
                    if col in df.columns and pd.notna(row[col]):
                        desc = str(row[col]).strip()
                        break
                if not desc:
                    desc = self.conditions.get(cond_id, "")
                    
                task_id = f"TASK-{current_idx:03d}"
                current_idx += 1
                
                new_tasks.append({
                    "task_id": task_id,
                    "condition_id": cond_id,
                    "name": name,
                    "description": desc
                })
            
            if new_tasks:
                reply = QMessageBox.question(self, "导入确认", f"解析到 {len(new_tasks)} 个任务，是否追加到列表？",
                                             QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    self.tasks.extend(new_tasks)
                    self.refresh_table()
                    QMessageBox.information(self, "成功", "导入完成")
            else:
                QMessageBox.warning(self, "警告", "未能在文件中找到有效的任务数据。\n请确保包含 'Condition'/'工况' 列。")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入失败:\n{e}")

    def save_to_json(self):
        if not self.tasks:
            QMessageBox.warning(self, "警告", "任务列表为空，无法保存")
            return
            
        try:
            # Ensure unique IDs
            ids = [t['task_id'] for t in self.tasks]
            if len(ids) != len(set(ids)):
                QMessageBox.warning(self, "错误", "存在重复的 Task ID，请修正后再保存")
                return
                
            data = {
                "tasks": self.tasks,
                "execution_order": [t['task_id'] for t in self.tasks],
                "metadata": {
                    "created_at": datetime.utcnow().isoformat() + "Z",
                    "version": "1.0",
                    "description": "Generated by Task Creator App"
                }
            }
            
            # Backup existing
            if TASKS_LIST_FILE.exists():
                backup_name = TASKS_LIST_FILE.with_suffix(f".bak_{datetime.now().strftime('%Y%m%d%H%M%S')}.json")
                try:
                    import shutil
                    shutil.copy2(TASKS_LIST_FILE, backup_name)
                except:
                    pass
            
            with open(TASKS_LIST_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
            QMessageBox.information(self, "成功", f"任务列表已保存至:\n{TASKS_LIST_FILE}")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败:\n{e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))
    
    # Increase font size
    font = app.font()
    font.setPointSize(10)
    app.setFont(font)
    
    window = TaskCreatorApp()
    window.show()
    
    sys.exit(app.exec_())
