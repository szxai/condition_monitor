# 工况参数定义模板（扩展版）

## 概述

为了提高识别准确性、实时性以及工况调度灵活性，系统支持**扩展版工况信息表**（`referencePosition/ConditionExtendedTemplate.csv`）。本文档给出推荐字段、填写要求与最佳实践。

> 兼容性：旧版字段（`Feature1/2/3/4`）仍然可用，但推荐逐步迁移到扩展版格式，以利用多途径点、优先级和自动跳过配置。

---

## 字段分组

| 分组 | 字段 | 说明 |
|------|------|------|
| 基本信息 | `Condition` | 工况唯一名称 |
| | `Description` | 人类可读描述，便于监控输出 |
| | `Group` | 线路/区域分组，可用于调度分析 |
| | `Priority` | 调度优先级（越大越优先，仅在 `priority` 模式生效） |
| 时间参数 | `Ref_Time_Min/Ref_Time/Ref_Time_Max` | 统计参考（当前用于报表） |
| 多圈 | `RequiredLaps` | 需要完整执行的圈数（Start→End 计 1 圈） |
| 起止范围 | `Start_*`, `End_*` | 必填，定义工况起点/终点范围 |
| 动态途径点 | `Waypoint01_*` … `WaypointNN_*` | 可配置多点路径，结合 `WaypointNN_Required` 指示是否必须经过 |
| 循环区域 | `LoopZone01_*` … `LoopZoneNN_*`, `LoopZoneNN_Count` | 指定需要进入 N 次的区域（如在园区内绕行） |
| 禁行区域 | `Forbidden01_*`, `Forbidden02_*` … | 驾驶过程不得进入，否则判定失败 |
| 自动跳过 | `SkipDistanceThresholdM`, `SkipTimeThresholdS` | 针对该工况的自动跳过判定阈值 |

### 坐标字段命名

每个坐标区域包含 4 个字段：`_LonLB`, `_LonUB`, `_LatLB`, `_LatUB`。例如：

```
Waypoint01_LonLB, Waypoint01_LonUB, Waypoint01_LatLB, Waypoint01_LatUB
```

并可附加 `Waypoint01_Required`（`TRUE/FALSE`）。支持 `Waypoint01` ~ `Waypoint20`，也可以书写成 `Waypoint1`（解析器同时识别 `01`/`1`）。

### 兼容字段

- `Feature1/Feature2/Feature3` 会自动转换为必经点；
- `Feature4` 会自动转换为第一块禁行区域；
- 新表中 `ForbiddenXX` 可继续扩展禁行区域。

---

## 示例（节选）

```csv
Condition,Description,Group,Priority,Ref_Time_Min,Ref_Time,Ref_Time_Max,RequiredLaps,Start_LonLB,Start_LonUB,Start_LatLB,Start_LatUB,End_LonLB,End_LonUB,End_LatLB,End_LatUB,Waypoint01_LonLB,Waypoint01_LonUB,Waypoint01_LatLB,Waypoint01_LatUB,Waypoint01_Required,LoopZone01_LonLB,LoopZone01_LonUB,LoopZone01_LatLB,LoopZone01_LatUB,LoopZone01_Count,Forbidden01_LonLB,Forbidden01_LonUB,Forbidden01_LatLB,Forbidden01_LatUB,SkipDistanceThresholdM,SkipTimeThresholdS
CY,"城运-示例路径","UrbanLine-A",10,1100,1260,1900,1,119.42175,119.42185,31.03598,31.0361,119.4218,119.42188,31.036,31.03608,119.42178,119.4219,31.03585,31.03595,TRUE,,,,,,119.42285,119.42305,31.03335,31.0335,220,25
```

含义：
- 进入 `Start` 区即认为开始，不再强制停车；
- 必须依次通过 `Waypoint01/02`，否则无法进入完成状态；
- 进入 `Forbidden01` 判定失败；
- 若车辆远离起点超过 220 m 并持续 25 s，同时距离呈增长趋势，将自动跳过该工况并排到队尾。

---

## 填写指南

### 1. 坐标范围

- 推荐跨度：0.0001 ~ 0.001 度（约 10~100 m），兼顾检测灵敏度与GPS漂移；
- 起点/终点范围要覆盖车辆正常停靠或通过区域，避免误触发；
- 途径点范围要覆盖道路宽度及车辆允许的偏移。

