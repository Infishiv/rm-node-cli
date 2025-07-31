"""
Professional logging system for RM-Node CLI.

This module provides comprehensive logging with:
- File logging with rotation
- Crash logging
- Monitoring issue tracking
- Structured logging for different components
- Error tracking and reporting
"""

import logging
import logging.handlers
import os
import sys
import traceback
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import threading
import queue
import time

class RMNodeLogger:
    """Professional logging system for RM-Node CLI."""
    
    def __init__(self, config_dir: str, log_level: str = "INFO"):
        """
        Initialize the logging system.
        
        Args:
            config_dir: Configuration directory where logs will be stored
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        self.config_dir = Path(config_dir)
        self.log_level = getattr(logging, log_level.upper())
        self.log_dir = self.config_dir / "logs"
        self.log_dir.mkdir(exist_ok=True)
        
        # Initialize loggers
        self._setup_loggers()
        self._setup_crash_logging()
        self._setup_monitoring_logging()
        
        # Error tracking
        self.error_count = 0
        self.crash_count = 0
        self.monitoring_issues = []
        
        # Thread-safe error queue
        self.error_queue = queue.Queue()
        self._start_error_monitor()
    
    def _setup_loggers(self):
        """Setup all loggers with proper handlers."""
        # Main application logger
        self.app_logger = logging.getLogger("rm_node_cli")
        self.app_logger.setLevel(self.log_level)
        
        # MQTT operations logger
        self.mqtt_logger = logging.getLogger("rm_node_cli.mqtt")
        self.mqtt_logger.setLevel(self.log_level)
        
        # Shell logger
        self.shell_logger = logging.getLogger("rm_node_cli.shell")
        self.shell_logger.setLevel(self.log_level)
        
        # Command logger
        self.command_logger = logging.getLogger("rm_node_cli.commands")
        self.command_logger.setLevel(self.log_level)
        
        # Monitoring logger
        self.monitor_logger = logging.getLogger("rm_node_cli.monitoring")
        self.monitor_logger.setLevel(self.log_level)
        
        # Setup handlers for each logger
        self._setup_file_handlers()
        self._setup_console_handlers()
    
    def _setup_file_handlers(self):
        """Setup file handlers with rotation."""
        # Main application log
        app_handler = logging.handlers.RotatingFileHandler(
            self.log_dir / "rm-node.log",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        app_handler.setFormatter(self._get_formatter())
        self.app_logger.addHandler(app_handler)
        
        # MQTT operations log
        mqtt_handler = logging.handlers.RotatingFileHandler(
            self.log_dir / "mqtt.log",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=3
        )
        mqtt_handler.setFormatter(self._get_formatter())
        self.mqtt_logger.addHandler(mqtt_handler)
        
        # Shell operations log
        shell_handler = logging.handlers.RotatingFileHandler(
            self.log_dir / "shell.log",
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3
        )
        shell_handler.setFormatter(self._get_formatter())
        self.shell_logger.addHandler(shell_handler)
        
        # Commands log
        command_handler = logging.handlers.RotatingFileHandler(
            self.log_dir / "commands.log",
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3
        )
        command_handler.setFormatter(self._get_formatter())
        self.command_logger.addHandler(command_handler)
        
        # Monitoring log
        monitor_handler = logging.handlers.RotatingFileHandler(
            self.log_dir / "monitoring.log",
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3
        )
        monitor_handler.setFormatter(self._get_formatter())
        self.monitor_logger.addHandler(monitor_handler)
    
    def _setup_console_handlers(self):
        """Setup console handlers for immediate feedback."""
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(self._get_console_formatter())
        
        # Only add console handler to app logger for main output
        self.app_logger.addHandler(console_handler)
    
    def _get_formatter(self):
        """Get detailed formatter for file logging."""
        return logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
    
    def _get_console_formatter(self):
        """Get simple formatter for console output."""
        return logging.Formatter('%(levelname)s: %(message)s')
    
    def _setup_crash_logging(self):
        """Setup crash logging system."""
        self.crash_logger = logging.getLogger("rm_node_cli.crash")
        self.crash_logger.setLevel(logging.ERROR)
        
        # Crash log handler (no rotation for crash logs)
        crash_handler = logging.FileHandler(self.log_dir / "crashes.log")
        crash_handler.setFormatter(self._get_formatter())
        self.crash_logger.addHandler(crash_handler)
    
    def _setup_monitoring_logging(self):
        """Setup monitoring issue logging."""
        self.monitoring_logger = logging.getLogger("rm_node_cli.monitoring.issues")
        self.monitoring_logger.setLevel(logging.WARNING)
        
        # Monitoring issues handler
        monitoring_handler = logging.handlers.RotatingFileHandler(
            self.log_dir / "monitoring_issues.log",
            maxBytes=2*1024*1024,  # 2MB
            backupCount=3
        )
        monitoring_handler.setFormatter(self._get_formatter())
        self.monitoring_logger.addHandler(monitoring_handler)
    
    def _start_error_monitor(self):
        """Start background error monitoring thread."""
        def error_monitor():
            while True:
                try:
                    error_info = self.error_queue.get(timeout=1)
                    if error_info is None:  # Shutdown signal
                        break
                    
                    # Process error
                    self._process_error(error_info)
                    
                except queue.Empty:
                    continue
                except Exception as e:
                    # Log the error in the monitor itself
                    self.crash_logger.error(f"Error in error monitor: {str(e)}")
        
        self.error_monitor_thread = threading.Thread(target=error_monitor, daemon=True)
        self.error_monitor_thread.start()
    
    def _process_error(self, error_info: Dict[str, Any]):
        """Process and categorize errors."""
        error_type = error_info.get('type', 'unknown')
        error_msg = error_info.get('message', '')
        error_traceback = error_info.get('traceback', '')
        node_id = error_info.get('node_id', 'unknown')
        
        if error_type == 'crash':
            self.crash_count += 1
            self.crash_logger.error(
                f"CRASH - {error_msg}\n"
                f"Node: {node_id}\n"
                f"Traceback: {error_traceback}"
            )
        elif error_type == 'monitoring':
            self.monitoring_issues.append({
                'timestamp': datetime.now().isoformat(),
                'node_id': node_id,
                'message': error_msg,
                'traceback': error_traceback
            })
            self.monitoring_logger.warning(
                f"MONITORING ISSUE - {error_msg}\n"
                f"Node: {node_id}\n"
                f"Traceback: {error_traceback}"
            )
        else:
            self.error_count += 1
            self.app_logger.error(
                f"ERROR - {error_msg}\n"
                f"Node: {node_id}\n"
                f"Traceback: {error_traceback}"
            )
    
    def log_crash(self, error: Exception, node_id: str = "unknown", context: str = ""):
        """Log a crash with full context."""
        error_info = {
            'type': 'crash',
            'message': str(error),
            'traceback': traceback.format_exc(),
            'node_id': node_id,
            'context': context,
            'timestamp': datetime.now().isoformat()
        }
        self.error_queue.put(error_info)
    
    def log_monitoring_issue(self, issue: str, node_id: str = "unknown", context: str = ""):
        """Log a monitoring issue."""
        error_info = {
            'type': 'monitoring',
            'message': issue,
            'traceback': traceback.format_exc(),
            'node_id': node_id,
            'context': context,
            'timestamp': datetime.now().isoformat()
        }
        self.error_queue.put(error_info)
    
    def log_connection_issue(self, node_id: str, issue: str, retry_count: int = 0):
        """Log connection-related issues."""
        self.mqtt_logger.warning(
            f"Connection issue for node {node_id}: {issue} "
            f"(retry {retry_count})"
        )
    
    def log_command_execution(self, command: str, args: List[str], success: bool, 
                            duration: float, node_count: int = 0):
        """Log command execution details."""
        status = "SUCCESS" if success else "FAILED"
        self.command_logger.info(
            f"Command: {command} {args} - {status} "
            f"(duration: {duration:.2f}s, nodes: {node_count})"
        )
    
    def log_shell_interaction(self, user_input: str, response_type: str = "command"):
        """Log shell interactions."""
        self.shell_logger.debug(
            f"Shell interaction - Type: {response_type}, Input: {user_input}"
        )
    
    def get_log_summary(self) -> Dict[str, Any]:
        """Get a summary of all logging activity."""
        return {
            'error_count': self.error_count,
            'crash_count': self.crash_count,
            'monitoring_issues_count': len(self.monitoring_issues),
            'log_files': {
                'main': str(self.log_dir / "rm-node.log"),
                'mqtt': str(self.log_dir / "mqtt.log"),
                'shell': str(self.log_dir / "shell.log"),
                'commands': str(self.log_dir / "commands.log"),
                'monitoring': str(self.log_dir / "monitoring.log"),
                'crashes': str(self.log_dir / "crashes.log"),
                'monitoring_issues': str(self.log_dir / "monitoring_issues.log")
            },
            'recent_monitoring_issues': self.monitoring_issues[-10:] if self.monitoring_issues else []
        }
    
    def cleanup(self):
        """Cleanup logging resources."""
        # Send shutdown signal to error monitor
        self.error_queue.put(None)
        
        # Wait for monitor thread to finish
        if hasattr(self, 'error_monitor_thread'):
            self.error_monitor_thread.join(timeout=5)
        
        # Log final summary
        summary = self.get_log_summary()
        self.app_logger.info(f"Logging session ended. Summary: {summary}")

# Global logger instance
_global_logger: Optional[RMNodeLogger] = None

def get_logger() -> RMNodeLogger:
    """Get the global logger instance."""
    global _global_logger
    if _global_logger is None:
        raise RuntimeError("Logger not initialized. Call setup_logging() first.")
    return _global_logger

def setup_logging(config_dir: str, log_level: str = "INFO") -> RMNodeLogger:
    """Setup the global logging system."""
    global _global_logger
    _global_logger = RMNodeLogger(config_dir, log_level)
    return _global_logger

def log_crash(error: Exception, node_id: str = "unknown", context: str = ""):
    """Log a crash using the global logger."""
    logger = get_logger()
    logger.log_crash(error, node_id, context)

def log_monitoring_issue(issue: str, node_id: str = "unknown", context: str = ""):
    """Log a monitoring issue using the global logger."""
    logger = get_logger()
    logger.log_monitoring_issue(issue, node_id, context) 