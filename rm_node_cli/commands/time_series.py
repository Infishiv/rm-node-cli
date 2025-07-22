"""
Time series data commands for MQTT CLI.
"""
import click
import json
import time
import asyncio
import sys
import logging
from typing import Optional, List, Union
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
def tsdata():
    """Manage time series data operations."""
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

@tsdata.command()
@click.option('--node-id', required=True, help='Node ID to send data for')
@click.option('--param-name', required=True, help='Parameter name')
@click.option('--value', required=True, help='Parameter value')
@click.option('--data-type', type=click.Choice(['string', 'int', 'float', 'bool', 'object']), default='string', help='Data type')
@click.option('--simple', is_flag=True, help='Use simple format')
@click.option('--expiry-days', '-d', type=int, help='Optional expiration days for data retention (simple format only)')
@click.option('--basic-ingest', is_flag=True, help='Use basic ingest topic ($aws/rules/esp_*_ts_ingest/...) to save costs')
@click.pass_context
@debug_log
def send(ctx, node_id, param_name, value, data_type, simple, expiry_days, basic_ingest):
    """Send time series data point.
    
    Examples:
    rm-node tsdata send --node-id node123 --param-name temperature --value 25.5
    rm-node tsdata send --node-id node123 --param-name status --value true --data-type bool
    rm-node tsdata batch --node-id node123 --param-name humidity --values 45 48 52 --interval 60
    """
    try:
        # Create event loop for async operations
        logger.debug("Creating event loop for async operations")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Ensure connection
        logger.debug(f"Ensuring connection to node {node_id}")
        if not loop.run_until_complete(ensure_node_connection(ctx, node_id)):
            sys.exit(1)
            
        mqtt_client = ctx.obj.get('MQTT')
        if not mqtt_client:
            logger.debug("No active MQTT connection found")
            click.echo(click.style("✗ No active MQTT connection", fg='red'), err=True)
            sys.exit(1)

        logger.debug(f"Validating node ID: {node_id}")
        validate_node_id(node_id)
        
        # Convert value to the correct type
        try:
            logger.debug(f"Converting value to type {data_type}")
            if data_type == 'bool':
                value = value.lower() in ('true', '1', 'yes', 'on')
            elif data_type == 'int':
                value = int(value)
            elif data_type == 'float':
                value = float(value)
            elif data_type == 'array':
                value = json.loads(value)
                if not isinstance(value, list):
                    raise ValueError("Value must be a valid JSON array")
            elif data_type == 'object':
                value = json.loads(value)
                if not isinstance(value, dict):
                    raise ValueError("Value must be a valid JSON object")
            logger.debug(f"Value converted successfully: {value}")
        except (ValueError, json.JSONDecodeError) as e:
            logger.debug(f"Value conversion failed: {str(e)}")
            click.echo(click.style(f"✗ Invalid value for type {data_type}: {str(e)}", fg='red'), err=True)
            sys.exit(1)
        
        timestamp = int(time.time())
        
        if simple:
            logger.debug("Using simple time series format")
            payload = {
                "name": param_name,
                "dt": data_type,
                "t": timestamp,
                "v": {"value": value}
            }
            if expiry_days is not None:
                logger.debug(f"Adding expiry days: {expiry_days}")
                payload["d"] = expiry_days
                
            topic = "$aws/rules/esp_simple_ts_ingest/node/" if basic_ingest else "node/"
            topic += f"{node_id}/simple_tsdata"
        else:
            logger.debug("Using standard time series format")
            payload = {
                "ts_data_version": "2021-09-13",
                "ts_data": [{
                    "name": param_name,
                    "dt": data_type,
                    "ow": False,
                    "records": [{
                        "v": {"value": value},
                        "t": timestamp
                    }]
                }]
            }
            topic = "$aws/rules/esp_ts_ingest/node/" if basic_ingest else "node/"
            topic += f"{node_id}/tsdata"

        logger.debug(f"Publishing to topic: {topic}")
        if mqtt_client.publish(topic, json.dumps(payload), qos=1):
            logger.debug("Time series data published successfully")
            click.echo(click.style(f"✓ Sent time series data for node {node_id}", fg='green'))
            click.echo(json.dumps(payload, indent=2))
            return 0
        else:
            logger.debug("Failed to publish time series data")
            click.echo(click.style("✗ Failed to publish time series data", fg='red'), err=True)
            sys.exit(1)
        
    except Exception as e:
        logger.debug(f"Error in send: {str(e)}")
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        sys.exit(1)

