"""
OTA (Over-The-Air) update commands for MQTT CLI.
"""
import click
import json
import time
import os
import logging
from pathlib import Path
from ..utils.exceptions import MQTTOTAError
from ..utils.validators import validate_version, validate_timeout
from typing import Optional
from ..utils.validators import validate_node_id
from ..utils.exceptions import MQTTConnectionError
from ..commands.connection import connect_node
from ..mqtt_operations import MQTTOperations
from ..utils.config_manager import ConfigManager
from ..utils.debug_logger import debug_log, debug_step
from ..core.mqtt_client import get_active_mqtt_client

# Get logger for this module
logger = logging.getLogger(__name__)

@click.group()
def ota():
    """OTA update management commands."""
    pass

@ota.command('fetch')
@click.option('--node-id', required=True, help='Node ID to fetch OTA update for')
@click.option('--fw-version', required=True, help='Current firmware version')
@click.option('--network-id', help='Network ID for Thread-based OTA')
@click.pass_context
@debug_log
def fetch_ota(ctx, node_id: str, fw_version: str, network_id: Optional[str]):
    """Request OTA update for a node.
    
    Example: mqtt-cli ota fetch --node-id node123 --fw-version 1.0.0 --network-id net123
    """
    try:
        # Get or establish connection using centralized function
        logger.debug(f"Getting or establishing connection for node {node_id}")
        mqtt_client = get_active_mqtt_client(ctx, auto_connect=True, node_id=node_id)
        if not mqtt_client:
            logger.debug("Failed to get MQTT client")
            click.echo(click.style("✗ Failed to connect to node", fg='red'), err=True)
            raise click.Abort()

        # Prepare payload
        logger.debug("Preparing OTA fetch payload")
        payload = {
            "fw_version": fw_version
        }
        if network_id:
            logger.debug(f"Adding network_id {network_id} to payload")
            payload["network_id"] = network_id
            
        # Publish to OTA fetch topic
        topic = f"node/{node_id}/otafetch"
        logger.debug(f"Publishing to topic: {topic}")
        if mqtt_client.publish(topic, json.dumps(payload), qos=1):
            logger.debug("Successfully published OTA fetch request")
            click.echo(click.style("✓ OTA fetch request sent", fg='green'))
        else:
            logger.debug("Failed to publish OTA fetch request")
            click.echo(click.style("✗ Failed to send OTA fetch request", fg='red'), err=True)
            
    except Exception as e:
        logger.debug(f"Error in fetch_ota: {str(e)}")
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        raise click.Abort()

@ota.command('status')
@click.option('--node-id', required=True, help='Node ID(s) to update status for. Can be single ID or comma-separated list')
@click.option('--status', 
              type=click.Choice(['in-progress', 'success', 'rejected', 'failed', 'delayed']), 
              required=True, 
              help='OTA update status')
@click.option('--job-id', required=True, help='OTA job ID')
@click.option('--network-id', help='Network ID')
@click.option('--info', help='Additional information about the OTA status')
@click.pass_context
@debug_log
def update_status(ctx, node_id: str, status: str, job_id: str, network_id: str, info: Optional[str]):
    """Update OTA status for one or more nodes.
    
    Examples:
        mqtt-cli ota status --node-id node123 --status in-progress --job-id job123 --info "25% complete"
        mqtt-cli ota status --node-id "node123,node456" --status in-progress --job-id job123
    """
    try:
        # Split node_id if it contains commas
        logger.debug(f"Processing node IDs: {node_id}")
        node_ids = [n.strip() for n in node_id.split(',')]
        logger.debug(f"Split into {len(node_ids)} node IDs: {node_ids}")
        
        # Process each node in parallel
        for node_id in node_ids:
            try:
                # Get or establish connection using centralized function
                logger.debug(f"Getting or establishing connection for node {node_id}")
                mqtt_client = get_active_mqtt_client(ctx, auto_connect=True, node_id=node_id)
                if not mqtt_client:
                    logger.debug(f"Failed to get MQTT client for node {node_id}")
                    click.echo(click.style(f"✗ Failed to connect to node {node_id}", fg='red'), err=True)
                    continue
                
                # Prepare payload
                logger.debug("Preparing OTA status payload")
                payload = {
                    "status": status,
                    "ota_job_id": job_id
                }
                if network_id:
                    logger.debug(f"Adding network_id {network_id} to payload")
                    payload["network_id"] = network_id
                if info:
                    logger.debug(f"Adding additional info to payload: {info}")
                    payload["additional_info"] = info
                    
                # Publish to OTA status topic
                topic = f"node/{node_id}/otastatus"
                logger.debug(f"Publishing to topic: {topic}")
                if mqtt_client.publish(topic, json.dumps(payload), qos=1):
                    logger.debug(f"Successfully published OTA status for node {node_id}")
                    click.echo(click.style(f"✓ OTA status updated for node {node_id}", fg='green'))
                else:
                    logger.debug(f"Failed to publish OTA status for node {node_id}")
                    click.echo(click.style(f"✗ Failed to update OTA status for node {node_id}", fg='red'), err=True)
                    
            except Exception as e:
                logger.debug(f"Error processing node {node_id}: {str(e)}")
                click.echo(click.style(f"✗ Error for node {node_id}: {str(e)}", fg='red'), err=True)
            
    except Exception as e:
        logger.debug(f"Error in update_status: {str(e)}")
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        raise click.Abort()

