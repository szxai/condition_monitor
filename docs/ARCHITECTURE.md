# 系统架构与数据流（2026-04）

## 1. 系统目标
- 实时读取 GPS（USB 或 CSV），按工况模板判断任务是否开始、进行、完成、失败或跳过。
- 支持多任务编排（外部任务清单或传统工况队列）。
- 同时支持 CLI 工作流与 GUI 工作流（调试界面/驾驶员界面）。
- 输出可持久化状态与事件 JSON，便于外部系统集成。

## 2. 目录与文件职责

### 2.1 入口与界面
- `main.py`：CLI 主入口，负责系统生命周期、命令行参数、交互命令。
- `gui_main_qt.py`：GUI 主入口，包含入口页、调试界面、驾驶员界面、语音播报逻辑。
- `condition_hint_editor.py`：工况模板编辑器（点位、圈次提示、地图框选）。
- `task_creator_app.py`：任务清单编辑器。

### 2.2 核心业务
- `monitor/condition_monitor.py`：单工况/组合工况状态机与进度提示生成核心。
- `monitor/task_manager.py`：任务调度、状态持久化、跳过/手动完成、输出 JSON 聚合。

### 2.3 数据模型与解析
- `models/condition.py`：工况模型（起终点、关键点、循环区、提示、计分基准时间）。
- `models/gps_data.py`：GPS 采样数据模型。
- `utils/condition_parser.py`：工况 CSV 解析器（动态点位、分圈提示、开始前提示）。
- `utils/task_list_parser.py`：任务清单解析与兼容处理。

### 2.4 设备与基础设施
- `gps/gps_reader.py`：GPS 读取抽象与实现（USB 串口 / CSV 回放）。
- `utils/json_output.py`：事件 JSON 构建与保存。
- `utils/logger.py`：日志初始化。
- `utils/command_listener.py`：CLI 交互输入监听线程。

### 2.5 配置与数据文件
- `config/config.json`：运行配置（GPS、任务、UI、语音开关）。
- `config/tasks_list.json`：任务模板（执行顺序与任务描述，不含实时状态）。
- `referencePosition/ConditionExtendedTemplate.csv`：工况模板主文件。
- `output/task_status.json`：实时任务状态与事件输出文件。

## 3. 核心类与主要方法

### 3.1 `ConditionMonitor`（`monitor/condition_monitor.py`）
- `update(gps)`：按状态机推进单工况状态。
- `get_progress_info()`：输出界面实时展示数据（提示、圈数、检查点、循环区）。
- `get_summary()`：输出工况总结（时间、速度、距离、评分、原因）。
- `_calculate_completion_score(duration_seconds)`：按 `Ref_Time_Min/Max` 计算完成评分。

### 3.2 `CompositeConditionMonitor`（`monitor/condition_monitor.py`）
- 用于同名工况多候选区域场景。
- 未锁定前并行观察，锁定后仅跟踪激活工况。
- `get_progress_info()` 和 `get_summary()` 对外保持统一结构。

### 3.3 `TaskManager`（`monitor/task_manager.py`）
- `update(gps)`：驱动当前任务更新、触发状态持久化、产出 UI 数据。
- `get_all_tasks_status()`：汇总已完成/进行中/待执行任务状态。
- `_finalize_current_monitor(result_flag)`：任务结束收尾、写执行日志、输出 JSON。
- `skip_current(...)` / `complete_current(...)`：人工跳过与人工完成。

### 3.4 `MainWindow`（`gui_main_qt.py`）
- `update_loop()`：定时读取 GPS，驱动任务更新和 UI 刷新。
- `update_ui(gps, update_info)`：更新当前任务、队列、地图、提示、评分。
- `update_queue()`：按模式渲染任务队列（调试表格 / 驾驶员卡片）。
- `_set_operation_hint_text()` / `_maybe_speak_operation_hint()`：提示显示与语音播报解耦。

## 4. 状态机与业务规则

### 4.1 工况状态
- `NOT_STARTED`：等待进入起点。
- `IN_PROGRESS`：已进入工况流程。
- `COMPLETING`：已达终点，等待完成确认。
- `COMPLETED`：自动完成。
- `MANUAL_COMPLETED`：人工完成。
- `FAILED`：失败（例如进入禁行区）。
- `SKIPPED`：跳过。

### 4.2 关键规则
- 进入 `Start` 区域触发开始。
- `Waypoint` 按顺序校验（区分必经与参考）。
- `LoopZone` 按配置统计进入次数。
- 满足条件后进入 `End` 并完成确认。
- 多圈任务未完成总圈数时回到等待下一圈。
- 自动跳过基于“距离起点阈值 + 时间阈值 + 远离趋势”联合判定。

## 5. 提示与语音逻辑

### 5.1 提示来源
- 开始前提示：`Prestart_Hint` / `Prestart_LapNN_Hint`
- 关键点提示：`<Point>_Hint` / `<Point>_LapNN_Hint`
- 循环区提示：`<LoopZone>_Hint` / `<LoopZone>_LapNN_Hint`

### 5.2 语音播报行为（当前实现）
- 提示变化才播报（去重 + 限频）。
- 到达起点单独播报“到达起点”。
- 不播报“下一个关键点”引导，仅播报操作内容本体。
- 准备阶段仅播报提示第一行。
- 跨平台后端：
  - Windows：`System.Speech`（PowerShell）
  - Linux：`spd-say` 优先，`espeak` 兜底

## 6. 评分规则（全工作流生效）
- 输入：工况实际完成时长 `duration_seconds`，模板基准 `Ref_Time_Min/Ref_Time_Max`。
- 规则：
  - 时长在区间内：`100.0`
  - 低于下限或高于上限：按超出比例扣分，最低 `0.0`
- 落地位置：
  - 实时状态：`task_status.json` 的 `completion_score`
  - 汇总输出：`output_task_status(...)` 的 `current_task/all_tasks_status`
  - 界面展示：当前任务评分 + 驾驶员队列卡片评分

## 7. 数据流（端到端）

```text
GPS设备/CSV
  -> gps_reader.read()
  -> GPSData
  -> TaskManager.update()
     -> ConditionMonitor.update()
     -> progress_info / summary / completion_score
     -> task_status.json 持久化
  -> GUI update_ui()
     -> 当前任务、队列、地图、提示、语音
  -> json_output.output_task_status()
     -> output/task_status.json 事件输出
```

## 8. 配置字段说明（关键）
- `gps.mode`：`csv` / `usb`
- `gps.csv_file` / `gps.rate`：CSV 回放源与速率
- `gps.port` / `gps.baudrate`：串口参数
- `conditions.file`：工况模板
- `task_list_file`：任务清单
- `status_output_file`：状态输出文件
- `task_options.auto_skip.*`：自动跳过策略
- `ui.default_view_mode`：默认界面模式
- `ui.voice_prompt_enabled`：语音播报开关

## 9. 开发与扩展建议
- 新增 GPS 源：实现 `GPSReader` 接口并在工厂注册。
- 新增状态规则：优先在 `ConditionMonitor.update()` 内扩展，保持 `get_progress_info()` 输出结构稳定。
- 新增 UI 展示项：优先通过 `update_info` 通道扩展，避免直接耦合内部对象。
- 新增输出字段：同步更新 `summary`、`task_status` 与 GUI 显示，保持链路一致。

