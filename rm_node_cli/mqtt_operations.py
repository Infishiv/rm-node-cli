"""
MQTT operations for ESP RainMaker.
"""
import paho.mqtt.client as mqtt
import ssl
import json
import time
import logging
import os
import asyncio
from pathlib import Path
import AWSIoTPythonSDK
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
from typing import Optional, Dict, Any, Callable
import click
import sys

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
        
        # Use root.pem from the certificate directory or fallback to project's certs directory
        if not root_path:
            # First try to find root.pem in the same directory as the node certificate
            cert_dir = Path(cert_path).parent
            root_path = cert_dir / 'root.pem'
            
            # If not found there, try the project's certs directory
            if not root_path.exists():
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
        self.ping_interval = 45  # Check connection every 45 seconds (longer than ESP 20s keep-alive)
        self._connect_lock = asyncio.Lock()

        # Disable all AWS IoT SDK logging
        for logger_name in ['AWSIoTPythonSDK', 
                          'AWSIoTPythonSDK.core',
                          'AWSIoTPythonSDK.core.protocol.internal.clients',
                          'AWSIoTPythonSDK.core.protocol.mqtt_core',
                          'AWSIoTPythonSDK.core.protocol.internal.workers',
                          'AWSIoTPythonSDK.core.protocol.internal.defaults',
                          'AWSIoTPythonSDK.core.protocol.internal.events']:
            logging.getLogger(logger_name).setLevel(logging.CRITICAL)  # Set to CRITICAL to suppress all messages

        self._configure_mqtt_client()

    def _configure_mqtt_client(self):
        """Configure MQTT client with certificate paths."""
        for f in [self.cert_path, self.key_path, self.root_path]:
            if not os.path.exists(f):
                raise MQTTOperationsException(f"Certificate file not found: {f}")

        self.mqtt_client.configureEndpoint(self.broker, PORT)
        self.mqtt_client.configureCredentials(self.root_path, self.key_path, self.cert_path)
        
        # Optimized for ESP RainMaker and scalability
        self.mqtt_client.configureConnectDisconnectTimeout(8)  # Faster connection
        self.mqtt_client.configureMQTTOperationTimeout(6)     # Faster operations
        self.mqtt_client.configureAutoReconnectBackoffTime(1, 16, 10)  # Shorter backoff
        self.mqtt_client.configureOfflinePublishQueueing(100)  # Limited queue to prevent memory issues
        self.mqtt_client.configureDrainingFrequency(5)        # Faster draining: 5 Hz
        
        # Set keep-alive to match ESP RainMaker
        self.mqtt_client.configureMQTTOperationTimeout(6)  # 6 sec for fast response

    async def connect_async(self):
        """Connect to MQTT broker asynchronously with status tracking"""
        async with self._connect_lock:
            try:
                if not self.connected:
                    # Run connect in a thread pool since it's blocking
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, self.mqtt_client.connect)
                    if result:
                        self.connected = True
                        self.last_ping = time.time()
                    return result
                return True
            except Exception as e:
                self.connected = False
                raise MQTTOperationsException(f"Failed to connect: {str(e)}")

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

    async def disconnect_async(self):
        """Disconnect asynchronously from MQTT broker."""
        try:
            # Use silent disconnect to avoid "Disconnect error: 4" messages
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._silent_disconnect)
            self.connected = False
            return result
        except Exception:
            # Suppress disconnect errors during shutdown
            self.connected = False
            return True

    def disconnect(self):
        try:
            # Use silent disconnect to avoid "Disconnect error: 4" messages
            result = self._silent_disconnect()
            self.connected = False
            return result
        except Exception:
            # Suppress disconnect errors during shutdown
            self.connected = False
            return True
            
    def _silent_disconnect(self):
        """Silently disconnect without generating error messages."""
        try:
            # Temporarily suppress AWS IoT SDK logging during disconnect
            self._suppress_aws_logging()
            
            # Disconnect without waiting for broker response
            result = self.mqtt_client.disconnect()
            
            # Restore logging
            self._restore_aws_logging()
            return result
        except Exception:
            # Restore logging even if disconnect fails
            self._restore_aws_logging()
            # Suppress all disconnect errors
            return True
            
    def _suppress_aws_logging(self):
        """Temporarily suppress AWS IoT SDK logging during disconnect."""
        for logger_name in ['AWSIoTPythonSDK', 
                          'AWSIoTPythonSDK.core',
                          'AWSIoTPythonSDK.core.protocol.internal.clients',
                          'AWSIoTPythonSDK.core.protocol.mqtt_core',
                          'AWSIoTPythonSDK.core.protocol.internal.workers',
                          'AWSIoTPythonSDK.core.protocol.internal.defaults',
                          'AWSIoTPythonSDK.core.protocol.internal.events']:
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.CRITICAL)
            
    def _restore_aws_logging(self):
        """Restore AWS IoT SDK logging to normal level."""
        for logger_name in ['AWSIoTPythonSDK', 
                          'AWSIoTPythonSDK.core',
                          'AWSIoTPythonSDK.core.protocol.internal.clients',
                          'AWSIoTPythonSDK.core.protocol.mqtt_core',
                          'AWSIoTPythonSDK.core.protocol.internal.workers',
                          'AWSIoTPythonSDK.core.protocol.internal.defaults',
                          'AWSIoTPythonSDK.core.protocol.internal.events']:
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.ERROR)

    async def is_connected_async(self) -> bool:
        """Check if connected asynchronously with better validation."""
        try:
            # Quick check first
            if not self.connected:
                return False
                
            # Only check every ping_interval seconds to avoid overwhelming
            current_time = time.time()
            if current_time - self.last_ping < self.ping_interval:
                return self.connected
                
            # Try to publish to a test topic with timeout
            test_topic = f"$aws/things/{self.node_id}/ping"
            try:
                # Use a short timeout for ping operations
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, 
                        lambda: self.mqtt_client.publish(test_topic, "", 0)),
                    timeout=2.0  # 2 second timeout for ping
                )
                
                self.connected = bool(result)
                self.last_ping = current_time
                return self.connected
                
            except asyncio.TimeoutError:
                # Ping timed out, connection might be stale
                self.connected = False
                return False
            except Exception:
                # Any other error indicates connection issues
                self.connected = False
                return False
                
        except Exception:
            self.connected = False
            return False

    def is_connected(self) -> bool:
        """Check if connected with better validation."""
        try:
            # Quick check first
            if not self.connected:
                return False
                
            # Only check every ping_interval seconds to avoid overwhelming
            current_time = time.time()
            if current_time - self.last_ping < self.ping_interval:
                return self.connected
                
            # Try to publish to a test topic
            test_topic = f"$aws/things/{self.node_id}/ping"
            try:
                result = self.mqtt_client.publish(test_topic, "", 0)
                self.connected = bool(result)
                self.last_ping = current_time
                return self.connected
            except Exception:
                # Any error indicates connection issues
                self.connected = False
                return False
                
        except Exception:
            self.connected = False
            return False

    async def publish_async(self, topic, payload, qos=1):
        """Publish message asynchronously with retry logic and optional serialization"""
        try:
            if not await self.is_connected_async():
                await self.connect_async()

            if isinstance(payload, (dict, list)):
                payload = json.dumps(payload)

            # Use QoS 0 for status updates to avoid waiting for acknowledgment
            if 'otastatus' in topic:
                qos = 0

            # Run publish in a thread pool since it's blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, 
                lambda: self.mqtt_client.publish(topic, payload, qos))
            
            if result:
                # Only log at debug level
                self.logger.debug(f"Published to {topic}: {payload}")
            return result
        except Exception as e:
            self.logger.error(f"Publish failed: {str(e)}")
            raise MQTTOperationsException(f"Publish failed: {str(e)}")

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

    async def subscribe_async(self, topic, qos=1, callback=None):
        """Subscribe to a topic asynchronously"""
        try:
            if not await self.is_connected_async():
                await self.connect_async()

            if callback is None:
                callback = self._on_message

            # Ensure QoS is an integer
            qos = int(qos)
            
            # Run subscribe in a thread pool since it's blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, 
                lambda: self.mqtt_client.subscribe(topic, qos, callback))
            
            if result:
                # Only log at debug level
                self.logger.debug(f"Subscribed to {topic}")
            return result
        except Exception as e:
            self.logger.error(f"Subscribe failed: {str(e)}")
            raise MQTTOperationsException(f"Subscribe failed: {str(e)}")

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

    async def unsubscribe_async(self, topic):
        """Unsubscribe from a topic asynchronously"""
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, 
                lambda: self.mqtt_client.unsubscribe(topic))
            
            if result:
                # Only log at debug level
                self.logger.debug(f"Unsubscribed from {topic}")
            return result
        except Exception as e:
            raise MQTTOperationsException(f"Unsubscribe failed: {str(e)}")

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

    async def reconnect_async(self) -> bool:
        """Attempt to reconnect to MQTT broker asynchronously."""
        try:
            await self.disconnect_async()
            await asyncio.sleep(1)  # Brief delay before reconnecting
            return await self.connect_async()
        except Exception:
            return False

    def reconnect(self) -> bool:
        """Attempt to reconnect to MQTT broker."""
        try:
            self.disconnect()
            time.sleep(1)  # Brief delay before reconnecting
            return self.connect()
        except Exception:
            return False

    async def ping_async(self) -> bool:
        """Check if connection is alive and ping if needed asynchronously."""
        try:
            current_time = time.time()
            if current_time - self.last_ping >= self.ping_interval:
                # Publish a ping message to a temporary topic
                ping_topic = f"node/{self.node_id}/ping"
                if await self.publish_async(ping_topic, json.dumps({"timestamp": current_time}), 0):
                    self.last_ping = current_time
                    return True
                return False
            return True
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
