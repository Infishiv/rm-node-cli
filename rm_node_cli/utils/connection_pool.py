"""
Connection pool manager for handling large-scale node connections efficiently.

This module provides:
1. Rate-limited connection establishment
2. Connection pool management with limits
3. Circuit breaker pattern for failed connections
4. Batch processing capabilities
5. Resource-aware monitoring
"""

import asyncio
import time
import logging
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum
from collections import deque
import random


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"
    CIRCUIT_OPEN = "circuit_open"


@dataclass
class ConnectionStats:
    """Statistics for a node connection."""
    connection_attempts: int = 0
    successful_connections: int = 0
    failed_connections: int = 0
    last_attempt_time: float = 0
    last_success_time: float = 0
    consecutive_failures: int = 0
    total_uptime: float = 0
    connection_start_time: Optional[float] = None


@dataclass
class PoolConfig:
    """Configuration for the connection pool optimized for ESP RainMaker."""
    max_concurrent_connections: int = 0  # Unlimited connections
    connection_rate_limit: int = 0       # Unlimited rate
    batch_size: int = 0                  # No batching
    circuit_breaker_threshold: int = 3   # failures before circuit opens
    circuit_breaker_timeout: int = 120   # 2 minutes (shorter for faster retry)
    connection_timeout: int = 8          # optimized for ESP RainMaker
    operation_timeout: int = 6           # optimized for ESP RainMaker
    health_check_interval: int = 25      # aligned with ESP RainMaker 20s keep-alive + margin
    max_retries: int = 2                 # fewer retries for faster startup
    retry_backoff_base: float = 1.5      # shorter backoff
    jitter_range: float = 0.2            # slightly more jitter
    esp_keepalive_time: int = 20        # ESP RainMaker keep-alive period


