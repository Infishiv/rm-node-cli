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
import logging
import sys
import os
import signal
from pathlib import Path
from typing import Dict, List, Optional

# Import CLI components
from mqtt_cli.utils.config_manager import ConfigManager
from mqtt_cli.utils.cert_finder import find_node_cert_key_pairs
from mqtt_cli.utils.debug_logger import debug_log, debug_step
from mqtt_cli.core.mqtt_client import MQTTOperations
from mqtt_cli.utils.connection_manager import ConnectionManager

# Get logger
logger = logging.getLogger(__name__)

class RMNodeManager:
    """Manages all node connections and background operations."""
    
    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self.config_manager = ConfigManager(config_dir)
        self.connections: Dict[str, MQTTOperations] = {}
        self.broker_url: Optional[str] = None
        self.cert_path: Optional[str] = None
        self.running = True
        
    @debug_step("Discovering nodes")
    def discover_nodes(self) -> List[tuple]:
        """Discover all nodes from certificate directory."""
        if not self.cert_path:
            raise Exception("Certificate path not set")
            
        nodes = find_node_cert_key_pairs(Path(self.cert_path))
        if not nodes:
            raise Exception(f"No nodes found in {self.cert_path}")
            
        logger.debug(f"Discovered {len(nodes)} nodes")
        return nodes
        
    @debug_step("Connecting to all nodes")
    async def connect_all_nodes(self) -> bool:
        """Connect to all discovered nodes."""
        try:
            nodes = self.discover_nodes()
            connected_count = 0
            
            for node_id, cert_path, key_path in nodes:
                try:
                    logger.debug(f"Connecting to node: {node_id}")
                    
                    # Create MQTT client for this node
                    mqtt_client = MQTTOperations(
                        broker=self.broker_url,
                        node_id=node_id,
                        cert_path=cert_path,
                        key_path=key_path
                    )
                    
                    # Connect
                    if mqtt_client.connect():
                        self.connections[node_id] = mqtt_client
                        # Store node config
                        self.config_manager.add_node(node_id, cert_path, key_path)
                        connected_count += 1
                        click.echo(click.style(f"✓ Connected to {node_id}", fg='green'))
                    else:
                        click.echo(click.style(f"✗ Failed to connect to {node_id}", fg='red'))
                        
                except Exception as e:
                    logger.debug(f"Error connecting to {node_id}: {str(e)}")
                    click.echo(click.style(f"✗ Error connecting to {node_id}: {str(e)}", fg='red'))
                    
            if connected_count == 0:
                click.echo(click.style("✗ No nodes connected successfully", fg='red'))
                return False
                
            click.echo(click.style(f"✓ Connected to {connected_count}/{len(nodes)} nodes", fg='green'))
            return True
            
        except Exception as e:
            logger.debug(f"Error in connect_all_nodes: {str(e)}")
            click.echo(click.style(f"✗ Error: {str(e)}", fg='red'))
            return False
            
    @debug_step("Starting background listeners")
    async def start_background_listeners(self):
        """Start background listeners for all important topics."""
        if not self.connections:
            return
            
        # Topics to subscribe to for all nodes
        topics = [
            "params/remote",      # Parameter responses
            "otaurl",            # OTA responses
            "to-cloud",          # Command responses  
            "status",            # Status updates
            "alert"              # User alerts
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
                except Exception as e:
                    logger.debug(f"Error handling message from {node_id}: {str(e)}")
            return handler
        
        # Subscribe to all topics for all connected nodes
        for node_id, mqtt_client in self.connections.items():
            for topic_suffix in topics:
                full_topic = f"node/{node_id}/{topic_suffix}"
                handler = create_message_handler(node_id, topic_suffix)
                
                try:
                    if mqtt_client.subscribe(full_topic, qos=1, callback=handler):
                        logger.debug(f"Subscribed to {full_topic}")
                    else:
                        logger.debug(f"Failed to subscribe to {full_topic}")
                except Exception as e:
                    logger.debug(f"Error subscribing to {full_topic}: {str(e)}")
                    
        click.echo(click.style(f"✓ Started background listeners for {len(self.connections)} nodes", fg='green'))
        
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
        
    def publish_to_node(self, node_id: str, topic_suffix: str, payload: str, qos: int = 1) -> bool:
        """Publish message to specific node."""
        if node_id not in self.connections:
            return False
            
        full_topic = f"node/{node_id}/{topic_suffix}"
        try:
            return self.connections[node_id].publish(full_topic, payload, qos=qos)
        except Exception as e:
            logger.debug(f"Error publishing to {node_id}: {str(e)}")
            return False
            
    def get_connected_nodes(self) -> List[str]:
        """Get list of connected node IDs."""
        return list(self.connections.keys())
        
    async def cleanup(self):
        """Clean up all connections."""
        self.running = False
        for node_id, mqtt_client in self.connections.items():
            try:
                mqtt_client.disconnect()
                logger.debug(f"Disconnected from {node_id}")
            except Exception as e:
                logger.debug(f"Error disconnecting from {node_id}: {str(e)}")
        self.connections.clear()

# Global manager instance
manager: Optional[RMNodeManager] = None

def signal_handler(signum, frame):
    """Handle interrupt signals."""
    global manager
    click.echo("\n\nShutting down...")
    if manager:
        asyncio.create_task(manager.cleanup())
    sys.exit(0)

@click.command()
@click.option('--cert-path', required=True, 
              help='Path to certificates directory containing node certificates')
@click.option('--broker-id', required=True,
              help='MQTT broker URL (e.g., mqtts://broker.example.com:8883)')
@click.option('--config-dir', default='.rm-node',
              help='Configuration directory (default: .rm-node)')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@debug_log
def main(cert_path: str, broker_id: str, config_dir: str, debug: bool):
    """
    RM-Node CLI - Efficient MQTT Node Management
    
    Connect to all nodes and start an interactive shell for managing them.
    
    Examples:
        rm-node --cert-path /path/to/certs --broker-id mqtts://broker.example.com:8883
    """
    global manager
    
    try:
        # Set up signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Configure logging
        if debug:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.INFO)
            
        # Create configuration directory
        config_path = Path(config_dir).resolve()
        config_path.mkdir(exist_ok=True)
        
        # Initialize manager
        manager = RMNodeManager(str(config_path))
        manager.broker_url = broker_id
        manager.cert_path = cert_path
        
        # Store configuration
        manager.config_manager.set_broker(broker_id)
        manager.config_manager.set_cert_path(cert_path)
        
        click.echo(click.style("RM-Node CLI Starting...", fg='green', bold=True))
        click.echo(f"Certificate path: {cert_path}")
        click.echo(f"Broker: {broker_id}")
        click.echo(f"Config directory: {config_path}")
        click.echo("-" * 60)
        
        # Create event loop and run async operations
        async def setup_and_run():
            # Connect to all nodes
            if not await manager.connect_all_nodes():
                click.echo(click.style("✗ Failed to connect to any nodes", fg='red'))
                sys.exit(1)
                
            # Start background listeners
            await manager.start_background_listeners()
            
            # Import and start the interactive shell
            from rm_node_cli.persistent_shell import start_interactive_shell
            await start_interactive_shell(manager)
            
        # Run the async setup
        asyncio.run(setup_and_run())
        
    except KeyboardInterrupt:
        click.echo("\n\nShutdown requested by user")
    except Exception as e:
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'))
        sys.exit(1)
    finally:
        if manager:
            asyncio.run(manager.cleanup())

if __name__ == '__main__':
    main() 