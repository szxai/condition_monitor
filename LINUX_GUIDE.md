# Linux (Ubuntu 22.04) 部署与配置指南

本程序已验证可移植至 Linux 环境（推荐 Ubuntu 22.04），主要用于通过 USB GPS 模块进行工况监控。

## 1. 环境准备

### 1.1 安装 Python 3.10+
Ubuntu 22.04 默认已安装 Python 3.10。可以通过以下命令检查：
```bash
python3 --version
```

### 1.2 安装系统依赖
PyQt5 在 Linux 下通常需要额外的系统图形库支持。请运行以下命令安装：
```bash
sudo apt-get update
sudo apt-get install -y python3-pip libxcb-xinerama0 libxcb-cursor0
```

## 2. 安装项目依赖

在项目根目录下，使用 pip 安装 Python 依赖库：
```bash
pip3 install -r requirements.txt
```

如果遇到权限问题，可以添加 `--user` 参数：
```bash
pip3 install --user -r requirements.txt
```

## 3. 串口权限配置 (关键步骤)

在 Linux 中，普通用户默认没有权限访问 USB 串口设备（如 `/dev/ttyUSB0`）。需要将当前用户添加到 `dialout` 组。

1. **查看当前用户组**：
   ```bash
   groups
   ```

2. **添加用户到 dialout 组**：
   ```bash
   sudo usermod -aG dialout $USER
   ```

3. **生效更改**：
   **必须注销并重新登录**，或者重启系统，权限设置才会生效。

4. **验证串口设备**：
   插入 USB GPS 模块后，运行以下命令查看设备名：
   ```bash
   ls -l /dev/ttyUSB*
   ```
   通常设备名为 `/dev/ttyUSB0`。

## 4. 程序配置

程序默认会根据操作系统自动选择 GPS 读取模式，但在 Linux 下建议明确配置。

### 方式一：通过 GUI 设置（推荐）
1. 运行程序：`python3 gui_main_qt.py`
2. 点击工具栏的 **"⚙ 参数设置"**。
3. 将 **GPS 模式** 修改为 `usb`。
   - `port`: 通常为 `/dev/ttyUSB0` 或 `/dev/ttyACM0` (取决于硬件连接)
5. 设置 **波特率**（通常为 4800 或 9600，取决于硬件）。
6. 点击保存并重启程序。

### 方式二：手动修改配置文件
编辑 `config/config.json` 文件：

```json
{
  "gps": {
    "mode": "usb",
    "port": "/dev/ttyUSB0",
    "baudrate": 4800,
    "csv_file": ""
  },
  ...
}
```

## 5. 运行程序

### 启动 GUI 界面
```bash
python3 gui_main_qt.py
```

### 常见问题排查

**Q1: 报错 `ModuleNotFoundError: No module named 'serial'`**
A: 请确保已安装依赖：`pip3 install pyserial`。注意不是 `serial`，而是 `pyserial`。

**Q2: 报错 `Permission denied: '/dev/ttyUSB0'`**
A: 请参考第 3 节“串口权限配置”，将用户加入 `dialout` 组并重启。临时解决方法是使用 `sudo python3 gui_main_qt.py`（不推荐）。

**Q3: 界面显示不全或字体过小**
A: `gui_main_qt.py` 中已启用 Fusion 风格和字体调整。如果仍有问题，可能需要检查系统的 DPI 设置或安装缺失的字体。

**Q4: 地图箭头不显示**
A: 确保 GPS 已定位（有经纬度输出）。如果 GPS 尚未定位，经纬度为 0,0，可能导致地图显示异常。
