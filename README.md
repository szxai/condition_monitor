# 工况监控系统（Condition Monitor）

本项目用于实时读取车辆 GPS 轨迹，按“工况定义”判断工况是否开始/进行/完成，并支持将多个工况按任务队列顺序调度执行（支持 CLI 与 PyQt 界面）。

## 快速开始

### 1) 安装依赖

```bash
pip install -r requirements.txt
```

如需启动 PyQt 界面：

```bash
pip install PyQt5
```

### 2) 启动方式

- 命令行模式（适合跑批/调试）：

```bash
python main.py
```

- 图形界面模式（推荐日常使用）：

```bash
python gui_main_qt.py
```

## 核心概念

### 工况定义（Condition CSV）

工况定义文件路径来自 [config.json](file:///c:/Users/77010/0_SAIC/03_HardwareDevelop/02_ConditionMonitor/config/config.json) 的：

- `conditions.file`

推荐使用 [ConditionExtendedTemplate.csv](file:///c:/Users/77010/0_SAIC/03_HardwareDevelop/02_ConditionMonitor/referencePosition/ConditionExtendedTemplate.csv) 模板。

- 工况 ID：CSV 的 `Condition` 列
- 工况名称：CSV 的 `Description` 列

界面“正在执行”区域会显示两行：第一行工况 ID（Condition），第二行工况名称（Description）。

### 任务列表（tasks_list.json：当日任务模板）

[tasks_list.json](file:///c:/Users/77010/0_SAIC/03_HardwareDevelop/02_ConditionMonitor/config/tasks_list.json) 只描述“当日需要跑哪些任务、顺序是什么”，是一个模板文件：

- 程序不会把运行状态写回此文件
- 文件中不需要（也不建议）包含 `state/start_time/end_time/completion_reason/manual_completion` 等运行字段

当前模板格式示例：

```json
{
  "tasks": [
    {
      "task_id": "TASK-001",
      "condition_id": "PV-PABC",
      "name": "比利时路工况测试",
      "description": "这是第一个测试工况的描述"
    }
  ],
  "execution_order": ["TASK-001"],
  "metadata": {
    "created_at": "2026-03-09T10:00:00Z",
    "version": "1.3",
    "description": "标准任务列表模板"
  }
}
```

### 任务状态（task_status.json：唯一实时状态源）

[task_status.json](file:///c:/Users/77010/0_SAIC/03_HardwareDevelop/02_ConditionMonitor/output/task_status.json) 是程序运行过程中的“唯一实时状态源”：

- 程序会实时更新该文件
- 程序启动时会读取该文件，并与 tasks_list.json 的任务清单合并后在界面展示

该文件可能出现两种结构（程序均兼容）：

- 实时 KV 格式（运行中）：`{ "TASK-001": { ...status... }, "TASK-002": { ... } }`
- 事件报告格式（任务完成/程序结束时）：`{ "event_type": "...", "all_tasks_status": [ ... ] }`

## 跳过任务（Skip）的规则

- 被“自动跳过 / 人工跳过”的任务不算完成
- 会被重新加入队列末尾，待其它任务完成后再尝试
- 界面与状态文件中会保留跳过原因（`skip_reason`），并以“等待重试”方式展示

## 配置说明（config/config.json）

[config.json](file:///c:/Users/77010/0_SAIC/03_HardwareDevelop/02_ConditionMonitor/config/config.json) 常用字段：

- `gps.mode`：`auto / csv / usb`
  - Windows 推荐 `csv`
  - Ubuntu/车端推荐 `usb`（需要 pyserial）
- `gps.csv_file` / `gps.rate`：CSV 模拟文件与读数频率
- `gps.port` / `gps.baudrate`：USB 串口配置
- `conditions.file`：工况定义 CSV 文件
- `task_list_file`：任务模板文件（默认 `config/tasks_list.json`）
- `status_output_file`：任务状态文件（默认 `output/task_status.json`）
- `task_options.mode`：传统模式下的调度策略：`sequential / nearest / priority`
  - 使用外部任务列表（task_list_file）时，执行顺序以 `execution_order` 为准
- `task_options.auto_skip`：自动跳过策略（距离/时间阈值）
- `ui.interactive_commands`：是否启用命令行交互命令

## 目录结构（常用）

```
02_ConditionMonitor/
├── main.py                 # CLI 主入口
├── gui_main_qt.py          # PyQt GUI 入口
├── config/
│   ├── config.json         # 系统配置
│   └── tasks_list.json     # 当日任务模板（只读）
├── output/
│   └── task_status.json    # 实时任务状态（读写）
├── referencePosition/
│   └── ConditionExtendedTemplate.csv  # 工况模板
├── gps/                    # GPS 读取
├── monitor/                # 任务调度/工况监控
└── utils/                  # 解析与工具
```

## 进一步阅读

- [ARCHITECTURE.md](file:///c:/Users/77010/0_SAIC/03_HardwareDevelop/02_ConditionMonitor/docs/ARCHITECTURE.md)
- [CONDITION_TEMPLATE.md](file:///c:/Users/77010/0_SAIC/03_HardwareDevelop/02_ConditionMonitor/docs/CONDITION_TEMPLATE.md)

