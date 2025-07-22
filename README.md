# RM-Node CLI

**Efficient MQTT Node Management for ESP RainMaker**

A modern, user-friendly command-line interface for managing ESP RainMaker nodes with persistent connections, section-based command organization, and automatic background monitoring.

## 🚀 Features

- **Persistent Connections**: Connect to all nodes at startup and maintain connections
- **Section-Based Commands**: Organized command structure matching ESP RainMaker MQTT swagger specification
- **Background Monitoring**: Automatic subscription to all relevant MQTT topics
- **Interactive Shell**: User-friendly shell with contextual help and examples
- **Swagger Compliant**: Uses official ESP RainMaker MQTT topics and message formats
- **Zero Connection Management**: No need to manually connect/disconnect from nodes

## 📋 Requirements

- Python 3.7+
- ESP RainMaker certificates
- MQTT broker access (AWS IoT Core)

## 🔧 Installation

### From Source

```bash
git clone https://github.com/espressif/rm-node-cli.git
cd rm-node-cli
pip install -e .
```

## 🎯 Quick Start

1. **Start the CLI with your certificates:**
   ```bash
   rm-node --cert-path /path/to/certs --broker-id your-broker-url
   ```

2. **Use the interactive shell:**
   ```bash
   rm-node(5 nodes)> help
   rm-node(5 nodes)> node config light
   rm-node(5 nodes)> node params Light power=true brightness=75
   rm-node(5 nodes)> ota fetch 1.2.3
   ```

## 📖 Command Sections

### NODE Section (Configuration & Parameters)
```bash
node config <device_type>                    # Configure node device type
node params <device> <param>=<value>         # Set device parameters
node init-params <device> <param>=<value>    # Initialize device parameters
node group-params <device> <param>=<value>   # Set group parameters
```

### OTA Section (Over-The-Air Updates)
```bash
ota fetch <version>                          # Request firmware download
ota request                                  # Request OTA with auto-monitoring
```

### TSDATA Section (Time Series Data)
```bash
tsdata tsdata <json_file>                    # Send complex time series data
tsdata simple-tsdata <json_file>             # Send simple time series data
```

### USER Section (User Management & Alerts)
```bash
user map <user_id> <secret_key>              # Map user to nodes
user alert <message>                         # Send user alert
```

### COMMAND Section (TLV Protocol)
```bash
command send-command <role> <command> [<data>] # Send TLV command
```

### Utility Commands
```bash
nodes                                        # List connected nodes
status                                       # Show detailed connection status
help [section]                               # Show help (general or specific)
clear                                        # Clear screen
exit                                         # Exit shell
```

## 📊 MQTT Topics Used

The CLI uses official ESP RainMaker MQTT topics as specified in the [swagger documentation](https://swaggermqtt.rainmaker.espressif.com/).

## 📝 License

This project is licensed under the Apache License 2.0.

---

**Made with ❤️ by the ESP Team**
