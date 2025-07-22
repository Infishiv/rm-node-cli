"""
Node configuration and parameters management.

This module provides commands for managing node configuration and parameters
in compliance with ESP RainMaker MQTT swagger specification.
All parameter commands use the standardized device name -> parameter format.
"""
import click
import json
import sys
import time
import asyncio
import uuid
import os
import logging
import shutil
import requests
from pathlib import Path
from ..utils.exceptions import MQTTError
from ..utils.validators import validate_node_id
from ..utils.exceptions import MQTTConnectionError
from ..commands.connection import connect_node
from ..utils.config_manager import ConfigManager
from ..mqtt_operations import MQTTOperations
from ..utils.debug_logger import debug_log, debug_step
from ..core.mqtt_client import get_active_mqtt_client

# Get logger for this module
logger = logging.getLogger(__name__)

# Get the path to the configs directory (parent directory of this file)
CONFIGS_DIR = Path(__file__).parent.parent.parent / 'configs'

DEVICE_TEMPLATES = {
    'light': 'light_config.json',
    'heater': 'heater_config.json',
    'washer': 'washer_config.json'
}

@debug_step("Creating node configuration")
def create_node_specific_config(node_id: str, device_type: str, project_name: str = None) -> dict:
    """Create a node-specific configuration based on the template.
    
    Args:
        node_id: The ID of the node
        device_type: Type of device (light, heater, washer)
        project_name: Optional project name
        
    Returns:
        dict: Node-specific configuration
    """
    if device_type not in DEVICE_TEMPLATES:
        logger.debug(f"Invalid device type: {device_type}")
        raise MQTTError(f"Invalid device type. Choose from: {', '.join(DEVICE_TEMPLATES.keys())}")
        
    template_file = CONFIGS_DIR / DEVICE_TEMPLATES[device_type]
    if not template_file.exists():
        logger.debug(f"Template file not found: {template_file}")
        raise MQTTError(f"Template file not found: {template_file}")
        
    try:
        with open(template_file, 'r') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        logger.debug(f"Invalid JSON in template: {str(e)}")
        raise MQTTError("Invalid template configuration")
        
    # Replace placeholders
    config['node_id'] = node_id
    if project_name:
        config['info']['project_name'] = project_name
    
    logger.debug(f"Created configuration for node {node_id} with device type {device_type}")
    return config

@debug_step("Saving configuration")
def save_node_config(node_id: str, config: dict) -> None:
    """Save node-specific configuration to file.
    
    Args:
        node_id: The ID of the node
        config: Configuration dictionary to save
    """
    config_file = CONFIGS_DIR / f"{node_id}_config.json"
    try:
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=4)
        logger.debug(f"Configuration saved to {config_file}")
    except Exception as e:
        logger.debug(f"Failed to save configuration: {str(e)}")
        raise MQTTError(f"Failed to save configuration: {str(e)}")

@debug_step("Retrieving configuration")
def get_stored_config(node_id: str, create_if_missing: bool = True) -> dict:
    """Get stored configuration for a node.
    
    Args:
        node_id: The ID of the node
        create_if_missing: Whether to create a node-specific config if none exists
        
    Returns:
        dict: Node configuration
    """
    config_file = CONFIGS_DIR / f"{node_id}_config.json"
    
    # If node-specific config doesn't exist and create_if_missing is True
    if not config_file.exists() and create_if_missing:
        logger.debug(f"Creating new configuration for node {node_id}")
        config = create_node_specific_config(node_id)
        save_node_config(node_id, config)
        return config
        
    # If node-specific config exists, use it
    if config_file.exists():
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            logger.debug(f"Loaded configuration for node {node_id}")
            return config
        except json.JSONDecodeError as e:
            logger.debug(f"Invalid JSON in config file: {str(e)}")
            raise MQTTError(f"Invalid configuration file for node {node_id}")
            
    # If we get here, no config exists and we're not creating one
    logger.debug(f"No configuration found for node {node_id}")
    raise MQTTError(f"No configuration found for node {node_id}")

