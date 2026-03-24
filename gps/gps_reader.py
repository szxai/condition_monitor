"""
GPS数据读取器（支持USB和CSV模拟）
"""
import sys
import time
import csv
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional, Iterator
from models.gps_data import GPSData
from utils.logger import logger, setup_raw_logger
from utils.geo import haversine_distance_m


class GPSReader(ABC):
    """GPS读取器抽象基类"""
    
    @abstractmethod
    def read(self) -> Optional[GPSData]:
        """读取一条GPS数据"""
        pass
    
    @abstractmethod
    def close(self):
        """关闭读取器"""
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class USBGPSReader(GPSReader):
    """USB GPS读取器（Ubuntu环境）"""
    
    def __init__(self, port: str = '/dev/ttyACM0', baudrate: int = 115200):
        """
        初始化USB GPS读取器
        
        Args:
            port: USB端口路径，默认 /dev/ttyACM0
            baudrate: 波特率，默认 115200
        """
        self.port = port
        self.baudrate = baudrate
        self.serial = None
        self.raw_logger = setup_raw_logger()
        self.last_valid_data = {}  # Cache for merging GGA/RMC data
        self._init_serial()
    
    def _init_serial(self):
        """初始化串口连接"""
        logger.info(f"Attempting to open USB serial port: {self.port} @ {self.baudrate}")
        try:
            import serial
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1.0
            )
            logger.info(f"Successfully opened serial port {self.port}")
        except ImportError:
            logger.error("pyserial not installed")
            raise ImportError("需要安装pyserial库: pip install pyserial")
        except Exception as e:
            logger.error(f"Failed to open USB port {self.port}: {e}")
            raise ConnectionError(f"无法打开USB端口 {self.port}: {e}")
    
    def read(self) -> Optional[GPSData]:
        """从USB读取GPS数据（NMEA格式）"""
        if not self.serial or not self.serial.is_open:
            logger.warning("Serial port not open, attempting to reconnect...")
            try:
                self._init_serial()
            except Exception:
                return None
        
        try:
            latest_data = None
            lines_processed = 0
            max_lines = 100 # Avoid blocking main thread if buffer is full
            
            # Read all available data to clear buffer and get latest status
            while self.serial.in_waiting > 0 and lines_processed < max_lines:
                raw_line = self.serial.readline()
                lines_processed += 1
                line = raw_line.decode('utf-8', errors='ignore').strip()
                
                # Log raw data (Only log GGA/RMC to reduce I/O overhead and latency)
                if line.startswith(('$GPGGA', '$GNGGA', '$GPRMC', '$GNRMC')):
                    self.raw_logger.info(line)
                
                if line.startswith('$GPGGA') or line.startswith('$GNGGA'):  # GGA格式包含位置信息
                    data = self._parse_nmea_gga(line)
                    if data:
                        # Merge with cached data
                        latest_data = self._merge_gps_data(data)
                    else:
                        logger.warning(f"Failed to parse GGA line: {line}")
                elif line.startswith('$GPRMC') or line.startswith('$GNRMC'):  # RMC包含速度/航向
                    data = self._parse_nmea_rmc(line)
                    if data:
                        latest_data = self._merge_gps_data(data)
                elif line.startswith('$'):
                    # Log other NMEA sentences for debugging purposes
                    pass
            
            # If buffer is still full after processing max_lines, flush it to catch up
            if self.serial.in_waiting > 1024:
                logger.warning(f"GPS Serial buffer overflow ({self.serial.in_waiting} bytes), flushing to reduce latency")
                self.serial.reset_input_buffer()
                
            return latest_data
                
        except Exception as e:
            logger.error(f"Error reading/parsing GPS data: {e}")
        
        return None
    
    def _merge_gps_data(self, new_data: GPSData) -> GPSData:
        """Merge new GPS data with cached values to prevent flickering"""
        
        # Sanity check for coordinate jumps (Drift Filter)
        # If new data implies impossible speed (> 400 km/h), reject it
        if self.last_valid_data.get('latitude') is not None and \
           self.last_valid_data.get('longitude') is not None and \
           new_data.latitude is not None and new_data.longitude is not None:
            
            last_lat = self.last_valid_data['latitude']
            last_lon = self.last_valid_data['longitude']
            
            # Simple check: If exactly 0.0, reject (unless valid 0,0 location, but rare for car test)
            if abs(new_data.latitude) < 0.0001 and abs(new_data.longitude) < 0.0001:
                # logger.warning("Rejected (0,0) coordinates")
                return self._create_merged_data()
            
            dist = haversine_distance_m(last_lon, last_lat, new_data.longitude, new_data.latitude)
            
            # If distance is significant, check time
            if dist > 10.0: # Only check if moved > 10m
                last_time = self.last_valid_data.get('timestamp')
                if last_time:
                    time_diff = (new_data.timestamp - last_time).total_seconds()
                    # Only check speed if time diff is reasonable (>0.05s) to avoid div/0 or huge spikes
                    if time_diff > 0.05:
                        speed_m_s = dist / time_diff
                        speed_kmh = speed_m_s * 3.6
                        
                        # Threshold: 400 km/h (approx 111 m/s)
                        if speed_kmh > 400:
                            logger.warning(f"GPS Drift Detected: Jump {dist:.1f}m in {time_diff:.2f}s ({speed_kmh:.1f} km/h). Ignoring.")
                            return self._create_merged_data()

        # Update cache with non-None values
        if new_data.latitude is not None: self.last_valid_data['latitude'] = new_data.latitude
        if new_data.longitude is not None: self.last_valid_data['longitude'] = new_data.longitude
        if new_data.altitude is not None: self.last_valid_data['altitude'] = new_data.altitude
        if new_data.speed is not None: self.last_valid_data['speed'] = new_data.speed
        if new_data.heading is not None: self.last_valid_data['heading'] = new_data.heading
        
        # Always use the latest timestamp
        self.last_valid_data['timestamp'] = new_data.timestamp
        
        return self._create_merged_data()
    
    def _create_merged_data(self) -> GPSData:
        return GPSData(
            timestamp=self.last_valid_data.get('timestamp', datetime.now()),
            latitude=self.last_valid_data.get('latitude', 0.0),
            longitude=self.last_valid_data.get('longitude', 0.0),
            altitude=self.last_valid_data.get('altitude'),
            speed=self.last_valid_data.get('speed'),
            heading=self.last_valid_data.get('heading')
        )

    def _parse_nmea_rmc(self, line: str) -> Optional[GPSData]:
        """解析NMEA RMC格式数据"""
        try:
            parts = line.split(',')
            if len(parts) < 12:
                logger.warning(f"Incomplete RMC line: {line}")
                return None
                
            # Status check (A=Active, V=Void)
            if parts[2] != 'A':
                # logger.debug("GPS Void status in RMC")
                return None
                
            # Time
            time_str = parts[1]
            if len(time_str) >= 6:
                hour = int(time_str[0:2])
                minute = int(time_str[2:4])
                second = int(time_str[4:6])
                timestamp = datetime.now().replace(hour=hour, minute=minute, second=second)
            else:
                timestamp = datetime.now()
                
            # Latitude
            lat_deg = float(parts[3][:2])
            lat_min = float(parts[3][2:])
            latitude = lat_deg + lat_min / 60.0
            if parts[4] == 'S':
                latitude = -latitude
                
            # Longitude
            lon_deg = float(parts[5][:3])
            lon_min = float(parts[5][3:])
            longitude = lon_deg + lon_min / 60.0
            if parts[6] == 'W':
                longitude = -longitude
                
            # Speed (knots -> km/h)
            speed_knots = float(parts[7]) if parts[7] else 0.0
            speed_kmh = speed_knots * 1.852
            
            # Heading
            heading = float(parts[8]) if parts[8] else 0.0
            
            return GPSData(
                timestamp=timestamp,
                latitude=latitude,
                longitude=longitude,
                speed=speed_kmh,
                heading=heading,
                altitude=None # RMC doesn't have altitude
            )
        except (ValueError, IndexError) as e:
            logger.warning(f"Error parsing RMC: {e}")
            return None

    def _parse_nmea_gga(self, line: str) -> Optional[GPSData]:
        """解析NMEA GGA格式数据"""
        try:
            parts = line.split(',')
            if len(parts) < 15:
                logger.warning(f"Incomplete GGA line: {line}")
                return None
            
            # 解析时间
            time_str = parts[1]  # UTC时间 HHMMSS.SSS
            if len(time_str) >= 6:
                hour = int(time_str[0:2])
                minute = int(time_str[2:4])
                second = int(time_str[4:6])
                timestamp = datetime.now().replace(hour=hour, minute=minute, second=second)
            else:
                timestamp = datetime.now()
            
            # 解析纬度
            lat_deg = float(parts[2][:2])
            lat_min = float(parts[2][2:])
            latitude = lat_deg + lat_min / 60.0
            if parts[3] == 'S':
                latitude = -latitude
            
            # 解析经度
            lon_deg = float(parts[4][:3])
            lon_min = float(parts[4][3:])
            longitude = lon_deg + lon_min / 60.0
            if parts[5] == 'W':
                longitude = -longitude
            
            # 解析海拔
            altitude = None
            if parts[9]:
                try:
                    altitude = float(parts[9])
                except ValueError:
                    pass
            
            return GPSData(
                timestamp=timestamp,
                longitude=longitude,
                latitude=latitude,
                altitude=altitude
            )
        except (ValueError, IndexError) as e:
            print(f"解析NMEA数据错误: {e}")
            return None
    
    def close(self):
        """关闭串口"""
        if self.serial and self.serial.is_open:
            self.serial.close()


