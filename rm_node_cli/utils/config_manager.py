"""
Configuration manager for MQTT CLI.
"""
import json
from pathlib import Path
from typing import Dict, Optional, Tuple, List

class ConfigManager:
    """Manages MQTT CLI configuration including broker and node details."""
    
    DEFAULT_BROKER = "a1p72mufdu6064-ats.iot.us-east-1.amazonaws.com"
    
    def __init__(self, config_dir: Path):
        """Initialize the configuration manager."""
        self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / 'config.json'
        self.config = {
            'broker': self.DEFAULT_BROKER,
            'nodes': {},  # node_id -> {'cert_path': str, 'key_path': str}
            'admin_cli_path': None,
            'cert_paths': []  # Support multiple certificate paths
        }
        self._load()
        
        # Ensure all configured nodes have valid certificate paths
        self._validate_node_paths()

    def _load(self):
        """Load configuration from file."""
        if self.config_file.exists():
            try:
                loaded_config = json.loads(self.config_file.read_text())
                self.config.update(loaded_config)
            except json.JSONDecodeError:
                pass
        
        # Ensure required keys exist
        if 'nodes' not in self.config:
            self.config['nodes'] = {}

    def _save(self):
        """Save configuration to file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps(self.config, indent=2))

    def _validate_node_paths(self):
        """Validate and update node certificate paths."""
        invalid_nodes = []
        for node_id, node_info in self.config['nodes'].items():
            cert_path = Path(node_info['cert_path'])
            key_path = Path(node_info['key_path'])
            
            # Check if paths exist
            if not cert_path.exists() or not key_path.exists():
                invalid_nodes.append(node_id)
                continue
                
            # Update paths to be absolute
            node_info['cert_path'] = str(cert_path.resolve())
            node_info['key_path'] = str(key_path.resolve())
            
        # Remove invalid nodes
        for node_id in invalid_nodes:
            del self.config['nodes'][node_id]
            
        if invalid_nodes:
            self._save()

    def set_broker(self, broker: str):
        """Set the MQTT broker URL."""
        self.config['broker'] = broker
        self._save()

    def get_broker(self) -> str:
        """Get the current MQTT broker URL."""
        return self.config.get('broker', self.DEFAULT_BROKER)
    
    def set_cert_path(self, cert_path: str):
        """Set the certificate path (legacy method for backward compatibility)."""
        self.config['cert_path'] = cert_path
        self._save()
    
    def get_cert_path(self) -> Optional[str]:
        """Get the certificate path (legacy method for backward compatibility)."""
        return self.config.get('cert_path')
    
    def set_cert_paths(self, cert_paths: Tuple[str, ...]):
        """Set multiple certificate paths."""
        self.config['cert_paths'] = list(cert_paths)
        self._save()
    
    def get_cert_paths(self) -> List[str]:
        """Get all certificate paths."""
        return self.config.get('cert_paths', [])

    def set_admin_cli_path(self, path: str):
        """Set the Nodes's Certs path."""
        self.config['admin_cli_path'] = str(Path(path).resolve())
        self._save()

    def get_admin_cli_path(self) -> Optional[str]:
        """Get the Nodes's Certs path."""
        return self.config.get('admin_cli_path')

    def add_node(self, node_id: str, cert_path: str, key_path: str):
        """Add or update a node's certificate paths."""
        cert_path = Path(cert_path)
        key_path = Path(key_path)
        
        if not cert_path.exists():
            raise FileNotFoundError(f"Certificate file not found: {cert_path}")
        if not key_path.exists():
            raise FileNotFoundError(f"Key file not found: {key_path}")
            
        self.config['nodes'][node_id] = {
            'cert_path': str(cert_path.resolve()),
            'key_path': str(key_path.resolve())
        }
        self._save()

    def get_node_paths(self, node_id: str) -> Optional[Tuple[str, str]]:
        """Get certificate paths for a node."""
        node_info = self.config['nodes'].get(node_id)
        if node_info:
            cert_path = Path(node_info['cert_path'])
            key_path = Path(node_info['key_path'])
            
            if cert_path.exists() and key_path.exists():
                return str(cert_path), str(key_path)
                
            # Remove invalid node
            del self.config['nodes'][node_id]
            self._save()
            
        return None

    def list_nodes(self) -> Dict[str, dict]:
        """Get all configured nodes."""
        return self.config['nodes']

    def remove_node(self, node_id: str) -> bool:
        """Remove a node's configuration."""
        if node_id in self.config['nodes']:
            del self.config['nodes'][node_id]
            self._save()
            return True
        return False

    def reset(self):
        """Reset configuration to defaults."""
        self.config = {
            'broker': self.DEFAULT_BROKER,
            'nodes': {},
            'admin_cli_path': None,
            'cert_paths': []
        }
        self._save() 