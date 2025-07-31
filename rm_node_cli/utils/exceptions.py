"""
Custom exceptions for MQTT CLI.
"""

class MQTTError(Exception):
    """Base exception for MQTT CLI errors."""
    pass

class MQTTConnectionError(MQTTError):
    """Exception raised for MQTT connection errors."""
    pass

class MQTTMessageError(MQTTError):
    """Exception raised for MQTT messaging errors."""
    pass

class MQTTValidationError(MQTTError):
    """Exception raised for validation errors."""
    pass

class MQTTOTAError(MQTTError):
    """Exception raised for OTA update errors."""
    pass

class MQTTOperationsException(MQTTError):
    """Exception raised for MQTT operations errors."""
    pass 