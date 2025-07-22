"""
User-node mapping commands for ESP RainMaker.

This module provides commands for managing user-node mappings and sending alerts.
"""
import click
import json
import time
import asyncio
import sys
import logging
from ..utils.exceptions import MQTTError
from ..utils.validators import validate_node_id
from ..utils.exceptions import MQTTConnectionError
from ..commands.connection import connect_node
from ..utils.config_manager import ConfigManager
from ..mqtt_operations import MQTTOperations
from ..utils.debug_logger import debug_log, debug_step
from ..utils.connection_manager import ConnectionManager
from ..core.mqtt_client import get_active_mqtt_client

# Get logger for this module
logger = logging.getLogger(__name__)

@click.group()
def user():
    """Manage user-node mappings."""
    pass

@debug_step("Ensuring node connection")
async def ensure_node_connection(ctx, node_id: str) -> bool:
    """Ensure connection to a node is active, connect if needed."""
    try:
        mqtt_client = get_active_mqtt_client(ctx, auto_connect=True, node_id=node_id)
        if mqtt_client:
            ctx.obj['MQTT'] = mqtt_client
            return True
        return False
    except Exception as e:
        logger.debug(f"Connection error: {str(e)}")
        click.echo(click.style(f"✗ Connection error: {str(e)}", fg='red'), err=True)
        return False

@user.command()
@click.option('--node-id', required=True, help='Node ID to map')
@click.option('--user-id', required=True, help='User ID to map')
@click.option('--secret-key', required=True, help='Secret key for authentication')
@click.option('--timeout', type=int, help='Mapping timeout in seconds')
@click.option('--reset', is_flag=True, help='Reset existing mapping')
@click.pass_context
@debug_log
def map(ctx, node_id, user_id, secret_key, timeout, reset):
    """Map a user to a node.
    
    Examples:
    rm-node user map --node-id node123 --user-id user456 --secret-key abc123
    rm-node user alert --node-id node123 --message "System update required"
    """
    try:
        # Create event loop for async operations
        logger.debug("Creating event loop for async operations")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Ensure connection
        logger.debug(f"Ensuring connection to node {node_id}")
        if not loop.run_until_complete(ensure_node_connection(ctx, node_id)):
            logger.debug("Failed to establish connection")
            click.echo(click.style("✗ Failed to connect", fg='red'), err=True)
            sys.exit(1)
            
        mqtt_client = ctx.obj.get('MQTT')
        if not mqtt_client:
            logger.debug("No active MQTT connection found")
            click.echo(click.style("✗ No active MQTT connection", fg='red'), err=True)
            sys.exit(1)
            
        logger.debug(f"Validating node ID: {node_id}")
        validate_node_id(node_id)
        
        mapping = {
            "node_id": node_id,
            "user_id": user_id,
            "secret_key": secret_key,
            "reset": reset,
            "timeout": timeout
        }
        logger.debug(f"Created mapping payload for node {node_id} and user {user_id}")

        topic = f"node/{node_id}/user/mapping"
        logger.debug(f"Publishing to topic: {topic}")
        if mqtt_client.publish(topic, json.dumps(mapping), qos=1):
            logger.debug("Successfully published user mapping")
            click.echo(click.style(f"✓ Created user mapping for node {node_id}", fg='green'))
            click.echo("\nMapping Details:")
            click.echo(f"Node ID: {node_id}")
            click.echo(f"User ID: {user_id}")
            click.echo(f"Reset: {reset}")
            click.echo(f"Timeout: {timeout} seconds")
            return 0
        else:
            logger.debug("Failed to publish user mapping")
            click.echo(click.style("✗ Failed to publish user mapping", fg='red'), err=True)
            sys.exit(1)
        
    except Exception as e:
        logger.debug(f"Error in map_user: {str(e)}")
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        sys.exit(1)

@user.command()
@click.option('--node-id', required=True, help='Node ID to send alert to')
@click.option('--message', required=True, help='Alert message')
@click.pass_context
@debug_log
def alert(ctx, node_id, message):
    """Send an alert to a user mapped to a node.
    
    Examples:
    rm-node user map --node-id node123 --user-id user456 --secret-key abc123
    rm-node user map --node-id node123 --user-id user456 --secret-key abc123 --reset
    rm-node user map --node-id node123 --user-id user456 --secret-key abc123 --timeout 600
    """
    try:
        # Create event loop for async operations
        logger.debug("Creating event loop for async operations")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Ensure connection
        logger.debug(f"Ensuring connection to node {node_id}")
        if not loop.run_until_complete(ensure_node_connection(ctx, node_id)):
            logger.debug("Failed to establish connection")
            click.echo(click.style("✗ Failed to connect", fg='red'), err=True)
            sys.exit(1)
            
        mqtt_client = ctx.obj.get('MQTT')
        if not mqtt_client:
            logger.debug("No active MQTT connection found")
            click.echo(click.style("✗ No active MQTT connection", fg='red'), err=True)
            sys.exit(1)
            
        logger.debug(f"Validating node ID: {node_id}")
        validate_node_id(node_id)
        
        payload = {
            "nodeId": node_id,
            "messageBody": {
                "message": message
            }
        }
        logger.debug(f"Created alert payload for node {node_id}")

        topic = f"node/{node_id}/alert"
        logger.debug(f"Publishing to topic: {topic}")
        if mqtt_client.publish(topic, json.dumps(payload), qos=1):
            logger.debug("Successfully published alert")
            click.echo(click.style(f"✓ Sent alert for node {node_id}", fg='green'))
            click.echo("\nAlert Details:")
            click.echo(f"Node ID: {node_id}")
            click.echo(f"Message: {message}")
            click.echo("\nFull Payload:")
            click.echo(json.dumps(payload, indent=2))
            return 0
        else:
            logger.debug("Failed to publish alert")
            click.echo(click.style("✗ Failed to publish alert", fg='red'), err=True)
            sys.exit(1)
        
    except Exception as e:
        logger.debug(f"Error in send_alert: {str(e)}")
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        sys.exit(1) 