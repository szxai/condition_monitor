# 日志系统使用说明 (Logging System Guide)

本程序内置了日志系统，用于记录运行时的关键信息、错误和调试数据，特别是用于排查GPS连接问题。

## 日志文件位置

所有日志文件保存在程序运行目录下的 `logs/` 文件夹中。
每次启动程序，都会生成一个新的日志文件，文件名格式为：
`monitor_YYYYMMDD_HHMMSS.log`
例如：`monitor_20231027_143000.log`

## 日志内容

日志记录了以下几类信息：
1. **系统启动**：配置加载、模块初始化状态。
2. **GPS连接**：
   - 尝试打开串口（包含端口号和波特率）。
   - 串口打开成功或失败。
   - 读取数据错误或异常断开重连。
3. **任务执行**：
   - 任务状态变更（等待 -> 进行中 -> 完成）。
   - 自动跳过逻辑触发。
   - 手动操作（跳过、完成、重置）。
4. **原始GPS数据**：
   - 所有接收到的 NMEA 数据（`$GPGGA`, `$GNRMC` 等）会保存在 `gps_logs/` 文件夹下，用于详细分析信号质量和漂移情况。
5. **系统心跳**：
   - 每60秒记录一次系统状态（GPS连接状态、当前任务），确保程序在长时间运行时仍在正常工作。
6. **异常错误**：程序崩溃或运行时错误的详细堆栈信息。

## 如何排查 "GPS等待数据" 问题

如果程序一直显示 "GPS: 等待信号..."，请按以下步骤检查日志：

1. 打开 `logs/` 目录，找到最新的日志文件。
2. 搜索关键词 `USB` 或 `Serial`。
3. **正常情况**：
   ```
   INFO - Attempting to open USB serial port: /dev/ttyACM0 @ 115200
   INFO - Successfully opened serial port /dev/ttyACM0
   ```
   如果看到上述信息，说明串口已成功打开。如果之后没有报错，但界面仍无数据，可能是：
   - GPS模块没有发送数据（检查硬件连接）。
   - 波特率不匹配（数据乱码或无法解析）。
   - **查看 `gps_logs/`**：检查是否有数据进来。如果 `gps_logs/` 是空的，说明串口完全没收到数据。如果有乱码，说明波特率不对。

4. **异常情况**：
   - **权限错误**：
     ```
     ERROR - Failed to open USB port /dev/ttyACM0: [Errno 13] Permission denied
     ```
     解决方法：运行 `sudo chmod 777 /dev/ttyACM0`。
   - **找不到设备**：
     ```
     ERROR - Failed to open USB port ...: [Errno 2] No such file or directory
     ```
     解决方法：检查USB线连接，或使用 `ls /dev/tty*` 确认端口号是否正确。
   - **pyserial缺失**：
     ```
     ERROR - pyserial not installed
     ```
     解决方法：运行 `pip install pyserial`。

## 调整日志级别

默认日志级别为 `INFO`。如果需要更详细的调试信息（如查看原始GPS数据），可以修改 `utils/logger.py` 中的设置：

```python
# utils/logger.py
def setup_logger(..., level=logging.DEBUG):  # 将 INFO 改为 DEBUG
```

**注意**：开启 DEBUG 级别会产生大量日志，仅在调试时使用。
