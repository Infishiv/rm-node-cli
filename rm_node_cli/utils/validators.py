"""
Validation utilities for MQTT CLI.
"""
import re
from urllib.parse import urlparse
from .exceptions import MQTTValidationError

def validate_broker_url(broker_url: str) -> None:
    """Validate MQTT broker URL format."""
    try:
        parsed = urlparse(broker_url)
        if not parsed.scheme in ['mqtt', 'mqtts']:
            raise MQTTValidationError("Broker URL must start with mqtt:// or mqtts://")
        if not parsed.hostname:
            raise MQTTValidationError("Broker URL must include a hostname")
    except Exception as e:
        raise MQTTValidationError(f"Invalid broker URL: {str(e)}")

def validate_topic(topic: str) -> None:
    """Validate MQTT topic format."""
    if not topic:
        raise MQTTValidationError("Topic cannot be empty")
    
    # MQTT topic validation rules
    if len(topic) > 65535:
        raise MQTTValidationError("Topic length exceeds maximum allowed (65,535 bytes)")
    
    if '#' in topic and topic[-1] != '#':
        raise MQTTValidationError("Wildcard '#' must be at the end of the topic")
    
    if topic.count('#') > 1:
        raise MQTTValidationError("Only one '#' wildcard allowed in topic")
    
    if '//' in topic:
        raise MQTTValidationError("Empty topic level (double forward slash) is not allowed")

def validate_qos(qos: int) -> None:
    """Validate QoS level."""
    if not isinstance(qos, int) or qos not in [0, 1, 2]:
        raise MQTTValidationError("QoS must be 0, 1, or 2")

def validate_node_id(node_id: str) -> None:
    """Validate node ID format."""
    if not node_id:
        raise MQTTValidationError("Node ID cannot be empty")
    
    # Add your specific node ID format validation rules here
    if not re.match(r'^[a-zA-Z0-9_-]+$', node_id):
        raise MQTTValidationError("Node ID can only contain alphanumeric characters, underscores, and hyphens")

def validate_version(version: str) -> None:
    """Validate version string format (e.g., '1.0.0')."""
    if not re.match(r'^\d+\.\d+\.\d+$', version):
        raise MQTTValidationError("Version must be in format X.Y.Z (e.g., 1.0.0)")

def validate_file_path(file_path: str) -> None:
    """Validate file path."""
    if not file_path:
        raise MQTTValidationError("File path cannot be empty")
    
    # Add your specific file path validation rules here
    # For example, check if path contains invalid characters
    invalid_chars = '<>:"|?*'
    if any(char in file_path for char in invalid_chars):
        raise MQTTValidationError(f"File path contains invalid characters: {invalid_chars}")

def validate_timeout(timeout: int) -> None:
    """Validate timeout value."""
    if not isinstance(timeout, int) or timeout < 0:
        raise MQTTValidationError("Timeout must be a positive integer") 