@tsdata.command()
@click.option('--node-id', required=True, help='Node ID to send data for')
@click.option('--param-name', required=True, help='Parameter name')
@click.option('--values', required=True, multiple=True, help='Parameter values')
@click.option('--data-type', type=click.Choice(['string', 'int', 'float', 'bool', 'object']), default='string', help='Data type')
@click.option('--interval', type=int, default=60, help='Interval between data points in seconds')
@click.option('--basic-ingest', is_flag=True, help='Use basic ingest topic ($aws/rules/esp_ts_ingest/...) to save costs')
@click.pass_context
@debug_log
def batch(ctx, node_id, param_name, values, data_type, interval, basic_ingest):
    """Send batch time series data.
    
    Examples:
    rm-node tsdata send --node-id node123 --param-name temperature --value 25.5
    rm-node tsdata send --node-id node123 --param-name status --value true --data-type bool --simple
    rm-node tsdata send --node-id node123 --param-name config --value '{"mode":"auto"}' --data-type object
    """
    try:
        # Create event loop for async operations
        logger.debug("Creating event loop for async operations")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Ensure connection
        logger.debug(f"Ensuring connection to node {node_id}")
        if not loop.run_until_complete(ensure_node_connection(ctx, node_id)):
            sys.exit(1)
            
        mqtt_client = ctx.obj.get('MQTT')
        if not mqtt_client:
            logger.debug("No active MQTT connection found")
            click.echo(click.style("✗ No active MQTT connection", fg='red'), err=True)
            sys.exit(1)

        logger.debug(f"Validating node ID: {node_id}")
        validate_node_id(node_id)
        
        # Convert values to the correct type
        converted_values = []
        try:
            logger.debug(f"Converting {len(values)} values to type {data_type}")
            for val in values:
                if data_type == 'bool':
                    val = val.lower() in ('true', '1', 'yes', 'on')
                elif data_type == 'int':
                    val = int(val)
                elif data_type == 'float':
                    val = float(val)
                elif data_type == 'array':
                    val = json.loads(val)
                    if not isinstance(val, list):
                        raise ValueError("Value must be a valid JSON array")
                elif data_type == 'object':
                    val = json.loads(val)
                    if not isinstance(val, dict):
                        raise ValueError("Value must be a valid JSON object")
                converted_values.append(val)
            logger.debug("Values converted successfully")
        except (ValueError, json.JSONDecodeError) as e:
            logger.debug(f"Value conversion failed: {str(e)}")
            click.echo(click.style(f"✗ Invalid value for type {data_type}: {str(e)}", fg='red'), err=True)
            sys.exit(1)
            
        # Create records with timestamps
        logger.debug("Creating records with timestamps")
        base_timestamp = int(time.time())
        records = []
        for i, val in enumerate(converted_values):
            records.append({
                "v": {"value": val},
                "t": base_timestamp + (i * interval)
            })
            
        payload = {
            "ts_data_version": "2021-09-13",
            "ts_data": [{
                "name": param_name,
                "dt": data_type,
                "ow": False,
                "records": records
            }]
        }
        
        topic = "$aws/rules/esp_ts_ingest/node/" if basic_ingest else "node/"
        topic += f"{node_id}/tsdata"
        
        logger.debug(f"Publishing batch data to topic: {topic}")
        if mqtt_client.publish(topic, json.dumps(payload), qos=1):
            logger.debug("Batch time series data published successfully")
            click.echo(click.style(f"✓ Sent batch time series data for node {node_id}", fg='green'))
            click.echo(json.dumps(payload, indent=2))
            return 0
        else:
            logger.debug("Failed to publish batch time series data")
            click.echo(click.style("✗ Failed to publish time series data", fg='red'), err=True)
            sys.exit(1)
            
    except Exception as e:
        logger.debug(f"Error in batch: {str(e)}")
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        sys.exit(1)

