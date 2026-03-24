
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime

def setup_logger(name="ConditionMonitor", log_dir="logs", level=logging.INFO):
    """
    Setup a logger that writes to both console and a rotating file.
    
    Args:
        name: Logger name
        log_dir: Directory to store log files
        level: Logging level
        
    Returns:
        logging.Logger instance
    """
    # Create logs directory if it doesn't exist
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Check if handlers already exist to avoid duplicate logs
    if logger.handlers:
        return logger
        
    # Formatters
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    )
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # File Handler (Rotating)
    # New log file for each run session based on timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"monitor_{timestamp}.log")
    
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(file_formatter)
    
    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info(f"Logger initialized. Log file: {log_file}")
    
    return logger

def setup_raw_logger(name="RawGPS", log_dir="gps_logs"):
    """
    Setup a logger for raw GPS data (NMEA sentences).
    
    Args:
        name: Logger name
        log_dir: Directory to store raw log files
        
    Returns:
        logging.Logger instance
    """
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    if logger.handlers:
        return logger
        
    # Format: Just the message, no timestamp (NMEA has time)
    formatter = logging.Formatter('%(message)s')
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"gps_raw_{timestamp}.log")
    
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    return logger

# Global logger instance (can be imported directly if needed, but setup_logger is preferred)
logger = logging.getLogger("ConditionMonitor")
