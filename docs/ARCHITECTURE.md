# 系统架构说明

## 系统设计原则

1. **识别准确**：通过多关键点验证确保工况识别准确
2. **实时性强**：低延迟GPS数据读取和状态更新
3. **逻辑清晰**：明确的状态转换和任务管理

## 核心模块

### 1. 数据模型层 (`models/`)

#### `condition.py`
- `GPSPoint`: GPS坐标范围定义
- `PathCheckpoint`: 单个途径点定义（名称、范围、是否必经）
- `ConditionDefinition`: 工况完整定义（多途径点、禁行区、优先级、跳过阈值）

#### `gps_data.py`
- `GPSData`: GPS数据点模型

### 2. GPS读取层 (`gps/`)

#### `gps_reader.py`
- `GPSReader`: 抽象基类
- `USBGPSReader`: USB GPS读取器（Ubuntu）
- `CSVGPSReader`: CSV模拟读取器（Windows）
- `create_gps_reader()`: 工厂函数

**设计特点**：
- 统一接口，支持多种数据源
- 自动检测运行环境
- CSV模式支持速率控制

### 3. 工具层 (`utils/`)

#### `condition_parser.py`
- `ConditionParser`: CSV工况定义解析器

**功能**：
- 解析标准格式CSV
- 处理缺失字段（兼容性）
- 数据验证

### 4. 监控层 (`monitor/`)

#### `condition_monitor.py`
- `ConditionState`: `NOT_STARTED / IN_PROGRESS / COMPLETING / COMPLETED / FAILED / SKIPPED`
- `ConditionMonitor`: 负责开始检测、途径点与循环区域验证、多圈计数、禁行区检测、速度统计、跳过标记

**状态转换逻辑**：
```
NOT_STARTED → IN_PROGRESS → COMPLETING → COMPLETED
        ↑          ↓             ↓
        │        FAILED        SKIPPED
        └─────────────── 自动跳过/人工跳过
```

**关键点与循环流程**：
1. Start: 进入起点范围立即进入 `IN_PROGRESS`
2. Waypoints: 顺序检测所有必经点（支持参考点用于保持“进行中”状态）
3. LoopZones: 对每个 `LoopZoneNN` 统计进入次数，需达到 `LoopZoneNN_Count` 才允许进入终点
4. Forbidden: 若进入禁行区立即 `FAILED`
5. End: 所有必经点与循环区域达标且进入终点 → `COMPLETING`
6. Multi-lap: 每次完成 End 后计 1 圈，直到 `RequiredLaps` 圈全部完成才进入 `COMPLETED`

#### `task_manager.py`
- `TaskManager`: 任务调度核心

**功能**：
- 支持 `sequential / nearest / priority` 三种调度策略
- `preferred_conditions`：允许手动指定优先执行的工况
- 自动/人工跳过：可由系统根据距离阈值触发，也可通过命令行手动触发，均把工况排队尾
- 记录执行日志（开始/结束时间、平均/最大/最小车速、行驶距离、跳过/失败原因）

### 5. 主程序 (`main.py`)

#### `ConditionMonitorSystem`
- 系统初始化和配置
- 主监控循环
- 状态输出和日志
- 交互命令处理（`status`/`skip`/`log`/`next`/`exit`）

#### `utils/command_listener.py`
- 后台线程，阻塞式读取控制台输入
- 与 `ConditionMonitorSystem` 协同，实现人工跳过和实时状态查询

## 数据流

```
GPS设备/CSV文件
    ↓
GPSReader (USB/CSV)
    ↓
GPSData
    ↓
TaskManager（调度、跳过判定、日志）
    ↓
ConditionMonitor（途径点/速度/禁行区）
    ↓
状态更新 + 统计输出
```

## 状态监控逻辑

### 开始检测
1. GPS进入 `Start` 范围 → 立即 `IN_PROGRESS`
2. 记录开始时间，开启速度/距离统计

### 进度监控
- 顺序检查所有 `Required=TRUE` 的 `WaypointNN`
- 循环区域 `LoopZoneNN` 的进入次数必须达到 `LoopZoneNN_Count`
- `Required=FALSE` 的途径点用于保持“进行中”状态
- 检测是否进入任意 `ForbiddenNN` 区域（触发 `FAILED`）

### 完成检测
1. 所有必经点与循环区域次数已满足
2. GPS进入 `End` 范围 → `COMPLETING`
3. 在 `End` 范围停留 ≥0.5 s 视为完成一圈
4. 若已完成 `RequiredLaps` 圈 → `COMPLETED`，否则回到 `NOT_STARTED` 等待下一圈

### 自动跳过
1. TaskManager 持续计算车辆与当前工况起点中心的距离
2. 若距离连续增大且超过阈值，并持续指定时间 → 标记为 `SKIPPED`
3. 工况被重置并移动到任务列表末端

## 配置系统

### 配置文件结构
```json
{
  "gps": { ... },
  "conditions": { "file": "..." },
  "task_list": ["CY", "AA"],
  "task_options": {
    "mode": "nearest",
    "preferred_conditions": ["ST"],
    "auto_skip": {
      "enabled": true,
      "distance_threshold_m": 200,
      "time_threshold_s": 30
    }
  }
}
```

### 命令行参数
- `--config`: 配置文件路径
- `--gps-mode`: GPS模式
- `--csv-file`: CSV文件路径
- `--rate`: CSV读取速率
- `--conditions-file`: 工况定义文件
- `--task-mode`: 调度模式（sequential/nearest/priority）
- `--preferred`: 逗号分隔的优先工况列表
- `--auto-skip-distance` / `--auto-skip-time` / `--disable-auto-skip`
- `--no-interactive`: 关闭命令监听线程（默认开启，可输入 `status/skip/log/next/exit`）

## 扩展性

### 添加新的GPS数据源
1. 继承 `GPSReader` 基类
2. 实现 `read()` 和 `close()` 方法
3. 在 `create_gps_reader()` 中注册

### 自定义监控逻辑
1. 修改 `ConditionMonitor.update()` 方法
2. 调整状态转换条件
3. 添加新的状态或验证规则

## 性能考虑

1. **GPS读取频率**：默认0.1秒循环，可根据需要调整
2. **状态输出**：仅在状态发生变化或产生总结时打印详细信息
3. **状态摘要**：默认每5秒输出一次，可通过代码调整
4. **统计开销**：速度/距离统计仅在工况开始后进行，避免多余计算

## 错误处理

1. **GPS读取失败**：输出错误，继续尝试
2. **工况定义错误**：跳过无效行，输出警告
3. **状态异常**：自动重置或标记失败

## 测试建议

1. **单元测试**：各模块独立测试
2. **集成测试**：使用CSV模拟数据测试完整流程
3. **实际测试**：使用真实GPS设备验证

