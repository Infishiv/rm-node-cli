"""
RM-Node CLI - A command-line interface for ESP RainMaker MQTT node management.
"""

import os
import sys
import logging
from pathlib import Path

__version__ = "1.0.0"

# Configure basic logging
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

__all__ = ['__version__']