@debug_step("Retrieving parameters")
def get_stored_params(node_id: str) -> dict:
    """Get stored parameters for a node."""
    params_file = CONFIGS_DIR / f"{node_id}_params.json"
    
    if not params_file.exists():
        params_file = CONFIGS_DIR / "default_params.json"
        if not params_file.exists():
            logger.debug("No parameters found")
            raise MQTTError("No default parameters found")
            
    try:
        with open(params_file, 'r') as f:
            params = json.load(f)
        logger.debug(f"Loaded parameters from {params_file}")
        return params
    except json.JSONDecodeError as e:
        logger.debug(f"Invalid JSON in parameters file: {str(e)}")
        raise MQTTError("Invalid parameters file")

@debug_step("Validating swagger-compliant payload")
def validate_device_params_payload(payload: dict, device_name: str) -> bool:
    """Validate that payload follows MQTT swagger specification format.
    
    Expected format: {device_name: {param1: value1, param2: value2}}
    
    Args:
        payload: The payload to validate
        device_name: Expected device name
        
    Returns:
        bool: True if valid
        
    Raises:
        MQTTError: If payload format is invalid
    """
    if not isinstance(payload, dict):
        raise MQTTError("Payload must be a dictionary")
        
    if device_name not in payload:
        raise MQTTError(f"Device '{device_name}' not found in payload")
        
    if not isinstance(payload[device_name], dict):
        raise MQTTError(f"Parameters for device '{device_name}' must be a dictionary")
        
    logger.debug(f"Payload validation successful for device: {device_name}")
    return True

@debug_step("Creating swagger-compliant payload")
def create_device_params_payload(params: dict, device_name: str) -> dict:
    """Create MQTT swagger-compliant payload format.
    
    Converts: {device_name: {params}} or raw {params}
    To: {device_name: {params}}
    
    Args:
        params: Parameter dictionary
        device_name: Target device name
        
    Returns:
        dict: Swagger-compliant payload
    """
    # If params already has the device name as key, use it directly
    if device_name in params and isinstance(params[device_name], dict):
        payload = {device_name: params[device_name]}
        logger.debug(f"Using existing device structure for {device_name}")
    else:
        # If params is the raw parameter dict, wrap it with device name
        payload = {device_name: params}
        logger.debug(f"Wrapping parameters with device name: {device_name}")
        
    validate_device_params_payload(payload, device_name)
    return payload

@debug_step("Creating single parameter payload")
def create_single_param_payload(device_name: str, param_name: str, param_value: str, param_type: str = 'string') -> dict:
    """Create swagger-compliant payload for a single parameter.
    
    Args:
        device_name: Name of the device
        param_name: Name of the parameter
        param_value: Value of the parameter (as string)
        param_type: Type of the parameter (string, int, float, bool)
        
    Returns:
        dict: Swagger-compliant payload
    """
    # Convert value to appropriate type
    try:
        if param_type == 'int':
            converted_value = int(param_value)
        elif param_type == 'float':
            converted_value = float(param_value)
        elif param_type == 'bool':
            converted_value = param_value.lower() in ('true', '1', 'yes', 'on')
        else:  # string or default
            converted_value = param_value
            
        logger.debug(f"Converted parameter {param_name}={param_value} to type {param_type}: {converted_value}")
    except (ValueError, AttributeError) as e:
        raise MQTTError(f"Invalid value '{param_value}' for type '{param_type}': {str(e)}")
    
    # Create swagger-compliant payload
    payload = {
        device_name: {
            param_name: converted_value
        }
    }
    
    validate_device_params_payload(payload, device_name)
    logger.debug(f"Created single parameter payload: {payload}")
    return payload

@debug_step("Creating multiple parameters payload")
def create_multi_param_payload(device_name: str, param_data: list) -> dict:
    """Create swagger-compliant payload for multiple parameters.
    
    Args:
        device_name: Name of the device
        param_data: List of tuples (param_name, param_value, param_type)
        
    Returns:
        dict: Swagger-compliant payload
    """
    device_params = {}
    
    for param_name, param_value, param_type in param_data:
        # Convert value to appropriate type
        try:
            if param_type == 'int':
                converted_value = int(param_value)
            elif param_type == 'float':
                converted_value = float(param_value)
            elif param_type == 'bool':
                converted_value = param_value.lower() in ('true', '1', 'yes', 'on')
            else:  # string or default
                converted_value = param_value
                
            device_params[param_name] = converted_value
            logger.debug(f"Added parameter {param_name}={converted_value} (type: {param_type})")
        except (ValueError, AttributeError) as e:
            raise MQTTError(f"Invalid value '{param_value}' for parameter '{param_name}' of type '{param_type}': {str(e)}")
    
    # Create swagger-compliant payload
    payload = {device_name: device_params}
    validate_device_params_payload(payload, device_name)
    logger.debug(f"Created multi-parameter payload: {payload}")
    return payload

