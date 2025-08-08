#!/usr/bin/env python3
"""
RMNode CLI - A user-friendly MQTT node management CLI.

This is the main entry point that:
1. Takes --cert-path and --broker-id as initial parameters
2. Auto-discovers all nodes from certificates
3. Connects to ALL nodes simultaneously
4. Starts background listeners for all topics
5. Opens an interactive shell for commands
"""

import click
import asyncio
import json
import sys
import os
import time
import signal
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from .mqtt_operations import MQTTOperations
from .utils.config_manager import ConfigManager
from .utils.connection_manager import ConnectionManager
from .utils.debug_logger import debug_log, debug_step
from .utils.exceptions import MQTTConnectionError
from .utils.cert_finder import find_node_cert_key_pairs, find_by_mac_address, find_certificates_in_directory
from .utils.logger import setup_logging, get_logger, log_crash, log_monitoring_issue
from .utils.connection_pool import ConnectionPool, PoolConfig
from .utils.optimized_monitoring import AdaptiveMonitor, SelectiveSubscriptionManager, MonitoringLevel

# Get logger
logger = logging.getLogger(__name__)

# Global shutdown event
shutdown_event = asyncio.Event()

class RMNodeManager:
    """Manages all node connections and background operations with scalable architecture."""
    
    def __init__(self, config_dir: str, max_nodes: int = 1000):
        self.config_dir = config_dir
        self.config_manager = ConfigManager(config_dir)
        self.broker_url: Optional[str] = None
        self.cert_paths: List[str] = []  # Support multiple paths
        self.running = True
        
        # Optimized for ESP RainMaker (20s keep-alive) 
        pool_config = PoolConfig(
            max_concurrent_connections=min(max_nodes, 100),  # AWS IoT limits
            connection_rate_limit=30,  # Faster startup
            batch_size=15,  # Smaller batches for better progress feedback
            circuit_breaker_threshold=3,  # Faster failure detection  
            circuit_breaker_timeout=120,  # 2 minutes (faster recovery)
            connection_timeout=8,  # Optimized for ESP RainMaker
            operation_timeout=6,   # Optimized for ESP RainMaker
            health_check_interval=25,  # Aligned with ESP 20s keep-alive
            max_retries=2,  # Fewer retries for faster startup
            esp_keepalive_time=20  # ESP RainMaker keep-alive period
        )
        
        self.connection_pool = ConnectionPool(pool_config)
        self.adaptive_monitor = AdaptiveMonitor(max_concurrent_monitors=min(max_nodes // 10, 50))
        self.subscription_manager = SelectiveSubscriptionManager(max_subscriptions=min(max_nodes * 3, 300))
        
        # Background task for maintaining connections
        self.connection_task = None
        self.monitoring_task = None
        self.is_running = False
        
        # OTA job storage - two files system
        self.ota_jobs_file = os.path.join(config_dir, "ota_jobs.json")
        self.ota_status_history_file = os.path.join(config_dir, "ota_status_history.json")
        self.ota_jobs = self._load_ota_jobs()
        self.ota_status_history = self._load_ota_status_history()
        
    @debug_step("Discovering nodes")
    def discover_nodes(self) -> List[tuple]:
        """Discover all nodes from multiple certificate directories using threading."""
        if not self.cert_paths:
            raise Exception("Certificate paths not set")
            
        all_nodes = []
        
        # Import threading modules
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        def discover_nodes_in_path(cert_path: str) -> List[tuple]:
            """Discover nodes in a single certificate path."""
            try:
                path_nodes = []
                cert_path_obj = Path(cert_path)
                
                # Method 1: Try MAC address directory structure first
                logger.debug(f"Trying MAC address directory structure in {cert_path}")
                mac_results = find_by_mac_address(cert_path_obj)
                if mac_results:
                    logger.debug(f"Found {len(mac_results)} nodes in MAC directory structure in {cert_path}")
                    path_nodes.extend(mac_results)
                
                # Method 2: Try node_details structure
                logger.debug(f"Trying node_details structure in {cert_path}")
                try:
                    # First check if we're already in a node_details structure
                    cert_pairs = find_certificates_in_directory(cert_path_obj)
                    if cert_pairs:
                        logger.debug(f"Found {len(cert_pairs)} nodes in directory structure in {cert_path}")
                        path_nodes.extend(cert_pairs)
                        
                    # Then try traditional node_details search
                    node_pairs = find_node_cert_key_pairs(cert_path)
                    if node_pairs:
                        logger.debug(f"Found {len(node_pairs)} nodes in node_details structure in {cert_path}")
                        path_nodes.extend(node_pairs)
                except Exception as e:
                    logger.debug(f"Error in node_details search in {cert_path}: {str(e)}")
                
                return path_nodes
            except Exception as e:
                logger.debug(f"Error discovering nodes in {cert_path}: {str(e)}")
                return []
        
        # Use ThreadPoolExecutor to discover nodes in parallel
        with ThreadPoolExecutor(max_workers=min(len(self.cert_paths), 4)) as executor:
            # Submit all discovery tasks
            future_to_path = {executor.submit(discover_nodes_in_path, path): path for path in self.cert_paths}
            
            # Collect results as they complete
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    path_nodes = future.result()
                    all_nodes.extend(path_nodes)
                    logger.debug(f"Completed discovery in {path}: {len(path_nodes)} nodes found")
                except Exception as e:
                    logger.debug(f"Error in discovery thread for {path}: {str(e)}")
        
        # Remove duplicates based on node_id
        unique_nodes = {}
        for node_id, cert_path, key_path in all_nodes:
            if node_id not in unique_nodes:
                unique_nodes[node_id] = (node_id, cert_path, key_path)
        
        final_nodes = list(unique_nodes.values())
        
        if not final_nodes:
            paths_str = ", ".join(self.cert_paths)
            raise Exception(f"No nodes found in any of the certificate paths: {paths_str}")
            
        logger.debug(f"Discovered {len(final_nodes)} unique nodes across {len(self.cert_paths)} paths")
        return final_nodes
        
    @debug_step("Connecting to all nodes")
    async def connect_all_nodes(self) -> Tuple[int, int]:
        """Connect to all discovered nodes using scalable connection pool."""
        try:
            nodes = self.discover_nodes()
            
            if not nodes:
                click.echo(click.style("✗ No nodes discovered", fg='red'))
                return 0, 0
            
            # Set broker in connection pool
            self.connection_pool.set_broker(self.broker_url)
            
            # Start connection pool
            await self.connection_pool.start()
            
            # Connect nodes in batches with rate limiting
            connected_count, total_count = await self.connection_pool.connect_nodes_batch(
                nodes, MQTTOperations
            )
            
            if connected_count == 0:
                click.echo(click.style("✗ No nodes connected successfully", fg='red'))
                return 0, total_count
                
            # Store connections in config for persistent shell access
            connected_nodes = self.connection_pool.get_connected_nodes()
            for node_id in connected_nodes:
                # Find cert/key paths for this node
                for n_id, cert_path, key_path in nodes:
                    if n_id == node_id:
                        self.config_manager.add_node(node_id, cert_path, key_path)
                        break
                        
            click.echo(click.style(f"✓ Connected to {connected_count}/{total_count} nodes", fg='green'))
            
            # Show timing information
            click.echo(click.style("🔄 Finalizing setup...", fg='yellow'))
            
            # Start optimized monitoring
            await self._start_optimized_monitoring(connected_nodes)
            
            return connected_count, total_count
            
        except Exception as e:
            logger.debug(f"Error in connect_all_nodes: {str(e)}")
            click.echo(click.style(f"✗ Error: {str(e)}", fg='red'))
            return 0, 0

    async def _start_optimized_monitoring(self, connected_nodes: List[str]):
        """Start optimized monitoring for connected nodes."""
        try:
            click.echo(click.style("🔄 Setting up adaptive monitoring...", fg='yellow'))
            
            # Start adaptive monitor (this should be fast)
            await self.adaptive_monitor.start()
            
            # Add connected nodes to monitoring with appropriate levels
            # Prioritize based on ESP RainMaker keep-alive requirements
            for i, node_id in enumerate(connected_nodes):
                if i < 20:  # First 20 nodes get high priority (more critical)
                    level = MonitoringLevel.HIGH
                elif i < 40:  # Next 20 nodes get normal priority  
                    level = MonitoringLevel.NORMAL
                else:  # Rest get low priority to save resources
                    level = MonitoringLevel.LOW
                    
                self.adaptive_monitor.add_node(node_id, level)
                
            click.echo(click.style(f"✓ Started optimized monitoring for {len(connected_nodes)} nodes", fg='blue'))
            click.echo(click.style("💡 Monitoring adapts automatically based on node health", fg='cyan'))
            
        except Exception as e:
            logger.error(f"Error starting optimized monitoring: {str(e)}")
            click.echo(click.style(f"⚠ Monitoring setup had issues: {str(e)}", fg='yellow'))
            
    def get_connection(self, node_id: str):
        """Get connection for a specific node."""
        return self.connection_pool.get_connection(node_id)
        
    def get_connected_nodes(self) -> List[str]:
        """Get list of all connected node IDs."""
        return self.connection_pool.get_connected_nodes()
        
    @property
    def connections(self) -> Dict[str, any]:
        """Backward compatibility property for accessing connections."""
        # Return a dict-like object that provides access to connections
        connected_nodes = self.connection_pool.get_connected_nodes()
        return {node_id: self.connection_pool.get_connection(node_id) 
                for node_id in connected_nodes}

    async def start_background_connections(self):
        """Start background task to maintain connections using connection pool."""
        if self.connection_task is not None:
            return
            
        self.is_running = True
        # The connection pool handles its own background maintenance
        # We just need to start monitoring tasks
        self.monitoring_task = asyncio.create_task(self._maintain_monitoring())
        
    async def stop_background_connections(self):
        """Stop the background connection and monitoring tasks."""
        self.is_running = False
        
        # Stop connection pool
        if self.connection_pool:
            await self.connection_pool.stop()
            
        # Stop monitoring
        if self.adaptive_monitor:
            await self.adaptive_monitor.stop()
            
        if self.connection_task:
            self.connection_task.cancel()
            try:
                await self.connection_task
            except asyncio.CancelledError:
                pass
            self.connection_task = None
            
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
            self.monitoring_task = None

    async def _maintain_monitoring(self):
        """Background task to maintain monitoring and adjust levels."""
        while self.is_running and not shutdown_event.is_set():
            try:
                # Get monitoring summary
                summary = self.adaptive_monitor.get_monitoring_summary()
                
                # Adjust monitoring based on performance
                if summary["nodes_with_errors"] > 10:
                    # Too many errors, increase monitoring for all
                    await self.adaptive_monitor.bulk_adjust_monitoring({"max_errors": 1})
                    
                # Log monitoring status periodically
                if summary["total_nodes"] > 0:
                    logger.debug(f"Monitoring {summary['total_nodes']} nodes, "
                               f"{summary['active_monitors']} active monitors, "
                               f"{summary['nodes_with_errors']} with errors")
                
                # Wait before next check
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=60)
                except asyncio.TimeoutError:
                    continue
                
            except Exception as e:
                logger.error(f"Error in monitoring maintenance: {str(e)}")
                await asyncio.sleep(10)  # Short delay on error

    @debug_step("Starting background listeners")
    async def start_background_listeners(self):
        """Start optimized background listeners using selective subscription."""
        connected_nodes = self.connection_pool.get_connected_nodes()
        if not connected_nodes:
            return
            
        # Topics to subscribe to for all nodes
        topics = [
            "params/remote",      # Parameter responses from nodes
            "otaurl",            # OTA URL responses from nodes
            "to-node",           # Command requests to nodes (we monitor)
        ]
        
        def create_message_handler(node_id: str, topic_suffix: str):
            """Create a message handler for a specific node and topic."""
            def handler(client, userdata, message):
                try:
                    payload = message.payload.decode('utf-8')
                    timestamp = click.style(f"[{time.strftime('%H:%M:%S')}]", fg='blue')
                    node_color = click.style(f"[{node_id}]", fg='cyan')
                    topic_color = click.style(f"[{topic_suffix}]", fg='yellow')
                    click.echo(f"{timestamp} {node_color} {topic_color} {payload}")
                    
                    # Special handling for OTA URL responses
                    if topic_suffix == "otaurl":
                        try:
                            ota_response = json.loads(payload)
                            if self.store_ota_job(node_id, ota_response):
                                click.echo(click.style(f"✓ Stored OTA job {ota_response.get('ota_job_id', 'unknown')} for {node_id}", fg='green'))
                        except json.JSONDecodeError:
                            logger.debug(f"Invalid JSON in OTA response from {node_id}")
                        except Exception as e:
                            logger.debug(f"Error processing OTA response from {node_id}: {str(e)}")
                    
                    # Store node responses from to-node topic
                    elif topic_suffix == "to-node":
                        try:
                            response_data = json.loads(payload)
                            # Store in persistent shell if available
                            if hasattr(self, 'shell') and hasattr(self.shell, '_store_node_response'):
                                self.shell._store_node_response(node_id, response_data)
                                click.echo(click.style(f"✓ Stored node response for {node_id}", fg='green'))
                        except json.JSONDecodeError:
                            logger.debug(f"Invalid JSON in node response from {node_id}")
                        except Exception as e:
                            logger.debug(f"Error processing node response from {node_id}: {str(e)}")
                    
                    # Store remote parameters from params/remote topic
                    elif topic_suffix == "params/remote":
                        try:
                            params_data = json.loads(payload)
                            # Store in persistent shell if available
                            if hasattr(self, 'shell') and hasattr(self.shell, '_store_remote_params'):
                                self.shell._store_remote_params(node_id, params_data)
                                click.echo(click.style(f"✓ Stored remote params for {node_id}", fg='green'))
                        except json.JSONDecodeError:
                            logger.debug(f"Invalid JSON in remote params from {node_id}")
                        except Exception as e:
                            logger.debug(f"Error processing remote params from {node_id}: {str(e)}")
                            
                except Exception as e:
                    logger.debug(f"Error handling message from {node_id}: {str(e)}")
            return handler
        
        # Subscribe using selective subscription manager for better resource management
        click.echo(click.style("🔄 Setting up topic subscriptions...", fg='yellow'))
        
        success_count = 0
        total_subscriptions = 0
        
        # Prioritize high-priority nodes for subscriptions
        for node_id in connected_nodes[:50]:  # Limit to first 50 nodes to avoid overload
            mqtt_client = self.connection_pool.get_connection(node_id)
            if not mqtt_client:
                continue
                
            node_success = True
            for topic_suffix in topics:
                full_topic = f"node/{node_id}/{topic_suffix}"
                handler = create_message_handler(node_id, topic_suffix)
                
                try:
                    # Use QoS 0 for better performance and ESP RainMaker compatibility
                    if await mqtt_client.subscribe_async(full_topic, qos=0, callback=handler):
                        logger.debug(f"Subscribed to {full_topic}")
                        total_subscriptions += 1
                    else:
                        logger.debug(f"Failed to subscribe to {full_topic}")
                        node_success = False
                        break  # Skip remaining topics for this node if one fails
                except Exception as e:
                    logger.debug(f"Error subscribing to {full_topic}: {str(e)}")
                    node_success = False
                    break  # Skip remaining topics for this node if one fails
            
            if node_success:
                success_count += 1
                
            # Add small delay to prevent overwhelming broker
            if success_count % 10 == 0:  # Every 10 nodes
                await asyncio.sleep(0.1)
                    
        # Show a single summary message
        if success_count == min(len(connected_nodes), 50):
            click.echo(click.style(f"✓ Monitoring {total_subscriptions} topic subscriptions on {success_count} nodes", fg='green'))
        else:
            click.echo(click.style(f"⚠ Started monitoring with partial success: {success_count}/{min(len(connected_nodes), 50)} nodes", fg='yellow'))

    def publish_to_all(self, topic_suffix: str, payload: str, qos: int = 1) -> int:
        """Publish message to all connected nodes."""
        success_count = 0
        for node_id, mqtt_client in self.connections.items():
            full_topic = f"node/{node_id}/{topic_suffix}"
            try:
                if mqtt_client.publish(full_topic, payload, qos=qos):
                    success_count += 1
                    logger.debug(f"Published to {full_topic}")
                else:
                    logger.debug(f"Failed to publish to {full_topic}")
            except Exception as e:
                logger.debug(f"Error publishing to {node_id}: {str(e)}")
        return success_count
        
    async def publish_to_node(self, node_id: str, topic: str, payload, qos: int = 1) -> bool:
        """Publish message to specific node with retry logic."""
        if node_id not in self.connections:
            return False
            
        max_retries = 3
        retry_delay = 1  # seconds
        
        for attempt in range(max_retries):
            try:
                # Check if connection is still alive
                if not self.connections[node_id].is_connected():
                    logger.debug(f"Connection lost for {node_id}, attempting reconnect (attempt {attempt + 1}/{max_retries})")
                    # Try to reconnect using the existing client
                    try:
                        if self.connections[node_id].reconnect():
                            logger.debug(f"Successfully reconnected to {node_id}")
                        else:
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay)
                                continue
                            else:
                                logger.debug(f"Failed to reconnect to {node_id} after {max_retries} attempts")
                                return False
                    except Exception as reconnect_error:
                        logger.debug(f"Reconnect error for {node_id}: {str(reconnect_error)}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            continue
                        else:
                            return False
                
                # Try to publish
                result = await self.connections[node_id].publish_async(topic, payload, qos=qos)
                if result:
                    return True
                else:
                    if attempt < max_retries - 1:
                        logger.debug(f"Publish failed for {node_id} (attempt {attempt + 1}/{max_retries}), retrying...")
                        await asyncio.sleep(retry_delay)
                    else:
                        logger.debug(f"Failed to publish to {node_id} after {max_retries} attempts")
                        return False
                        
            except Exception as e:
                logger.debug(f"Error publishing to {node_id} (attempt {attempt + 1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                else:
                    return False
        
        return False
            
    def get_connected_nodes(self) -> List[str]:
        """Get list of connected node IDs."""
        return [node_id for node_id, client in self.connections.items() if client.is_connected()]
        
    def _load_ota_jobs(self) -> Dict[str, Dict[str, Any]]:
        """Load OTA jobs from JSON file."""
        try:
            if os.path.exists(self.ota_jobs_file):
                with open(self.ota_jobs_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.debug(f"Error loading OTA jobs: {str(e)}")
        return {}
        
    def _save_ota_jobs(self):
        """Save OTA jobs to JSON file."""
        try:
            with open(self.ota_jobs_file, 'w') as f:
                json.dump(self.ota_jobs, f, indent=2)
        except Exception as e:
            logger.debug(f"Error saving OTA jobs: {str(e)}")
            
    def _load_ota_status_history(self) -> Dict[str, Dict[str, Any]]:
        """Load OTA status history from JSON file."""
        try:
            if os.path.exists(self.ota_status_history_file):
                with open(self.ota_status_history_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.debug(f"Error loading OTA status history: {str(e)}")
        return {}
        
    def _save_ota_status_history(self):
        """Save OTA status history to JSON file."""
        try:
            with open(self.ota_status_history_file, 'w') as f:
                json.dump(self.ota_status_history, f, indent=2)
        except Exception as e:
            logger.debug(f"Error saving OTA status history: {str(e)}")
            
    def store_ota_job(self, node_id: str, ota_response: Dict[str, Any]):
        """Store OTA job information from response."""
        try:
            # Extract OTA job ID from response
            ota_job_id = ota_response.get('ota_job_id')
            if not ota_job_id:
                logger.debug("No ota_job_id found in response")
                return False
                
            # Initialize node entry if it doesn't exist
            if node_id not in self.ota_jobs:
                self.ota_jobs[node_id] = {}
                
            # Store the OTA job with timestamp
            self.ota_jobs[node_id][ota_job_id] = {
                **ota_response,
                'timestamp': int(time.time() * 1000),
                'received_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            # Save to file
            self._save_ota_jobs()
            
            logger.debug(f"Stored OTA job {ota_job_id} for node {node_id}")
            return True
            
        except Exception as e:
            logger.debug(f"Error storing OTA job: {str(e)}")
            return False
            
    def get_ota_jobs(self, node_id: Optional[str] = None) -> Dict[str, Any]:
        """Get stored OTA jobs, optionally filtered by node ID."""
        if node_id:
            return self.ota_jobs.get(node_id, {})
        return self.ota_jobs
        
    def clear_ota_jobs(self, node_id: Optional[str] = None):
        """Clear OTA jobs, optionally for a specific node."""
        if node_id:
            if node_id in self.ota_jobs:
                del self.ota_jobs[node_id]
                self._save_ota_jobs()
        else:
            self.ota_jobs = {}
            self._save_ota_jobs()
            
    def move_ota_job_to_history(self, node_id: str, job_id: str, status: str):
        """Move OTA job from primary to history with status."""
        if node_id in self.ota_jobs and job_id in self.ota_jobs[node_id]:
            # Get the job data
            job_data = self.ota_jobs[node_id][job_id].copy()
            
            # Add status and timestamp
            job_data['ota_status'] = status
            job_data['status_timestamp'] = int(time.time() * 1000)
            job_data['status_received_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
            
            # Initialize history entry if needed
            if node_id not in self.ota_status_history:
                self.ota_status_history[node_id] = {}
            
            # Move to history
            self.ota_status_history[node_id][job_id] = job_data
            
            # Remove from primary
            del self.ota_jobs[node_id][job_id]
            
            # Clean up empty node entries
            if not self.ota_jobs[node_id]:
                del self.ota_jobs[node_id]
            
            # Save both files
            self._save_ota_jobs()
            self._save_ota_status_history()
            
            logger.debug(f"Moved OTA job {job_id} for node {node_id} to history with status {status}")
            return True
        return False
        
    def get_ota_status_history(self, node_id: Optional[str] = None) -> Dict[str, Any]:
        """Get OTA status history, optionally filtered by node ID."""
        if node_id:
            return self.ota_status_history.get(node_id, {})
        return self.ota_status_history

    async def disconnect_all_nodes(self):
        """Disconnect from all connected nodes."""
        logger.debug("Disconnecting from all nodes...")
        
        if not self.connections:
            logger.debug("No connections to disconnect")
            return 0, 0
            
        # Create disconnect tasks for all nodes
        disconnect_tasks = []
        for node_id in list(self.connections.keys()):
            task = self._disconnect_single_node(node_id)
            disconnect_tasks.append(task)
            
        if disconnect_tasks:
            # Wait for all disconnect operations to complete
            results = await asyncio.gather(*disconnect_tasks, return_exceptions=True)
            
            # Count successful disconnections
            success_count = sum(1 for result in results if result and not isinstance(result, Exception))
            failed_count = len(results) - success_count
            
            logger.debug(f"Disconnected from {success_count}/{len(results)} nodes")
            return success_count, len(results)
        
        return 0, 0

    async def _disconnect_single_node(self, node_id: str) -> bool:
        """Disconnect from a single node."""
        try:
            if node_id in self.connections:
                client = self.connections[node_id]
                
                # Disconnect the client
                if await client.disconnect_async():
                    # Remove from manager connections
                    del self.connections[node_id]
                    logger.debug(f"Successfully disconnected from {node_id}")
                    return True
                else:
                    logger.debug(f"Failed to disconnect from {node_id}")
                    return False
            else:
                logger.debug(f"Node {node_id} is not connected")
                return False
        except Exception as e:
            logger.error(f"Error disconnecting from {node_id}: {str(e)}")
            return False

    async def cleanup(self):
        """Fast cleanup - stop background tasks but skip full disconnection for speed."""
        logger.debug("Starting fast cleanup...")
        self.running = False
        
        # Set shutdown event to stop background tasks
        shutdown_event.set()
        
        # Stop background tasks without waiting for full disconnection
        # This is much faster and suitable for ESP RainMaker's 20s keep-alive
        await self.stop_background_connections()
        
        # For ESP RainMaker, the connections will timeout naturally (20s keep-alive)
        # No need to explicitly disconnect each node for faster exit
        logger.debug("Fast cleanup completed")

# Global manager instance
manager: Optional[RMNodeManager] = None
loop: Optional[asyncio.AbstractEventLoop] = None

def handle_exception(loop, context):
    """Handle exceptions in the event loop."""
    msg = context.get("exception", context["message"])
    logger.error(f"Caught exception: {msg}")

def cleanup_and_exit():
    """Fast cleanup and exit the program."""
    if manager and loop:
        try:
            if loop.is_running():
                # Schedule fast cleanup
                future = asyncio.run_coroutine_threadsafe(manager.cleanup(), loop)
                # Very short timeout for fast exit
                future.result(timeout=0.5)
            else:
                # If loop is not running, run cleanup directly
                loop.run_until_complete(manager.cleanup())
        except Exception as e:
            logger.debug(f"Fast exit, ignoring cleanup error: {str(e)}")
    sys.exit(0)

def signal_handler(signum, frame):
    """Handle interrupt signals."""
    click.echo("\nExiting...")
    cleanup_and_exit()

@click.command()
@click.option('--cert-path', required=True, multiple=True,
              help='Path to certificates directory containing node certificates (can specify multiple times)')
@click.option('--broker-id', default='mqtts://a1p72mufdu6064-ats.iot.us-east-1.amazonaws.com/',
              help='MQTT broker URL (default: mqtts://a1p72mufdu6064-ats.iot.us-east-1.amazonaws.com/)')
@click.option('--config-dir', default=str(Path.home() / '.rm-node'),
              help='Configuration directory (default: ~/.rm-node)')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.option('--max-nodes', default=1000, type=int,
              help='Maximum number of nodes to handle (default: 1000)')
@debug_log
def main(cert_path: Tuple[str, ...], broker_id: str, config_dir: str, debug: bool, max_nodes: int):
    """
    RM-Node CLI - Efficient MQTT Node Management
    
    Connect to all nodes and start an interactive shell for managing them.
    
    Examples:
        rm-node --cert-path /path/to/certs
        rm-node --cert-path /path/to/certs --broker-id mqtts://broker.example.com:8883
        rm-node --cert-path /path1/certs --cert-path /path2/certs
    """
    global manager, loop
    
    try:
        # Create configuration directory with proper error handling
        try:
            config_path = Path(config_dir).resolve()
            config_path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            click.echo(click.style(f"✗ Error: Permission denied creating config directory at {config_path}", fg='red'))
            click.echo("Please specify a different config directory using --config-dir or ensure you have write permissions")
            sys.exit(1)
        except Exception as e:
            click.echo(click.style(f"✗ Error creating config directory: {str(e)}", fg='red'))
            sys.exit(1)
            
        # Setup professional logging system
        log_level = "DEBUG" if debug else "INFO"
        logger = setup_logging(str(config_path), log_level)
        app_logger = logger.app_logger
        
        # Initialize manager with max_nodes parameter
        manager = RMNodeManager(str(config_path), max_nodes=max_nodes)
        manager.broker_url = broker_id
        manager.cert_paths = list(cert_path)  # Store multiple paths
        
        # Store configuration
        manager.config_manager.set_broker(broker_id)
        manager.config_manager.set_cert_paths(cert_path)  # Store multiple paths
        
        app_logger.info("RM-Node CLI Starting...")
        app_logger.info(f"Certificate paths: {', '.join(cert_path)}")
        app_logger.info(f"Broker: {broker_id}")
        app_logger.info(f"Config directory: {config_path}")
        
        click.echo(click.style("RM-Node CLI Starting...", fg='green', bold=True))
        click.echo(f"Certificate paths: {', '.join(cert_path)}")
        click.echo(f"Broker: {broker_id}")
        click.echo(f"Config directory: {config_path}")
        click.echo("-" * 60)
        
        # Create event loop and run async operations
        async def setup_and_run():
            try:
                # Connect to all nodes
                connected_count, total_nodes = await manager.connect_all_nodes()
                if connected_count == 0:
                    click.echo(click.style("✗ Failed to connect to any nodes", fg='red'))
                    sys.exit(1)
                    
                # Start background listeners
                await manager.start_background_listeners()
                
                # Set debug level for persistent shell if debug mode is enabled
                if debug:
                    logger.shell_logger.setLevel(logging.DEBUG)
                    click.echo(click.style("🔍 Debug mode enabled for interactive shell", fg='yellow'))
                    app_logger.info("Debug mode enabled for interactive shell")
                
                # Import and start the interactive shell
                from .persistent_shell import start_interactive_shell
                await start_interactive_shell(manager, str(config_path))
            finally:
                # Ensure cleanup happens
                await manager.cleanup()
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Create and configure event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.set_exception_handler(handle_exception)
        
        # Run the async setup
        loop.run_until_complete(setup_and_run())
        
    except KeyboardInterrupt:
        app_logger.info("Shutdown requested by user")
        click.echo("\n\nShutdown requested by user")
        cleanup_and_exit()
    except Exception as e:
        # Log the crash with full context
        log_crash(e, context="main_function")
        app_logger.error(f"Critical error in main function: {str(e)}")
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'))
        cleanup_and_exit()
        sys.exit(1)
    finally:
        # Cleanup logging
        try:
            logger.cleanup()
        except Exception as cleanup_error:
            print(f"Error during logging cleanup: {cleanup_error}")
        
        if loop:
            loop.close() 