@tsdata.command()
@click.option('--node-id', required=True, help='Node ID to send data for')
@click.option('--param-name', required=True, help='Parameter name')
@click.option('--values', required=True, multiple=True, help='Parameter values')
@click.option('--data-type', type=click.Choice(['string', 'int', 'float', 'bool', 'object']), default='string', help='Data type')
@click.option('--interval', type=int, default=60, help='Interval between data points in seconds')
@click.pass_context
@debug_log
def batch_send(ctx, node_id, param_name, values, data_type, interval):
    """Send batch time series data.
    
    Examples:
    rm-node tsdata batch --node-id node123 --param-name temperature --values 25.5 26.0 26.5 --interval 60
    rm-node tsdata batch --node-id node123 --param-name status --values true false true --data-type bool
    rm-node tsdata batch --node-id node123 --param-name config --values '{"mode":"auto"}' '{"mode":"manual"}' --data-type object
    """
    try:
        # Create event loop for async operations
        logger.debug("Creating event loop for async operations")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Ensure connection
        logger.debug(f"Ensuring connection to node {node_id}")
        if not loop.run_until_complete(ensure_node_connection(ctx, node_id)):
            sys.exit(1)
            
        mqtt_client = ctx.obj.get('MQTT')
        if not mqtt_client:
            logger.debug("No active MQTT connection found")
            click.echo(click.style("✗ No active MQTT connection", fg='red'), err=True)
            sys.exit(1)

        logger.debug(f"Validating node ID: {node_id}")
        validate_node_id(node_id)
        
        # Convert values to the correct type
        converted_values = []
        try:
            logger.debug(f"Converting {len(values)} values to type {data_type}")
            for val in values:
                if data_type == 'bool':
                    val = val.lower() in ('true', '1', 'yes', 'on')
                elif data_type == 'int':
                    val = int(val)
                elif data_type == 'float':
                    val = float(val)
                elif data_type == 'array':
                    val = json.loads(val)
                    if not isinstance(val, list):
                        raise ValueError("Value must be a valid JSON array")
                elif data_type == 'object':
                    val = json.loads(val)
                    if not isinstance(val, dict):
                        raise ValueError("Value must be a valid JSON object")
                converted_values.append(val)
            logger.debug("Values converted successfully")
        except (ValueError, json.JSONDecodeError) as e:
            logger.debug(f"Value conversion failed: {str(e)}")
            click.echo(click.style(f"✗ Invalid value for type {data_type}: {str(e)}", fg='red'), err=True)
            sys.exit(1)
            
        # Create records with timestamps
        logger.debug("Creating records with timestamps")
        base_timestamp = int(time.time())
        records = []
        for i, val in enumerate(converted_values):
            records.append({
                "v": {"value": val},
                "t": base_timestamp + (i * interval)
            })
            
        payload = {
            "ts_data_version": "2021-09-13",
            "ts_data": [{
                "name": param_name,
                "dt": data_type,
                "ow": False,
                "records": records
            }]
        }
        
        topic = "$aws/rules/esp_ts_ingest/node/"
        topic += f"{node_id}/tsdata"
        
        logger.debug(f"Publishing batch data to topic: {topic}")
        if mqtt_client.publish(topic, json.dumps(payload), qos=1):
            logger.debug("Batch time series data published successfully")
            click.echo(click.style(f"✓ Sent batch time series data for node {node_id}", fg='green'))
            click.echo(json.dumps(payload, indent=2))
            return 0
        else:
            logger.debug("Failed to publish batch time series data")
            click.echo(click.style("✗ Failed to publish time series data", fg='red'), err=True)
            sys.exit(1)
            
    except Exception as e:
        logger.debug(f"Error in batch_send: {str(e)}")
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        sys.exit(1) 