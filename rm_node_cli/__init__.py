"""
MQTT CLI - A command-line interface for MQTT operations.
"""

import os
import sys
import click
import logging
from pathlib import Path
from .commands.connection import connection
from .commands.ota import ota
from .utils.connection_manager import ConnectionManager
from .utils.config_manager import ConfigManager
from .mqtt_operations import MQTTOperations

__all__ = ['MQTTOperations', 'ConfigManager']

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Get logger for this module
logger = logging.getLogger(__name__)

# Default configuration directory
config_dir = Path.home() / '.rm-node'

# Create config directory if it doesn't exist
config_dir.mkdir(parents=True, exist_ok=True)

# Add module directory to Python path
module_dir = Path(__file__).parent.parent
sys.path.insert(0, str(module_dir))

@click.group()
@click.pass_context
def cli(ctx):
    """MQTT CLI tool for device management."""
    # Initialize context
    ctx.ensure_object(dict)
    
    # Set up config directory
    ctx.obj['CONFIG_DIR'] = config_dir
    
    # Initialize connection manager
    ctx.obj['CONNECTION_MANAGER'] = ConnectionManager(config_dir)
    
    # Load active connection if any
    active_connection = ctx.obj['CONNECTION_MANAGER'].get_active_connection()
    if active_connection:
        ctx.obj['MQTT'] = active_connection
        ctx.obj['NODE_ID'] = ctx.obj['CONNECTION_MANAGER'].active_node

# Register command groups
cli.add_command(connection)
cli.add_command(ota)