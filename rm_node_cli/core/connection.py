"""
Connection manager for MQTT CLI.
"""
import json
from pathlib import Path
from ..mqtt_operations import MQTTOperations

class ConnectionManager:
    """Manages connections with persistent storage"""
    def __init__(self, storage_file=".mqtt_connections.json"):
        self.storage_file = Path(storage_file)
        self.connections = {}  # node_id: {'broker': str, 'cert_path': str, 'key_path': str, 'client': MQTTOperations}
        self.active_node = None
        self._load()

    def _load(self):
        if self.storage_file.exists():
            try:
                data = json.loads(self.storage_file.read_text())
                self.connections = data.get('connections', {})
                # We don't store the client object in the file
                for node_id in self.connections:
                    self.connections[node_id]['client'] = None
                self.active_node = data.get('active_node')
            except json.JSONDecodeError:
                pass

    def _save(self):
        # Prepare data without client objects
        save_data = {
            'connections': {
                node_id: {k: v for k, v in data.items() if k != 'client'} 
                for node_id, data in self.connections.items()
            },
            'active_node': self.active_node
        }
        self.storage_file.write_text(json.dumps(save_data))

    def add_connection(self, node_id, broker, cert_path, key_path, client):
        self.connections[node_id] = {
            'broker': broker,
            'cert_path': cert_path,
            'key_path': key_path,
            'client': client
        }
        self.active_node = node_id
        self._save()

    def remove_connection(self, node_id):
        if node_id in self.connections:
            # Disconnect the client if it exists
            if self.connections[node_id]['client']:
                self.connections[node_id]['client'].disconnect()
            
            del self.connections[node_id]
            
            # Update active node if needed
            if self.active_node == node_id:
                self.active_node = next(iter(self.connections.keys()), None)
            
            self._save()
            return True
        return False

    def disconnect_all(self):
        results = {}
        for node_id in list(self.connections.keys()):
            results[node_id] = self.remove_connection(node_id)
        return results

    def get_active_client(self):
        if self.active_node and self.active_node in self.connections:
            return self.connections[self.active_node]['client']
        return None

    def list_connections(self):
        return [
            (node_id, data['client'].is_connected() if data['client'] else False)
            for node_id, data in self.connections.items()
        ] 