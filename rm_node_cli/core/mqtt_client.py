"""
MQTT client operations for MQTT CLI.
"""
import logging
import click
import sys
from pathlib import Path

from ..mqtt_operations import MQTTOperations
from ..utils.cert_finder import get_cert_and_key_paths, get_cert_paths_from_direct_path

def connect_single_node(broker: str, node_id: str, base_path: str, direct_cert_path: str = None, mac_address: str = None) -> tuple:
    """Helper function to connect a single node"""
    try:
        # If direct_cert_path is provided, use it with MAC address or node_details search
        if direct_cert_path:
            cert_path, key_path = get_cert_paths_from_direct_path(direct_cert_path, node_id, mac_address)
        else:
            cert_path, key_path = get_cert_and_key_paths(base_path, node_id)
            
        # Create MQTT client with certificate paths
        mqtt_client = MQTTOperations(
            broker=broker,
            node_id=node_id,
            cert_path=cert_path,
            key_path=key_path
        )
        
        # Attempt connection
        if mqtt_client.connect():
            return mqtt_client, cert_path, key_path
        else:
            return None, None, None
            
    except Exception as e:
        return None, None, None

def get_active_mqtt_client(ctx, auto_connect=False, node_id=None):
    """Get or create MQTT client for the specified node"""
    from ..utils.config_manager import ConfigManager
    
    config_manager = ctx.obj.get('CONFIG_MANAGER')
    
    if auto_connect and node_id:
        click.echo(click.style(f"Auto-connecting to node {node_id}...", fg='yellow'))
        broker = ctx.obj.get('BROKER')
        cert_path = ctx.obj.get('CERT_PATH')
        mac_address = ctx.obj.get('MAC_ADDRESS')  # Get MAC address from context
        
        try:
            # Check if we have a MAC address path (for MAC-based discovery)
            if mac_address and '/' in mac_address:
                # MAC address contains a path, use it for MAC-based certificate search
                cert_path, key_path = get_cert_paths_from_direct_path(mac_address, node_id, None)
                # Store certificate paths in config for future use
                if config_manager:
                    config_manager.add_node(node_id, cert_path, key_path)
            # Try direct certificate path if provided
            elif cert_path:
                cert_path, key_path = get_cert_paths_from_direct_path(cert_path, node_id, mac_address)
                # Store certificate paths in config for future use
                if config_manager:
                    config_manager.add_node(node_id, cert_path, key_path)
            else:
                # Try to get from existing configuration
                cert_paths = config_manager.get_node_paths(node_id) if config_manager else None
                if cert_paths:
                    cert_path, key_path = cert_paths
                else:
                    # If not in config, try default location using node_details structure
                    base_path = ctx.obj['CERT_FOLDER']
                    cert_path, key_path = get_cert_and_key_paths(base_path, node_id)
                    # Store certificate paths in config for future use
                    if config_manager:
                        config_manager.add_node(node_id, cert_path, key_path)
            
            # Create and connect MQTT client
            mqtt_client = MQTTOperations(
                broker=broker,
                node_id=node_id,
                cert_path=cert_path,
                key_path=key_path
            )
            
            if mqtt_client.connect():
                click.echo(click.style(f"✓ Connected to node {node_id}", fg='green'))
                
                # Store connection in connection manager
                connection_manager = ctx.obj.get('CONNECTION_MANAGER')
                if connection_manager:
                    connection_manager.add_connection(node_id, broker, cert_path, key_path, mqtt_client)
                
                return mqtt_client
            else:
                click.echo(click.style(f"✗ Failed to connect to node {node_id}", fg='red'))
                return None
                
        except Exception as e:
            click.echo(click.style(f"✗ Connection error for node {node_id}: {str(e)}", fg='red'))
            return None
    
    # If not auto-connecting, try to get existing connection
    connection_manager = ctx.obj.get('CONNECTION_MANAGER')
    if connection_manager and node_id:
        return connection_manager.get_connection(node_id)
    
    return None 