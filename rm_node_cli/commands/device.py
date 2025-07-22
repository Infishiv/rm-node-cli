"""
Device management commands for MQTT CLI.
"""
import click
import json
import asyncio
import sys
import uuid
import logging
from ..utils.exceptions import MQTTError, MQTTConnectionError
from ..utils.validators import validate_node_id
from ..commands.connection import connect_node
from ..utils.config_manager import ConfigManager
from ..mqtt_operations import MQTTOperations
from ..utils.debug_logger import debug_log, debug_step
from ..core.mqtt_client import get_active_mqtt_client
import time

# Get logger for this module
logger = logging.getLogger(__name__)

@click.group()
def device():
    """Manage device operations."""
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

@debug_step("Formatting TLV message")
def format_tlv_message(request_id: str, role: int, command: int, data: dict = None) -> dict:
    """Format message in TLV format according to ESP RainMaker spec."""
    logger.debug(f"Creating TLV message with request_id={request_id}, role={role}, command={command}")
    message = {
        "1": request_id,  # T:1 - Request ID
        "2": int(role),   # T:2 - Role (1=admin, 2=primary, 4=secondary)
        "5": command      # T:5 - Command
    }
    if data:
        logger.debug(f"Adding command data to TLV message: {data}")
        message["6"] = data  # T:6 - Command data (optional)
    return message

@device.command('send-command')
@click.option('--node-id', required=True, help='Node ID to send command to')
@click.option('--request-id', help='Unique request ID (generated if not provided)')
@click.option('--role', type=click.Choice(['1', '2', '4']), required=True, 
              help='User role (1=admin, 2=primary, 4=secondary)')
@click.option('--command', type=int, required=True,
              help='Command code (0=get pending, 16=request file upload, 17=get file download, 20=confirm upload)')
@click.option('--command-data', help='Optional command data as JSON string')
@click.pass_context
@debug_log
def send_node_command(ctx, node_id: str, request_id: str, role: str, command: int, command_data: str):
    """Send command to node using TLV format.
    
    Example: rm-node device send-command --node-id node123 --role 1 --command 0
    """
    try:
        # Create event loop for async operations
        logger.debug("Creating event loop for async operations")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Ensure connection
        logger.debug(f"Ensuring connection to node {node_id}")
        if not loop.run_until_complete(ensure_node_connection(ctx, node_id)):
            click.echo(click.style("✗ Failed to connect", fg='red'), err=True)
            sys.exit(1)
            
        mqtt_client = ctx.obj.get('MQTT')
        if not mqtt_client:
            logger.debug("No active MQTT connection found")
            click.echo(click.style("✗ No MQTT client available", fg='red'), err=True)
            sys.exit(1)

        # Generate request ID if not provided
        if not request_id:
            request_id = str(uuid.uuid4())[:22]  # First 22 chars of UUID
            logger.debug(f"Generated request ID: {request_id}")

        # Parse command data if provided
        data = None
        if command_data:
            try:
                logger.debug(f"Parsing command data: {command_data}")
                data = json.loads(command_data)
            except json.JSONDecodeError:
                logger.debug("Invalid JSON in command data")
                raise MQTTError("Invalid JSON in command data")

        # Format TLV message
        logger.debug("Formatting TLV message")
        message = format_tlv_message(request_id, role, command, data)
        
        # Publish command
        topic = f"node/{node_id}/to-node"
        logger.debug(f"Publishing command to topic: {topic}")
        if mqtt_client.publish(topic, json.dumps(message), qos=1):
            logger.debug("Command published successfully")
            click.echo(click.style(f"✓ Sent command to node {node_id}", fg='green'))
            click.echo("\nCommand Details:")
            click.echo("-" * 40)
            click.echo(f"Request ID: {request_id}")
            click.echo(f"Role: {role}")
            click.echo(f"Command: {command}")
            if data:
                click.echo("\nCommand Data:")
                click.echo(json.dumps(data, indent=2))
            click.echo("-" * 40)
            return 0
        else:
            logger.debug("Failed to publish command")
            raise MQTTError("Failed to send command")
            
    except MQTTError as e:
        logger.debug(f"MQTT error in send_node_command: {str(e)}")
        click.echo(click.style(f"✗ Failed to send command: {str(e)}", fg='red'), err=True)
        sys.exit(1)
    except Exception as e:
        logger.debug(f"Error in send_node_command: {str(e)}")
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        sys.exit(1)

@device.command('send-alert')
@click.option('--node-id', required=True, help='Node ID to send alert to')
@click.option('--message', required=True, help='Alert message')
@click.option('--basic-ingest', is_flag=True, help='Use basic ingest mode')
@click.pass_context
@debug_log
def send_alert(ctx, node_id: str, message: str, basic_ingest: bool):
    """Send an alert from a device.
    
    Example: rm-node device send-alert --node-id node123 --message "Temperature high!"
    Or with basic ingest: rm-node device send-alert --node-id node123 --message "Alert!" --basic-ingest
    """
    try:
        # Create event loop for async operations
        logger.debug("Creating event loop for async operations")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Ensure connection
        logger.debug(f"Ensuring connection to node {node_id}")
        if not loop.run_until_complete(ensure_node_connection(ctx, node_id)):
            click.echo(click.style("✗ Failed to connect", fg='red'), err=True)
            sys.exit(1)
            
        mqtt_client = ctx.obj.get('MQTT')
        if not mqtt_client:
            logger.debug("No active MQTT connection found")
            click.echo(click.style("✗ No MQTT client available", fg='red'), err=True)
            sys.exit(1)

        # Prepare alert payload
        logger.debug(f"Preparing alert payload for node {node_id}")
        alert = {
            "node_id": node_id,
            "message": message,
            "timestamp": int(time.time() * 1000)
        }
        
        # Choose topic based on ingest type
        if basic_ingest:
            topic = f"$aws/rules/esp_node_alert/{node_id}"
            logger.debug(f"Using basic ingest topic: {topic}")
        else:
            topic = f"node/{node_id}/alert"
            logger.debug(f"Using standard alert topic: {topic}")
            
        # Publish alert
        logger.debug("Publishing alert message")
        if mqtt_client.publish(topic, json.dumps(alert), qos=1):
            logger.debug("Alert published successfully")
            click.echo(click.style(f"✓ Sent alert from node {node_id}", fg='green'))
            click.echo("\nAlert Details:")
            click.echo("-" * 40)
            click.echo(json.dumps(alert, indent=2))
            click.echo("-" * 40)
            return 0
        else:
            logger.debug("Failed to publish alert")
            raise MQTTError("Failed to send alert")
            
    except MQTTError as e:
        logger.debug(f"MQTT error in send_alert: {str(e)}")
        click.echo(click.style(f"✗ Failed to send alert: {str(e)}", fg='red'), err=True)
        sys.exit(1)
    except Exception as e:
        logger.debug(f"Error in send_alert: {str(e)}")
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        sys.exit(1) 