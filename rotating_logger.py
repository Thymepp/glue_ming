"""
Enterprise-Grade Rotating Logger Handler
==========================================
A robust, thread-safe rotating logger with time-based and size-based rotation.
Designed for easy integration into any Python application.

Features:
- Size-based and time-based rotation
- Configurable log levels and formats
- Thread-safe operations
- Automatic log cleanup (retention policy)
- JSON configuration support
- Multiple logger instances
- Console and file output
- Colored console output (optional)
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import json

# Export log levels so users don't need to import logging
DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL


class AppLogger:
    """
    Enterprise-grade logger with rotating file handlers.
    
    Example usage:
        # Basic usage
        logger = AppLogger(name="my_app", log_dir="logs")
        logger.info("Application started")
        
        # Advanced usage with custom configuration
        logger = AppLogger(
            name="my_app",
            log_dir="logs",
            max_bytes=50*1024*1024,  # 50MB
            backup_count=10,
            log_level=logging.DEBUG,
            console_output=True
        )
    """
    
    # Default configuration
    DEFAULT_CONFIG = {
        'max_bytes': 10 * 1024 * 1024,  # 10MB
        'backup_count': 5,
        'log_level': logging.INFO,
        'console_output': True,
        'log_format': '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        'date_format': '%Y-%m-%d %H:%M:%S',
        'encoding': 'utf-8',
        'when': 'midnight',  # For time-based rotation: 'S', 'M', 'H', 'D', 'midnight'
        'interval': 1,
        'use_timed_rotation': False,
        'use_colored_console': False
    }
    
    # ANSI color codes for console output
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'        # Reset
    }
    
    _instances: Dict[str, logging.Logger] = {}
    
    def __init__(
        self,
        name: str,
        log_dir: str = "logs",
        max_bytes: int = None,
        backup_count: int = None,
        log_level: int = None,
        console_output: bool = None,
        log_format: str = None,
        date_format: str = None,
        when: str = None,
        interval: int = None,
        use_timed_rotation: bool = None,
        use_colored_console: bool = None,
        config_file: Optional[str] = None
    ):
        """
        Initialize the enterprise logger.
        
        Args:
            name: Logger name (typically application name)
            log_dir: Directory to store log files
            max_bytes: Maximum size of each log file before rotation (bytes)
            backup_count: Number of backup files to keep
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            console_output: Whether to output logs to console
            log_format: Custom log format string
            date_format: Date format string
            when: When to rotate (for timed rotation): 'S', 'M', 'H', 'D', 'midnight'
            interval: Interval for timed rotation
            use_timed_rotation: Use time-based rotation instead of size-based
            use_colored_console: Use colored output for console
            config_file: Path to JSON configuration file
        """
        self.name = name
        self.config = self._load_config(config_file)
        
        # Override defaults with provided arguments
        if max_bytes is not None:
            self.config['max_bytes'] = max_bytes
        if backup_count is not None:
            self.config['backup_count'] = backup_count
        if log_level is not None:
            self.config['log_level'] = log_level
        if console_output is not None:
            self.config['console_output'] = console_output
        if log_format is not None:
            self.config['log_format'] = log_format
        if date_format is not None:
            self.config['date_format'] = date_format
        if when is not None:
            self.config['when'] = when
        if interval is not None:
            self.config['interval'] = interval
        if use_timed_rotation is not None:
            self.config['use_timed_rotation'] = use_timed_rotation
        if use_colored_console is not None:
            self.config['use_colored_console'] = use_colored_console
        
        self.log_dir = Path(log_dir)
        self.logger = self._setup_logger()
        
        # Store instance for retrieval
        AppLogger._instances[name] = self.logger
    
    def _load_config(self, config_file: Optional[str]) -> Dict[str, Any]:
        """Load configuration from file or use defaults."""
        config = self.DEFAULT_CONFIG.copy()
        
        if config_file and os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    user_config = json.load(f)
                    config.update(user_config)
            except Exception as e:
                print(f"Warning: Could not load config file {config_file}: {e}")
        
        return config
    
    def _setup_logger(self) -> logging.Logger:
        """Set up and configure the logger with handlers."""
        # Create logger
        logger = logging.getLogger(self.name)
        logger.setLevel(self.config['log_level'])
        logger.propagate = False
        
        # Clear existing handlers to avoid duplicates
        logger.handlers.clear()
        
        # Create log directory if it doesn't exist
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Create formatters
        file_formatter = logging.Formatter(
            self.config['log_format'],
            datefmt=self.config['date_format']
        )
        
        # Add file handler (rotating or timed)
        log_file = self.log_dir / f"{self.name}.log"
        
        if self.config['use_timed_rotation']:
            file_handler = TimedRotatingFileHandler(
                filename=str(log_file),
                when=self.config['when'],
                interval=self.config['interval'],
                backupCount=self.config['backup_count'],
                encoding=self.config['encoding']
            )
        else:
            file_handler = RotatingFileHandler(
                filename=str(log_file),
                maxBytes=self.config['max_bytes'],
                backupCount=self.config['backup_count'],
                encoding=self.config['encoding']
            )
        
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(self.config['log_level'])
        logger.addHandler(file_handler)
        
        # Add console handler if enabled
        if self.config['console_output']:
            console_handler = logging.StreamHandler(sys.stdout)
            
            if self.config['use_colored_console']:
                console_formatter = ColoredFormatter(
                    self.config['log_format'],
                    datefmt=self.config['date_format']
                )
            else:
                console_formatter = file_formatter
            
            console_handler.setFormatter(console_formatter)
            console_handler.setLevel(self.config['log_level'])
            logger.addHandler(console_handler)
        
        return logger
    
    @classmethod
    def get_logger(cls, name: str) -> Optional[logging.Logger]:
        """
        Retrieve an existing logger instance by name.
        
        Args:
            name: Logger name
            
        Returns:
            Logger instance or None if not found
        """
        return cls._instances.get(name)
    
    def set_level(self, level: int):
        """Change the logging level dynamically."""
        self.logger.setLevel(level)
        for handler in self.logger.handlers:
            handler.setLevel(level)
    
    def add_handler(self, handler: logging.Handler):
        """Add a custom handler to the logger."""
        self.logger.addHandler(handler)
    
    def remove_handler(self, handler: logging.Handler):
        """Remove a handler from the logger."""
        self.logger.removeHandler(handler)
    
    # Convenience methods for logging
    def debug(self, message: str, *args, **kwargs):
        """Log a debug message."""
        self.logger.debug(message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs):
        """Log an info message."""
        self.logger.info(message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        """Log a warning message."""
        self.logger.warning(message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs):
        """Log an error message."""
        self.logger.error(message, *args, **kwargs)
    
    def critical(self, message: str, *args, **kwargs):
        """Log a critical message."""
        self.logger.critical(message, *args, **kwargs)
    
    def exception(self, message: str, *args, **kwargs):
        """Log an exception with traceback."""
        self.logger.exception(message, *args, **kwargs)


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colored output for console."""
    
    def format(self, record):
        # Save original levelname
        original_levelname = record.levelname
        
        # Add color
        color = AppLogger.COLORS.get(record.levelname, '')
        reset = AppLogger.COLORS['RESET']
        record.levelname = f"{color}{record.levelname}{reset}"
        
        # Format the message
        formatted = super().format(record)
        
        # Restore original levelname
        record.levelname = original_levelname
        
        return formatted