class ConnectionPool:
    """Manages a pool of MQTT connections with rate limiting and circuit breaker."""
    
    def __init__(self, config: PoolConfig = None):
        self.config = config or PoolConfig()
        self.connections: Dict[str, any] = {}  # node_id -> MQTTOperations
        self.connection_states: Dict[str, ConnectionState] = {}
        self.connection_stats: Dict[str, ConnectionStats] = {}
        self.pending_connections: Set[str] = set()
        self.circuit_breaker_timers: Dict[str, float] = {}
        
        # Rate limiting - unlimited if set to 0
        if self.config.max_concurrent_connections > 0:
            self.connection_semaphore = asyncio.Semaphore(self.config.max_concurrent_connections)
        else:
            self.connection_semaphore = None
            
        if self.config.connection_rate_limit > 0:
            self.rate_limiter = asyncio.Semaphore(self.config.connection_rate_limit)
        else:
            self.rate_limiter = None
            
        self.rate_limiter_reset_task = None
        
        # Health monitoring
        self.health_check_task = None
        self.is_running = False
        
        # Logger
        self.logger = logging.getLogger("rm_node_cli.connection_pool")
        
    async def start(self):
        """Start the connection pool and background tasks."""
        self.is_running = True
        self.rate_limiter_reset_task = asyncio.create_task(self._reset_rate_limiter())
        self.health_check_task = asyncio.create_task(self._health_check_loop())
        self.logger.info("Connection pool started")
        
    async def stop(self):
        """Stop the connection pool with fast shutdown."""
        self.is_running = False
        
        # Suppress AWS IoT SDK logging during shutdown to eliminate error messages
        self._suppress_aws_logging()
        
        # Suppress our own logging during shutdown
        self.logger.setLevel(logging.CRITICAL)
        
        # Cancel background tasks immediately
        if self.rate_limiter_reset_task:
            self.rate_limiter_reset_task.cancel()
        if self.health_check_task:
            self.health_check_task.cancel()
            
        # Fast disconnect without waiting for individual operations
        await self.disconnect_all()
        
    async def connect_nodes_batch(self, nodes: List[Tuple[str, str, str]], 
                                 mqtt_operations_class) -> Tuple[int, int]:
        """Connect nodes with rate limiting (unlimited if batch_size=0)."""
        total_nodes = len(nodes)
        successful = 0
        
        if self.config.batch_size > 0:
            # Process nodes in batches
            for i in range(0, total_nodes, self.config.batch_size):
                batch = nodes[i:i + self.config.batch_size]
                batch_successful = await self._connect_batch(batch, mqtt_operations_class)
                successful += batch_successful
                
                # Minimal delay between batches for faster progress
                if i + self.config.batch_size < total_nodes:
                    await asyncio.sleep(0.1)  # Reduced from 0.5s
        else:
            # Unlimited mode - process all nodes at once
            successful = await self._connect_batch(nodes, mqtt_operations_class)
                
        return successful, total_nodes
        
    async def _connect_batch(self, batch: List[Tuple[str, str, str]], 
                           mqtt_operations_class) -> int:
        """Connect a batch of nodes concurrently."""
        tasks = []
        for node_id, cert_path, key_path in batch:
            if self._should_attempt_connection(node_id):
                task = self._connect_single_node(node_id, cert_path, key_path, mqtt_operations_class)
                tasks.append(task)
                
        if not tasks:
            return 0
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return sum(1 for result in results if result is True)
        
    async def _connect_single_node(self, node_id: str, cert_path: str, key_path: str,
                                 mqtt_operations_class) -> bool:
        """Connect a single node with rate limiting and circuit breaker."""
        # Check circuit breaker
        if not self._should_attempt_connection(node_id):
            return False
            
        # Acquire rate limiter
        if self.rate_limiter:
            await self.rate_limiter.acquire()
            
        # Acquire connection semaphore
        if self.connection_semaphore:
            async with self.connection_semaphore:
                return await self._do_connection(node_id, cert_path, key_path, mqtt_operations_class)
        else:
            return await self._do_connection(node_id, cert_path, key_path, mqtt_operations_class)
            
    async def _do_connection(self, node_id: str, cert_path: str, key_path: str,
                           mqtt_operations_class) -> bool:
        """Perform the actual connection with retries."""
        if node_id not in self.connection_stats:
            self.connection_stats[node_id] = ConnectionStats()
            
        stats = self.connection_stats[node_id]
        self.connection_states[node_id] = ConnectionState.CONNECTING
        self.pending_connections.add(node_id)
        
        try:
            for attempt in range(self.config.max_retries):
                stats.connection_attempts += 1
                stats.last_attempt_time = time.time()
                
                try:
                    # Create MQTT client
                    mqtt_client = mqtt_operations_class(
                        broker=self._get_broker(),
                        node_id=node_id,
                        cert_path=cert_path,
                        key_path=key_path
                    )
                    
                    # Set reduced timeouts for better scalability
                    mqtt_client.mqtt_client.configureConnectDisconnectTimeout(self.config.connection_timeout)
                    mqtt_client.mqtt_client.configureMQTTOperationTimeout(self.config.operation_timeout)
                    
                    # Connect with timeout
                    connect_task = mqtt_client.connect_async()
                    result = await asyncio.wait_for(connect_task, timeout=self.config.connection_timeout)
                    
                    if result:
                        self.connections[node_id] = mqtt_client
                        self.connection_states[node_id] = ConnectionState.CONNECTED
                        stats.successful_connections += 1
                        stats.last_success_time = time.time()
                        stats.consecutive_failures = 0
                        stats.connection_start_time = time.time()
                        
                        # Print connection success immediately like before
                        import click
                        click.echo(click.style(f"✓ Connected to {node_id}", fg='green'))
                        return True
                    else:
                        raise Exception("Connection returned False")
                        
                except asyncio.TimeoutError:
                    error_msg = f"Connection timeout for {node_id} (attempt {attempt + 1})"
                    self.logger.warning(error_msg)
                    if attempt == 0:  # Only show error on first attempt to reduce noise
                        import click
                        click.echo(click.style(f"{error_msg}", fg='yellow'))
                    await self._handle_connection_failure(node_id, "Connection timeout", attempt)
                    
                except Exception as e:
                    error_msg = f"Connection error for {node_id} (attempt {attempt + 1}): {str(e)}"
                    self.logger.warning(error_msg)
                    if attempt == 0:  # Only show error on first attempt to reduce noise
                        import click
                        click.echo(click.style(f"✗ {error_msg}", fg='red'))
                    await self._handle_connection_failure(node_id, str(e), attempt)
                    
                # Exponential backoff with jitter
                if attempt < self.config.max_retries - 1:
                    delay = (self.config.retry_backoff_base ** attempt) + random.uniform(0, self.config.jitter_range)
                    await asyncio.sleep(delay)
                    
            # All retries failed
            self._open_circuit_breaker(node_id)
            return False
            
        finally:
            self.pending_connections.discard(node_id)
            if self.connection_states.get(node_id) == ConnectionState.CONNECTING:
                self.connection_states[node_id] = ConnectionState.FAILED
                
    async def _handle_connection_failure(self, node_id: str, error: str, attempt: int):
        """Handle connection failure with circuit breaker logic."""
        stats = self.connection_stats[node_id]
        stats.failed_connections += 1
        stats.consecutive_failures += 1
        
        if stats.consecutive_failures >= self.config.circuit_breaker_threshold:
            self._open_circuit_breaker(node_id)
            
    def _open_circuit_breaker(self, node_id: str):
        """Open circuit breaker for a node."""
        self.connection_states[node_id] = ConnectionState.CIRCUIT_OPEN
        self.circuit_breaker_timers[node_id] = time.time()
        self.logger.warning(f"Circuit breaker opened for {node_id}")
        
    def _should_attempt_connection(self, node_id: str) -> bool:
        """Check if we should attempt connection based on circuit breaker."""
        state = self.connection_states.get(node_id, ConnectionState.DISCONNECTED)
        
        if state == ConnectionState.CIRCUIT_OPEN:
            # Check if circuit breaker timeout has passed
            if node_id in self.circuit_breaker_timers:
                elapsed = time.time() - self.circuit_breaker_timers[node_id]
                if elapsed > self.config.circuit_breaker_timeout:
                    self.connection_states[node_id] = ConnectionState.DISCONNECTED
                    del self.circuit_breaker_timers[node_id]
                    return True
            return False
            
        return state in [ConnectionState.DISCONNECTED, ConnectionState.FAILED]
        
    async def _reset_rate_limiter(self):
        """Reset rate limiter every second."""
        while self.is_running:
            await asyncio.sleep(1.0)
            # Release all permits and re-initialize
            if self.rate_limiter:
                for _ in range(self.config.connection_rate_limit):
                    try:
                        self.rate_limiter.release()
                    except ValueError:
                        break  # Semaphore is already at max
                    
    async def _health_check_loop(self):
        """Background health check for connections."""
        while self.is_running:
            await asyncio.sleep(self.config.health_check_interval)
            await self._perform_health_checks()
            
    async def _perform_health_checks(self):
        """Check health of all connections."""
        if not self.connections:
            return
            
        # Check a subset of connections each time to avoid overwhelming
        check_batch_size = min(10, len(self.connections))
        nodes_to_check = list(self.connections.keys())[:check_batch_size]
        
        for node_id in nodes_to_check:
            try:
                mqtt_client = self.connections[node_id]
                if not await mqtt_client.is_connected_async():
                    self.logger.warning(f"Health check failed for {node_id}")
                    self.connection_states[node_id] = ConnectionState.FAILED
                    del self.connections[node_id]
            except Exception as e:
                self.logger.error(f"Health check error for {node_id}: {str(e)}")
                
    def get_connection(self, node_id: str):
        """Get connection for a node."""
        return self.connections.get(node_id)
        
    def get_connected_nodes(self) -> List[str]:
        """Get list of connected node IDs."""
        return [node_id for node_id, state in self.connection_states.items() 
                if state == ConnectionState.CONNECTED]
                
    def get_connection_stats(self) -> Dict[str, Dict]:
        """Get connection statistics."""
        stats = {}
        for node_id, connection_stats in self.connection_stats.items():
            stats[node_id] = {
                "state": self.connection_states.get(node_id, ConnectionState.DISCONNECTED).value,
                "attempts": connection_stats.connection_attempts,
                "successful": connection_stats.successful_connections,
                "failed": connection_stats.failed_connections,
                "consecutive_failures": connection_stats.consecutive_failures,
                "last_success": connection_stats.last_success_time,
                "uptime": self._calculate_uptime(connection_stats)
            }
        return stats
        
    def _calculate_uptime(self, stats: ConnectionStats) -> float:
        """Calculate uptime for a connection."""
        if stats.connection_start_time:
            return time.time() - stats.connection_start_time
        return 0
        
    async def disconnect_all(self):
        """Disconnect all nodes with fast shutdown to avoid error messages."""
        if not self.connections:
            return
            
        # Clear connections immediately without waiting for individual disconnects
        # This prevents "Disconnect error: 4" messages from AWS IoT SDK
        connections_to_clear = list(self.connections.items())
        self.connections.clear()
        self.connection_states.clear()
        
        # Disconnect in background without waiting for results
        for node_id, mqtt_client in connections_to_clear:
            try:
                # Use silent disconnect to avoid error messages
                asyncio.create_task(self._silent_disconnect(mqtt_client))
            except Exception:
                # Ignore any disconnect errors during shutdown
                pass
                
    async def _silent_disconnect(self, mqtt_client):
        """Silently disconnect MQTT client without generating error messages."""
        try:
            # Disconnect without waiting for broker response
            await mqtt_client.disconnect_async()
        except Exception:
            # Suppress all disconnect errors during shutdown
            pass
        
    def _get_broker(self):
        """Get broker URL - to be set by the main manager."""
        # This will be set by the manager when initializing
        return getattr(self, '_broker_url', None)
        
    def set_broker(self, broker_url: str):
        """Set the broker URL."""
        self._broker_url = broker_url
        
    def _suppress_aws_logging(self):
        """Suppress AWS IoT SDK logging during shutdown."""
        # Suppress all AWS IoT SDK logging
        for logger_name in ['AWSIoTPythonSDK', 
                          'AWSIoTPythonSDK.core',
                          'AWSIoTPythonSDK.core.protocol.internal.clients',
                          'AWSIoTPythonSDK.core.protocol.mqtt_core',
                          'AWSIoTPythonSDK.core.protocol.internal.workers',
                          'AWSIoTPythonSDK.core.protocol.internal.defaults',
                          'AWSIoTPythonSDK.core.protocol.internal.events',
                          'AWSIoTPythonSDK.core.protocol.internal.connection',
                          'AWSIoTPythonSDK.core.protocol.internal.threading',
                          'AWSIoTPythonSDK.core.protocol.internal.websocket']:
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.CRITICAL)
        
        # Also suppress any other potential verbose loggers
        for logger_name in ['paho.mqtt', 'paho.mqtt.client', 'paho.mqtt.publish']:
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.CRITICAL)