class CSVGPSReader(GPSReader):
    """CSV GPS读取器（Windows调试环境）"""
    
    def __init__(self, csv_file: str, rate: float = 1.0):
        """
        初始化CSV GPS读取器
        
        Args:
            csv_file: CSV文件路径
            rate: 读取速率（每秒更新的行数），默认1.0
                 - 当rate > 1000时，将忽略时间间隔直接连续读取
        """
        self.csv_file = Path(csv_file)
        if not self.csv_file.exists():
            raise FileNotFoundError(f"GPS CSV文件不存在: {csv_file}")
        
        self.rate = rate
        self.interval = 1.0 / rate if 0 < rate <= 1000 else 0.0
        self.file = None
        self.reader = None
        self.last_read_time = 0
        self.current_row = 0  # 当前读取的行号
        self.total_rows = 0   # CSV文件总行数
        self._init_csv()
    
    def _init_csv(self):
        """初始化CSV文件读取"""
        self.file = open(self.csv_file, 'r', encoding='utf-8')
        # 计算总行数
        self.file.seek(0)
        self.total_rows = sum(1 for _ in self.file)
        self.file.seek(0)
        # 创建reader
        self.reader = csv.DictReader(self.file)
        self.current_row = 1  # 从第一行数据开始（跳过表头）
        self.last_read_time = time.time()
    
    def read(self) -> Optional[GPSData]:
        """从CSV读取GPS数据（按速率控制）"""
        current_time = time.time()
        
        # 控制读取速率（仅当速率 <= 1000时）
        if self.rate <= 1000 and current_time - self.last_read_time < self.interval:
            return None
        
        try:
            row = next(self.reader, None)
            if row is None:
                # 文件读取完毕，重新开始
                print("CSV文件读取完毕，重新开始")
                self.file.seek(0)
                self.reader = csv.DictReader(self.file)
                self.current_row = 1
                row = next(self.reader, None)
            
            if row:
                # 打印当前读取的行号
                print(f"GPS CSV读取行 {self.current_row}/{self.total_rows}", end="\r")
                
                self.last_read_time = current_time
                self.current_row += 1
                return self._parse_csv_row(row)
        except Exception as e:
            print(f"读取CSV GPS数据错误: {e}")
        
        return None
    
    def _parse_csv_row(self, row: dict) -> Optional[GPSData]:
        """解析CSV行数据"""
        try:
            # 尝试解析时间戳（支持多种格式）
            timestamp_str = row.get('timestamp', row.get('time', row.get('Time', '')))
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str)
                except ValueError:
                    try:
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        timestamp = datetime.now()
            else:
                timestamp = datetime.now()
            
            # 解析经纬度 - 支持多种格式和大小写
            longitude = float(row.get('GPS_Longtitude', row.get('Longitude', row.get('longitude', row.get('Lon', row.get('lon', 0))))))
            latitude = float(row.get('GPS_Latitude', row.get('Latitude', row.get('latitude', row.get('Lat', row.get('lat', 0))))))
            
            # 解析可选字段
            altitude = None
            if 'altitude' in row or 'alt' in row:
                try:
                    altitude = float(row.get('altitude', row.get('alt', 0)))
                except (ValueError, KeyError):
                    pass
            
            speed = None
            if 'speed' in row:
                try:
                    speed = float(row['speed'])
                except (ValueError, KeyError):
                    pass
            
            heading = None
            if 'heading' in row:
                try:
                    heading = float(row['heading'])
                except (ValueError, KeyError):
                    pass
            
            return GPSData(
                timestamp=timestamp,
                longitude=longitude,
                latitude=latitude,
                altitude=altitude,
                speed=speed,
                heading=heading
            )
        except (ValueError, KeyError) as e:
            print(f"解析CSV行数据错误: {e}, 行数据: {row}")
            return None
    
    def close(self):
        """关闭CSV文件"""
        if self.file:
            self.file.close()


