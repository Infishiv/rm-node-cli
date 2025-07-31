"""
Connection manager for MQTT CLI.
"""
import os
import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from ..mqtt_operations import MQTTOperations

class ConnectionManager:
    """Manages MQTT client connections and their persistence."""
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.connections: Dict[str, MQTTOperations] = {}
        self.connection_info: Dict[str, dict] = {}
        self.active_node = None
        self.state_file = config_dir / 'connection.json'
        self.logger = logging.getLogger(__name__)
        self._load()
        
        # Background task for maintaining connections
        self.connection_task = None
        self.is_running = False

    def _load(self):
        """Load connection info from state file."""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self.connection_info = data.get('connections', {})
                    self.active_node = data.get('active_node')
        except Exception as e:
            self.logger.warning(f"Failed to load connection state: {str(e)}")
            self.connection_info = {}
            self.active_node = None

    def _save(self):
        """Save connection info to state file."""
        try:
            data = {
                'connections': self.connection_info,
                'active_node': self.active_node
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            self.logger.warning(f"Failed to save connection state: {str(e)}")

    async def connect_all_nodes(self) -> Tuple[int, int]:
        """
        Connect to all nodes concurrently.
        
        Returns:
            Tuple[int, int]: (number of successful connections, total number of nodes)
        """
        if not self.connection_info:
            return 0, 0
            
        # Create tasks for all connections
        connection_tasks = []
        for node_id, info in self.connection_info.items():
            task = self._connect_node(node_id, info)
            connection_tasks.append(task)
            
        # Wait for all connections to complete
        results = await asyncio.gather(*connection_tasks, return_exceptions=True)
        
        # Count successful connections
        success_count = sum(1 for result in results if result)
        return success_count, len(self.connection_info)

    async def _connect_node(self, node_id: str, info: dict) -> bool:
        """
        Connect to a single node asynchronously.
        
        Args:
            node_id: The node ID to connect
            info: Connection information dictionary
            
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            client = MQTTOperations(
                broker=info['broker'],
                node_id=node_id,
                cert_path=info['cert_path'],
                key_path=info['key_path']
            )
            if await client.connect_async():
                self.connections[node_id] = client
                self.logger.info(f"Successfully connected to node {node_id}")
                return True
        except Exception as e:
            self.logger.warning(f"Failed to connect to {node_id}: {str(e)}")
        return False

    async def start_background_connections(self):
        """Start background task to maintain connections to all nodes."""
        if self.connection_task is not None:
            return
            
        self.is_running = True
        self.connection_task = asyncio.create_task(self._maintain_connections())
        
    async def stop_background_connections(self):
        """Stop the background connection maintenance task."""
        self.is_running = False
        if self.connection_task:
            self.connection_task.cancel()
            try:
                await self.connection_task
            except asyncio.CancelledError:
                pass
            self.connection_task = None

    async def _maintain_connections(self):
        """Background task to maintain connections to all nodes."""
        while self.is_running:
            try:
                # Attempt to connect any disconnected nodes
                for node_id, info in self.connection_info.items():
                    if node_id not in self.connections or not self.connections[node_id].is_connected():
                        await self._connect_node(node_id, info)
                
                # Wait before next check
                await asyncio.sleep(30)  # Check every 30 seconds
            except Exception as e:
                self.logger.error(f"Error in connection maintenance: {str(e)}")
                await asyncio.sleep(5)  # Short delay on error

    def add_connection(self, node_id: str, broker: str, cert_path: str, key_path: str, client: MQTTOperations):
        """
        Add a new connection.
        
        Args:
            node_id: The node ID
            broker: The broker URL
            cert_path: Path to the node certificate
            key_path: Path to the node key
            client: The connected MQTT client
        """
        self.connections[node_id] = client
        self.connection_info[node_id] = {
            'broker': broker,
            'cert_path': str(cert_path),
            'key_path': str(key_path)
        }
        self.active_node = node_id
        self._save()

    async def remove_connection(self, node_id: str) -> bool:
        """Remove a connection."""
        if node_id in self.connections:
            client = self.connections[node_id]
            try:
                await client.disconnect_async()
            except:
                pass
            del self.connections[node_id]
            del self.connection_info[node_id]
            
            if self.active_node == node_id:
                self.active_node = None
            
            self._save()
            return True
        return False

    def get_connection(self, node_id: str) -> Optional[MQTTOperations]:
        """Get a connection by node ID."""
        return self.connections.get(node_id)

    def get_connected_nodes(self) -> List[str]:
        """Get list of currently connected node IDs."""
        return [node_id for node_id, client in self.connections.items() if client.is_connected()]

    def get_active_node(self) -> Optional[str]:
        """Get the currently active node ID."""
        return self.active_node

    def get_active_connection(self) -> Optional[MQTTOperations]:
        """Get the currently active connection."""
        if self.active_node:
            return self.get_connection(self.active_node)
        return None

    async def disconnect_all(self) -> dict:
        """Disconnect all connections."""
        results = {}
        for node_id in list(self.connections.keys()):
            results[node_id] = await self.remove_connection(node_id)
        return results

    def list_connections(self) -> list:
        """List all stored connection information."""
        return list(self.connection_info.keys())

    async def update_connection_broker(self, node_id: str, broker: str):
        """Update broker URL for a connection."""
        if node_id in self.connection_info:
            self.connection_info[node_id]['broker'] = broker
            self._save()
            # Force reconnect with new broker
            if node_id in self.connections:
                try:
                    await self.connections[node_id].disconnect_async()
                except:
                    pass
                del self.connections[node_id] 