def list_available_devices(params: dict) -> list:
    """List available device names from parameters."""
    if not isinstance(params, dict):
        return []
    return list(params.keys())



@click.group()
def node():
    """Node configuration and parameters management commands.
    
    All parameter commands comply with ESP RainMaker MQTT swagger specification
    using the standardized device name -> parameter format.
    """
    pass

@node.command('config')
@click.option('--node-id', required=True, help='Node ID to configure')
@click.option('--device-type', type=click.Choice(['light', 'heater', 'washer']), required=True, 
              help='Type of device to configure')
@click.option('--config-file', type=click.Path(exists=True), help='Custom JSON file containing node configuration')
@click.option('--project-name', help='Project name for the device')
@click.pass_context
@debug_log
def set_config(ctx, node_id, device_type, config_file, project_name):
    """Set node configuration using predefined templates.
    
    This command sets the complete node configuration including device definitions,
    parameter schemas, and metadata. This is different from parameter updates.
    
    Examples:
        mqtt-cli node config --node-id node123 --device-type light --project-name "Smart Home"
        mqtt-cli node config --node-id node123 --device-type heater --config-file custom_config.json
    """
    try:
        # Note: This command is now deprecated in favor of the new rm-node CLI
        click.echo(click.style("WARNING: This command is deprecated. Use the new rm-node CLI:", fg='yellow'))
        click.echo("   rm-node --cert-path <path> --broker-id <broker>")
        click.echo("   Then use: config <device_type>")
        click.echo()
        
        # For backward compatibility, still provide the functionality
        mqtt_client = ctx.obj.get('MQTT')
        if not mqtt_client:
            logger.debug("No active MQTT connection found")
            click.echo(click.style("ERROR: No active MQTT connection. Use the new rm-node CLI instead.", fg='red'), err=True)
            sys.exit(1)

        # Get configuration
        if config_file:
            # Use custom config file if provided
            logger.debug(f"Loading configuration from file: {config_file}")
            with open(config_file, 'r') as f:
                config = json.load(f)
        else:
            # Create config from template
            logger.debug(f"Creating configuration from {device_type} template")
            config = create_node_specific_config(node_id, device_type, project_name)

        # Basic validation
        logger.debug("Validating configuration")
        required_fields = ['node_id', 'info', 'devices']
        missing_fields = [field for field in required_fields if field not in config]
        if missing_fields:
            logger.debug(f"Missing required fields in configuration: {missing_fields}")
            click.echo(click.style(f"✗ Missing required fields: {', '.join(missing_fields)}", fg='red'), err=True)
            sys.exit(1)

        # Validate node_id matches
        if config['node_id'] != node_id:
            logger.debug(f"Configuration node_id mismatch: {config['node_id']} != {node_id}")
            click.echo(click.style(f"✗ Config file node_id '{config['node_id']}' does not match specified node_id '{node_id}'", fg='red'), err=True)
            sys.exit(1)

        # Save the configuration locally
        logger.debug("Saving configuration locally")
        save_node_config(node_id, config)
        click.echo(click.style("✓ Saved configuration locally", fg='green'))

        # Simple topic structure
        topic = f"node/{node_id}/config"
        
        # Publish config
        if mqtt_client.publish(topic, json.dumps(config), qos=1):
            click.echo(click.style(f"✓ Published configuration for node {node_id}", fg='green'))
            click.echo("\nConfiguration:")
            click.echo(json.dumps(config, indent=2))
            return 0
        else:
            click.echo(click.style("✗ Failed to publish configuration", fg='red'), err=True)
            sys.exit(1)
            
    except json.JSONDecodeError as e:
        click.echo(click.style(f"✗ Invalid JSON in config file: {str(e)}", fg='red'), err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        sys.exit(1)

@node.command('params')
@click.option('--node-id', required=True, help='Node ID to set parameters for')
@click.option('--device-name', required=True, help='Name of the device to set parameters for')
@click.option('--params-file', type=click.Path(exists=True), help='JSON file containing parameters')
@click.option('--remote', is_flag=True, help='Use remote parameters topic instead of local')
@click.option('--params', multiple=True, help='Parameters in format "name:value:type" (type optional, defaults to string)')
@click.pass_context
@debug_log
def set_params(ctx, node_id: str, device_name: str, params_file: str, remote: bool, params: tuple):
    """Set parameters for a specific device on a node.
    
    SWAGGER COMPLIANT: Uses device name -> parameter format as per MQTT specification.
    
    Examples:
        # Set multiple parameters
        mqtt-cli node params --node-id node123 --device-name "Light" --params "brightness:165:int" --params "power:true:bool"
        
        # From file (for complex configurations)
        mqtt-cli node params --node-id node123 --device-name "Light" --params-file params.json
        
        # Use remote topic
        mqtt-cli node params --node-id node123 --device-name "Light" --params "brightness:165:int" --remote
    """
    try:
        # Note: This command is now deprecated in favor of the new rm-node CLI
        click.echo(click.style("WARNING: This command is deprecated. Use the new rm-node CLI:", fg='yellow'))
        click.echo("   rm-node --cert-path <path> --broker-id <broker>")
        click.echo("   Then use: params <device_name> <param>=<value>")
        click.echo()
        
        # For backward compatibility, still provide the functionality
        mqtt_client = ctx.obj.get('MQTT')
        if not mqtt_client:
            logger.debug("No active MQTT connection found")
            click.echo(click.style("ERROR: No active MQTT connection. Use the new rm-node CLI instead.", fg='red'), err=True)
            sys.exit(1)
        
        # Determine parameter source and create payload
        payload = None
        
        # Priority 1: Multiple parameters via --params
        if params:
            logger.debug(f"Using parameters: {list(params)}")
            try:
                param_data = []
                for param_spec in params:
                    parts = param_spec.split(':')
                    if len(parts) < 2:
                        raise MQTTError(f"Invalid parameter format '{param_spec}'. Use 'name:value' or 'name:value:type'")
                    
                    p_name = parts[0]
                    p_value = parts[1] 
                    p_type = parts[2] if len(parts) > 2 else 'string'
                    
                    if p_type not in ['string', 'int', 'float', 'bool']:
                        raise MQTTError(f"Invalid parameter type '{p_type}'. Use: string, int, float, bool")
                    
                    param_data.append((p_name, p_value, p_type))
                
                payload = create_multi_param_payload(device_name, param_data)
                click.echo(click.style(f"Created {len(param_data)} parameters for device {device_name}", fg='green'))
            except MQTTError as e:
                click.echo(click.style(f"✗ {str(e)}", fg='red'), err=True)
                sys.exit(1)
                
        # Priority 2: Use parameters file
        elif params_file:
            logger.debug(f"Loading parameters from file: {params_file}")
            try:
                with open(params_file, 'r') as f:
                    params_dict = json.load(f)
                payload = create_device_params_payload(params_dict, device_name)
                click.echo(click.style(f"Loaded parameters from {params_file}", fg='green'))
            except (json.JSONDecodeError, FileNotFoundError) as e:
                click.echo(click.style(f"✗ Error reading params file: {str(e)}", fg='red'), err=True)
                sys.exit(1)
            except MQTTError as e:
                click.echo(click.style(f"✗ {str(e)}", fg='red'), err=True)
                try:
                    with open(params_file, 'r') as f:
                        params_dict = json.load(f)
                    devices = list_available_devices(params_dict)
                    if devices:
                        click.echo(f"Available devices: {', '.join(devices)}")
                except:
                    pass
                sys.exit(1)
        
        # No parameter source specified
        else:
            click.echo(click.style("No parameter source specified", fg='red'), err=True)
            click.echo("Choose one of these options:")
            click.echo("  - Parameters: --params 'name:value:type'")
            click.echo("  - From file: --params-file FILE")
            sys.exit(1)

        # Topic structure based on remote/local
        topic = f"node/{node_id}/params/local"
        logger.debug(f"Publishing to topic: {topic}")

        # Publish parameters
        if mqtt_client.publish(topic, json.dumps(payload), qos=1):
            click.echo(click.style(f"Set {'remote' if remote else 'local'} parameters for device {device_name} on node {node_id}", fg='green'))
            click.echo("\nSwagger-compliant payload:")
            click.echo(json.dumps(payload, indent=2))
            return 0
        else:
            click.echo(click.style("✗ Failed to publish parameters", fg='red'), err=True)
            sys.exit(1)
        
    except Exception as e:
        logger.debug(f"Error in set_params: {str(e)}")
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        sys.exit(1)

@node.command('monitor')
@click.option('--node-id', required=True, help='Node ID to monitor')
@click.option('--timeout', default=60, type=int, help='Monitoring timeout in seconds')
@click.pass_context
@debug_log
def monitor_node(ctx, node_id: str, timeout: int):
    """Monitor node status and parameters.
    
    Example: mqtt-cli node monitor --node-id node123 --timeout 120
    """
    try:
        # Note: This command is now deprecated in favor of the new rm-node CLI
        click.echo(click.style("WARNING: This command is deprecated. Use the new rm-node CLI which provides", fg='yellow'))
        click.echo("   background monitoring automatically for all connected nodes.")
        click.echo()
        
        # For backward compatibility, still provide the functionality
        mqtt_client = ctx.obj.get('MQTT')
        if not mqtt_client:
            click.echo(click.style("ERROR: No active MQTT connection. Use the new rm-node CLI instead.", fg='red'), err=True)
            sys.exit(1)
            
        # Only monitor remote parameters topic
        topic = f"node/{node_id}/params/remote"
            
        def on_message(client, userdata, message):
            click.echo(message.payload.decode())
                
        # Subscribe to remote parameters topic
        if not mqtt_client.subscribe(topic=topic, callback=on_message):
            click.echo(click.style(f"✗ Failed to subscribe", fg='red'), err=True)
            sys.exit(1)
            
        click.echo("Monitoring started... Press Ctrl+C to stop")
        
        try:
            start_time = time.time()
            while True:
                if time.time() - start_time > timeout:
                    break
                    
                if not mqtt_client.ping():
                    mqtt_client.reconnect()
                    mqtt_client.subscribe(topic=topic, callback=on_message)
                
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\nStopped")
        finally:
            try:
                mqtt_client.unsubscribe(topic)
            except:
                pass
            
    except Exception as e:
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        sys.exit(1)



@node.command('init-params')
@click.option('--node-id', required=True, help='Node ID to initialize parameters for')
@click.option('--device-name', required=True, help='Name of the device to initialize parameters for')
@click.option('--params-file', type=click.Path(exists=True), help='JSON file containing initial parameters')
@click.option('--params', multiple=True, help='Parameters in format "name:value:type" (type optional, defaults to string)')
@click.pass_context
@debug_log
def init_params(ctx, node_id: str, device_name: str, params_file: str, params: tuple):
    """Initialize node parameters for a specific device.
    
    SWAGGER COMPLIANT: Uses device name -> parameter format as per MQTT specification.
    
    Examples:
        # Initialize multiple parameters
        mqtt-cli node init-params --node-id node123 --device-name "Light" --params "brightness:50:int" --params "power:false:bool"
        
        # From file (for complex configurations)
        mqtt-cli node init-params --node-id node123 --device-name "Light" --params-file init_params.json
    """
    try:
        logger.debug(f"Initializing parameters for node {node_id}, device {device_name}")
        
        # Note: This command is now deprecated in favor of the new rm-node CLI
        click.echo(click.style("WARNING: This command is deprecated. Use the new rm-node CLI:", fg='yellow'))
        click.echo("   rm-node --cert-path <path> --broker-id <broker>")
        click.echo("   Then use: params <device_name> <param>=<value>")
        click.echo()
        
        # For backward compatibility, still provide the functionality
        mqtt_client = ctx.obj.get('MQTT')
        if not mqtt_client:
            logger.debug("No active MQTT connection found")
            click.echo(click.style("ERROR: No active MQTT connection. Use the new rm-node CLI instead.", fg='red'), err=True)
            sys.exit(1)
        
        # Determine parameter source and create payload
        payload = None
        
        # Priority 1: Multiple parameters via --params
        if params:
            logger.debug(f"Using parameters: {list(params)}")
            try:
                param_data = []
                for param_spec in params:
                    parts = param_spec.split(':')
                    if len(parts) < 2:
                        raise MQTTError(f"Invalid parameter format '{param_spec}'. Use 'name:value' or 'name:value:type'")
                    
                    p_name = parts[0]
                    p_value = parts[1] 
                    p_type = parts[2] if len(parts) > 2 else 'string'
                    
                    if p_type not in ['string', 'int', 'float', 'bool']:
                        raise MQTTError(f"Invalid parameter type '{p_type}'. Use: string, int, float, bool")
                    
                    param_data.append((p_name, p_value, p_type))
                
                payload = create_multi_param_payload(device_name, param_data)
                click.echo(click.style(f"Created {len(param_data)} initialization parameters for device {device_name}", fg='green'))
            except MQTTError as e:
                click.echo(click.style(f"✗ {str(e)}", fg='red'), err=True)
                sys.exit(1)
        
        # Priority 2: Use parameters file
        elif params_file:
            logger.debug(f"Loading parameters from file: {params_file}")
            try:
                with open(params_file, 'r') as f:
                    params_dict = json.load(f)
                payload = create_device_params_payload(params_dict, device_name)
                click.echo(click.style(f"✓ Loaded parameters from {params_file}", fg='green'))
            except (json.JSONDecodeError, FileNotFoundError) as e:
                click.echo(click.style(f"✗ Error reading params file: {str(e)}", fg='red'), err=True)
                sys.exit(1)
            except MQTTError as e:
                click.echo(click.style(f"✗ {str(e)}", fg='red'), err=True)
                sys.exit(1)
        
        # No parameter source specified
        else:
            click.echo(click.style("No parameter source specified", fg='red'), err=True)
            click.echo("Choose one of these options:")
            click.echo("  - Parameters: --params 'name:value:type'")
            click.echo("  - From file: --params-file FILE")
            sys.exit(1)
                
        # Topic for initial parameters (local only)
        topic = f"node/{node_id}/params/local/init"
        logger.debug(f"Publishing to topic: {topic}")
        
        # Publish parameters
        if mqtt_client.publish(topic, json.dumps(payload), qos=1):
            logger.debug("Parameters published successfully")
            click.echo(click.style(f"Initialized parameters for device {device_name} on node {node_id}", fg='green'))
            click.echo("\nSwagger-compliant payload:")
            click.echo(json.dumps(payload, indent=2))
            return 0
        else:
            logger.debug("Failed to publish parameters")
            click.echo(click.style("✗ Failed to initialize parameters", fg='red'), err=True)
            sys.exit(1)
            
    except Exception as e:
        logger.debug(f"Error in init_params: {str(e)}")
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        sys.exit(1)

@node.command('group-params')
@click.option('--node-ids', required=True, help='Comma-separated list of node IDs')
@click.option('--device-name', required=True, help='Name of the device to set parameters for')
@click.option('--params-file', type=click.Path(exists=True), help='JSON file containing parameters')
@click.option('--params', multiple=True, help='Parameters in format "name:value:type" (type optional, defaults to string)')
@click.option('--group-id', required=True, help='Group ID for the parameter update')
@click.pass_context
@debug_log
def group_params(ctx, node_ids: str, device_name: str, params_file: str, params: tuple, group_id: str):
    """Set parameters for a specific device across multiple nodes.
    
    SWAGGER COMPLIANT: Uses device name -> parameter format as per MQTT specification.
    
    Examples:
        # Set multiple parameters across multiple nodes
        mqtt-cli node group-params --node-ids "node1,node2,node3" --device-name "Light" --params "brightness:75:int" --params "power:true:bool" --group-id "group1"
        
        # From file (for complex configurations)
        mqtt-cli node group-params --node-ids "node1,node2,node3" --device-name "Light" --params-file group_params.json --group-id "group1"
    """
    try:
        # Split node IDs
        node_list = [n.strip() for n in node_ids.split(',')]
        logger.debug(f"Processing group parameters for nodes: {node_list}")
        
        # Note: This command is now deprecated in favor of the new rm-node CLI
        click.echo(click.style("WARNING: This command is deprecated. Use the new rm-node CLI which", fg='yellow'))
        click.echo("   automatically handles multiple nodes with simple commands.")
        click.echo()
        
        # Determine parameter source and create payload
        payload = None
        
        # Priority 1: Multiple parameters via --params
        if params:
            logger.debug(f"Using parameters: {list(params)}")
            try:
                param_data = []
                for param_spec in params:
                    parts = param_spec.split(':')
                    if len(parts) < 2:
                        raise MQTTError(f"Invalid parameter format '{param_spec}'. Use 'name:value' or 'name:value:type'")
                    
                    p_name = parts[0]
                    p_value = parts[1] 
                    p_type = parts[2] if len(parts) > 2 else 'string'
                    
                    if p_type not in ['string', 'int', 'float', 'bool']:
                        raise MQTTError(f"Invalid parameter type '{p_type}'. Use: string, int, float, bool")
                    
                    param_data.append((p_name, p_value, p_type))
                
                payload = create_multi_param_payload(device_name, param_data)
                click.echo(click.style(f"Created {len(param_data)} group parameters for device {device_name}", fg='green'))
            except MQTTError as e:
                click.echo(click.style(f"Error: {str(e)}", fg='red'), err=True)
                sys.exit(1)
        
        # Priority 2: Use parameters file
        elif params_file:
            logger.debug(f"Loading parameters from file: {params_file}")
            try:
                with open(params_file, 'r') as f:
                    params_dict = json.load(f)
                payload = create_device_params_payload(params_dict, device_name)
                click.echo(click.style(f"Loaded parameters from {params_file}", fg='green'))
            except (json.JSONDecodeError, FileNotFoundError) as e:
                click.echo(click.style(f"Error reading params file: {str(e)}", fg='red'), err=True)
                sys.exit(1)
            except MQTTError as e:
                click.echo(click.style(f"Error: {str(e)}", fg='red'), err=True)
                sys.exit(1)
        
        # No parameter source specified
        else:
            click.echo(click.style("No parameter source specified", fg='red'), err=True)
            click.echo("Choose one of these options:")
            click.echo("  - Parameters: --params 'name:value:type'")
            click.echo("  - From file: --params-file FILE")
            sys.exit(1)
        
        # Display what will be sent
        click.echo(click.style(f"Setting parameters for device '{device_name}' on {len(node_list)} nodes with group ID '{group_id}'", fg='blue'))
        click.echo("\nSwagger-compliant payload:")
        click.echo(json.dumps(payload, indent=2))
        click.echo()
        
        success_count = 0
        failed_nodes = []
        
        # For backward compatibility - this should use the new rm-node CLI
        mqtt_client = ctx.obj.get('MQTT')
        if not mqtt_client:
            click.echo(click.style("ERROR: No active MQTT connection. Use the new rm-node CLI instead.", fg='red'))
            sys.exit(1)
            
        # Process each node (simplified - assumes single connection)
        for node_id in node_list:
            logger.debug(f"Processing node: {node_id}")
            try:
                    
                # Topic for group parameters with group ID
                topic = f"node/{node_id}/params/local/{group_id}"
                logger.debug(f"Publishing to topic: {topic}")
                
                # Publish parameters
                if mqtt_client.publish(topic, json.dumps(payload), qos=1):
                    logger.debug(f"Parameters published successfully for node {node_id}")
                    click.echo(click.style(f"Updated parameters for device {device_name} on node {node_id}", fg='green'))
                    success_count += 1
                else:
                    logger.debug(f"Failed to publish parameters for node {node_id}")
                    failed_nodes.append(f"{node_id} (publish failed)")
                    
            except Exception as e:
                logger.debug(f"Error processing node {node_id}: {str(e)}")
                failed_nodes.append(f"{node_id} ({str(e)})")
                continue
        
        # Summary
        click.echo("\n" + "="*50)
        click.echo(click.style(f"Successfully updated: {success_count}/{len(node_list)} nodes", fg='green'))
        
        if failed_nodes:
            click.echo(click.style(f"Failed nodes:", fg='red'))
            for failed in failed_nodes:
                click.echo(f"  - {failed}")
        
        if success_count == 0:
            sys.exit(1)
                
    except Exception as e:
        logger.debug(f"Error in group_params: {str(e)}")
        click.echo(click.style(f"Error: {str(e)}", fg='red'), err=True)
        sys.exit(1) 

def get_node_connection(ctx, node_id: str):
    """Get MQTT connection for a specific node (backward compatibility)."""
    mqtt_client = ctx.obj.get('MQTT')
    return mqtt_client

def get_node_manager(ctx):
    """Get the node manager from context (for new rm-node CLI)."""
    return ctx.obj.get('NODE_MANAGER') 