def create_gps_reader(mode: str = 'auto', **kwargs) -> GPSReader:
    """
    创建GPS读取器工厂函数
    
    Args:
        mode: 模式 ('usb', 'csv', 'auto')
            - 'usb': USB模式（Ubuntu）
            - 'csv': CSV模式（Windows调试）
            - 'auto': 自动检测（Windows优先CSV，Linux优先USB）
        **kwargs: 其他参数
            - USB模式: port, baudrate
            - CSV模式: csv_file, rate
    
    Returns:
        GPS读取器实例
    """
    if mode == 'auto':
        # 自动检测操作系统
        if sys.platform.startswith('win'):
            mode = 'csv'
        else:
            mode = 'usb'
    
    if mode == 'usb':
        port = kwargs.get('port', '/dev/ttyACM0')
        baudrate = kwargs.get('baudrate', 115200)
        return USBGPSReader(port=port, baudrate=baudrate)
    
    elif mode == 'csv':
        csv_file = kwargs.get('csv_file')
        if not csv_file:
            raise ValueError("CSV模式需要提供csv_file参数")
        rate = kwargs.get('rate', 1.0)
        return CSVGPSReader(csv_file=csv_file, rate=rate)
    
    else:
        raise ValueError(f"不支持的GPS读取模式: {mode}")

