"""
Persistent Interactive Shell for RMNode CLI.

This shell provides a user-friendly interface for managing all connected nodes
with section-based commands that mirror the actual command modules structure.
"""

import click
import asyncio
import json
import sys
import os
import time
from datetime import datetime
from typing import Optional, List, Dict, Any

# Import command modules
from .commands import node_config

class PersistentShell:
    """Interactive shell for managing connected nodes with section-based command organization."""
    
    def __init__(self, manager):
        self.manager = manager
        self.running = True
        
        # Organize commands by actual module sections (only publishing commands)
        self.command_sections = {
            'node': {
                'commands': ['config', 'params', 'init-params', 'group-params'],
                'description': 'Node configuration and parameter management',
                'module': 'node_config.py'
            },
            'ota': {
                'commands': ['fetch', 'request'],
                'description': 'Over-The-Air update operations',
                'module': 'ota.py'
            },
            'tsdata': {
                'commands': ['tsdata', 'simple-tsdata'],
                'description': 'Time series data operations', 
                'module': 'time_series.py'
            },
            'user': {
                'commands': ['map', 'alert'],
                'description': 'User mapping and alert operations',
                'module': 'user_mapping.py'
            },
            'command': {
                'commands': ['send-command'],
                'description': 'Device command operations (TLV protocol)',
                'module': 'device.py'
            },
            'utility': {
                'commands': ['nodes', 'status', 'help', 'clear', 'exit'],
                'description': 'Shell utility commands',
                'module': 'built-in'
            }
        }
        
        # Section-based command handlers
        self.command_handlers = {
            # Node section (from node_config.py)
            'node': self._handle_node_section,
            
            # OTA section (from ota.py)
            'ota': self._handle_ota_section,
            
            # Time Series section (from time_series.py)
            'tsdata': self._handle_tsdata_section,
            
            # User section (from user_mapping.py)
            'user': self._handle_user_section,
            
            # Command section (from device.py)
            'command': self._handle_command_section,
            
            # Utility commands
            'nodes': self._handle_nodes,
            'status': self._handle_status,
            'help': self._handle_help,
            'clear': self._handle_clear,
            'exit': self._handle_exit,
            'quit': self._handle_exit,
        }
        
    def get_prompt(self) -> str:
        """Get the shell prompt showing connected nodes."""
        connected = len(self.manager.get_connected_nodes())
        return click.style(f"rm-node({connected} nodes)> ", fg='green', bold=True)
        
    async def run(self):
        """Run the interactive shell."""
        # Display welcome message
        self._show_welcome()
        
        while self.running:
            try:
                # Get user input
                try:
                    command_line = input(self.get_prompt())
                except (EOFError, KeyboardInterrupt):
                    click.echo("\nExiting...")
                    break
                    
                # Skip empty lines
                command_line = command_line.strip()
                if not command_line:
                    continue
                    
                # Parse and execute command
                await self._execute_command(command_line)
                
            except Exception as e:
                click.echo(click.style(f"Error: {str(e)}", fg='red'))
                
    def _show_welcome(self):
        """Display welcome message with section-based command overview."""
        connected_nodes = self.manager.get_connected_nodes()
        
        click.echo()
        click.echo(click.style("RM-Node Interactive Shell", fg='green', bold=True))
        click.echo(click.style("=" * 50, fg='blue'))
        click.echo(f"Connected to {len(connected_nodes)} node(s):")
        for i, node_id in enumerate(connected_nodes, 1):
            click.echo(f"  {i}. {click.style(node_id, fg='cyan')}")
        click.echo()
        
        # Show section-based command overview
        click.echo(click.style("Command Sections:", fg='blue', bold=True))
        click.echo("  node <command>      - Node configuration & parameters")
        click.echo("  ota <command>       - Over-The-Air update operations (fetch, request)")
        click.echo("  tsdata <command>    - Time series data operations (tsdata, simple-tsdata)")
        click.echo("  user <command>      - User mapping & alerts")
        click.echo("  command <command>   - Device command operations (TLV protocol)")
        click.echo("  nodes               - Show connected nodes")
        click.echo("  status              - Show detailed status")
        click.echo("  help [section]      - Show help (general or section-specific)")
        click.echo("  exit                - Exit shell")
        click.echo()
        click.echo("Type 'help' to see all available commands by section.")
        click.echo("Type 'help <section>' for section-specific commands.")
        click.echo(click.style("=" * 50, fg='blue'))
        click.echo()
        
    async def _execute_command(self, command_line: str):
        """Parse and execute a command with section-aware routing."""
        parts = command_line.split()
        if not parts:
            return
            
        command = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []
        
        if command in self.command_handlers:
            await self.command_handlers[command](args)
        else:
            click.echo(click.style(f"Unknown command: {command}", fg='red'))
            click.echo("Type 'help' for available sections and commands.")
                
    async def _handle_help(self, args: List[str]):
        """Show section-based help information."""
        if not args:
            # Show main help with all sections
            click.echo("\nRM-Node CLI - Section-Based Command Reference")
            click.echo("=" * 60)
            click.echo()
            
            for section, info in self.command_sections.items():
                if section == 'utility':
                    continue
                    
                click.echo(click.style(f"{section.upper()} Section ({info['module']}):", fg='blue', bold=True))
                click.echo(f"  {info['description']}")
                click.echo("  Commands:")
                for cmd in info['commands']:
                    click.echo(f"    {section} {cmd}")
                click.echo()
            
            click.echo(click.style("UTILITY Commands:", fg='blue', bold=True))
            click.echo("  nodes                        - List connected nodes")
            click.echo("  status                       - Detailed connection status")
            click.echo("  help [section]               - Show section-specific help")
            click.echo("  clear                        - Clear screen")
            click.echo("  exit                         - Exit shell")
            click.echo()
            
            click.echo(click.style("Examples:", fg='yellow', bold=True))
            click.echo("  node config light            # Configure all nodes as light devices")
            click.echo("  node params Light power=true # Set light parameters")
            click.echo("  ota fetch 1.2.3             # Fetch firmware version 1.2.3")
            click.echo("  ota request                  # Request OTA with monitoring")
            click.echo("  tsdata tsdata sensor.json    # Send complex time series data")
            click.echo("  tsdata simple-tsdata temp.json # Send simple time series data")
            click.echo("  user alert 'System update'   # Send alert to all nodes")
            click.echo("  command send-command 1 0     # Send TLV command (admin, get pending)")
            click.echo("  help node                    # Show node section commands")
            click.echo()
            
        else:
            # Show specific section help
            await self._show_section_help(args[0].lower())
                
    async def _show_section_help(self, section: str):
        """Show detailed help for a specific section."""
        if section == 'node':
            click.echo("\nNODE Section (node_config.py):")
            click.echo("Node configuration and parameter management commands.")
            click.echo()
            click.echo("Commands:")
            click.echo("  node config <device_type>                    - Configure node device type")
            click.echo("  node params <device> <param>=<value>         - Set device parameters")
            click.echo("  node init-params <device> <param>=<value>    - Initialize device parameters")
            click.echo("  node group-params <device> <param>=<value>   - Set group parameters")
            click.echo()
            click.echo("Device types: light, heater, washer")
            click.echo()
            click.echo("Examples:")
            click.echo("  node config light")
            click.echo("  node params Light brightness=75 power=true")
            click.echo("  node init-params Light brightness=50")
            click.echo("  node group-params Light power=false")
            
        elif section == 'ota':
            click.echo("\nOTA Section (ota.py):")
            click.echo("Over-The-Air update operations.")
            click.echo()
            click.echo("Commands:")
            click.echo("  ota fetch <version>               - Request firmware download")
            click.echo("  ota request                       - Request OTA from nodes (with monitoring)")
            click.echo()
            click.echo("Topics used:")
            click.echo("  node/<node_id>/otafetch           - Fetch requests")
            click.echo("  node/<node_id>/otaurl             - OTA URL responses (monitored)")
            click.echo()
            click.echo("Examples:")
            click.echo("  ota fetch 1.2.3")
            click.echo("  ota request")
            
        elif section == 'tsdata':
            click.echo("\nTSDATA Section (time_series.py):")
            click.echo("Time series data operations based on ESP RainMaker MQTT topics.")
            click.echo()
            click.echo("Commands:")
            click.echo("  tsdata tsdata <json_file>         - Send complex time series data")
            click.echo("  tsdata simple-tsdata <json_file>  - Send simple time series data")
            click.echo()
            click.echo("Topics used:")
            click.echo("  node/<node_id>/tsdata             - Complex time series format")
            click.echo("  node/<node_id>/simple_tsdata      - Simple time series format")
            click.echo()
            click.echo("Examples:")
            click.echo("  tsdata tsdata sensor_data.json")
            click.echo("  tsdata simple-tsdata temperature.json")
            
        elif section == 'user':
            click.echo("\nUSER Section (user_mapping.py):")
            click.echo("User mapping and alert operations.")
            click.echo()
            click.echo("Commands:")
            click.echo("  user map <user_id> <secret_key>          - Map user to nodes")
            click.echo("  user alert <message>                     - Send user alert")
            click.echo()
            click.echo("Topics used:")
            click.echo("  node/<node_id>/user/mapping              - User mapping")
            click.echo("  node/<node_id>/alert                     - Alert messages")
            click.echo()
            click.echo("Examples:")
            click.echo("  user map user123 secret_key_abc")
            click.echo("  user alert 'System maintenance soon'")
            
        elif section == 'command':
            click.echo("\nCOMMAND Section (device.py):")
            click.echo("Device command operations with TLV protocol.")
            click.echo()
            click.echo("Commands:")
            click.echo("  command send-command <role> <command> [<data>]  - Send TLV command")
            click.echo()
            click.echo("Roles: 1=admin, 2=primary, 4=secondary")
            click.echo("Commands: 0=get pending, 16=upload, 17=download, 20=confirm")
            click.echo()
            click.echo("Topics used:")
            click.echo("  node/<node_id>/to-node                   - Command requests")
            click.echo("  node/<node_id>/from-node                 - Command responses (monitored)")
            click.echo()
            click.echo("Examples:")
            click.echo("  command send-command 1 0")
            click.echo("  command send-command 2 16 '{\"file\":\"firmware.bin\"}'")
            
        else:
            click.echo(f"No detailed help available for '{section}'")
            click.echo("Available sections: node, ota, tsdata, user, command")

    # Utility Commands
    async def _handle_nodes(self, args: List[str]):
        """List connected nodes."""
        nodes = self.manager.get_connected_nodes()
        click.echo(f"\nConnected Nodes ({len(nodes)}):")
        click.echo("-" * 40)
        for i, node_id in enumerate(nodes, 1):
            click.echo(f"  {i}. {click.style(node_id, fg='cyan')}")
        click.echo()
        
    async def _handle_status(self, args: List[str]):
        """Show detailed connection status."""
        nodes = self.manager.get_connected_nodes()
        
        click.echo(f"\nConnection Status:")
        click.echo("=" * 50)
        
        # Broker information
        click.echo(f"Broker URL: {click.style(self.manager.broker_url, fg='cyan')}")
        click.echo(f"Config Directory: {click.style(self.manager.config_dir, fg='cyan')}")
        click.echo()
        
        # Connection summary
        click.echo(f"Connected Nodes: {click.style(str(len(nodes)), fg='green')} nodes")
        click.echo(f"MQTT Connections: {click.style('Online', fg='green')}")
        click.echo(f"Background Listeners: {click.style('Active', fg='green')}")
        click.echo()
        
        # List connected nodes
        if nodes:
            click.echo("Connected Node IDs:")
            for i, node_id in enumerate(nodes, 1):
                click.echo(f"  {i:2d}. {click.style(node_id, fg='cyan')}")
            click.echo()
        
        # Monitored topics
        monitored_topics = [
            "params/remote",      # Parameter responses
            "otaurl",            # OTA responses  
            "to-cloud",          # Command responses
            "status",            # Status updates
            "alert"              # User alerts
        ]
        
        click.echo("Monitored Topics (per node):")
        for topic in monitored_topics:
            full_topic = f"node/+/{topic}"
            click.echo(f"  - {click.style(full_topic, fg='yellow')}")
        click.echo()
        
        # Topic descriptions
        topic_descriptions = {
            "params/remote": "Parameter responses from nodes",
            "otaurl": "OTA firmware download URLs", 
            "to-cloud": "Command execution responses",
            "status": "Node status updates",
            "alert": "User alert messages"
        }
        
        for topic, description in topic_descriptions.items():
            click.echo(f"  {click.style(topic, fg='yellow'):15} - {description}")
        click.echo()
        
        # Statistics
        total_subscriptions = len(nodes) * len(monitored_topics)
        click.echo("Statistics:")
        click.echo(f"  Total subscriptions: {click.style(str(total_subscriptions), fg='green')}")
        click.echo(f"  Topics per node: {click.style(str(len(monitored_topics)), fg='green')}")
        click.echo()

    # NODE Section (from node_config.py)
    async def _handle_node_section(self, args: List[str]):
        """Handle NODE section commands: node <subcommand> [args...]"""
        if not args:
            click.echo(click.style("NODE Section Commands:", fg='blue', bold=True))
            click.echo("  node config <device_type>                    - Configure node device type")
            click.echo("  node params <device> <param>=<value>         - Set device parameters")
            click.echo("  node init-params <device> <param>=<value>    - Initialize device parameters")
            click.echo("  node group-params <device> <param>=<value>   - Set group parameters")
            click.echo()
            click.echo("Type 'help node' for detailed information.")
            return
            
        subcommand = args[0].lower()
        sub_args = args[1:] if len(args) > 1 else []
        
        if subcommand == 'config':
            await self._node_config(sub_args)
        elif subcommand == 'params':
            await self._node_params(sub_args)
        elif subcommand == 'init-params':
            await self._node_init_params(sub_args)
        elif subcommand == 'group-params':
            await self._node_group_params(sub_args)
        else:
            click.echo(click.style(f"Unknown node command: {subcommand}", fg='red'))
            click.echo("Available commands: config, params, init-params, group-params")
            click.echo("Type 'help node' for detailed information.")

    async def _node_config(self, args: List[str]):
        """Handle node config command."""
        if not args:
            click.echo(click.style("Usage: node config <device_type>", fg='yellow'))
            click.echo("Available types: light, heater, washer")
            return
            
        device_type = args[0].lower()
        if device_type not in ['light', 'heater', 'washer']:
            click.echo(click.style(f"Invalid device type: {device_type}", fg='red'))
            click.echo("Available types: light, heater, washer")
            return
            
        # Apply configuration to all connected nodes
        nodes = self.manager.get_connected_nodes()
        if not nodes:
            click.echo(click.style("No nodes connected", fg='yellow'))
            return
            
        click.echo(f"Configuring {len(nodes)} node(s) as {click.style(device_type, fg='cyan')} device...")
        
        success_count = 0
        for node_id in nodes:
            try:
                await self.manager.publish_to_node(node_id, f"node/{node_id}/config", {
                    "device_type": device_type,
                    "timestamp": int(time.time() * 1000)
                })
                success_count += 1
            except Exception as e:
                click.echo(click.style(f"Failed to configure {node_id}: {str(e)}", fg='red'))
                
        if success_count > 0:
            click.echo(click.style(f"Successfully configured {success_count}/{len(nodes)} nodes as {device_type}", fg='green'))
        else:
            click.echo(click.style("Failed to configure any nodes", fg='red'))

    async def _node_params(self, args: List[str]):
        """Handle node params command."""
        if len(args) < 2:
            click.echo(click.style("Usage: node params <device_name> <param1>=<value1> [<param2>=<value2> ...]", fg='yellow'))
            click.echo("Example: node params Light brightness=75 power=true")
            return
            
        device_name = args[0]
        param_specs = args[1:]
        
        # Parse parameters
        try:
            device_params = {}
            for param_spec in param_specs:
                if '=' not in param_spec:
                    click.echo(click.style(f"Invalid parameter format: {param_spec}", fg='red'))
                    click.echo("Use format: param_name=value")
                    return
                    
                param_name, param_value = param_spec.split('=', 1)
                
                # Auto-detect type and convert
                converted_value = self._auto_convert_value(param_value)
                device_params[param_name] = converted_value
                
            # Create swagger-compliant payload
            payload = {device_name: device_params}
            
            # Publish to all nodes
            topic_suffix = "params/local"
            payload_json = json.dumps(payload)
            
            success_count = self.manager.publish_to_all(topic_suffix, payload_json)
            
            click.echo(click.style(f"Set parameters for {device_name} on {success_count} nodes", fg='green'))
            click.echo(f"Payload: {json.dumps(payload, indent=2)}")
            
        except Exception as e:
            click.echo(click.style(f"✗ Error: {str(e)}", fg='red'))
            
    async def _node_init_params(self, args: List[str]):
        """Handle node init-params command."""
        if len(args) < 2:
            click.echo(click.style("Usage: node init-params <device_name> <param1>=<value1> [<param2>=<value2> ...]", fg='yellow'))
            click.echo("Example: node init-params Light brightness=50")
            return
            
        device_name = args[0]
        param_specs = args[1:]
        
        # Parse parameters
        try:
            device_params = {}
            for param_spec in param_specs:
                if '=' not in param_spec:
                    click.echo(click.style(f"Invalid parameter format: {param_spec}", fg='red'))
                    click.echo("Use format: param_name=value")
                    return
                    
                param_name, param_value = param_spec.split('=', 1)
                
                # Auto-detect type and convert
                converted_value = self._auto_convert_value(param_value)
                device_params[param_name] = converted_value
                
            # Create swagger-compliant payload
            payload = {device_name: device_params}
            
            # Publish to all nodes
            topic_suffix = "params/local"
            payload_json = json.dumps(payload)
            
            success_count = self.manager.publish_to_all(topic_suffix, payload_json)
            
            click.echo(click.style(f"Initialized parameters for {device_name} on {success_count} nodes", fg='green'))
            click.echo(f"Payload: {json.dumps(payload, indent=2)}")
            
        except Exception as e:
            click.echo(click.style(f"✗ Error: {str(e)}", fg='red'))

    async def _node_group_params(self, args: List[str]):
        """Handle node group-params command."""
        if len(args) < 2:
            click.echo(click.style("Usage: node group-params <device_name> <param1>=<value1> [<param2>=<value2> ...]", fg='yellow'))
            click.echo("Example: node group-params Light power=false")
            return
            
        device_name = args[0]
        param_specs = args[1:]
        
        # Parse parameters
        try:
            device_params = {}
            for param_spec in param_specs:
                if '=' not in param_spec:
                    click.echo(click.style(f"Invalid parameter format: {param_spec}", fg='red'))
                    click.echo("Use format: param_name=value")
                    return
                    
                param_name, param_value = param_spec.split('=', 1)
                
                # Auto-detect type and convert
                converted_value = self._auto_convert_value(param_value)
                device_params[param_name] = converted_value
                
            # Create swagger-compliant payload
            payload = {device_name: device_params}
            
            # Publish to all nodes
            topic_suffix = "params/local"
            payload_json = json.dumps(payload)
            
            success_count = self.manager.publish_to_all(topic_suffix, payload_json)
            
            click.echo(click.style(f"Set group parameters for {device_name} on {success_count} nodes", fg='green'))
            click.echo(f"Payload: {json.dumps(payload, indent=2)}")
            
        except Exception as e:
            click.echo(click.style(f"✗ Error: {str(e)}", fg='red'))

    # OTA Section (from ota.py)
    async def _handle_ota_section(self, args: List[str]):
        """Handle OTA section commands: ota <subcommand> [args...]"""
        if not args:
            click.echo(click.style("OTA Section Commands:", fg='blue', bold=True))
            click.echo("  ota fetch <version>               - Request firmware download")
            click.echo("  ota request                       - Request OTA from nodes (with monitoring)")
            click.echo()
            click.echo("Type 'help ota' for detailed information.")
            return
            
        subcommand = args[0].lower()
        sub_args = args[1:] if len(args) > 1 else []
        
        if subcommand == 'fetch':
            if not sub_args:
                click.echo(click.style("Usage: ota fetch <version>", fg='yellow'))
                click.echo("Example: ota fetch 1.2.3")
                return
                
            fw_version = sub_args[0]
            
            # Publish to all nodes using official ESP RainMaker topic
            success_count = 0
            nodes = self.manager.get_connected_nodes()
            
            for node_id in nodes:
                try:
                    topic = f"node/{node_id}/otafetch"
                    payload = {
                        "fw_version": fw_version,
                        "timestamp": int(time.time() * 1000)
                    }
                    payload_json = json.dumps(payload)
                    await self.manager.publish_to_node(node_id, topic, payload_json)
                    success_count += 1
                except Exception as e:
                    click.echo(click.style(f"Failed to send to {node_id}: {str(e)}", fg='red'))
            
            click.echo(click.style(f"Sent OTA fetch request (v{fw_version}) to {success_count} nodes", fg='green'))
            click.echo(f"Topic: node/<node_id>/otafetch")
            click.echo("Watch for responses on monitored 'otaurl' topic...")
            
        elif subcommand == 'request':
            # This command requests OTA and automatically monitors for responses
            click.echo(click.style("Requesting OTA updates from all nodes...", fg='blue'))
            
            success_count = 0
            nodes = self.manager.get_connected_nodes()
            
            for node_id in nodes:
                try:
                    topic = f"node/{node_id}/otarequest"
                    payload = {
                        "action": "request_update",
                        "timestamp": int(time.time() * 1000)
                    }
                    payload_json = json.dumps(payload)
                    await self.manager.publish_to_node(node_id, topic, payload_json)
                    success_count += 1
                except Exception as e:
                    click.echo(click.style(f"Failed to send to {node_id}: {str(e)}", fg='red'))
            
            click.echo(click.style(f"Sent OTA request to {success_count} nodes", fg='green'))
            click.echo("Background monitoring is automatically active for:")
            click.echo("  - node/<node_id>/otaurl     - OTA URL responses")
            click.echo("  - node/<node_id>/otastatus  - OTA status updates")
            click.echo("Watch for responses in real-time...")
            
        else:
            click.echo(click.style(f"Unknown OTA command: {subcommand}", fg='red'))
            click.echo("Available commands: fetch, request")
            click.echo("Type 'help ota' for detailed information.")

    # Time Series Section (from time_series.py)
    async def _handle_tsdata_section(self, args: List[str]):
        """Handle TSDATA section commands: tsdata <subcommand> [args...]"""
        if not args:
            click.echo(click.style("TSDATA Section Commands:", fg='blue', bold=True))
            click.echo("  tsdata tsdata <json_file>         - Send complex time series data")
            click.echo("  tsdata simple-tsdata <json_file>  - Send simple time series data")
            click.echo()
            click.echo("Type 'help tsdata' for detailed information.")
            return
            
        subcommand = args[0].lower()
        sub_args = args[1:] if len(args) > 1 else []
        
        if subcommand == 'tsdata':
            if not sub_args:
                click.echo(click.style("Usage: tsdata tsdata <json_file>", fg='yellow'))
                click.echo("Example: tsdata tsdata sensor_data.json")
                return
                
            json_file = sub_args[0]
            
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                    
                # Publish to all nodes using the official ESP RainMaker topic
                success_count = 0
                nodes = self.manager.get_connected_nodes()
                
                for node_id in nodes:
                    try:
                        topic = f"node/{node_id}/tsdata"
                        payload_json = json.dumps(data)
                        await self.manager.publish_to_node(node_id, topic, payload_json)
                        success_count += 1
                    except Exception as e:
                        click.echo(click.style(f"Failed to send to {node_id}: {str(e)}", fg='red'))
                
                click.echo(click.style(f"Sent complex time series data from {json_file} to {success_count} nodes", fg='green'))
                click.echo(f"Topic: node/<node_id>/tsdata")
                click.echo(f"Data entries: {len(data) if isinstance(data, (list, dict)) else 'N/A'}")
                
            except FileNotFoundError:
                click.echo(click.style(f"File not found: {json_file}", fg='red'))
            except json.JSONDecodeError as e:
                click.echo(click.style(f"Invalid JSON in {json_file}: {str(e)}", fg='red'))
            except Exception as e:
                click.echo(click.style(f"Error: {str(e)}", fg='red'))

        elif subcommand == 'simple-tsdata':
            if not sub_args:
                click.echo(click.style("Usage: tsdata simple-tsdata <json_file>", fg='yellow'))
                click.echo("Example: tsdata simple-tsdata temperature.json")
                return
                
            json_file = sub_args[0]
            
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                    
                # Publish to all nodes using the official ESP RainMaker topic
                success_count = 0
                nodes = self.manager.get_connected_nodes()
                
                for node_id in nodes:
                    try:
                        topic = f"node/{node_id}/simple_tsdata"
                        payload_json = json.dumps(data)
                        await self.manager.publish_to_node(node_id, topic, payload_json)
                        success_count += 1
                    except Exception as e:
                        click.echo(click.style(f"Failed to send to {node_id}: {str(e)}", fg='red'))
                
                click.echo(click.style(f"Sent simple time series data from {json_file} to {success_count} nodes", fg='green'))
                click.echo(f"Topic: node/<node_id>/simple_tsdata")
                click.echo(f"Data entries: {len(data) if isinstance(data, (list, dict)) else 'N/A'}")
                
            except FileNotFoundError:
                click.echo(click.style(f"File not found: {json_file}", fg='red'))
            except json.JSONDecodeError as e:
                click.echo(click.style(f"Invalid JSON in {json_file}: {str(e)}", fg='red'))
            except Exception as e:
                click.echo(click.style(f"Error: {str(e)}", fg='red'))
                
        else:
            click.echo(click.style(f"Unknown TSDATA command: {subcommand}", fg='red'))
            click.echo("Available commands: tsdata, simple-tsdata")
            click.echo("Type 'help tsdata' for detailed information.")

    # User Section (from user_mapping.py)
    async def _handle_user_section(self, args: List[str]):
        """Handle USER section commands: user <subcommand> [args...]"""
        if not args:
            click.echo(click.style("USER Section Commands:", fg='blue', bold=True))
            click.echo("  user map <user_id> <secret_key>          - Map user to nodes")
            click.echo("  user alert <message>                     - Send user alert")
            click.echo()
            click.echo("Type 'help user' for detailed information.")
            return
            
        subcommand = args[0].lower()
        sub_args = args[1:] if len(args) > 1 else []
        
        if subcommand == 'map':
            if len(sub_args) < 2:
                click.echo(click.style("Usage: user map <user_id> <secret_key>", fg='yellow'))
                return
                
            user_id = sub_args[0]
            secret_key = sub_args[1]
            
            payload = {
                "user_id": user_id,
                "secret_key": secret_key,
                "operation": "map",
                "timestamp": int(time.time() * 1000)
            }
            
            success_count = self.manager.publish_to_all("user/mapping", json.dumps(payload))
            click.echo(click.style(f"Mapped user {user_id} to {success_count} nodes", fg='green'))
            
        elif subcommand == 'alert':
            if not sub_args:
                click.echo(click.style("Usage: user alert <message>", fg='yellow'))
                return
                
            message = ' '.join(sub_args)
            
            payload = {
                "message": message,
                "timestamp": int(time.time() * 1000),
                "type": "user_alert"
            }
            
            success_count = self.manager.publish_to_all("alert", json.dumps(payload))
            click.echo(click.style(f"Sent user alert to {success_count} nodes", fg='green'))
            click.echo(f"Message: '{click.style(message, fg='cyan')}'")
            
        else:
            click.echo(click.style(f"Unknown USER command: {subcommand}", fg='red'))
            click.echo("Available commands: map, alert")
            click.echo("Type 'help user' for detailed information.")

    # Command Section (from device.py)
    async def _handle_command_section(self, args: List[str]):
        """Handle COMMAND section commands: command <subcommand> [args...]"""
        if not args:
            click.echo(click.style("COMMAND Section Commands:", fg='blue', bold=True))
            click.echo("  command send-command <role> <command> [<data>]  - Send TLV command")
            click.echo()
            click.echo("Type 'help command' for detailed information.")
            return
            
        subcommand = args[0].lower()
        sub_args = args[1:] if len(args) > 1 else []
        
        if subcommand == 'send-command':
            if len(sub_args) < 2:
                click.echo(click.style("Usage: command send-command <role> <command> [<data>]", fg='yellow'))
                click.echo("Example: command send-command 1 0")
                return
                
            role_str = sub_args[0]
            command_str = sub_args[1]
            data_str = sub_args[2] if len(sub_args) > 2 else None
            
            try:
                role = int(role_str)
                command = int(command_str)
                
                # Parse data if provided
                data = None
                if data_str:
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        # If not JSON, treat as string
                        data = data_str
                
                # Create TLV format payload according to ESP RainMaker spec
                import uuid
                request_id = str(uuid.uuid4())[:22]  # 22 character request ID
                
                payload = {
                    "1": request_id,  # T:1 - Request ID
                    "2": role,        # T:2 - Role (1=admin, 2=primary, 4=secondary)
                    "5": command      # T:5 - Command
                }
                
                if data:
                    payload["6"] = data  # T:6 - Command data (optional)
                
                # Publish to all nodes using official ESP RainMaker topic
                success_count = 0
                nodes = self.manager.get_connected_nodes()
                
                for node_id in nodes:
                    try:
                        topic = f"node/{node_id}/to-node"
                        payload_json = json.dumps(payload)
                        await self.manager.publish_to_node(node_id, topic, payload_json)
                        success_count += 1
                    except Exception as e:
                        click.echo(click.style(f"Failed to send to {node_id}: {str(e)}", fg='red'))
                        
                click.echo(click.style(f"Sent TLV command (role {role}, cmd {command}) to {success_count} nodes", fg='green'))
                click.echo(f"Topic: node/<node_id>/to-node")
                click.echo(f"Request ID: {request_id}")
                click.echo("Background monitoring active for responses on 'from-node' topic...")
                click.echo(f"Payload: {json.dumps(payload, indent=2)}")
                
            except ValueError:
                click.echo(click.style(f"Invalid role or command: {role_str} {command_str}", fg='red'))
                click.echo("Role must be 1 (admin), 2 (primary), or 4 (secondary)")
                click.echo("Command must be a number (0=get pending, 16=upload, 17=download, 20=confirm)")
            except Exception as e:
                click.echo(click.style(f"Error: {str(e)}", fg='red'))

        else:
            click.echo(click.style(f"Unknown COMMAND command: {subcommand}", fg='red'))
            click.echo("Available commands: send-command")
            click.echo("Type 'help command' for detailed information.")

    def _auto_convert_value(self, value: str):
        """Auto-detect and convert parameter value type."""
        # Try boolean first
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true'
            
        # Try integer
        try:
            if '.' not in value:
                return int(value)
        except ValueError:
            pass
            
        # Try float
        try:
            return float(value)
        except ValueError:
            pass
            
        # Default to string
        return value

    async def _handle_exit(self, args: List[str]):
        """Exit the shell."""
        click.echo("Goodbye!")
        self.running = False
        
    async def _handle_clear(self, args: List[str]):
        """Clear the screen."""
        os.system('clear' if os.name == 'posix' else 'cls')

async def start_interactive_shell(manager):
    """Start the interactive shell with the given manager."""
    shell = PersistentShell(manager)
    await shell.run() 