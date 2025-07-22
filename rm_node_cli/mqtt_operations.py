"""
MQTT operations for ESP RainMaker.
"""
import paho.mqtt.client as mqtt
import ssl
import json
import time
import logging
import os
from pathlib import Path
import AWSIoTPythonSDK
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
from typing import Optional, Dict, Any, Callable
import click
import sys
from .utils.exceptions import MQTTOperationsException

PORT = 443
OPERATION_TIMEOUT = 30
CONNECT_DISCONNECT_TIMEOUT = 20


class MQTTOperationsException(Exception):
    """Class to handle MQTTOperations method exceptions."""

class MQTTOperations:
    """MQTT client operations."""
    def __init__(self, broker, node_id, cert_path, key_path, root_path=None):
        self.broker = broker
        self.node_id = node_id
        self.cert_path = cert_path
        self.key_path = key_path
        
        # Use root.pem from our project's certs directory
        if not root_path:
            script_dir = Path(__file__).resolve().parent.parent
            root_path = script_dir / 'certs' / 'root.pem'
            if not root_path.exists():
                raise MQTTOperationsException(f"Root CA certificate not found at {root_path}")
        
        self.root_path = str(root_path)
        self.mqtt_client = AWSIoTMQTTClient(node_id)
        self.subscription_messages = {}
        self.old_msgs = {}
        self.logger = logging.getLogger("mqtt_cli")
        self.connected = False
        self.last_ping = 0
        self.ping_interval = 30  # Check connection every 30 seconds

        # Disable all AWS IoT SDK logging
        for logger_name in ['AWSIoTPythonSDK', 
                          'AWSIoTPythonSDK.core',
                          'AWSIoTPythonSDK.core.protocol.internal.clients',
                          'AWSIoTPythonSDK.core.protocol.mqtt_core',
                          'AWSIoTPythonSDK.core.protocol.internal.workers',
                          'AWSIoTPythonSDK.core.protocol.internal.defaults',
                          'AWSIoTPythonSDK.core.protocol.internal.events']:
            logging.getLogger(logger_name).setLevel(logging.ERROR)

        self._configure_mqtt_client()

    def _configure_mqtt_client(self):
        """Configure MQTT client with certificate paths."""
        for f in [self.cert_path, self.key_path, self.root_path]:
            if not os.path.exists(f):
                raise MQTTOperationsException(f"Certificate file not found: {f}")

        self.mqtt_client.configureEndpoint(self.broker, PORT)
        self.mqtt_client.configureCredentials(self.root_path, self.key_path, self.cert_path)
        self.mqtt_client.configureConnectDisconnectTimeout(CONNECT_DISCONNECT_TIMEOUT)
        self.mqtt_client.configureMQTTOperationTimeout(OPERATION_TIMEOUT)
        self.mqtt_client.configureAutoReconnectBackoffTime(1, 32, 20)
        self.mqtt_client.configureOfflinePublishQueueing(-1)  # Infinite publish queueing
        self.mqtt_client.configureDrainingFrequency(2)  # Draining: 2 Hz
        self.mqtt_client.configureConnectDisconnectTimeout(10)  # 10 sec
        self.mqtt_client.configureMQTTOperationTimeout(30)  # 30 sec instead of 5 sec

    def _check_connection(self):
        """Check connection status by attempting to publish to a test topic."""
        try:
            # Only check every ping_interval seconds
            current_time = time.time()
            if current_time - self.last_ping < self.ping_interval:
                return self.connected
                
            # Try to publish to a test topic
            test_topic = f"$aws/things/{self.node_id}/ping"
            result = self.mqtt_client.publish(test_topic, "", 0)
            
            self.connected = bool(result)
            self.last_ping = current_time
            return self.connected
            
        except Exception as e:
            self.connected = False
            return False

    def connect(self):
        """Connect to MQTT broker with status tracking"""
        try:
            if not self.connected:
                result = self.mqtt_client.connect()
                if result:
                    self.connected = True
                    self.last_ping = time.time()
                return result
            return True
        except Exception as e:
            self.connected = False
            raise MQTTOperationsException(f"Failed to connect: {str(e)}")

    def disconnect(self):
        try:
            result = self.mqtt_client.disconnect()
            if result:
                self.connected = False
            return result
        except Exception as e:
            raise MQTTOperationsException(f"Failed to disconnect: {str(e)}")

    def is_connected(self):
        """Check if currently connected"""
        return self._check_connection()

    def publish(self, topic, payload, qos=1):
        """Publish message with retry logic and optional serialization"""
        try:
            if not self.is_connected():
                self.connect()

            if isinstance(payload, (dict, list)):
                payload = json.dumps(payload)

            # Use QoS 0 for status updates to avoid waiting for acknowledgment
            if 'otastatus' in topic:
                qos = 0

            result = self.mqtt_client.publish(topic, payload, qos)
            if result:
                # Only log at debug level
                self.logger.debug(f"Published to {topic}: {payload}")
            return result
        except Exception as e:
            self.logger.error(f"Publish failed: {str(e)}")
            raise MQTTOperationsException(f"Publish failed: {str(e)}")

    def subscribe(self, topic, qos=1, callback=None):
        """Subscribe to a topic"""
        try:
            if not self.is_connected():
                self.connect()

            if callback is None:
                callback = self._on_message

            # Ensure QoS is an integer
            qos = int(qos)
            
            # Subscribe with proper parameter order for AWSIoTMQTTClient
            result = self.mqtt_client.subscribe(topic, qos, callback)
            if result:
                # Only log at debug level
                self.logger.debug(f"Subscribed to {topic}")
            return result
        except Exception as e:
            self.logger.error(f"Subscribe failed: {str(e)}")
            raise MQTTOperationsException(f"Subscribe failed: {str(e)}")

    def unsubscribe(self, topic):
        """Unsubscribe from a topic"""
        try:
            result = self.mqtt_client.unsubscribe(topic)
            if result:
                # Only log at debug level
                self.logger.debug(f"Unsubscribed from {topic}")
            return result
        except Exception as e:
            raise MQTTOperationsException(f"Unsubscribe failed: {str(e)}")

    def _on_message(self, client, userdata, message):
        """Default message callback"""
        try:
            payload = json.loads(message.payload.decode())
            self.subscription_messages[message.topic] = payload
            self.logger.info(json.dumps(payload, indent=2))
            self.old_msgs.setdefault(message.topic, []).append(payload)
        except json.JSONDecodeError:
            self.logger.warning(f"Non-JSON message received: {message.payload.decode()}")
            self.subscription_messages[message.topic] = message.payload.decode()
            self.old_msgs.setdefault(message.topic, []).append(message.payload.decode())

    def reconnect(self) -> bool:
        """Attempt to reconnect to MQTT broker."""
        try:
            self.disconnect()
            time.sleep(1)  # Brief delay before reconnecting
            return self.connect()
        except Exception:
            return False

    def ping(self) -> bool:
        """Check if connection is alive and ping if needed."""
        try:
            current_time = time.time()
            if current_time - self.last_ping >= self.ping_interval:
                # Publish a ping message to a temporary topic
                ping_topic = f"node/{self.node_id}/ping"
                if self.mqtt_client.publish(ping_topic, json.dumps({"timestamp": current_time}), 0):
                    self.last_ping = current_time
                    return True
                return False
            return True
        except Exception:
            return False


class PublishResult:
    def __init__(self, success=True):
        self._published = success

    def wait_for_publish(self, timeout=None):
        return True

    def is_published(self):
        return self._published