@ota.command('request')
@click.option('--node-id', required=True, help='Node ID(s) to request OTA update for. Can be single ID or comma-separated list')
@click.option('--timeout', default=60, type=int, help='Timeout in seconds (default: 60)')
@click.pass_context
@debug_log
def request(ctx, node_id: str, timeout: int):
    """Listen for OTA URL responses from one or more nodes and update status.
    
    Examples:
        mqtt-cli ota request --node-id node123 --timeout 120
        mqtt-cli ota request --node-id "node123,node456" --timeout 120
    """
    try:
        logger.debug(f"Validating timeout value: {timeout}")
        validate_timeout(timeout)
        
        # Split node_id if it contains commas
        logger.debug(f"Processing node IDs: {node_id}")
        node_ids = [n.strip() for n in node_id.split(',')]
        logger.debug(f"Split into {len(node_ids)} node IDs: {node_ids}")
        
        # Track responses and MQTT clients for each node
        responses_received = {node_id: False for node_id in node_ids}
        mqtt_clients = {}
        logger.debug(f"Initialized response tracking for nodes: {list(responses_received.keys())}")

        @debug_step("Publishing status update")
        def publish_status_update(node_id, job_id, status, network_id=None, info=None):
            """Helper function to publish status updates with improved retry logic"""
            status_map = {
                "1": {"status": "success", "info": "Update completed successfully"},
                "2": {"status": "failed", "info": "Update failed"},
                "3": {"status": "in-progress", "info": "Update in progress"},
                "4": {"status": "rejected", "info": "Update rejected"},
                "5": {"status": "delayed", "info": "Update delayed"}
            }
            
            # Get the status and info from the map
            logger.debug(f"Processing status update for node {node_id} with status code {status}")
            if status in status_map:
                status_info = status_map[status]
                status = status_info["status"]
                info = status_info["info"]
                logger.debug(f"Mapped status code {status} to: {status_info}")

            try:
                mqtt_client = mqtt_clients.get(node_id)
                if not mqtt_client:
                    logger.debug(f"No MQTT client found for node {node_id}")
                    click.echo(click.style(f"✗ No MQTT client found for node {node_id}", fg='red'), err=True)
                    return False

                # Prepare payload
                logger.debug("Preparing status update payload")
                payload = {
                    "status": status,
                    "ota_job_id": job_id
                }
                if network_id:
                    logger.debug(f"Adding network_id {network_id} to payload")
                    payload["network_id"] = network_id
                if info:
                    logger.debug(f"Adding additional info to payload: {info}")
                    payload["additional_info"] = info

                # Publish to OTA status topic with enhanced retry logic
                topic = f"node/{node_id}/otastatus"
                max_retries = 3
                retry_delay = 2  # seconds between retries
                logger.debug(f"Publishing to topic {topic} with {max_retries} retries")

                for attempt in range(max_retries):
                    try:
                        # Check connection before publishing
                        if not mqtt_client.is_connected():
                            logger.debug(f"Connection lost, attempting reconnect (attempt {attempt + 1}/{max_retries})")
                            click.echo(click.style(f"\nReconnecting to node {node_id} (attempt {attempt + 1}/{max_retries})...", fg='yellow'))
                            if not mqtt_client.reconnect():
                                if attempt < max_retries - 1:
                                    logger.debug("Reconnect failed, will retry after delay")
                                    time.sleep(retry_delay)
                                    continue
                                else:
                                    logger.debug("All reconnect attempts failed")
                                    click.echo(click.style(f"✗ Failed to reconnect to node {node_id}", fg='red'), err=True)
                                    return False

                        # Try to publish
                        logger.debug(f"Attempting to publish (attempt {attempt + 1}/{max_retries})")
                        if mqtt_client.publish(topic, json.dumps(payload), qos=1):
                            logger.debug("Successfully published status update")
                            click.echo(click.style(f"\nStatus Update Details:"))
                            click.echo(click.style(f"Node ID: {node_id}"))
                            click.echo(click.style(f"OTA Job ID: {job_id}"))
                            click.echo(click.style(f"Status: {status}"))
                            return True
                        
                        if attempt < max_retries - 1:
                            logger.debug(f"Publish failed, will retry (attempt {attempt + 2}/{max_retries})")
                            click.echo(click.style(f"Retrying status update (attempt {attempt + 2}/{max_retries})...", fg='yellow'))
                            time.sleep(retry_delay)
                        
                    except Exception as e:
                        if attempt < max_retries - 1:
                            logger.debug(f"Error during publish attempt {attempt + 1}: {str(e)}")
                            click.echo(click.style(f"Error during publish (attempt {attempt + 1}): {str(e)}", fg='yellow'))
                            time.sleep(retry_delay)
                        else:
                            logger.debug(f"Final publish attempt failed: {str(e)}")
                            click.echo(click.style(f"✗ Error during publish: {str(e)}", fg='red'), err=True)
                            return False

                logger.debug(f"Failed to publish after {max_retries} attempts")
                click.echo(click.style(f"✗ Failed to publish status update after {max_retries} attempts", fg='red'), err=True)
                return False
                
            except Exception as e:
                logger.debug(f"Error in publish_status_update: {str(e)}")
                click.echo(click.style(f"✗ Error updating status: {str(e)}", fg='red'), err=True)
                return False

        @debug_step("Processing OTA response")
        def on_ota_response(client, userdata, message):
            try:
                topic_parts = message.topic.split('/')
                if len(topic_parts) >= 2:
                    current_node = topic_parts[1]
                    if current_node not in node_ids:
                        logger.debug(f"Received response for unknown node {current_node}, ignoring")
                        return
                        
                logger.debug(f"Received OTA response from node {current_node}")
                click.echo("\n" + "="*50)
                click.echo(f"Received OTA response from node {current_node}")
                click.echo("="*50)
                
                try:
                    logger.debug("Parsing response payload")
                    response = json.loads(message.payload.decode())
                    click.echo(json.dumps(response, indent=2))
                    click.echo("-"*50)
                    
                    if not response.get('ota_job_id'):
                        logger.debug("No OTA job ID found in response")
                        click.echo(click.style("No OTA job ID in response", fg='yellow'))
                        return
                        
                    # Prompt for status update
                    logger.debug("Prompting for status update")
                    while True:
                        click.echo("\nSelect OTA status to send:")
                        click.echo("1. success")
                        click.echo("2. failed")
                        click.echo("3. in-progress")
                        click.echo("4. rejected")
                        click.echo("5. delayed")
                        click.echo("0. Skip status update")
                        
                        try:
                            choice = input("\nEnter your choice (0-5): ").strip()
                            logger.debug(f"User selected choice: {choice}")
                            
                            if choice == "0":
                                logger.debug("User chose to skip status update")
                                click.echo("Skipping status update")
                                break
                                
                            if choice in ["1", "2", "3", "4", "5"]:
                                logger.debug(f"Publishing status update with choice {choice}")
                                if publish_status_update(current_node, response['ota_job_id'], choice):
                                    logger.debug(f"Status update successful for node {current_node}")
                                    responses_received[current_node] = True
                                    break
                            else:
                                logger.debug(f"Invalid choice entered: {choice}")
                                click.echo(click.style("Invalid choice. Please select 0-5", fg='red'))
                                
                        except KeyboardInterrupt:
                            logger.debug("Status update cancelled by user")
                            click.echo("\nStatus update cancelled")
                            break
                        except Exception as e:
                            logger.debug(f"Error during status update prompt: {str(e)}")
                            click.echo(click.style(f"Error: {str(e)}", fg='red'))
                            break
                            
                except json.JSONDecodeError:
                    logger.debug("Failed to parse JSON response")
                    click.echo(click.style("Invalid JSON in response", fg='red'))
                    click.echo("Raw payload: " + message.payload.decode())
                    
            except Exception as e:
                logger.debug(f"Error processing OTA response: {str(e)}")
                click.echo(click.style(f"Error processing response: {str(e)}", fg='red'))
 
        # Process each node
        logger.debug("Getting connection manager")
        connection_manager = ctx.obj.get('CONNECTION_MANAGER')
        if not connection_manager:
            logger.debug("Connection manager not initialized")
            click.echo(click.style("✗ Connection manager not initialized", fg='red'), err=True)
            raise click.Abort()

        for node_id in node_ids:
            try:
                logger.debug(f"Processing node {node_id}")
                # Use get_active_mqtt_client for consistent certificate handling
                mqtt_client = get_active_mqtt_client(ctx, auto_connect=True, node_id=node_id)
                if not mqtt_client:
                    logger.debug(f"Failed to get MQTT client for node {node_id}")
                    click.echo(click.style(f"✗ Failed to connect to node {node_id}", fg='red'), err=True)
                    continue

                # Store MQTT client reference
                mqtt_clients[node_id] = mqtt_client
                logger.debug(f"Stored MQTT client for node {node_id}")
 
                # Subscribe to response topic
                response_topic = f"node/{node_id}/otaurl"
                logger.debug(f"Subscribing to topic: {response_topic}")
                if not mqtt_client.subscribe(response_topic, qos=1, callback=on_ota_response):
                    logger.debug(f"Failed to subscribe to topic {response_topic}")
                    click.echo(click.style(f"✗ Failed to subscribe to response topic for node {node_id}", fg='red'), err=True)
                    continue
                    
                click.echo(f"Listening for OTA updates on {response_topic}...")
                
            except Exception as e:
                logger.debug(f"Error setting up node {node_id}: {str(e)}")
                click.echo(click.style(f"✗ Error for node {node_id}: {str(e)}", fg='red'), err=True)

        click.echo("\nMonitoring all nodes. Press Ctrl+C to stop...")
        logger.debug("Starting monitoring loop")
 
        try:
            # Keep the MQTT loop running
            start_time = time.time()
            while True:
                if all(responses_received.values()):
                    logger.debug("All nodes have responded and status updates completed")
                    click.echo(click.style("\nAll nodes have responded and status updates completed",fg='green'))
                    break
                    
                if time.time() - start_time > timeout:
                    pending_nodes = [n for n, received in responses_received.items() if not received]
                    if pending_nodes:
                        logger.debug(f"Timeout reached. Pending nodes: {pending_nodes}")
                        click.echo(click.style(f"\nTimeout reached. No response from: {', '.join(pending_nodes)}", fg='yellow'))
                    break

                # Check connection health for each client
                for node_id, mqtt_client in mqtt_clients.items():
                    if not mqtt_client.ping():
                        logger.debug(f"Connection lost for node {node_id}, attempting to reconnect")
                        click.echo(click.style(f"\nConnection lost for node {node_id}, attempting to reconnect...", fg='yellow'))
                        mqtt_client.reconnect()
                    
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            logger.debug("Monitoring stopped by user")
            click.echo("\nStopping OTA listener...")
        finally:
            # Cleanup: Unsubscribe and disconnect clients
            logger.debug("Cleaning up MQTT connections")
            for node_id, mqtt_client in mqtt_clients.items():
                try:
                    logger.debug(f"Unsubscribing node {node_id} from OTA updates")
                    mqtt_client.unsubscribe(f"node/{node_id}/otaurl")
                except:
                    logger.debug(f"Error unsubscribing node {node_id}")
                    pass
        
    except Exception as e:
        logger.debug(f"Error in request command: {str(e)}")
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        raise click.Abort()