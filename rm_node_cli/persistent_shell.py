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
import logging
import readline
from datetime import datetime
from typing import Optional, List, Dict, Any, Set
from pathlib import Path

# Shell-based CLI - no individual command modules needed
# All functionality is built into the shell sections

# Get logger for debug logging
logger = logging.getLogger("mqtt_cli.persistent_shell")

class PersistentShell:
    """Interactive shell for managing MQTT nodes with persistent session management."""
    
    def __init__(self, manager, config_dir: str = None):
        self.manager = manager
        self.running = True
        self.target_node_ids: Optional[Set[str]] = None  # Store target node IDs if specified
        
        # Use config_dir parameter or default to user's home directory
        if config_dir is None:
            self.config_dir = Path.home() / '.rm-node'
        else:
            self.config_dir = Path(config_dir)
        
        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Session management - separated into two files
        self.active_config_file = self.config_dir / 'active_config.json'
        self.config_history_file = self.config_dir / 'config_history.json'
        
        # Response storage files for node responses
        self.node_responses_file = self.config_dir / 'node_responses.json'
        self.remote_params_file = self.config_dir / 'remote_params.json'
        
        # Initialize session management
        self._initialize_session_management()
        
        # Initialize response storage
        self._initialize_response_storage()
        
        # Initialize command history
        self._initialize_command_history()
        
        # Track default files for commands that accept file inputs
        # Get the configs directory - try multiple locations
        import os
        import sys
        
        # Try to find configs directory
        possible_paths = [
            'configs',  # Relative to current directory
            os.path.join(os.path.dirname(__file__), '..', 'configs'),  # Relative to package
            os.path.join(os.path.dirname(__file__), 'configs'),  # Inside package
        ]
        
        self.configs_dir = None
        for path in possible_paths:
            if os.path.exists(path) and os.path.isdir(path):
                self.configs_dir = os.path.abspath(path)
                break
        
        if self.configs_dir is None:
            # Fallback to current directory
            self.configs_dir = os.path.abspath('configs')
        
        # Initialize command history
        self.command_history = []
        self.history_file = self.config_dir / 'command_history.txt'
        self._initialize_command_history()
        
        self.default_files = {
            'config': os.path.join(self.configs_dir, 'light_config.json'),  # Default to light config
            'params': os.path.join(self.configs_dir, 'light_params.json'),  # Default to light params
            'init-params': os.path.join(self.configs_dir, 'light_params.json'),  # Default to light params
            'group-params': os.path.join(self.configs_dir, 'light_params.json'),  # Default to light params
            'tsdata': os.path.join(self.configs_dir, 'tsdata.json'),        # Default time series data
            'simple_tsdata': os.path.join(self.configs_dir, 'simple_tsdata.json')  # Default simple time series data
        }
        
        # Organize commands by actual module sections (only publishing commands)
        self.command_sections = {
            'node': {
                'commands': ['config', 'params', 'init-params', 'group-params'],
                'description': 'Node configuration and parameter management',
                'module': 'node_config.py',
                'examples': [
                    'config light',
                    'params Light power=true brightness=75',
                    'init-params Light brightness=50',
                    'group-params Light power=false'
                ]
            },
            'ota': {
                'commands': ['fetch', 'send-ota-status', 'view-ota-jobs', 'view-ota-history', 'clear-ota-jobs'],
                'description': 'Over-The-Air update operations',
                'module': 'ota.py',
                'examples': [
                    'fetch 1.2.3',
                    'send-ota-status',
                    'view-ota-jobs',
                    'view-ota-history',
                    'clear-ota-jobs'
                ]
            },
            'tsdata': {
                'commands': ['tsdata', 'simple-tsdata'],
                'description': 'Time series data operations', 
                'module': 'time_series.py',
                'examples': [
                    'tsdata sensor_data.json',
                    'simple-tsdata temperature.json'
                ]
            },
            'user': {
                'commands': ['map', 'alert'],
                'description': 'User mapping and alert operations',
                'module': 'user_mapping.py',
                'examples': [
                    'map user123 secret_key_abc',
                    'alert "System maintenance scheduled"'
                ]
            },
            'command': {
                'commands': ['send-command'],
                'description': 'Device command operations (TLV protocol)',
                'module': 'command.py',
                'examples': [
                    'send-command --node-id node123 --json-payload "{\"Light\": {\"output\": true}}"'
                ]
            },
            'utility': {
                'commands': ['status', 'help', 'clear', 'disconnect', 'session-history', 'history', 'exit'],
                'description': 'Shell utility commands',
                'module': 'built-in',
                'examples': [
                    'status', 
                    'help',
                    'clear',
                    'disconnect',
                    'disconnect --node-id node123',
                    'session-history',
                    'history',
                    'exit'
                ]
            }
        }
        
        # Flattened command handlers - all commands are top-level
        self.command_handlers = {
            # NODE commands (flattened)
            'config': self._handle_config,
            'params': self._handle_params,
            'init-params': self._handle_init_params,
            'group-params': self._handle_group_params,
            
            # OTA commands (flattened)
            'fetch': self._handle_fetch,
            'send-ota-status': self._handle_send_ota_status,
            'view-ota-jobs': self._handle_ota_jobs,
            'view-ota-history': self._handle_ota_history,
            'clear-ota-jobs': self._handle_clear_ota_jobs,
            
            # TSDATA commands (flattened)
            'tsdata': self._handle_tsdata,
            'simple-tsdata': self._handle_simple_tsdata,
            
            # USER commands (flattened)
            'map': self._handle_map,
            'alert': self._handle_alert,
            
            # COMMAND commands (from command.py)
            'send-command': self._handle_send_command,
            
            # Utility commands
            'status': self._handle_status,
            'help': self._handle_help,
            'clear': self._handle_clear,
            'disconnect': self._handle_disconnect,
            'session-history': self._handle_session_history,
            'history': self._handle_history,
            'logs': self._handle_logs,
            'exit': self._handle_exit,
            'quit': self._handle_exit,
        }
        
    def _initialize_session_management(self):
        """Initialize session management by clearing active session and loading history."""
        import os
        
        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Clear active session on shell start
        self._clear_active_session()
        
        # Load connection history
        self._load_connection_history()
        
    def _clear_active_session(self):
        """Clear the active session file."""
        import json
        try:
            with open(self.active_config_file, 'w') as f:
                json.dump({
                    "session_start": int(time.time() * 1000),
                    "broker": self.manager.broker_url,
                    "cert_base_path": self._get_cert_base_path(),
                    "nodes": {}
                }, f, indent=2)
        except Exception as e:
            click.echo(click.style(f"Warning: Could not clear active session file: {str(e)}", fg='yellow'))
            
    def _load_connection_history(self):
        """Load connection history from file."""
        import json
        try:
            if self.config_history_file.exists():
                with open(self.config_history_file, 'r') as f:
                    self.connection_history = json.load(f)
            else:
                self.connection_history = {"nodes": {}}
        except Exception as e:
            click.echo(click.style(f"Warning: Could not load connection history: {str(e)}", fg='yellow'))
            self.connection_history = {"nodes": {}}
            
    def _save_connection_history(self):
        """Save connection history to file."""
        import json
        try:
            with open(self.config_history_file, 'w') as f:
                json.dump(self.connection_history, f, indent=2)
        except Exception as e:
            click.echo(click.style(f"Warning: Could not save connection history: {str(e)}", fg='yellow'))
            
    def _update_active_session(self, node_id: str, action: str):
        """Update active session with node connection/disconnection."""
        import json
        try:
            # Load current active session
            if self.active_config_file.exists():
                with open(self.active_config_file, 'r') as f:
                    active_session = json.load(f)
            else:
                active_session = {"session_start": int(time.time() * 1000), "nodes": {}}
            
            # Get node information from config.json
            node_info = self._get_node_info(node_id)
            
            # Update node status
            if action == "connect":
                active_session["nodes"][node_id] = {
                    "connected_at": int(time.time() * 1000),
                    "status": "connected",
                    "cert_path": node_info.get("cert_path", ""),
                    "key_path": node_info.get("key_path", "")
                }
            elif action == "disconnect":
                if node_id in active_session["nodes"]:
                    active_session["nodes"][node_id]["disconnected_at"] = int(time.time() * 1000)
                    active_session["nodes"][node_id]["status"] = "disconnected"
            
            # Save updated active session
            with open(self.active_config_file, 'w') as f:
                json.dump(active_session, f, indent=2)
                
        except Exception as e:
            click.echo(click.style(f"Warning: Could not update active session: {str(e)}", fg='yellow'))
            
    def _get_node_info(self, node_id: str) -> dict:
        """Get node information from config.json."""
        try:
            config_file = self.config_dir / 'config.json'
            if config_file.exists():
                with open(config_file, 'r') as f:
                    config = json.load(f)
                return config.get("nodes", {}).get(node_id, {})
        except Exception:
            return {}
            
    def _get_cert_base_path(self) -> str:
        """Get certificate base path from config.json."""
        try:
            config_file = self.config_dir / 'config.json'
            if config_file.exists():
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    return config.get("cert_path", "")
        except Exception:
            pass
        return ""
            
    def _update_connection_history(self, node_id: str, action: str):
        """Update connection history with node details."""
        timestamp = int(time.time() * 1000)
        
        # Get node information from config.json
        node_info = self._get_node_info(node_id)
        
        if node_id not in self.connection_history["nodes"]:
            self.connection_history["nodes"][node_id] = []
            
        if action == "connect":
            self.connection_history["nodes"][node_id].append({
                "action": "connected",
                "timestamp": timestamp,
                "session_id": self._get_session_id(),
                "cert_path": node_info.get("cert_path", ""),
                "key_path": node_info.get("key_path", ""),
                "broker": self.manager.broker_url,
                "cert_base_path": self._get_cert_base_path()
            })
        elif action == "disconnect":
            self.connection_history["nodes"][node_id].append({
                "action": "disconnected", 
                "timestamp": timestamp,
                "session_id": self._get_session_id(),
                "cert_path": node_info.get("cert_path", ""),
                "key_path": node_info.get("key_path", ""),
                "broker": self.manager.broker_url,
                "cert_base_path": self._get_cert_base_path()
            })
            
        # Save history
        self._save_connection_history()
        
    def _initialize_response_storage(self):
        """Initialize response storage files."""
        import json
        import os
        
        # Initialize node responses file
        if not os.path.exists(self.node_responses_file):
            try:
                with open(self.node_responses_file, 'w') as f:
                    json.dump({}, f, indent=2)
            except Exception as e:
                click.echo(click.style(f"Warning: Could not create node responses file: {str(e)}", fg='yellow'))
        
        # Initialize remote params file
        if not os.path.exists(self.remote_params_file):
            try:
                with open(self.remote_params_file, 'w') as f:
                    json.dump({}, f, indent=2)
            except Exception as e:
                click.echo(click.style(f"Warning: Could not create remote params file: {str(e)}", fg='yellow'))
                
    def _store_node_response(self, node_id: str, response_data: dict):
        """Store node response from node/+/to-node topic."""
        import json
        import os
        
        try:
            # Load existing responses
            if os.path.exists(self.node_responses_file):
                with open(self.node_responses_file, 'r') as f:
                    responses = json.load(f)
            else:
                responses = {}
            
            # Initialize node entry if not exists
            if node_id not in responses:
                responses[node_id] = []
            
            # Add new response with timestamp
            response_entry = {
                "timestamp": int(time.time() * 1000),
                "data": response_data
            }
            
            responses[node_id].append(response_entry)
            
            # Save updated responses
            with open(self.node_responses_file, 'w') as f:
                json.dump(responses, f, indent=2)
                
        except Exception as e:
            click.echo(click.style(f"Warning: Could not store node response: {str(e)}", fg='yellow'))
            
    def _store_remote_params(self, node_id: str, params_data: dict):
        """Store remote parameters from node/+/params/remote topic."""
        import json
        import os
        
        try:
            # Load existing remote params
            if os.path.exists(self.remote_params_file):
                with open(self.remote_params_file, 'r') as f:
                    remote_params = json.load(f)
            else:
                remote_params = {}
            
            # Initialize node entry if not exists
            if node_id not in remote_params:
                remote_params[node_id] = []
            
            # Add new params with timestamp
            params_entry = {
                "timestamp": int(time.time() * 1000),
                "data": params_data
            }
            
            remote_params[node_id].append(params_entry)
            
            # Save updated remote params
            with open(self.remote_params_file, 'w') as f:
                json.dump(remote_params, f, indent=2)
                
        except Exception as e:
            click.echo(click.style(f"Warning: Could not store remote params: {str(e)}", fg='yellow'))
    
    def _initialize_command_history(self):
        """Initialize command history functionality."""
        try:
            # Ensure the history directory exists
            history_dir = os.path.dirname(self.history_file)
            os.makedirs(history_dir, exist_ok=True)
            
            # Load existing command history
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    self.command_history = [line.strip() for line in f.readlines() if line.strip()]
                logger.debug(f"Loaded {len(self.command_history)} commands from history")
            else:
                self.command_history = []
                logger.debug("No command history found, starting fresh")
            
            # Configure readline for history
            readline.set_history_length(1000)  # Store up to 1000 commands
            
            # Load history into readline
            for command in self.command_history:
                readline.add_history(command)
                
        except Exception as e:
            logger.debug(f"Could not initialize command history: {str(e)}")
            self.command_history = []
    
    def _add_to_history(self, command: str):
        """Add a command to history."""
        if command.strip() and command.strip() not in self.command_history:
            self.command_history.append(command.strip())
            readline.add_history(command.strip())
            
            # Keep only last 1000 commands
            if len(self.command_history) > 1000:
                self.command_history = self.command_history[-1000:]
            
            # Save to file
            try:
                with open(self.history_file, 'w') as f:
                    for cmd in self.command_history:
                        f.write(f"{cmd}\n")
            except Exception as e:
                logger.debug(f"Could not save command history: {str(e)}")
    
    def _get_session_id(self):
        """Generate a session ID based on current session start time."""
        try:
            with open(self.active_config_file, 'r') as f:
                active_session = json.load(f)
                return active_session.get("session_start", int(time.time() * 1000))
        except:
            return int(time.time() * 1000)
            
    def _track_initial_connections(self):
        """Track initial connections for session management."""
        connected_nodes = self.manager.get_connected_nodes()
        for node_id in connected_nodes:
            # Update session management for initial connections
            self._update_active_session(node_id, "connect")
            self._update_connection_history(node_id, "connect")

    def _parse_node_ids(self, node_ids_str: str) -> Set[str]:
        """Parse and validate comma-separated node IDs."""
        if not node_ids_str:
            return set()
            
        # Remove any surrounding quotes and split by comma
        node_ids_str = node_ids_str.strip('"\'')
        node_ids = {node_id.strip().strip('"\'') for node_id in node_ids_str.split(',')}
        
        # Remove empty strings
        node_ids = {node_id for node_id in node_ids if node_id}
        
        # Validate against available nodes
        available_nodes = set(self.manager.get_connected_nodes())
        invalid_nodes = node_ids - available_nodes
        
        if invalid_nodes:
            raise ValueError(f"Invalid or unconnected node IDs: {', '.join(sorted(invalid_nodes))}")
            
        return node_ids

    def get_target_nodes(self) -> List[str]:
        """Get list of nodes to target based on --node-id flag."""
        if self.target_node_ids is None:
            # No specific nodes targeted, return all connected nodes
            nodes = self.manager.get_connected_nodes()
            logger.debug(f"No specific nodes targeted, using all connected nodes: {nodes}")
            return nodes
        logger.debug(f"Using specific target nodes: {list(self.target_node_ids)}")
        return list(self.target_node_ids)

    async def run(self):
        """Run the interactive shell."""
        # Start background connection maintenance
        await self.manager.start_background_connections()
        
        # Track initial connections for session management
        self._track_initial_connections()
        
        # Log debug mode status
        logger.debug("Interactive shell started")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Debug logging is enabled for interactive shell")
        
        # Display welcome message
        self._show_welcome()
        
        try:
            while self.running:
                try:
                    # Get user input with readline support
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
        finally:
            # Just stop background tasks, no need to disconnect MQTT
            await self.manager.stop_background_connections()
            
    def _show_welcome(self):
        """Display welcome message with simplified command overview."""
        connected_nodes = self.manager.get_connected_nodes()
        
        click.echo()
        click.echo(click.style(" RM-Node CLI", fg='green', bold=True))
        click.echo("=" * 40)
        click.echo(f"Connected: {click.style(f'{len(connected_nodes)} nodes', fg='cyan', bold=True)}")
        
        if connected_nodes:
            # Show just first few nodes to keep it clean
            display_nodes = connected_nodes[:3]
            for node_id in display_nodes:
                click.echo(f"  • {click.style(node_id, fg='cyan')}")
            if len(connected_nodes) > 3:
                click.echo(f"  • ... and {len(connected_nodes) - 3} more")
        
        click.echo()
        click.echo(click.style("Quick Start:", fg='blue', bold=True))
        click.echo("  help                Full command reference")
        click.echo("  status              Connection status")
        click.echo("  history             View command history")
        click.echo("  exit                Exit CLI")
        click.echo()
        click.echo(click.style("💡 Ready! Type 'help' to see all available commands", fg='yellow'))
        click.echo(click.style("💡 Use ↑/↓ arrows to navigate command history", fg='cyan'))
        click.echo("=" * 40)
        click.echo()
        
    async def _execute_command(self, command_line: str):
        """Parse and execute a command with section-aware routing."""
        logger.debug(f"Executing command: {command_line}")
        
        # Add command to history
        self._add_to_history(command_line)
        
        parts = command_line.split()
        if not parts:
            logger.debug("Empty command line, skipping")
            return
            
        # Handle global flags that can appear anywhere in the command line
        use_defaults = False  # Flag for --b option
        target_node_ids = None
        
        # First pass: extract global flags from anywhere in the command line
        filtered_parts = []
        i = 0
        while i < len(parts):
            if parts[i] == '--b':
                use_defaults = True
                logger.debug("--b flag detected, will use default/previous saved values")
                i += 1  # Skip this flag
            elif parts[i] == '--node-id' and i + 1 < len(parts):
                try:
                    # Handle the case where the node IDs are in quotes
                    node_ids_str = parts[i + 1]
                    if node_ids_str.startswith('"') and not node_ids_str.endswith('"'):
                        # Find the closing quote
                        for j in range(i + 2, len(parts)):
                            node_ids_str += ' ' + parts[j]
                            if parts[j].endswith('"'):
                                i = j  # Update i to skip the parts we've consumed
                                break
                    logger.debug(f"Parsing node IDs: {node_ids_str}")
                    target_node_ids = self._parse_node_ids(node_ids_str)
                    logger.debug(f"Target node IDs: {target_node_ids}")
                    i += 2  # Skip --node-id and its value
                except ValueError as e:
                    logger.debug(f"Error parsing node IDs: {str(e)}")
                    click.echo(click.style(f"Error: {str(e)}", fg='red'))
                    return
            else:
                filtered_parts.append(parts[i])
                i += 1
        
        # Now we have the command and args without global flags
        if not filtered_parts:
            logger.debug("No command found after filtering global flags")
            return
            
        command = filtered_parts[0].lower()
        args = filtered_parts[1:] if len(filtered_parts) > 1 else []
        logger.debug(f"Parsed command: {command}, args: {args}")
        
        # Store the global flags for command handlers to use
        self.use_defaults = use_defaults
        self.target_node_ids = target_node_ids
        
        if command in self.command_handlers:
            logger.debug(f"Found handler for command: {command}")
            await self.command_handlers[command](args)
            # Reset target_node_ids and use_defaults after command execution
            self.target_node_ids = None
            self.use_defaults = False
        else:
            logger.debug(f"Unknown command: {command}")
            click.echo(click.style(f"Unknown command: {command}", fg='red'))
            click.echo("Type 'help' for available sections and commands.")
                
    async def _handle_help(self, args: List[str]):
        """Handle help command with unified interface."""
        if not args:
            await self._show_unified_help()
        elif args[0] in self.command_sections:
            await self._show_section_help(args[0])
        else:
            await self._show_unified_help()
    
    async def _show_unified_help(self):
        """Show the unified, professional help interface."""
        click.echo()
        click.echo(click.style("RM-Node CLI — Command Reference", fg='blue', bold=True))
        click.echo("=" * 50)
        click.echo()
        
        click.echo(click.style("Global Options:", fg='yellow', bold=True))
        # click.echo("  --node-id TEXT     Optional: Comma-separated list of node IDs to target")
        click.echo("  --node-id TEXT     (Optional) Target specific nodes by comma-separated IDs; uses all nodes if not provided")
        click.echo("                     Example: --node-id 'node1,node2,node3'")
        click.echo("  --b                (Optional) Use default/previous saved values for command parameters")
        click.echo("                     Examples: config --b, --b config, params --b, --b params")
        click.echo()
        
        click.echo(click.style("┌─ NODE Commands", fg='green', bold=True))
        click.echo("  config                  Configure node")
        click.echo("  params                  View or update parameters")
        click.echo("  init-params             Initialize parameters")
        click.echo("  group-params            Manage grouped parameters")
        click.echo()
        
        click.echo(click.style("┌─ OTA Commands", fg='green', bold=True))
        click.echo("  fetch                   Fetch OTA image")
        click.echo("  send-ota-status         Send OTA status to nodes")
        click.echo("  view-ota-jobs           View stored active OTA jobs")
        click.echo("  view-ota-history        View completed OTA jobs with status")
        click.echo("  clear-ota-jobs          Clear stored OTA job data")
        click.echo()
            
        click.echo(click.style("┌─ TSDATA Commands", fg='green', bold=True))
        click.echo("  tsdata                  View raw data")
        click.echo("  simple-tsdata           View simplified data")
        click.echo()
        
        click.echo(click.style("┌─ USER Commands", fg='green', bold=True))
        click.echo("  map                     Map user to node")
        click.echo("  alert                   Manage alerts")
        click.echo()
        
        click.echo(click.style("┌─ DEVICE Commands", fg='green', bold=True))
        click.echo("  send-command            Send TLV command to device")
        click.echo()
        
        click.echo(click.style("┌─ UTILITIES", fg='cyan', bold=True))
        click.echo("  status                  Show connection status")
        click.echo("  help                    Show this help")
        click.echo("  logs                    Check logs for troubleshooting")
        click.echo("  disconnect              Disconnect from nodes (all or specific)")
        click.echo("  exit                    Exit CLI")
        click.echo()
        click.echo(click.style("💡 Use '<command> --help' for detailed command help", fg='yellow'))
        click.echo(click.style("💡 Use 'help utility' for detailed utility commands help", fg='yellow'))
        click.echo()
                
    async def _show_section_help(self, section: str):
        """Show detailed help for a specific section."""
        if section == 'node':
            click.echo()
            click.echo(click.style("┌─ NODE Commands Help", fg='green', bold=True))
            click.echo("Node configuration and parameter management")
            click.echo()
            click.echo(click.style("USAGE:", fg='yellow', bold=True))
            click.echo("  node config <device_type>")
            click.echo("  node params <device> <param>=<value> [<param2>=<value2>...]")
            click.echo("  node init-params <device> <param>=<value> [<param2>=<value2>...]")
            click.echo("  node group-params <device> <param>=<value> [<param2>=<value2>...]")
            click.echo()
            click.echo(click.style("PARAMETERS:", fg='blue', bold=True))
            click.echo("  device_type      light, heater, washer")
            click.echo("  device           Device name (e.g., Light, Heater, Washer)")
            click.echo("  param=value      Parameter assignments (auto-typed)")
            click.echo()
            click.echo(click.style("EXAMPLES:", fg='cyan', bold=True))
            click.echo("  node config light")
            click.echo("  node params Light brightness=75 power=true")
            click.echo("  node init-params Light brightness=50")
            click.echo("  node group-params Light power=false")
            click.echo()
            click.echo(click.style("MQTT TOPICS:", fg='magenta', bold=True))
            click.echo("  node/<node_id>/config")
            click.echo("  node/<node_id>/params/local")
            
        elif section == 'ota':
            click.echo()
            click.echo(click.style("┌─ OTA Commands Help", fg='green', bold=True))
            click.echo("Over-The-Air firmware update operations")
            click.echo()
            click.echo(click.style("USAGE:", fg='yellow', bold=True))
            click.echo("  fetch <version>              Request firmware download")
            click.echo("  send-ota-status [--job-id <id>] Send OTA status to nodes")
            click.echo("  view-ota-jobs [--node-id <id>]    View stored active OTA jobs")
            click.echo("  view-ota-history [--node-id <id>] View completed OTA jobs with status")
            click.echo("  clear-ota-jobs [--node-id <id>] Clear stored OTA job data")
            click.echo()
            click.echo(click.style("PARAMETERS:", fg='blue', bold=True))
            click.echo("  version          Firmware version (e.g., 1.2.3, 2.0.0)")
            click.echo("  job_id           Optional: Specific OTA job ID to send status for")
            click.echo("  node_id          Optional: Target specific node")
            click.echo()
            click.echo(click.style("EXAMPLES:", fg='cyan', bold=True))
            click.echo("  fetch 1.2.3")
            click.echo("  send-ota-status")
            click.echo("  send-ota-status --job-id job123")
            click.echo("  view-ota-jobs")
            click.echo("  view-ota-jobs --node-id node123")
            click.echo("  view-ota-history")
            click.echo("  view-ota-history --node-id node123")
            click.echo("  clear-ota-jobs")
            click.echo()
            click.echo(click.style("MQTT TOPICS:", fg='magenta', bold=True))
            click.echo("  node/<node_id>/otafetch    → Firmware download requests")
            click.echo("  node/<node_id>/otaurl      ← OTA URL responses (monitored)")
            click.echo("  node/<node_id>/otastatus   → Status updates")
            click.echo()
            click.echo(click.style("BEHAVIOR:", fg='white', bold=True))
            click.echo("  • fetch: Requests firmware download URLs from cloud")
            click.echo("  • send-ota-status: Sends 'success' status to nodes with active OTA jobs")
            click.echo("  • view-ota-jobs: View stored active OTA job information")
            click.echo("  • view-ota-history: View completed OTA jobs with their final status")
            click.echo("  • clear-ota-jobs: Clear stored OTA job data from both active and history")
            click.echo("  • Background monitoring automatically captures and stores OTA responses")
            click.echo("  • Jobs move to history when status is sent (except 'in-progress' status)")
            
        elif section == 'tsdata':
            click.echo()
            click.echo(click.style("┌─ TSDATA Commands Help", fg='green', bold=True))
            click.echo("Time series data operations")
            click.echo()
            click.echo(click.style("USAGE:", fg='yellow', bold=True))
            click.echo("  tsdata tsdata <json_file>")
            click.echo("  tsdata simple-tsdata <json_file>")
            click.echo()
            click.echo(click.style("PARAMETERS:", fg='blue', bold=True))
            click.echo("  json_file        Path to JSON file containing time series data")
            click.echo()
            click.echo(click.style("EXAMPLES:", fg='cyan', bold=True))
            click.echo("  tsdata tsdata sensor_data.json")
            click.echo("  tsdata simple-tsdata temperature.json")
            click.echo()
            click.echo(click.style("MQTT TOPICS:", fg='magenta', bold=True))
            click.echo("  node/<node_id>/tsdata         → Complex time series format")
            click.echo("  node/<node_id>/simple_tsdata  → Simple time series format")
            
        elif section == 'user':
            click.echo()
            click.echo(click.style("┌─ USER Commands Help", fg='green', bold=True))
            click.echo("User mapping and alert operations")
            click.echo()
            click.echo(click.style("USAGE:", fg='yellow', bold=True))
            click.echo("  user map <user_id> <secret_key>")
            click.echo("  user alert <message>")
            click.echo()
            click.echo(click.style("PARAMETERS:", fg='blue', bold=True))
            click.echo("  user_id          Unique user identifier")
            click.echo("  secret_key       User's secret authentication key")
            click.echo("  message          Alert message text (can contain spaces)")
            click.echo()
            click.echo(click.style("EXAMPLES:", fg='cyan', bold=True))
            click.echo("  user map user123 secret_key_abc")
            click.echo("  user alert 'System maintenance at 3PM'")
            click.echo("  user alert \"Firmware update available\"")
            click.echo()
            click.echo(click.style("MQTT TOPICS:", fg='magenta', bold=True))
            click.echo("  node/<node_id>/user/mapping  → User mapping requests")
            click.echo("  node/<node_id>/alert         → Alert messages")
            
        elif section == 'command':
            click.echo()
            click.echo(click.style("┌─ DEVICE Commands Help", fg='green', bold=True))
            click.echo("Device command operations with TLV protocol")
            click.echo()
            click.echo(click.style("USAGE:", fg='yellow', bold=True))
            click.echo("  command send-command <role> <command> [<data>]")
            click.echo()
            click.echo(click.style("PARAMETERS:", fg='blue', bold=True))
            click.echo("  role            1=admin, 2=primary, 4=secondary")
            click.echo("  command         0=get pending, 16=upload, 17=download, 20=confirm")
            click.echo("  data            Optional JSON data (auto-detected)")
            click.echo()
            click.echo(click.style("EXAMPLES:", fg='cyan', bold=True))
            click.echo("  command send-command 1 0")
            click.echo("  command send-command 2 16 '{\"file\":\"firmware.bin\"}'")
            click.echo("  command send-command 1 20")
            click.echo()
            click.echo(click.style("MQTT TOPICS:", fg='magenta', bold=True))
            click.echo("  node/<node_id>/to-node    → TLV command requests")
            click.echo("  node/<node_id>/from-node  ← Command responses (monitored)")
            click.echo()
            click.echo(click.style("TLV FORMAT:", fg='white', bold=True))
            click.echo("  T:1 → Request ID (auto-generated)")
            click.echo("  T:2 → Role (1, 2, or 4)")
            click.echo("  T:5 → Command code")
            click.echo("  T:6 → Optional command data")
            
        elif section == 'utility':
            click.echo()
            click.echo(click.style("┌─ UTILITY Commands Help", fg='green', bold=True))
            click.echo("Shell utility commands")
            click.echo()
            click.echo(click.style("USAGE:", fg='yellow', bold=True))
            click.echo("  status")
            click.echo("  help")
            click.echo("  clear")
            click.echo("  disconnect [--node-id <node_id>]")
            click.echo("  session-history [--node-id <node_id>]")
            click.echo("  exit")
            click.echo()
            click.echo(click.style("PARAMETERS:", fg='blue', bold=True))
            click.echo("  node_id          Optional: Specific node(s) to disconnect from")
            click.echo()
            click.echo(click.style("EXAMPLES:", fg='cyan', bold=True))
            click.echo("  status")
            click.echo("  help")
            click.echo("  clear")
            click.echo("  disconnect")
            click.echo("  disconnect --node-id node123")
            click.echo("  disconnect --node-id 'node1,node2,node3'")
            click.echo("  session-history")
            click.echo("  session-history --node-id node123")
            click.echo("  exit")
            click.echo()
            click.echo(click.style("DESCRIPTION:", fg='white', bold=True))
            click.echo("  status: Show connection status and statistics")
            click.echo("  help: Show command help and examples")
            click.echo("  clear: Clear the terminal screen")
            click.echo("  disconnect: Disconnect from MQTT nodes (all or specific)")
            click.echo("  session-history: View connection session history")
            click.echo("  exit: Exit the CLI (automatically disconnects from all nodes)")
            
        else:
            click.echo(f"No detailed help available for '{section}'")
            click.echo("Available sections: node, ota, tsdata, user, command, utility")

    # Utility Commands
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
        
        # Default Files Status
        click.echo(click.style("Default Files:", fg='yellow', bold=True))
        click.echo("-" * 50)
        
        # Show all default files with their status
        # Order files in a logical way
        file_order = [
            ('config', 'config'),
            ('params', 'params'),
            ('init-params', 'init-params'),
            ('group-params', 'group-params'),
            ('tsdata', 'tsdata'),
            ('simple_tsdata', 'simple-tsdata')
        ]
        
        for command_type, display_name in file_order:
            file_path = self.default_files[command_type]
            exists = os.path.exists(file_path)
            status = click.style("✓", fg='green') if exists else click.style("✗", fg='red')
            # Extract device type from filename for display
            device_type = os.path.splitext(os.path.basename(file_path))[0].split('_')[0]
            click.echo(f"  {display_name:15} → {file_path} ({device_type}) {status}")
        click.echo()
        
        # Monitored topics
        monitored_topics = [
            "params/remote",      # Parameter responses from nodes
            "otaurl",            # OTA URL responses from nodes
            "to-node",           # Command requests to nodes (we monitor)
        ]
        
        click.echo(click.style("Monitored Topics (per node):",fg='yellow',bold=True))
        for topic in monitored_topics:
            full_topic = f"node/+/{topic}"
            click.echo(f"  - {click.style(full_topic, fg='yellow')}")
        click.echo()
        
        # Topic descriptions
        topic_descriptions = {
            "params/remote": "Parameter responses from nodes",
            "otaurl": "OTA firmware download URLs from nodes", 
            "to-node": "Command requests sent from cloud to nodes",
        }
        
        for topic, description in topic_descriptions.items():
            click.echo(f"  {click.style(topic, fg='yellow'):15} - {description}")
        click.echo()
        
        # Statistics
        total_subscriptions = len(nodes) * len(monitored_topics)
        click.echo(click.style("Statistics:", fg='yellow', bold=True))
        click.echo(f"  Total subscriptions: {click.style(str(total_subscriptions), fg='green')}")
        click.echo(f"  Topics per node: {click.style(str(len(monitored_topics)), fg='green')}")
        click.echo()
        
        # OTA Jobs Status (Active jobs only)
        ota_jobs = self.manager.get_ota_jobs()
        total_ota_jobs = sum(len(jobs) for jobs in ota_jobs.values())
        nodes_with_ota_jobs = len([node for node, jobs in ota_jobs.items() if jobs])
        
        # OTA Status History
        ota_history = self.manager.get_ota_status_history()
        total_history_jobs = sum(len(jobs) for jobs in ota_history.values())
        nodes_with_history = len([node for node, jobs in ota_history.items() if jobs])
        
        click.echo(click.style("OTA Jobs Status:", fg='yellow', bold=True))
        click.echo("-" * 50)
        click.echo(f"  Active OTA jobs: {click.style(str(total_ota_jobs), fg='green')}")
        click.echo(f"  Nodes with active jobs: {click.style(str(nodes_with_ota_jobs), fg='green')}")
        if ota_jobs:
            click.echo("  Nodes with active jobs:")
            for node_id, jobs in ota_jobs.items():
                if jobs:
                    click.echo(f"    • {click.style(node_id, fg='cyan')}: {len(jobs)} job(s)")
        else:
            click.echo("  No active OTA jobs")
        click.echo()
        
        click.echo(click.style("OTA Status History:", fg='yellow', bold=True))
        click.echo("-" * 50)
        click.echo(f"  Completed OTA jobs: {click.style(str(total_history_jobs), fg='green')}")
        click.echo(f"  Nodes with history: {click.style(str(nodes_with_history), fg='green')}")
        if ota_history:
            click.echo("  Nodes with completed jobs:")
            for node_id, jobs in ota_history.items():
                if jobs:
                    click.echo(f"    • {click.style(node_id, fg='cyan')}: {len(jobs)} job(s)")
        else:
            click.echo("  No completed OTA jobs")
        click.echo()

    def _infer_device_type(self, filename: str) -> str:
        """Infer device type from filename.
        
        Args:
            filename: Name of the file
            
        Returns:
            Inferred device type or None if can't be determined
        """
        # Remove path and extension
        basename = os.path.splitext(os.path.basename(filename))[0]
        basename = basename.lower()
        
        # Try to match device types
        device_types = {
            'light': ['light', 'lamp', 'lgt'],
            'heater': ['heat', 'heater', 'hot'],
            'washer': ['wash', 'wsh', 'washer']
        }
        
        for device_type, patterns in device_types.items():
            if any(pattern in basename for pattern in patterns):
                return device_type
                
        return None

    async def _handle_config(self, args: List[str]):
        """Handle config command: config --device-type <type> [--config-file <file>]"""
        logger.debug(f"Handling config command with args: {args}")
        
        if any(a in args for a in ['help', '--help', '-h']):
            logger.debug("Showing config help")
            click.echo()
            click.echo("Usage: rmnode config [OPTIONS]")
            click.echo()
            click.echo("  Configure all connected nodes as specified device type.")
            click.echo("  When --device-type or --config-file is used, it automatically becomes the new default.")
            click.echo()

            click.echo()
            click.echo("Options:")
            click.echo("  --device-type TEXT    Device type to configure (light, heater, washer)")
            click.echo("                        If not provided, uses current default configuration")
            click.echo("  --config-file PATH    Optional JSON file containing configuration")
            click.echo("                        Device type will be taken from filename")
            click.echo("  --help                Show this message and exit")
            click.echo()
            click.echo("  Examples:")
            click.echo("      # Use current default configuration")
            click.echo("      rmnode config")
            click.echo()
            click.echo("      # Switch to heater configuration (becomes new default)")
            click.echo("      rmnode config --device-type heater")
            click.echo()
            click.echo("      # Use custom config file (becomes new default)")
            click.echo("      rmnode config --config-file wsh.json  # Uses 'wsh' as device type")
            click.echo()
            click.echo("MQTT Topic:")
            click.echo("  node/<node_id>/config")
            click.echo()
            return
            
        # Parse flags
        device_type = None
        config_file = None
        i = 0
        while i < len(args):
            if args[i] == '--device-type' and i+1 < len(args):
                device_type = args[i+1]
                logger.debug(f"Parsed device type: {device_type}")
                i += 2
            elif args[i] == '--config-file' and i+1 < len(args):
                config_file = args[i+1]
                logger.debug(f"Parsed config file: {config_file}")
                i += 2
            else:
                i += 1
                
        # If --b flag is set, force use of default config regardless of other parameters
        if hasattr(self, 'use_defaults') and self.use_defaults:
            config_file = self.default_files['config']
            device_type = os.path.basename(config_file).split('_')[0]
            logger.debug(f"--b flag detected, using default config: {config_file}, device type: {device_type}")
            if not os.path.exists(config_file):
                logger.debug(f"Default config file not found: {config_file}")
                click.echo(click.style("Error: Default config file not found", fg='red'))
                return
        # If no device type or config file provided and --b flag is not set, show help
        elif not device_type and not config_file:
            logger.debug("No parameters provided and --b flag not set")
            click.echo(click.style("Error: No device type or config file specified", fg='red'))
            click.echo("Use --device-type <type> or --config-file <file> to specify configuration")
            click.echo("Or use --b flag to use default configuration")
            return
                
        # If device type specified, use and set as default
        elif device_type:
            if device_type not in ['light', 'heater', 'washer']:
                logger.debug(f"Invalid device type: {device_type}")
                click.echo(click.style(f"Invalid device type: {device_type}", fg='red'))
                click.echo("Available types: light, heater, washer")
                return
            config_file = os.path.join(self.configs_dir, f"{device_type}_config.json")
            logger.debug(f"Using device type config file: {config_file}")
            if not os.path.exists(config_file):
                logger.debug(f"Config file not found: {config_file}")
                click.echo(click.style(f"Config file not found for {device_type}", fg='red'))
                return
            # Automatically update default when device type changes
            try:
                self._update_default_file('config', config_file)
                logger.debug(f"Updated default config file to: {config_file}")
                click.echo(click.style("✓ Updated default file for config", fg='green'))
            except ValueError as e:
                logger.debug(f"Could not update default file: {str(e)}")
                click.echo(click.style(f"Warning: Could not update default: {str(e)}", fg='yellow'))
                
        # If config file specified
        elif config_file:
            if not os.path.exists(config_file):
                logger.debug(f"Config file not found: {config_file}")
                click.echo(click.style(f"Config file not found: {config_file}", fg='red'))
                return
                
            # Extract device type from filename (without extension)
            device_type = os.path.splitext(os.path.basename(config_file))[0]
            logger.debug(f"Extracted device type from filename: {device_type}")
                
            # Automatically update default when config file changes
            try:
                self._update_default_file('config', config_file)
                logger.debug(f"Updated default config file to: {config_file}")
                click.echo(click.style("✓ Updated default file for config", fg='green'))
            except ValueError as e:
                logger.debug(f"Could not update default file: {str(e)}")
                click.echo(click.style(f"Warning: Could not update default: {str(e)}", fg='yellow'))
                
        logger.debug(f"Calling _node_config with device_type={device_type}, config_file={config_file}")
        # Call the config logic
        await self._node_config(device_type, config_file)

    async def _node_config(self, device_type: str, config_file: str):
        """Handle node config command."""
        # Get target nodes
        nodes = self.get_target_nodes()
        if not nodes:
            click.echo(click.style("No nodes available to configure", fg='yellow'))
            return
            
        logger.debug(f"Starting node configuration for {len(nodes)} nodes")
        logger.debug(f"Device type: {device_type}")
        logger.debug(f"Config file: {config_file}")
        
        click.echo(f"Configuring {len(nodes)} node(s) as {click.style(device_type, fg='cyan')} device...")
        
        # Load configuration from file
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            logger.debug(f"Loaded configuration from {config_file}")
        except Exception as e:
            logger.debug(f"Error reading config file {config_file}: {str(e)}")
            click.echo(click.style(f"Error reading config file: {str(e)}", fg='red'))
            return
            
        success_count = 0
        for node_id in nodes:
            try:
                logger.debug(f"Configuring node {node_id}")
                
                # Update node_id in config
                config['node_id'] = node_id
                config['device_type'] = device_type
                config['timestamp'] = int(time.time() * 1000)
                
                topic = f"node/{node_id}/config"
                logger.debug(f"Publishing to topic: {topic}")
                
                await self.manager.publish_to_node(node_id, topic, config)
                success_count += 1
                logger.debug(f"Successfully configured node {node_id}")
            except Exception as e:
                logger.debug(f"Failed to configure node {node_id}: {str(e)}")
                click.echo(click.style(f"Failed to configure {node_id}: {str(e)}", fg='red'))
                
        logger.debug(f"Configuration completed: {success_count}/{len(nodes)} nodes successful")
        if success_count > 0:
            click.echo(click.style(f"Successfully configured {success_count}/{len(nodes)} nodes as {device_type}", fg='green'))
        else:
            click.echo(click.style("Failed to configure any nodes", fg='red'))

    async def _handle_params(self, args: List[str]):
        """Handle params command: params --device <name> [--param key=value ...] [--params-file <file>]"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo(click.style("┌─ PARAMS Command Help", fg='green', bold=True))
            click.echo("Set device parameters on all connected nodes")
            click.echo("When --device or --params-file is used, it automatically becomes the new default.")
            click.echo()
            click.echo(click.style("USAGE:", fg='yellow', bold=True))
            click.echo("  params [--device <name>] [--param key=value ...] [--params-file <file>]")
            click.echo()
            click.echo(click.style("OPTIONS:", fg='blue', bold=True))
            click.echo("  --device           Device name (e.g., Light, Heater, Washer)")
            click.echo("                     If not provided, uses current default parameters")
            click.echo("  --param            Parameter assignment (repeatable)")
            click.echo("  --params-file      JSON file containing parameters")
            click.echo("                     Device type will be taken from filename")
            click.echo()
            click.echo(click.style("EXAMPLES:", fg='cyan', bold=True))
            click.echo("  # Use current default parameters")
            click.echo("  params")
            click.echo()
            click.echo("  # Switch to heater parameters (becomes new default)")
            click.echo("  params --device Heater")
            click.echo()
            click.echo("  # Using direct parameters")
            click.echo("  params --device Light --param brightness=75 --param power=true")
            click.echo()
            click.echo("  # Using custom parameter file (becomes new default)")
            click.echo("  params --params-file wsh.json  # Uses 'wsh' as device type")
            click.echo()
            click.echo(click.style("MQTT TOPIC:", fg='magenta', bold=True))
            click.echo("  node/<node_id>/params/local")
            click.echo()
            return
            
        device = None
        params = []
        params_file = None
        i = 0
        while i < len(args):
            if args[i] == '--device' and i+1 < len(args):
                device = args[i+1]
                i += 2
            elif args[i] == '--param' and i+1 < len(args):
                params.append(args[i+1])
                i += 2
            elif args[i] == '--params-file' and i+1 < len(args):
                params_file = args[i+1]
                i += 2
            else:
                i += 1
                
        # If --b flag is set, force use of default params regardless of other parameters
        if hasattr(self, 'use_defaults') and self.use_defaults:
            params_file = self.default_files['params']
            device = os.path.basename(params_file).split('_')[0].capitalize()
            logger.debug(f"--b flag detected, using default params: {params_file}, device: {device}")
            if not os.path.exists(params_file):
                click.echo(click.style("Error: Default params file not found", fg='red'))
                return
        # If no device or params file specified and --b flag is not set, show help
        elif not device and not params and not params_file:
            logger.debug("No parameters provided and --b flag not set")
            click.echo(click.style("Error: No device or parameters specified", fg='red'))
            click.echo("Use --device <name>, --param key=value, or --params-file <file> to specify parameters")
            click.echo("Or use --b flag to use default parameters")
            return
                
        # If device specified, use and set as default
        elif device:
            device_type = device.lower()
            if device_type not in ['light', 'heater', 'washer']:
                click.echo(click.style(f"Invalid device type: {device_type}", fg='red'))
                click.echo("Available types: light, heater, washer")
                return
                
            # If no params file provided, use device-specific one
            if not params_file and not params:
                params_file = os.path.join(self.configs_dir, f"{device_type}_params.json")
                if not os.path.exists(params_file):
                    click.echo(click.style(f"Params file not found for {device_type}", fg='red'))
                    return
                # Update default if different from current
                if params_file != self.default_files['params']:
                    try:
                        self._update_default_file('params', params_file)
                        click.echo(click.style("✓ Updated default file for params", fg='green'))
                    except ValueError as e:
                        click.echo(click.style(f"Warning: Could not update default: {str(e)}", fg='yellow'))
                    
        # If params file specified
        elif params_file:
            if not os.path.exists(params_file):
                click.echo(click.style(f"Params file not found: {params_file}", fg='red'))
                return
                
            # Extract device type from filename (without extension)
            device = os.path.splitext(os.path.basename(params_file))[0]
                
            # Update default if different from current
            if params_file != self.default_files['params']:
                try:
                    self._update_default_file('params', params_file)
                    click.echo(click.style("✓ Updated default file for params", fg='green'))
                except ValueError as e:
                    click.echo(click.style(f"Warning: Could not update default: {str(e)}", fg='yellow'))
                
        # Call the params logic with either direct params or file
        await self._node_params(device, params_file, params if not params_file else None)

    async def _handle_init_params(self, args: List[str]):
        """Handle init-params command: init-params --device <name> [--param key=value ...] [--params-file <file>]"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo(click.style("┌─ INIT-PARAMS Command Help", fg='green', bold=True))
            click.echo("Initialize device parameters on all connected nodes")
            click.echo("When --device or --params-file is used, it automatically becomes the new default.")
            click.echo()
            click.echo(click.style("USAGE:", fg='yellow', bold=True))
            click.echo("  init-params [--device <name>] [--param key=value ...] [--params-file <file>]")
            click.echo()
            click.echo(click.style("OPTIONS:", fg='blue', bold=True))
            click.echo("  --device           Device name (e.g., Light, Heater, Washer)")
            click.echo("                     If not provided, uses current default parameters")
            click.echo("  --param            Parameter assignment (repeatable)")
            click.echo("  --params-file      JSON file containing parameters")
            click.echo("                     Device type will be taken from filename")
            click.echo()
            click.echo(click.style("EXAMPLES:", fg='cyan', bold=True))
            click.echo("  # Use current default parameters")
            click.echo("  init-params")
            click.echo()
            click.echo("  # Switch to heater parameters (becomes new default)")
            click.echo("  init-params --device Heater")
            click.echo()
            click.echo("  # Using direct parameters")
            click.echo("  init-params --device Light --param brightness=50")
            click.echo()
            click.echo("  # Using custom parameter file (becomes new default)")
            click.echo("  init-params --params-file wsh.json  # Uses 'wsh' as device type")
            click.echo()
            click.echo(click.style("MQTT TOPIC:", fg='magenta', bold=True))
            click.echo("  node/<node_id>/params/local/init")
            click.echo()
            return
            
        device = None
        params = []
        params_file = None
        i = 0
        while i < len(args):
            if args[i] == '--device' and i+1 < len(args):
                device = args[i+1]
                i += 2
            elif args[i] == '--param' and i+1 < len(args):
                params.append(args[i+1])
                i += 2
            elif args[i] == '--params-file' and i+1 < len(args):
                params_file = args[i+1]
                i += 2
            else:
                i += 1
                
        # If --b flag is set, force use of default init-params regardless of other parameters
        if hasattr(self, 'use_defaults') and self.use_defaults:
            params_file = self.default_files['init-params']
            device = os.path.basename(params_file).split('_')[0].capitalize()
            logger.debug(f"--b flag detected, using default init-params: {params_file}, device: {device}")
            if not os.path.exists(params_file):
                click.echo(click.style("Error: Default params file not found", fg='red'))
                return
        # If no device or params file specified and --b flag is not set, show help
        elif not device and not params and not params_file:
            logger.debug("No parameters provided and --b flag not set")
            click.echo(click.style("Error: No device or parameters specified", fg='red'))
            click.echo("Use --device <name>, --param key=value, or --params-file <file> to specify parameters")
            click.echo("Or use --b flag to use default parameters")
            return
                
        # If device specified, use and set as default
        elif device:
            device_type = device.lower()
            if device_type not in ['light', 'heater', 'washer']:
                click.echo(click.style(f"Invalid device type: {device_type}", fg='red'))
                click.echo("Available types: light, heater, washer")
                return
                
            # If no params file provided, use device-specific one
            if not params_file and not params:
                params_file = os.path.join(self.configs_dir, f"{device_type}_params.json")
                if not os.path.exists(params_file):
                    click.echo(click.style(f"Params file not found for {device_type}", fg='red'))
                    return
                # Update default if different from current
                if params_file != self.default_files['init-params']:
                    try:
                        self._update_default_file('init-params', params_file)
                        click.echo(click.style("✓ Updated default file for init-params", fg='green'))
                    except ValueError as e:
                        click.echo(click.style(f"Warning: Could not update default: {str(e)}", fg='yellow'))
                    
        # If params file specified
        elif params_file:
            if not os.path.exists(params_file):
                click.echo(click.style(f"Params file not found: {params_file}", fg='red'))
                return
                
            # Extract device type from filename (without extension)
            device = os.path.splitext(os.path.basename(params_file))[0]
                
            # Update default if different from current
            if params_file != self.default_files['init-params']:
                try:
                    self._update_default_file('init-params', params_file)
                    click.echo(click.style("✓ Updated default file for init-params", fg='green'))
                except ValueError as e:
                    click.echo(click.style(f"Warning: Could not update default: {str(e)}", fg='yellow'))
                
        # Call the params logic with either direct params or file
        await self._node_params(device, params_file, params if not params_file else None, topic_suffix="params/local/init")

    async def _handle_group_params(self, args: List[str]):
        """Handle group-params command: group-params --device <name> [--param key=value ...] [--params-file <file>]"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo(click.style("┌─ GROUP-PARAMS Command Help", fg='green', bold=True))
            click.echo("Set group device parameters on all connected nodes")
            click.echo("When --device or --params-file is used, it automatically becomes the new default.")
            click.echo()
            click.echo(click.style("USAGE:", fg='yellow', bold=True))
            click.echo("  group-params [--device <name>] [--param key=value ...] [--params-file <file>]")
            click.echo()
            click.echo(click.style("OPTIONS:", fg='blue', bold=True))
            click.echo("  --device           Device name (e.g., Light, Heater, Washer)")
            click.echo("                     If not provided, uses current default parameters")
            click.echo("  --param            Parameter assignment (repeatable)")
            click.echo("  --params-file      JSON file containing parameters")
            click.echo("                     Device type will be taken from filename")
            click.echo()
            click.echo(click.style("EXAMPLES:", fg='cyan', bold=True))
            click.echo("  # Use current default parameters")
            click.echo("  group-params")
            click.echo()
            click.echo("  # Switch to heater parameters (becomes new default)")
            click.echo("  group-params --device Heater")
            click.echo()
            click.echo("  # Using direct parameters")
            click.echo("  group-params --device Light --param power=false")
            click.echo()
            click.echo("  # Using custom parameter file (becomes new default)")
            click.echo("  group-params --params-file wsh.json  # Uses 'wsh' as device type")
            click.echo()
            click.echo(click.style("MQTT TOPIC:", fg='magenta', bold=True))
            click.echo("  node/<node_id>/params/local/group")
            click.echo()
            return
            
        device = None
        params = []
        params_file = None
        i = 0
        while i < len(args):
            if args[i] == '--device' and i+1 < len(args):
                device = args[i+1]
                i += 2
            elif args[i] == '--param' and i+1 < len(args):
                params.append(args[i+1])
                i += 2
            elif args[i] == '--params-file' and i+1 < len(args):
                params_file = args[i+1]
                i += 2
            else:
                i += 1
                
        # If --b flag is set, force use of default group-params regardless of other parameters
        if hasattr(self, 'use_defaults') and self.use_defaults:
            params_file = self.default_files['group-params']
            device = os.path.basename(params_file).split('_')[0].capitalize()
            logger.debug(f"--b flag detected, using default group-params: {params_file}, device: {device}")
            if not os.path.exists(params_file):
                click.echo(click.style("Error: Default params file not found", fg='red'))
                return
        # If no device or params file specified and --b flag is not set, show help
        elif not device and not params and not params_file:
            logger.debug("No parameters provided and --b flag not set")
            click.echo(click.style("Error: No device or parameters specified", fg='red'))
            click.echo("Use --device <name>, --param key=value, or --params-file <file> to specify parameters")
            click.echo("Or use --b flag to use default parameters")
            return
                
        # If device specified, use and set as default
        elif device:
            device_type = device.lower()
            if device_type not in ['light', 'heater', 'washer']:
                click.echo(click.style(f"Invalid device type: {device_type}", fg='red'))
                click.echo("Available types: light, heater, washer")
                return
                
            # If no params file provided, use device-specific one
            if not params_file and not params:
                params_file = os.path.join(self.configs_dir, f"{device_type}_params.json")
                if not os.path.exists(params_file):
                    click.echo(click.style(f"Params file not found for {device_type}", fg='red'))
                    return
                # Update default if different from current
                if params_file != self.default_files['group-params']:
                    try:
                        self._update_default_file('group-params', params_file)
                        click.echo(click.style("✓ Updated default file for group-params", fg='green'))
                    except ValueError as e:
                        click.echo(click.style(f"Warning: Could not update default: {str(e)}", fg='yellow'))
                    
        # If params file specified
        elif params_file:
            if not os.path.exists(params_file):
                click.echo(click.style(f"Params file not found: {params_file}", fg='red'))
                return
                
            # Extract device type from filename (without extension)
            device = os.path.splitext(os.path.basename(params_file))[0]
                
            # Update default if different from current
            if params_file != self.default_files['group-params']:
                try:
                    self._update_default_file('group-params', params_file)
                    click.echo(click.style("✓ Updated default file for group-params", fg='green'))
                except ValueError as e:
                    click.echo(click.style(f"Warning: Could not update default: {str(e)}", fg='yellow'))
                
        # Call the params logic with either direct params or file
        await self._node_params(device, params_file, params if not params_file else None, topic_suffix="params/local/group")

    async def _node_params(self, device_name: str, params_file: str = None, direct_params: List[str] = None, topic_suffix: str = "params/local"):
        """Handle node params command.
        
        Args:
            device_name: Name of the device (Light, Heater, Washer)
            params_file: Optional path to params file
            direct_params: Optional list of param=value strings
            topic_suffix: Optional suffix for the MQTT topic
        """
        # Get target nodes
        nodes = self.get_target_nodes()
        if not nodes:
            click.echo(click.style("No nodes available", fg='yellow'))
            return
            
        # Parse parameters
        try:
            if params_file:
                # Load from file
                try:
                    with open(params_file, 'r') as f:
                        payload = json.load(f)
                except Exception as e:
                    click.echo(click.style(f"Error reading params file: {str(e)}", fg='red'))
                    return
            else:
                # Parse direct parameters
                device_params = {}
                for param_spec in direct_params:
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
            
            # Publish to target nodes
            payload_json = json.dumps(payload)
            
            success_count = 0
            for node_id in nodes:
                try:
                    topic = f"node/{node_id}/{topic_suffix}"
                    await self.manager.publish_to_node(node_id, topic, payload_json)
                    success_count += 1
                except Exception as e:
                    click.echo(click.style(f"Failed to publish to {node_id}: {str(e)}", fg='red'))
            
            click.echo(click.style(f"Set parameters for {device_name} on {success_count}/{len(nodes)} nodes", fg='green'))
            click.echo(f"Payload: {json.dumps(payload, indent=2)}")
            
        except Exception as e:
            click.echo(click.style(f"✗ Error: {str(e)}", fg='red'))

    # OTA Commands (flattened)
    async def _handle_fetch(self, args: List[str]):
        """Handle fetch command: fetch --version <version>"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo("Usage: rmnode fetch [OPTIONS]")
            click.echo()
            click.echo("  Request firmware download from ESP RainMaker cloud.")
            click.echo()
            click.echo("  Background monitoring captures responses automatically.")
            click.echo()
            click.echo("Options:")
            click.echo("  --version TEXT    Firmware version to fetch (e.g., 1.2.3)  [required]")
            click.echo("  --help           Show this message and exit")
            click.echo()
            click.echo("  Examples:")
            click.echo("      # Request specific firmware version")
            click.echo("      rmnode fetch --version 1.2.3")
            click.echo()
            click.echo("MQTT Topics:")
            click.echo("  node/<node_id>/otafetch    → Firmware download requests")
            click.echo("  node/<node_id>/otaurl      ← OTA URL responses (monitored)")
            click.echo()
            return
        version = None
        i = 0
        while i < len(args):
            if args[i] == '--version' and i+1 < len(args):
                version = args[i+1]
                i += 2
            else:
                i += 1
        if not version:
            click.echo(click.style("Error: --version is required", fg='red'))
            return
        # Call the fetch logic (reuse previous logic)
        await self._handle_fetch_core(version)

    async def _handle_fetch_core(self, version):
        # Publish to target nodes using official ESP RainMaker topic
        nodes = self.get_target_nodes()
        if not nodes:
            click.echo(click.style("No nodes available", fg='yellow'))
            return
            
        success_count = 0
        click.echo(click.style(f"Sending OTA fetch request (v{version}) to {len(nodes)} nodes...", fg='blue'))
        click.echo(f"Topic: node/<node_id>/otafetch")
        click.echo("Watch for responses on monitored 'otaurl' topic...")
        
        for node_id in nodes:
            try:
                topic = f"node/{node_id}/otafetch"
                payload = {
                    "fw_version": version,
                    "timestamp": int(time.time() * 1000)
                }
                payload_json = json.dumps(payload)
                await self.manager.publish_to_node(node_id, topic, payload_json)
                success_count += 1
            except Exception as e:
                click.echo(click.style(f"Failed to send to {node_id}: {str(e)}", fg='red'))
        
        if success_count > 0:
            click.echo(click.style(f"Successfully sent OTA fetch request to {success_count}/{len(nodes)} nodes", fg='green'))
        else:
            click.echo(click.style("Failed to send OTA fetch request to any nodes", fg='red'))

    async def _handle_send_ota_status(self, args: List[str]):
        """Handle send-ota-status command: send-ota-status [--job-id <id>]"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo(click.style("┌─ SEND-OTA-STATUS Command Help", fg='green', bold=True))
            click.echo("Send OTA status to nodes with stored OTA jobs")
            click.echo()
            click.echo(click.style("USAGE:", fg='yellow', bold=True))
            click.echo("  send-ota-status [--job-id <id>]")
            click.echo()
            click.echo(click.style("OPTIONS:", fg='blue', bold=True))
            click.echo("  --job-id TEXT     Optional: Specific OTA job ID to send status for")
            click.echo("                     If not provided, sends 'success' to all nodes with stored jobs")
            click.echo("  --help            Show this message and exit")
            click.echo()
            click.echo(click.style("EXAMPLES:", fg='cyan', bold=True))
            click.echo("  # Send 'success' status to all nodes with stored OTA jobs")
            click.echo("  send-ota-status")
            click.echo()
            click.echo("  # Send 'success' status for specific job ID")
            click.echo("  send-ota-status --job-id SjkorPDgo9Y7pZfPLAuuNc")
            click.echo()
            click.echo(click.style("BEHAVIOR:", fg='white', bold=True))
            click.echo("  • Without --job-id: Sends 'success' status to all nodes that have stored OTA jobs")
            click.echo("  • With --job-id: Sends 'success' status only to nodes that have the specific job ID")
            click.echo("  • Status is always 'success' (hardcoded for simplicity)")
            click.echo()
            click.echo(click.style("MQTT TOPIC:", fg='magenta', bold=True))
            click.echo("  node/<node_id>/otastatus")
            click.echo()
            return
        
        # Parse job_id if provided
        job_id = None
        i = 0
        while i < len(args):
            if args[i] == '--job-id' and i+1 < len(args):
                job_id = args[i+1]
                i += 2
            else:
                i += 1
        
        # Call the send OTA status logic
        await self._handle_send_ota_status_core(job_id)

    async def _handle_send_ota_status_core(self, job_id: Optional[str] = None):
        """Send OTA status to nodes with stored OTA jobs."""
        # Get stored OTA jobs (only active jobs)
        all_ota_jobs = self.manager.get_ota_jobs()
        
        if not all_ota_jobs:
            click.echo(click.style("No active OTA jobs found", fg='yellow'))
            click.echo("Use 'view-ota-jobs' to view active OTA jobs")
            return
        
        # Determine which nodes to send status to
        target_nodes = []
        
        if job_id:
            # Send status only to nodes that have the specific job ID
            for node_id, jobs in all_ota_jobs.items():
                if job_id in jobs:
                    target_nodes.append(node_id)
            
            if not target_nodes:
                click.echo(click.style(f"No nodes found with OTA job ID: {job_id}", fg='yellow'))
                click.echo("Use 'view-ota-jobs' to view available job IDs")
                return
                
            click.echo(f"Sending 'success' status for job ID '{job_id}' to {len(target_nodes)} node(s)...")
        else:
            # Send status to all nodes that have any stored OTA jobs
            target_nodes = [node_id for node_id, jobs in all_ota_jobs.items() if jobs]
            
            if not target_nodes:
                click.echo(click.style("No nodes with active OTA jobs found", fg='yellow'))
                return
                
            click.echo(f"Sending 'success' status to {len(target_nodes)} node(s) with active OTA jobs...")
        
        # Send status to target nodes
        success_count = 0
        status = "success"  # Hardcoded to 'success' as requested
        
        for node_id in target_nodes:
            try:
                # Get the actual job ID to use
                actual_job_id = job_id if job_id else list(all_ota_jobs[node_id].keys())[0]
                
                # Prepare payload
                payload = {
                    "status": status,
                    "ota_job_id": actual_job_id,
                    "timestamp": int(time.time() * 1000)
                }
                
                # Publish to OTA status topic
                topic = f"node/{node_id}/otastatus"
                await self.manager.publish_to_node(node_id, topic, json.dumps(payload))
                
                # Move job to history (except for in-progress status)
                if status != "in-progress":
                    self.manager.move_ota_job_to_history(node_id, actual_job_id, status)
                    click.echo(click.style(f"✓ Sent '{status}' status to node {node_id} (moved to history)", fg='green'))
                else:
                    click.echo(click.style(f"✓ Sent '{status}' status to node {node_id} (kept active)", fg='green'))
                
                success_count += 1
                
            except Exception as e:
                click.echo(click.style(f"✗ Failed to send status to node {node_id}: {str(e)}", fg='red'))
        
        # Summary
        click.echo()
        click.echo(click.style(f"Successfully sent OTA status to {success_count}/{len(target_nodes)} nodes", fg='green'))
        click.echo(f"Status: {status}")
        click.echo(f"Job ID: {job_id if job_id else 'auto-selected'}")
        click.echo(f"Topic: node/<node_id>/otastatus")
        if status != "in-progress":
            click.echo(f"Jobs moved to history: {success_count}")
        else:
            click.echo(f"Jobs kept active: {success_count}")

    async def _handle_ota_jobs(self, args: List[str]):
        """Handle view-ota-jobs command: view-ota-jobs [--node-id <node_id>]"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo(click.style("┌─ VIEW-OTA-JOBS Command Help", fg='green', bold=True))
            click.echo("View stored active OTA job information")
            click.echo()
            click.echo(click.style("USAGE:", fg='yellow', bold=True))
            click.echo("  view-ota-jobs [--node-id <node_id>]")
            click.echo()
            click.echo(click.style("OPTIONS:", fg='blue', bold=True))
            click.echo("  --node-id TEXT    Optional: Show jobs for specific node only")
            click.echo("  --help            Show this message and exit")
            click.echo()
            click.echo(click.style("EXAMPLES:", fg='cyan', bold=True))
            click.echo("  # Show all OTA jobs")
            click.echo("  view-ota-jobs")
            click.echo()
            click.echo("  # Show OTA jobs for specific node")
            click.echo("  view-ota-jobs --node-id node123")
            click.echo()
            return
            
        # Parse node_id if provided
        node_id = None
        i = 0
        while i < len(args):
            if args[i] == '--node-id' and i+1 < len(args):
                node_id = args[i+1]
                i += 2
            else:
                i += 1
                
        # Get OTA jobs
        ota_jobs = self.manager.get_ota_jobs(node_id)
        
        if not ota_jobs:
            if node_id:
                click.echo(click.style(f"No OTA jobs found for node {node_id}", fg='yellow'))
            else:
                click.echo(click.style("No OTA jobs found", fg='yellow'))
            return
            
        # Display OTA jobs
        click.echo()
        click.echo(click.style("📋 Stored OTA Jobs", fg='blue', bold=True))
        click.echo("=" * 60)
        
        total_jobs = 0
        for node_id, jobs in ota_jobs.items():
            if not jobs:
                continue
                
            click.echo()
            click.echo(click.style(f"Node: {node_id}", fg='cyan', bold=True))
            click.echo("-" * 40)
            
            for job_id, job_info in jobs.items():
                total_jobs += 1
                click.echo(f"Job ID: {click.style(job_id, fg='yellow')}")
                click.echo(f"Received: {job_info.get('received_at', 'Unknown')}")
                click.echo(f"Firmware Version: {job_info.get('fw_version', 'Unknown')}")
                click.echo(f"File Size: {job_info.get('file_size', 'Unknown')} bytes")
                click.echo(f"File MD5: {job_info.get('file_md5', 'Unknown')}")
                if 'url' in job_info:
                    url = job_info['url']
                    # Truncate long URLs for display
                    if len(url) > 80:
                        url = url[:77] + "..."
                    click.echo(f"Download URL: {url}")
                click.echo()
                
        click.echo(f"Total OTA jobs: {click.style(str(total_jobs), fg='green')}")
        click.echo("=" * 60)

    async def _handle_ota_history(self, args: List[str]):
        """Handle view-ota-history command: view-ota-history [--node-id <node_id>]"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo(click.style("┌─ VIEW-OTA-HISTORY Command Help", fg='green', bold=True))
            click.echo("View completed OTA jobs with their final status")
            click.echo()
            click.echo(click.style("USAGE:", fg='yellow', bold=True))
            click.echo("  view-ota-history [--node-id <node_id>]")
            click.echo()
            click.echo(click.style("OPTIONS:", fg='blue', bold=True))
            click.echo("  --node-id TEXT    Optional: Show history for specific node only")
            click.echo("  --help            Show this message and exit")
            click.echo()
            click.echo(click.style("EXAMPLES:", fg='cyan', bold=True))
            click.echo("  # Show all completed OTA jobs")
            click.echo("  view-ota-history")
            click.echo()
            click.echo("  # Show completed OTA jobs for specific node")
            click.echo("  view-ota-history --node-id node123")
            click.echo()
            return
            
        # Parse node_id if provided
        node_id = None
        i = 0
        while i < len(args):
            if args[i] == '--node-id' and i+1 < len(args):
                node_id = args[i+1]
                i += 2
            else:
                i += 1
                
        # Get OTA history
        ota_history = self.manager.get_ota_status_history(node_id)
        
        if not ota_history:
            if node_id:
                click.echo(click.style(f"No completed OTA jobs found for node {node_id}", fg='yellow'))
            else:
                click.echo(click.style("No completed OTA jobs found", fg='yellow'))
            return
            
        # Display OTA history
        click.echo()
        click.echo(click.style("📋 Completed OTA Jobs History", fg='blue', bold=True))
        click.echo("=" * 60)
        
        total_jobs = 0
        for node_id, jobs in ota_history.items():
            if not jobs:
                continue
                
            click.echo()
            click.echo(click.style(f"Node: {node_id}", fg='cyan', bold=True))
            click.echo("-" * 40)
            
            for job_id, job_info in jobs.items():
                total_jobs += 1
                status = job_info.get('ota_status', 'Unknown')
                status_color = 'green' if status == 'success' else 'red' if status == 'failed' else 'yellow'
                
                click.echo(f"Job ID: {click.style(job_id, fg='yellow')}")
                click.echo(f"Status: {click.style(status, fg=status_color, bold=True)}")
                click.echo(f"Received: {job_info.get('received_at', 'Unknown')}")
                click.echo(f"Completed: {job_info.get('status_received_at', 'Unknown')}")
                click.echo(f"Firmware Version: {job_info.get('fw_version', 'Unknown')}")
                click.echo(f"File Size: {job_info.get('file_size', 'Unknown')} bytes")
                click.echo(f"File MD5: {job_info.get('file_md5', 'Unknown')}")
                if 'url' in job_info:
                    url = job_info['url']
                    # Truncate long URLs for display
                    if len(url) > 80:
                        url = url[:77] + "..."
                    click.echo(f"Download URL: {url}")
                click.echo()
                
        click.echo(f"Total completed OTA jobs: {click.style(str(total_jobs), fg='green')}")
        click.echo("=" * 60)

    async def _handle_clear_ota_jobs(self, args: List[str]):
        """Handle clear-ota-jobs command: clear-ota-jobs [--node-id <node_id>]"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo(click.style("┌─ CLEAR-OTA-JOBS Command Help", fg='green', bold=True))
            click.echo("Clear stored OTA job data from both active and history")
            click.echo()
            click.echo(click.style("USAGE:", fg='yellow', bold=True))
            click.echo("  clear-ota-jobs [--node-id <node_id>]")
            click.echo()
            click.echo(click.style("OPTIONS:", fg='blue', bold=True))
            click.echo("  --node-id TEXT    Optional: Clear jobs for specific node only")
            click.echo("  --help            Show this message and exit")
            click.echo()
            click.echo(click.style("EXAMPLES:", fg='cyan', bold=True))
            click.echo("  # Clear all OTA jobs")
            click.echo("  clear-ota-jobs")
            click.echo()
            click.echo("  # Clear OTA jobs for specific node")
            click.echo("  clear-ota-jobs --node-id node123")
            click.echo()
            return
            
        # Parse node_id if provided
        node_id = None
        i = 0
        while i < len(args):
            if args[i] == '--node-id' and i+1 < len(args):
                node_id = args[i+1]
                i += 2
            else:
                i += 1
                
        # Confirm action
        if node_id:
            confirm = input(f"Are you sure you want to clear OTA jobs for node {node_id}? (y/N): ").strip().lower()
            if confirm != 'y':
                click.echo("Operation cancelled")
                return
        else:
            confirm = input("Are you sure you want to clear ALL OTA jobs? (y/N): ").strip().lower()
            if confirm != 'y':
                click.echo("Operation cancelled")
                return
                
        # Clear OTA jobs from both active and history
        self.manager.clear_ota_jobs(node_id)
        
        # Also clear history if clearing all or specific node
        if node_id:
            # Clear history for specific node
            history = self.manager.get_ota_status_history()
            if node_id in history:
                del history[node_id]
                self.manager._save_ota_status_history()
            click.echo(click.style(f"✓ Cleared OTA jobs and history for node {node_id}", fg='green'))
        else:
            # Clear all history
            self.manager.ota_status_history = {}
            self.manager._save_ota_status_history()
            click.echo(click.style("✓ Cleared all OTA jobs and history", fg='green'))

    # TSDATA Commands (flattened)
    def _update_default_file(self, command_type: str, file_path: str) -> None:
        """Update the default file for a command type.
        
        Args:
            command_type: The type of command ('config', 'params', 'tsdata', 'simple_tsdata')
            file_path: Path to the new default file
        """
        if not os.path.exists(file_path):
            raise ValueError(f"File not found: {file_path}")
            
        if command_type not in self.default_files:
            raise ValueError(f"Invalid command type: {command_type}")
            
        self.default_files[command_type] = file_path
        click.echo(click.style(f"✓ Updated default file for {command_type}", fg='green'))

    async def _handle_tsdata(self, args: List[str]):
        """Handle tsdata command: tsdata [--json-file <file>]"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo("Usage: rmnode tsdata [OPTIONS]")
            click.echo()
            click.echo("  Send complex time series data to all connected nodes.")
            click.echo("  If no file is provided, uses the default tsdata file.")
            click.echo("  Device name will be taken from filename.")
            click.echo()

            click.echo()
            click.echo("Options:")
            click.echo("  --json-file PATH    JSON file containing time series data")
            click.echo("                      If not provided, uses default file")
            click.echo("  --help              Show this message and exit")
            click.echo()
            click.echo("  Examples:")
            click.echo("      # Use default tsdata file")
            click.echo("      rmnode tsdata")
            click.echo()
            click.echo("      # Use custom file (becomes new default)")
            click.echo("      rmnode tsdata --json-file wsh_data.json  # Uses 'wsh_data' as name")
            click.echo()
            click.echo("MQTT Topic:")
            click.echo("  node/<node_id>/tsdata")
            click.echo()
            return
            
        json_file = None
        i = 0
        while i < len(args):
            if args[i] == '--json-file' and i+1 < len(args):
                json_file = args[i+1]
                i += 2
            else:
                i += 1
                
        # If --b flag is set, force use of default tsdata file regardless of other parameters
        if hasattr(self, 'use_defaults') and self.use_defaults:
            json_file = self.default_files['tsdata']
            logger.debug(f"--b flag detected, using default tsdata: {json_file}")
            if not os.path.exists(json_file):
                click.echo(click.style("Error: Default tsdata file not found", fg='red'))
                return
        # If no file provided and --b flag is not set, show help
        elif not json_file:
            logger.debug("No file provided and --b flag not set")
            click.echo(click.style("Error: No JSON file specified", fg='red'))
            click.echo("Use --json-file <file> to specify a JSON file")
            click.echo("Or use --b flag to use default tsdata file")
            return
                
        # If file specified, update default
        elif not os.path.exists(json_file):
            click.echo(click.style(f"File not found: {json_file}", fg='red'))
            return
            
        # Update default if new file provided
        if json_file != self.default_files['tsdata']:
            try:
                self._update_default_file('tsdata', json_file)
                click.echo(click.style("✓ Updated default file for tsdata", fg='green'))
            except ValueError as e:
                click.echo(click.style(f"Warning: Could not update default: {str(e)}", fg='yellow'))
                
        await self._handle_tsdata_command('tsdata', json_file)

    async def _handle_simple_tsdata(self, args: List[str]):
        """Handle simple-tsdata command: simple-tsdata [--json-file <file>]"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo("Usage: rmnode simple-tsdata [OPTIONS]")
            click.echo()
            click.echo("  Send simple time series data to all connected nodes.")
            click.echo("  If no file is provided, uses the default simple tsdata file.")
            click.echo("  Device name will be taken from filename.")
            click.echo()

            click.echo()
            click.echo("Options:")
            click.echo("  --json-file PATH    JSON file containing simple time series data")
            click.echo("                      If not provided, uses default file")
            click.echo("  --help              Show this message and exit")
            click.echo()
            click.echo("  Examples:")
            click.echo("      # Use default simple tsdata file")
            click.echo("      rmnode simple-tsdata")
            click.echo()
            click.echo("      # Use custom file (becomes new default)")
            click.echo("      rmnode simple-tsdata --json-file wsh_data.json  # Uses 'wsh_data' as name")
            click.echo()
            click.echo("MQTT Topic:")
            click.echo("  node/<node_id>/simple_tsdata")
            click.echo()
            return
            
        json_file = None
        i = 0
        while i < len(args):
            if args[i] == '--json-file' and i+1 < len(args):
                json_file = args[i+1]
                i += 2
            else:
                i += 1
                
        # If --b flag is set, force use of default simple tsdata file regardless of other parameters
        if hasattr(self, 'use_defaults') and self.use_defaults:
            json_file = self.default_files['simple_tsdata']
            logger.debug(f"--b flag detected, using default simple tsdata: {json_file}")
            if not os.path.exists(json_file):
                click.echo(click.style("Error: Default simple tsdata file not found", fg='red'))
                return
        # If no file provided and --b flag is not set, show help
        elif not json_file:
            logger.debug("No file provided and --b flag not set")
            click.echo(click.style("Error: No JSON file specified", fg='red'))
            click.echo("Use --json-file <file> to specify a JSON file")
            click.echo("Or use --b flag to use default simple tsdata file")
            return
                
        # If file specified, update default
        elif not os.path.exists(json_file):
            click.echo(click.style(f"File not found: {json_file}", fg='red'))
            return
            
        # Update default if new file provided
        if json_file != self.default_files['simple_tsdata']:
            try:
                self._update_default_file('simple_tsdata', json_file)
                click.echo(click.style("✓ Updated default file for simple-tsdata", fg='green'))
            except ValueError as e:
                click.echo(click.style(f"Warning: Could not update default: {str(e)}", fg='yellow'))
                
        await self._handle_tsdata_command('simple-tsdata', json_file)

    async def _handle_tsdata_command(self, command_type: str, json_file: str):
        """Common handler for tsdata and simple-tsdata commands."""
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
                
            # Determine topic based on command type
            topic_suffix = "tsdata" if command_type == "tsdata" else "simple_tsdata"
            
            # Get target nodes
            nodes = self.get_target_nodes()
            if not nodes:
                click.echo(click.style("No nodes available", fg='yellow'))
                return
            
            # Get device name from filename
            device_name = os.path.splitext(os.path.basename(json_file))[0]
            
            # Publish to target nodes using the official ESP RainMaker topic
            success_count = 0
            
            for node_id in nodes:
                try:
                    topic = f"node/{node_id}/{topic_suffix}"
                    payload_json = json.dumps(data)
                    await self.manager.publish_to_node(node_id, topic, payload_json)
                    success_count += 1
                except Exception as e:
                    click.echo(click.style(f"Failed to send to {node_id}: {str(e)}", fg='red'))
            
            click.echo(click.style(f"Sent {device_name} time series data to {success_count}/{len(nodes)} nodes", fg='green'))
            click.echo(f"Topic: node/<node_id>/{topic_suffix}")
            click.echo(f"Data entries: {len(data) if isinstance(data, (list, dict)) else 'N/A'}")
            
        except FileNotFoundError:
            click.echo(click.style(f"File not found: {json_file}", fg='red'))
        except json.JSONDecodeError as e:
            click.echo(click.style(f"Invalid JSON in {json_file}: {str(e)}", fg='red'))
        except Exception as e:
            click.echo(click.style(f"Error: {str(e)}", fg='red'))

    # USER Commands (flattened)
    async def _handle_map(self, args: List[str]):
        """Handle map command: map --user-id <id> --secret-key <key>"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo("Usage: rmnode map [OPTIONS]")
            click.echo()
            click.echo("  Map a user to all connected nodes.")
            click.echo()

            click.echo()
            click.echo("Options:")
            click.echo("  --user-id TEXT      Unique user identifier  [required]")
            click.echo("  --secret-key TEXT   User's secret authentication key  [required]")
            click.echo("  --help              Show this message and exit")
            click.echo()
            click.echo("  Examples:")
            click.echo("      # Map user with credentials")
            click.echo("      rmnode map --user-id user123 --secret-key abc")
            click.echo()
            click.echo("MQTT Topic:")
            click.echo("  node/<node_id>/user/mapping")
            click.echo()
            return
        user_id = None
        secret_key = None
        i = 0
        while i < len(args):
            if args[i] == '--user-id' and i+1 < len(args):
                user_id = args[i+1]
                i += 2
            elif args[i] == '--secret-key' and i+1 < len(args):
                secret_key = args[i+1]
                i += 2
            else:
                i += 1
        if not user_id or not secret_key:
            click.echo(click.style("Error: --user-id and --secret-key are required", fg='red'))
            return
        await self._handle_map_core(user_id, secret_key)

    async def _handle_map_core(self, user_id, secret_key):
        nodes = self.get_target_nodes()
        if not nodes:
            click.echo(click.style("No nodes available", fg='yellow'))
            return
            
        payload = {
            "user_id": user_id,
            "secret_key": secret_key,
            "operation": "map",
            "timestamp": int(time.time() * 1000)
        }
        
        success_count = 0
        for node_id in nodes:
            try:
                await self.manager.publish_to_node(node_id, f"node/{node_id}/user/mapping", json.dumps(payload))
                success_count += 1
            except Exception as e:
                click.echo(click.style(f"Failed to map user to {node_id}: {str(e)}", fg='red'))
                
        click.echo(click.style(f"Mapped user {user_id} to {success_count}/{len(nodes)} nodes", fg='green'))

    async def _handle_alert(self, args: List[str]):
        """Handle alert command: alert --message <msg>"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo("Usage: rmnode alert [OPTIONS]")
            click.echo()
            click.echo("  Send alert message to all connected nodes.")
            click.echo()

            click.echo()
            click.echo("Options:")
            click.echo("  --message TEXT    Alert message text (can contain spaces)  [required]")
            click.echo("  --help           Show this message and exit")
            click.echo()
            click.echo("  Examples:")
            click.echo("      # Send maintenance alert")
            click.echo("      rmnode alert --message 'System maintenance at 3PM'")
            click.echo()
            click.echo("MQTT Topic:")
            click.echo("  node/<node_id>/alert")
            click.echo()
            return
        message = None
        i = 0
        while i < len(args):
            if args[i] == '--message' and i+1 < len(args):
                message = args[i+1]
                i += 2
            else:
                i += 1
        if not message:
            click.echo(click.style("Error: --message is required", fg='red'))
            return
        await self._handle_alert_core(message)

    async def _handle_alert_core(self, message):
        nodes = self.get_target_nodes()
        if not nodes:
            click.echo(click.style("No nodes available", fg='yellow'))
            return
            
        payload = {
            "message": message,
            "timestamp": int(time.time() * 1000),
            "type": "user_alert"
        }
        
        success_count = 0
        for node_id in nodes:
            try:
                await self.manager.publish_to_node(node_id, f"node/{node_id}/alert", json.dumps(payload))
                success_count += 1
            except Exception as e:
                click.echo(click.style(f"Failed to send alert to {node_id}: {str(e)}", fg='red'))
                
        click.echo(click.style(f"Sent user alert to {success_count}/{len(nodes)} nodes", fg='green'))
        click.echo(f"Message: '{click.style(message, fg='cyan')}'")

    # DEVICE Commands (flattened)
    async def _handle_send_command(self, args: list):
        """Handle send-command: send-command --json-payload <json|file> (sends to specified nodes as JSON)"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo("Usage: send-command --json-payload <json|file>")
            click.echo()
            click.echo("  Send command requests or responses from nodes to the cloud.")
            click.echo("  Publishes to node/<node_id>/from-node as JSON for specified nodes.")
            click.echo()
            click.echo("Options:")
            click.echo("  --json-payload TEXT JSON payload to send (as JSON) [required]")
            click.echo("  --node-id TEXT      Optional: Comma-separated list of node IDs to target")
            click.echo("  --help              Show this message and exit")
            click.echo()
            click.echo("Examples:")
            click.echo("  send-command --json-payload '{\"Light\": {\"output\": true}}'")
            click.echo("  send-command --json-payload /path/to/send_command.json")
            click.echo("  send-command --node-id 'node1,node2' --json-payload '{\"Light\": {\"output\": true}}'")
            click.echo()
            return
        json_payload = None
        i = 0
        while i < len(args):
            if args[i] == '--json-payload' and i+1 < len(args):
                json_payload = args[i+1]
                i += 2
            else:
                i += 1
        if not json_payload:
            click.echo(click.style("Error: --json-payload is required", fg='red'))
            return
            
        # Get target nodes
        nodes = self.get_target_nodes()
        if not nodes:
            click.echo(click.style("No nodes available", fg='yellow'))
            return
            
        # Try to load JSON from file if path exists, else parse as string
        try:
            if os.path.isfile(json_payload):
                with open(json_payload, 'r') as f:
                    payload_dict = json.load(f)
            else:
                payload_dict = json.loads(json_payload)
        except Exception as e:
            click.echo(click.style(f"✗ Invalid JSON: {str(e)}", fg='red'), err=True)
            return
            
        try:
            # Send command to target nodes
            success_count = 0
            json_payload_str = json.dumps(payload_dict)
            
            for node_id in nodes:
                try:
                    topic = f"node/{node_id}/from-node"
                    await self.manager.publish_to_node(node_id, topic, json_payload_str)
                    success_count += 1
                except Exception as e:
                    click.echo(click.style(f"Failed to send to {node_id}: {str(e)}", fg='red'))
                    
            click.echo(click.style(f"✓ Sent JSON command to {success_count}/{len(nodes)} nodes", fg='green'))
            click.echo(f"\nCommand Details:")
            click.echo("-" * 60)
            click.echo(f"Format: JSON")
            click.echo(f"JSON Size: {len(json_payload_str)} bytes")
            click.echo("\nOriginal JSON Payload:")
            click.echo(json.dumps(payload_dict, indent=2))
            click.echo("-" * 60)
            
        except Exception as e:
            click.echo(click.style(f"✗ Failed to send command: {str(e)}", fg='red'), err=True)
            return

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

    async def _handle_disconnect(self, args: List[str]):
        """Handle disconnect command: disconnect [--node-id <node_id>]"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo(click.style("┌─ DISCONNECT Command Help", fg='green', bold=True))
            click.echo("Disconnect from MQTT nodes")
            click.echo()
            click.echo(click.style("USAGE:", fg='yellow', bold=True))
            click.echo("  disconnect [--node-id <node_id>]")
            click.echo()
            click.echo(click.style("OPTIONS:", fg='blue', bold=True))
            click.echo("  --node-id TEXT    Optional: Disconnect from specific node(s)")
            click.echo("                     If not provided, disconnects from all nodes")
            click.echo("  --help            Show this message and exit")
            click.echo()
            click.echo(click.style("EXAMPLES:", fg='cyan', bold=True))
            click.echo("  # Disconnect from all nodes")
            click.echo("  disconnect")
            click.echo()
            click.echo("  # Disconnect from specific node")
            click.echo("  disconnect --node-id node123")
            click.echo()
            click.echo("  # Disconnect from multiple nodes")
            click.echo("  disconnect --node-id 'node1,node2,node3'")
            click.echo()
            click.echo(click.style("BEHAVIOR:", fg='white', bold=True))
            click.echo("  • Disconnects from MQTT broker gracefully")
            click.echo("  • Removes nodes from connection manager")
            click.echo("  • Can disconnect from specific nodes or all nodes")
            click.echo("  • Background monitoring stops for disconnected nodes")
            click.echo()
            return
            
        # Parse node_id if provided (disconnect has its own --node-id handling)
        node_id = None
        i = 0
        while i < len(args):
            if args[i] == '--node-id' and i+1 < len(args):
                node_id = args[i+1]
                i += 2
            else:
                i += 1
                
        # Get target nodes - use disconnect-specific logic, not global target_node_ids
        if node_id:
            try:
                target_nodes = self._parse_node_ids(node_id)
                if not target_nodes:
                    click.echo(click.style("No valid nodes specified", fg='yellow'))
                    return
            except ValueError as e:
                click.echo(click.style(f"Error: {str(e)}", fg='red'))
                return
        else:
            # Disconnect from all connected nodes (ignore global target_node_ids)
            target_nodes = self.manager.get_connected_nodes()
            
        if not target_nodes:
            click.echo(click.style("No nodes to disconnect", fg='yellow'))
            return
            
        click.echo(f"Disconnecting from {len(target_nodes)} node(s)...")
        
        # Disconnect from target nodes using manager method
        if node_id:
            # Disconnect from specific nodes
            success_count = 0
            failed_nodes = []
            
            for target_node in target_nodes:
                if target_node in self.manager.connections:
                    result = await self.manager._disconnect_single_node(target_node)
                    if result:
                        success_count += 1
                        # Update session management
                        self._update_active_session(target_node, "disconnect")
                        self._update_connection_history(target_node, "disconnect")
                        click.echo(click.style(f"✓ Disconnected from {target_node}", fg='green'))
                    else:
                        failed_nodes.append(target_node)
                        click.echo(click.style(f"✗ Failed to disconnect from {target_node}", fg='red'))
                else:
                    click.echo(click.style(f"Node {target_node} is not connected", fg='yellow'))
        else:
            # Disconnect from all nodes
            success_count, total_count = await self.manager.disconnect_all_nodes()
            click.echo(click.style(f"✓ Disconnected from {success_count}/{total_count} nodes", fg='green'))
            failed_nodes = []
        
        # Summary
        click.echo()
        click.echo(click.style(f"Disconnect Summary:", fg='yellow', bold=True))
        click.echo(f"  Successfully disconnected: {click.style(str(success_count), fg='green')}")
        click.echo(f"  Failed to disconnect: {click.style(str(len(failed_nodes)), fg='red')}")
        
        if failed_nodes:
            click.echo(f"  Failed nodes: {', '.join(failed_nodes)}")
        
        if success_count > 0:
            click.echo(click.style(f"✓ Disconnect operation completed", fg='green'))
        else:
            click.echo(click.style("✗ No nodes were disconnected", fg='red'))



    async def _handle_exit(self, args: List[str]):
        """Exit the shell."""
        # Disconnect from all nodes before exiting
        connected_nodes = self.manager.get_connected_nodes()
        if connected_nodes:
            click.echo(f"Disconnecting from {len(connected_nodes)} node(s) before exit...")
            
            # Use the manager's disconnect method
            success_count, total_count = await self.manager.disconnect_all_nodes()
            click.echo(click.style(f"✓ Disconnected from {success_count}/{total_count} nodes", fg='green'))
        
        # Clear active session at shell end
        self._clear_active_session()
        
        click.echo(click.style("RM-Node CLI session terminated successfully", fg='blue', bold=True))
        self.running = False
        
    async def _handle_session_history(self, args: List[str]):
        """Handle session-history command: session-history [--node-id <node_id>]"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo(click.style("┌─ SESSION-HISTORY Command Help", fg='green', bold=True))
            click.echo("View connection session history")
            click.echo()
            click.echo(click.style("USAGE:", fg='yellow', bold=True))
            click.echo("  session-history [--node-id <node_id>]")
            click.echo()
            click.echo(click.style("OPTIONS:", fg='blue', bold=True))
            click.echo("  --node-id TEXT    Optional: Show history for specific node only")
            click.echo("  --help            Show this message and exit")
            click.echo()
            click.echo(click.style("EXAMPLES:", fg='cyan', bold=True))
            click.echo("  # Show all session history")
            click.echo("  session-history")
            click.echo()
            click.echo("  # Show session history for specific node")
            click.echo("  session-history --node-id node123")
            click.echo()
            return
            
        # Parse node_id if provided
        node_id = None
        i = 0
        while i < len(args):
            if args[i] == '--node-id' and i+1 < len(args):
                node_id = args[i+1]
                i += 2
            else:
                i += 1
                
        # Display session history
        click.echo()
        click.echo(click.style("📋 Connection Session History", fg='blue', bold=True))
        click.echo("=" * 60)
        
        # Show session-level information if available
        if os.path.exists(self.active_config_file):
            try:
                with open(self.active_config_file, 'r') as f:
                    active_config = json.load(f)
                    broker = active_config.get('broker', '')
                    cert_base_path = active_config.get('cert_base_path', '')
                    if broker or cert_base_path:
                        click.echo(click.style("Session Information:", fg='yellow', bold=True))
                        if broker:
                            click.echo(f"  Broker: {broker}")
                        if cert_base_path:
                            click.echo(f"  Cert Base: {cert_base_path}")
                        click.echo()
            except Exception:
                pass
        
        if node_id:
            # Show history for specific node (don't validate against connected nodes)
            if node_id in self.connection_history["nodes"]:
                self._display_node_history(node_id)
            else:
                click.echo(click.style(f"No history found for node {node_id}", fg='yellow'))
        else:
            # Show history for all nodes
            if not self.connection_history["nodes"]:
                click.echo(click.style("No connection history found", fg='yellow'))
            else:
                for node_id in sorted(self.connection_history["nodes"].keys()):
                    self._display_node_history(node_id)
                    click.echo()
                    
    def _display_node_history(self, node_id: str):
        """Display history for a specific node."""
        from datetime import datetime
        
        click.echo()
        click.echo(click.style(f"Node: {node_id}", fg='cyan', bold=True))
        click.echo("-" * 40)
        
        history = self.connection_history["nodes"][node_id]
        if not history:
            click.echo("  No history entries")
            return
            
        # Sort by timestamp (newest first)
        sorted_history = sorted(history, key=lambda x: x.get('timestamp', 0), reverse=True)
        
        for entry in sorted_history[:10]:  # Show last 10 entries
            action = entry.get('action', 'unknown')
            timestamp = entry.get('timestamp', 0)
            session_id = entry.get('session_id', 'unknown')
            cert_path = entry.get('cert_path', '')
            key_path = entry.get('key_path', '')
            
            # Convert timestamp to readable format
            dt = datetime.fromtimestamp(timestamp / 1000)
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            
            # Color code the action
            action_color = 'green' if action == 'connected' else 'red'
            action_icon = '✓' if action == 'connected' else '✗'
            
            click.echo(f"  {action_icon} {click.style(action, fg=action_color, bold=True)} at {time_str}")
            click.echo(f"    Session ID: {session_id}")
            if cert_path:
                click.echo(f"    Cert Path: {cert_path}")
            if key_path:
                click.echo(f"    Key Path: {key_path}")
            
            if len(sorted_history) > 10:
                click.echo(f"    ... and {len(sorted_history) - 10} more entries")

    async def _handle_logs(self, args: List[str]):
        """Handle logs command: logs [OPTIONS]"""
        if any(a in args for a in ['help', '--help', '-h']):
            click.echo()
            click.echo("Usage: logs [OPTIONS]")
            click.echo()
            click.echo("  Check log files for troubleshooting issues.")
            click.echo()
            click.echo("Options:")
            click.echo("  --check              Check for recent errors and issues")
            click.echo("  --errors             Show recent error entries")
            click.echo("  --crashes            Show recent crash entries")
            click.echo("  --monitoring         Show recent monitoring issues")
            click.echo("  --help               Show this message and exit")
            click.echo()
            click.echo("Examples:")
            click.echo("  logs --check         # Check for any issues")
            click.echo("  logs --errors        # Show recent errors")
            click.echo("  logs --crashes       # Show recent crashes")
            click.echo("  logs --monitoring    # Show monitoring issues")
            click.echo()
            return
        
        try:
            from .utils.logger import get_logger
            logger = get_logger()
            
            if '--check' in args:
                self._check_for_issues(logger)
            elif '--errors' in args:
                self._show_recent_errors(logger)
            elif '--crashes' in args:
                self._show_recent_crashes(logger)
            elif '--monitoring' in args:
                self._show_monitoring_issues(logger)
            else:
                # Default: check for issues
                self._check_for_issues(logger)
                
        except Exception as e:
            click.echo(click.style(f"Error accessing logs: {str(e)}", fg='red'))
            click.echo("Make sure the logging system is properly initialized.")
    
    def _check_for_issues(self, logger):
        """Check for recent errors and issues."""
        summary = logger.get_log_summary()
        
        click.echo()
        click.echo(click.style("🔍 Checking for Issues", fg='blue', bold=True))
        click.echo("=" * 40)
        
        has_issues = False
        
        # Check for crashes
        if summary['crash_count'] > 0:
            has_issues = True
            click.echo(click.style(f"⚠️  Found {summary['crash_count']} crash(es)", fg='red'))
        
        # Check for monitoring issues
        if summary['monitoring_issues_count'] > 0:
            has_issues = True
            click.echo(click.style(f"⚠️  Found {summary['monitoring_issues_count']} monitoring issue(s)", fg='yellow'))
        
        # Check for general errors
        if summary['error_count'] > 0:
            has_issues = True
            click.echo(click.style(f"⚠️  Found {summary['error_count']} error(s)", fg='red'))
        
        if not has_issues:
            click.echo(click.style("✅ No issues found", fg='green'))
        else:
            click.echo()
            click.echo(click.style("Use 'logs --errors', 'logs --crashes', or 'logs --monitoring' for details", fg='cyan'))
    
    def _show_recent_errors(self, logger):
        """Show recent error entries from main log."""
        summary = logger.get_log_summary()
        log_path = summary['log_files']['main']
        
        if not os.path.exists(log_path):
            click.echo(click.style("No log file found", fg='red'))
            return
        
        try:
            with open(log_path, 'r') as f:
                lines = f.readlines()
            
            error_lines = [line for line in lines if 'ERROR' in line]
            
            if not error_lines:
                click.echo(click.style("✅ No errors found", fg='green'))
                return
            
            click.echo()
            click.echo(click.style("🚨 Recent Errors", fg='red', bold=True))
            click.echo("=" * 40)
            
            for line in error_lines[-10:]:  # Show last 10 errors
                click.echo(line.strip())
                
        except Exception as e:
            click.echo(click.style(f"Error reading log file: {str(e)}", fg='red'))
    
    def _show_recent_crashes(self, logger):
        """Show recent crash entries."""
        summary = logger.get_log_summary()
        log_path = summary['log_files']['crashes']
        
        if not os.path.exists(log_path):
            click.echo(click.style("No crash log found", fg='red'))
            return
        
        try:
            with open(log_path, 'r') as f:
                lines = f.readlines()
            
            if not lines:
                click.echo(click.style("✅ No crashes found", fg='green'))
                return
            
            click.echo()
            click.echo(click.style("💥 Recent Crashes", fg='red', bold=True))
            click.echo("=" * 40)
            
            for line in lines[-10:]:  # Show last 10 crashes
                click.echo(line.strip())
                
        except Exception as e:
            click.echo(click.style(f"Error reading crash log: {str(e)}", fg='red'))
    
    def _show_monitoring_issues(self, logger):
        """Show recent monitoring issues."""
        summary = logger.get_log_summary()
        
        if not summary['recent_monitoring_issues']:
            click.echo(click.style("✅ No monitoring issues found", fg='green'))
            return
        
        click.echo()
        click.echo(click.style("⚠️  Recent Monitoring Issues", fg='yellow', bold=True))
        click.echo("=" * 40)
        
        for issue in summary['recent_monitoring_issues'][-10:]:
            timestamp = issue['timestamp']
            node_id = issue['node_id']
            message = issue['message']
            click.echo(f"{timestamp} - {node_id}: {message}")

    async def _handle_clear(self, args: List[str]):
        """Clear the screen."""
        os.system('clear' if os.name == 'posix' else 'cls')

    async def _handle_history(self, args: List[str]):
        """Show command history."""
        if not args:
            # Show all history
            if not self.command_history:
                click.echo(click.style("No command history available", fg='yellow'))
                return
            
            click.echo(click.style("Command History:", fg='blue', bold=True))
            click.echo("=" * 50)
            
            for i, command in enumerate(self.command_history[-20:], 1):  # Show last 20 commands
                click.echo(f"{i:2d}. {command}")
            
            if len(self.command_history) > 20:
                click.echo(f"... and {len(self.command_history) - 20} more commands")
                
        elif args[0] == '--clear':
            # Clear history
            self.command_history = []
            readline.clear_history()
            try:
                if os.path.exists(self.history_file):
                    os.remove(self.history_file)
                click.echo(click.style("✓ Command history cleared", fg='green'))
            except Exception as e:
                click.echo(click.style(f"Warning: Could not clear history file: {str(e)}", fg='yellow'))
                
        elif args[0] == '--help':
            # Show help
            click.echo()
            click.echo(click.style("Command History Help", fg='blue', bold=True))
            click.echo("=" * 30)
            click.echo("  history              Show last 20 commands")
            click.echo("  history --clear      Clear all command history")
            click.echo("  history --help       Show this help")
            click.echo()
            click.echo("Navigation:")
            click.echo("  ↑/↓ arrows           Navigate through command history")
            click.echo("  Ctrl+R               Search history (reverse search)")
            click.echo("  Ctrl+G               Cancel search")
            click.echo()
        else:
            click.echo(click.style("Unknown option. Use 'history --help' for usage", fg='red'))

    def get_prompt(self) -> str:
        """Get the shell prompt showing connected nodes."""
        total_nodes = len(self.manager.get_connected_nodes())
        if self.target_node_ids:
            return click.style(f"rm-node({len(self.target_node_ids)}/{total_nodes} nodes)> ", fg='green', bold=True)
        return click.style(f"rm-node({total_nodes} nodes)> ", fg='green', bold=True)


async def start_interactive_shell(manager, config_dir: str = None):
    """Start the interactive shell with the given manager."""
    shell = PersistentShell(manager, config_dir)
    # Pass shell instance to manager for response storage
    manager.shell = shell
    await shell.run() 