# Context manager for temporary log level changes
class TemporaryLogLevel:
    """Context manager to temporarily change log level."""
    
    def __init__(self, logger: AppLogger, level: int):
        self.logger = logger
        self.new_level = level
        self.old_level = logger.logger.level
    
    def __enter__(self):
        self.logger.set_level(self.new_level)
        return self.logger
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logger.set_level(self.old_level)


# Quick setup function for simple use cases
def quick_logger(
    name: str = "app",
    log_dir: str = "logs",
    level: int = logging.INFO,
    console: bool = True
) -> AppLogger:
    """
    Quickly create a logger with sensible defaults.
    
    Args:
        name: Logger name
        log_dir: Directory for log files
        level: Logging level
        console: Enable console output
        
    Returns:
        AppLogger instance
    """
    return AppLogger(
        name=name,
        log_dir=log_dir,
        log_level=level,
        console_output=console
    )


if __name__ == "__main__":
    # Demo usage
    print("=== Enterprise Logger Demo ===\n")
    
    # Example 1: Basic usage
    print("1. Basic Logger:")
    logger1 = quick_logger(name="demo_app", console=True)
    logger1.info("This is an info message")
    logger1.warning("This is a warning message")
    logger1.error("This is an error message")
    
    print("\n2. Advanced Logger with colored output:")
    logger2 = AppLogger(
        name="advanced_app",
        log_dir="logs",
        max_bytes=5*1024*1024,  # 5MB
        backup_count=3,
        log_level=logging.DEBUG,
        console_output=True,
        use_colored_console=True
    )
    logger2.debug("Debug message")
    logger2.info("Info message")
    logger2.warning("Warning message")
    logger2.error("Error message")
    logger2.critical("Critical message")
    
    print("\n3. Temporary log level change:")
    with TemporaryLogLevel(logger1, logging.DEBUG):
        logger1.debug("This debug message is visible")
    logger1.debug("This debug message is NOT visible")
    
    print("\n4. Exception logging:")
    try:
        raise ValueError("Example exception")
    except Exception:
        logger1.exception("An error occurred")
    
    print("\n5. Retrieving existing logger:")
    retrieved_logger = AppLogger.get_logger("demo_app")
    if retrieved_logger:
        retrieved_logger.info("Retrieved and logged successfully!")
    
    print("\n=== Demo Complete ===")
    print(f"Log files created in: {Path('logs').absolute()}")
