"""
Debug logging utility for MQTT CLI.
"""
import logging
import functools
import click
import inspect
from typing import Any, Callable

def get_command_logger(command_name: str) -> logging.Logger:
    """Get a logger for a specific command module."""
    logger = logging.getLogger(f"mqtt_cli.commands.{command_name}")
    return logger

def debug_log(func: Callable) -> Callable:
    """Decorator to add debug logging to command functions."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Get the command name from the function's module
        command_name = func.__module__.split('.')[-1]
        logger = get_command_logger(command_name)
        
        # Get context object from args or kwargs
        ctx = next((arg for arg in args if hasattr(arg, 'obj')), None)
        if ctx is None and 'ctx' in kwargs:
            ctx = kwargs['ctx']
            
        # Check if debug mode is enabled
        is_debug = ctx and ctx.obj and ctx.obj.get('DEBUG', False)
        
        if is_debug:
            # Log function call with arguments
            func_args = inspect.signature(func).bind(*args, **kwargs)
            func_args.apply_defaults()
            # Filter out context object from logged arguments
            filtered_args = {k: v for k, v in func_args.arguments.items() 
                           if k != 'ctx' and not k.startswith('_')}
            
            logger.debug(f"Executing {func.__name__} with args: {filtered_args}")
            
            try:
                result = func(*args, **kwargs)
                logger.debug(f"{func.__name__} completed successfully")
                return result
            except Exception as e:
                logger.exception(f"Error in {func.__name__}: {str(e)}")
                raise
        else:
            return func(*args, **kwargs)
            
    return wrapper

def debug_step(message: str) -> Callable:
    """Decorator to log debug steps within functions."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get the command name from the function's module
            command_name = func.__module__.split('.')[-1]
            logger = get_command_logger(command_name)
            
            # Get context object from args or kwargs
            ctx = next((arg for arg in args if hasattr(arg, 'obj')), None)
            if ctx is None and 'ctx' in kwargs:
                ctx = kwargs['ctx']
                
            # Check if debug mode is enabled
            is_debug = ctx and ctx.obj and ctx.obj.get('DEBUG', False)
            
            if is_debug:
                logger.debug(f"{message}")
            return func(*args, **kwargs)
        return wrapper
    return decorator 