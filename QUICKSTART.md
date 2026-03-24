# 快速开始指南

## 1. 安装依赖

```bash
pip install -r requirements.txt
```

## 2. 准备GPS数据

### Windows调试环境（CSV模拟）

创建GPS数据CSV文件，格式如下：

```csv
timestamp,longitude,latitude
2024-01-01 10:00:00,119.42175,31.03598
2024-01-01 10:00:01,119.42178,31.03590
```

### Ubuntu环境（USB GPS）

确保GPS设备已连接，检查设备路径：
```bash
ls /dev/ttyUSB*
```

## 3. 配置系统

编辑 `config.json`：

```json
{
  "gps": {
    "mode": "csv",
    "csv_file": "examples/gps_data_example.csv",
    "rate": 2.0
  },
  "conditions": {
    "file": "referencePosition/ConditionExtendedTemplate.csv"
  },
  "task_list": ["CY", "AA", "ST"],
  "task_options": {
    "mode": "nearest",
    "preferred_conditions": ["ST"],
    "auto_skip": {
      "enabled": true,
      "distance_threshold_m": 180,
      "time_threshold_s": 20
    }
  },
  "ui": {
    "interactive_commands": true
  }
}
```

## 4. 运行系统

```bash
python main.py
```

## 5. 查看输出

系统会实时输出：
- 当前GPS位置
- 状态变化 / 自动或人工跳过提示
- 各途径点通过情况（必经/参考）
- 完成后统计：开始/结束时间、平均/最大/最小车速、行驶距离

同时可以在命令行输入以下指令（默认启用交互模式）：

```
status   查看当前状态和最近记录
skip     人工跳过当前工况（放队尾）
log      查看执行/跳过历史
next     查看待执行队列
exit     停止程序
```

> 若在非交互环境运行，可附加 `--no-interactive` 或在 `config.json` 中将 `ui.interactive_commands` 设置为 `false`。

## 常见问题

### GPS数据读取失败

- **USB模式**：检查设备权限 `sudo chmod 666 /dev/ttyUSB0`
- **CSV模式**：检查文件路径和格式

### 工况无法识别

- 检查GPS坐标是否在工况定义范围内
- 确认工况定义文件格式正确
- 查看警告信息

### 常见调度问题

- 若车辆远离当前工况且被自动跳过，可调整 `auto_skip` 参数或在命令行添加 `--disable-auto-skip`
- 需要临时调整顺序，可使用 `--task-mode nearest` 或 `--preferred 工况A,工况B`