### 2. 途径点策略

- 途径点顺序即车辆期望路径；所有 `Required=TRUE` 的点必须通过；
- 可将关键弯道/必经分岔口设置为 `Required`，普通路段只需 `FALSE` 作为路径保持提示；
- 途径点数量越多，系统越容易判断车辆是否偏离，但也需要更准确的GPS数据。

### 3. 多圈与循环区域

- **`RequiredLaps`**：若需要在同一工况下往返多次（如反复进出仓库 3 次），将此字段设置为对应圈数；系统会在完成指定圈数前保持“进行中”，并在每圈结束后重新等待进入起点。
- **`LoopZoneXX` + `_Count`**：用于描述“进入某个区域并绕行多次再离开”的场景。每当车辆从区域外进入该区域记 1 次，只有达到 `Count` 次后才能满足完成条件；适合园区绕圈、环岛巡检等需求。

### 4. 禁行区域

- 用于定义“禁止驶入区域”，一旦进入立即判定失败；
- 推荐在容易混淆的支路口附近建立禁行区域；
- 每条工况可配置多个禁行块（`Forbidden01/02/...`）。

### 5. 自动跳过阈值

- 当车辆距离当前工况起点持续增大且超过 `SkipDistanceThresholdM`，并维持 `SkipTimeThresholdS` 秒，将自动跳过；
- 若未填写，系统采用全局默认值（200m/30s）；
- 对于距离短、需要立即执行的工况可设置更小的阈值。

### 6. 调度优先级与偏好

- `Priority` 仅在调度模式为 `priority` 时生效（越大越优先）；
- 也可以在配置文件的 `preferred_conditions` 中指定“临时优先”列表。

---

## 数据校验清单

- [ ] `Condition` 唯一且清晰；
- [ ] `Start_*` / `End_*` 坐标存在且 `LB < UB`；
- [ ] 每个 `WaypointXX` 块四个坐标要么全部填写，要么全部留空；
- [ ] 必经点覆盖路径上所有关键分支；
- [ ] 禁行区域不会与起点/途径点重叠；
- [ ] 自动跳过阈值符合业务预期；
- [ ] 参考时间满足 `Min < Ref < Max`；
- [ ] 描述、分组、优先级已补充（便于报表与调度）。
- [ ] 多圈/循环需求：`RequiredLaps` ≥ 1 且 `LoopZoneXX_Count` 填写合理。

---

## 最佳实践

1. **以轨迹反推范围**：先采集真实轨迹，统计经纬度范围后再加上安全裕度；
2. **途径点分层**：
   - 必经点：控制流程，通常是关键路口/收费站；
   - 可选点：用于保持“进行中”状态但不阻断流程；
3. **禁行区域可微调**：与实际道路保持 5~10 m 的缓冲，避免GPS跳动导致误判；
4. **定期复核**：道路施工或GPS漂移会影响判断，需要定期抽样验证；
5. **保留旧字段以兼容**：若暂未切换到新模板，至少确保 `Feature1/2/End` 可正确覆盖路径。

---

## 常见问题

### Q1. 仍然使用旧的 `Feature1/2/3/4` 会怎样？
系统会自动将其转换为必经点/禁行区，但无法使用多途径点、优先级和自动跳过配置。建议迁移到 `WaypointXX` / `ForbiddenXX` 结构。

### Q2. 如何判断途径点数量？
建议每个关键路口/分岔/检查点设置 1 个必经点；对于需要保持“进行中”状态的直线路段，可在每 200~300 m 放置一个 `Required=FALSE` 的途径点。

### Q3. 自动跳过之后还能再执行吗？
可以。被跳过的工况会自动重置并排到任务列表末尾，待车辆接近时会再次尝试。

### Q4. 平均速度如何统计？
系统会在工况开始后持续采样车速（优先使用GPS原始速度，缺失时根据相邻坐标计算），完成/跳过/失败时产出平均、最大、最小车速及位移，便于后续分析。

---

如需更多模板或示例，请参考 `referencePosition/ConditionExtendedTemplate.csv`，并在填表前确认使用 UTF-8 编码保存。***

