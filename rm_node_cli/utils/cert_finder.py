"""
Certificate finder utility for MQTT CLI.
"""
import os
import csv
from datetime import datetime
import click
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import logging
from .debug_logger import debug_log, debug_step

# Get logger for this module
logger = logging.getLogger(__name__)

@debug_step("Finding certificates in directory")
def find_certificates_in_directory(directory: Path) -> List[Tuple[str, str, str]]:
    """
    Find all certificate and key pairs in a directory and its subdirectories.
    Also looks for node.info files to get node IDs.
    
    Args:
        directory: Directory to search
        
    Returns:
        list: List of tuples (node_id, cert_path, key_path)
    """
    cert_pairs = []
    try:
        # Walk through all subdirectories
        for root, dirs, files in os.walk(directory):
            root_path = Path(root)
            
            # Look for node.info first
            node_info = root_path / 'node.info'
            if node_info.exists():
                node_id = read_node_info_file(node_info)
                if node_id:
                    # Look for certificate files
                    cert_path = root_path / 'node.crt'
                    key_path = root_path / 'node.key'
                    if cert_path.exists() and key_path.exists():
                        cert_pairs.append((node_id, str(cert_path), str(key_path)))
                        logger.debug(f"Found certificate pair for node {node_id} in {root_path}")
                        
        logger.debug(f"Found {len(cert_pairs)} certificate pairs in directory {directory}")
        return cert_pairs
    except Exception as e:
        logger.debug(f"Error searching directory {directory}: {str(e)}")
        return []

@debug_step("Reading MAC addresses from file")
def read_mac_addresses_from_file(file_path: str) -> Dict[str, str]:
    """
    Read MAC addresses from a file where filenames contain MAC addresses.
    
    Args:
        file_path: Path to directory containing files with MAC addresses
        
    Returns:
        dict: Dictionary mapping MAC addresses to their file paths
    """
    mac_dict = {}
    try:
        base_path = Path(file_path)
        if not base_path.exists():
            logger.debug(f"MAC address directory does not exist: {base_path}")
            return mac_dict

        # Walk through directory and subdirectories
        for root, _, files in os.walk(base_path):
            for file in files:
                # Extract 12-digit MAC address from filename if present
                mac_match = ''.join(c for c in file if c.isalnum())
                if len(mac_match) >= 12:  # Look for potential MAC in filename
                    mac_address = mac_match[:12].upper()  # Take first 12 chars
                    if all(c in '0123456789ABCDEF' for c in mac_address):  # Validate hex
                        file_path = str(Path(root) / file)
                        mac_dict[mac_address] = file_path
                        logger.debug(f"Found MAC address {mac_address} in file {file_path}")

        logger.debug(f"Found {len(mac_dict)} MAC addresses in directory")
        return mac_dict
    except Exception as e:
        logger.debug(f"Error reading MAC addresses from directory: {str(e)}")
        return mac_dict

@debug_step("Converting Unix path to Windows")
def convert_unix_path_to_windows(unix_path: str, base_path: str) -> str:
    """Convert Unix-style path to Windows path relative to base_path."""
    try:
        # Extract the relative path after esp-rainmaker-admin-cli
        if 'esp-rainmaker-admin-cli' in unix_path:
            relative_path = unix_path.split('esp-rainmaker-admin-cli/')[-1]
            # Convert to Windows path and join with base_path
            logger.debug(f"Converting path {unix_path} to Windows format")
            result = str(Path(base_path) / relative_path)
            logger.debug(f"Converted path: {result}")
            return result
        return unix_path
    except Exception as e:
        logger.debug(f"Path conversion failed: {str(e)}")
        return unix_path

@debug_step("Reading node info file")
def read_node_info_file(file_path: Path) -> Optional[str]:
    """
    Read node.info file and extract node_id.
    
    Args:
        file_path: Path to node.info file
        
    Returns:
        str: node_id if found, None otherwise
    """
    try:
        logger.debug(f"Reading node.info file: {file_path}")
        with open(file_path, 'r') as f:
            content = f.read().strip()
            logger.debug(f"Found node_id: {content}")
            return content
    except Exception as e:
        logger.debug(f"Failed to read node.info file: {str(e)}")
        return None

@debug_step("Finding certificates by MAC address")
def find_by_mac_address(directory: Path, node_id: str = None) -> List[Tuple[str, str, str]]:
    """
    Find certificate and key files in MAC address directories.
    
    Args:
        directory: Base directory containing MAC address directories
        node_id: Optional node ID to match against
        
    Returns:
        list: List of tuples (node_id, cert_path, key_path)
    """
    cert_pairs = []
    try:
        # Check immediate subdirectories for MAC address pattern
        for item in directory.iterdir():
            if not item.is_dir():
                continue
                
            # Check if directory name could be a MAC address (12 hex digits)
            dir_name = item.name.upper()
            if len(dir_name) == 12 and all(c in '0123456789ABCDEF' for c in dir_name):
                logger.debug(f"Found potential MAC directory: {item}")
                
                # Look for certificates
                node_info = item / 'node.info'
                cert_path = item / 'node.crt'
                key_path = item / 'node.key'
                
                if node_info.exists() and cert_path.exists() and key_path.exists():
                    found_node_id = read_node_info_file(node_info)
                    if found_node_id:
                        if node_id is None or node_id == found_node_id:
                            logger.debug(f"Found valid certificate pair for node {found_node_id}")
                            cert_pairs.append((found_node_id, str(cert_path), str(key_path)))
                            
        logger.debug(f"Found {len(cert_pairs)} certificate pairs in MAC directories")
        return cert_pairs
    except Exception as e:
        logger.debug(f"Error in MAC directory search: {str(e)}")
        return []

@debug_step("Finding node certificate key pairs")
def find_node_cert_key_pairs(base_path: str) -> List[Tuple[str, str, str]]:
    """
    Find all node ID, certificate, and key file pairs.
    Searches in node_details directory structure.
    
    Args:
        base_path: Base directory to search
    
    Returns:
        list: List of tuples containing (node_id, cert_path, key_path)
    """
    node_pairs = []
    base_path = Path(base_path)
    
    logger.debug(f"Searching for certificate pairs in {base_path}")
    
    try:
        # Find all node folders in node_details structure
        node_folders = find_node_folders(base_path)
        logger.debug(f"Found {len(node_folders)} node folders")

        for node_id, folder_path in node_folders:
            try:
                crt_path, key_path = find_crt_key_files(folder_path)
                if crt_path and key_path:
                    logger.debug(f"Found valid certificate pair for node {node_id}")
                    node_pairs.append((node_id, str(crt_path), str(key_path)))
                else:
                    logger.debug(f"Certificate files not found for node {node_id}")
            except Exception as e:
                logger.debug(f"Error processing node folder {folder_path}: {str(e)}")
                click.echo(click.style(f"Error processing node folder {folder_path}: {str(e)}", fg='yellow'))
                
    except Exception as e:
        logger.debug(f"Error accessing directory {base_path}: {str(e)}")
        click.echo(click.style(f"Error accessing directory {base_path}: {str(e)}", fg='yellow'))
    
    logger.debug(f"Found {len(node_pairs)} total certificate pairs")
    return node_pairs

@debug_step("Getting certificate and key paths")
def get_cert_and_key_paths(base_path: str, node_id: str) -> Tuple[str, str]:
    """Find certificate and key paths for a node."""
    logger.debug(f"Searching for certificates for node {node_id} in {base_path}")
    node_pairs = find_node_cert_key_pairs(base_path)
    
    for nodeID, cert_path, key_path in node_pairs:
        if str(nodeID) == str(node_id):
            logger.debug(f"Found certificates for node {node_id}")
            return cert_path, key_path
            
    logger.debug(f"No certificates found for node {node_id}")
    raise FileNotFoundError(f"Certificate and key not found for node {node_id}")

@debug_step("Getting root certificate path")
def get_root_cert_path(config_dir: Path) -> str:
    """Get path to root CA certificate."""
    logger.debug(f"Looking for root certificate in {config_dir}")
    
    # First check in config directory
    root_path = config_dir / 'certs' / 'root.pem'
    if root_path.exists():
        logger.debug(f"Found root certificate in config directory: {root_path}")
        return str(root_path)
        
    # Then check in package directory
    package_root = Path(__file__).resolve().parent.parent.parent
    root_path = package_root / 'certs' / 'root.pem'
    if root_path.exists():
        logger.debug(f"Found root certificate in package directory: {root_path}")
        return str(root_path)
        
    logger.debug("Root certificate not found in any location")
    raise FileNotFoundError("Root CA certificate not found")


# ---------------

def find_node_folders(base_path):
    """
    Search through base_path to find all node_details folders and then node-xxxxxx-node_id folders
    Returns a list of tuples with (node_id, full_path)
    """
    node_folders = []
    base_path = Path(base_path)

    # Walk through the directory structure
    for root, dirs, files in os.walk(base_path):
        # Check if current directory is node_details
        if Path(root).name == "node_details":
            # Look for node-xxxxxx-node_id folders
            for dir_name in dirs:
                if dir_name.startswith("node-") and "-" in dir_name[6:]:
                    # Extract node_id (part after the 6th dash)
                    node_id = dir_name.split("-", 6)[-1]
                    full_path = Path(root) / dir_name
                    node_folders.append((node_id, full_path))

    return node_folders


def find_crt_key_files(folder_path):
    """
    Find certificate and key files in the node folder
    Returns (crt_path, key_path) or (None, None) if not found
    """
    # List of possible certificate file names to check
    crt_candidates = [
        "node.crt",  # Primary candidate
        "crt-node.crt",  # Fallback candidate
        "certificate.crt",  # Additional fallback
    ]

    # List of possible key file names to check
    key_candidates = [
        "node.key",  # Primary candidate
        "key-node.key",  # Fallback candidate
        "private.key",  # Additional fallback
    ]

    # Check for certificate file
    crt_path = None
    for candidate in crt_candidates:
        test_path = folder_path / candidate
        if test_path.exists():
            crt_path = test_path
            break

    # Check for key file
    key_path = None
    for candidate in key_candidates:
        test_path = folder_path / candidate
        if test_path.exists():
            key_path = test_path
            break

    return crt_path, key_path


def find_node_cert_key_pairs_path(base_path):
    """
    Find all node ID, certificate, and key file pairs from node folders.

    Returns:
        list: List of tuples containing (node_id, cert_path, key_path)
    """
    node_pairs = []
    base_path = Path(base_path)

    # Find all node folders
    nodes = find_node_folders(base_path)

    for node_id, folder_path in nodes:
        crt_path, key_path = find_crt_key_files(folder_path)

        if crt_path and key_path:
            # Convert paths to strings
            node_pairs.append((
                node_id,
                str(crt_path.resolve()),
                str(key_path.resolve())
            ))
        else:
            print(f"Warning: Certificate files not found for node {node_id} in {folder_path}")

    return node_pairs

def get_cert_paths_from_direct_path(base_path: str, node_id: str) -> Tuple[str, str]:
    """
    Find certificate and key paths for a node using multiple search methods.
    This is used when --cert-path is provided in CLI.
    
    Search order:
    1. Try MAC address directory structure
    2. Try node_details structure if MAC search fails
    
    Args:
        base_path: Base directory to search
        node_id: Node ID to find certificates for
        
    Returns:
        tuple: (cert_path, key_path)
        
    Raises:
        FileNotFoundError: If certificates are not found using any method
    """
    base_path = Path(base_path)
    logger.debug(f"Searching for certificates for node {node_id} in {base_path}")
    
    # Method 1: Try MAC address directory structure first (simpler and more common)
    logger.debug("Trying MAC address directory structure")
    mac_results = find_by_mac_address(base_path, node_id)
    if mac_results:
        for found_node_id, cert_path, key_path in mac_results:
            if found_node_id == node_id:
                logger.debug(f"Found certificates in MAC directory structure")
                return cert_path, key_path
    
    # Method 2: Try node_details structure
    logger.debug("Trying node_details structure")
    try:
        # First check if we're already in a node_details structure
        cert_pairs = find_certificates_in_directory(base_path)
        for found_node_id, cert_path, key_path in cert_pairs:
            if found_node_id == node_id:
                logger.debug(f"Found certificates in node_details structure")
                return cert_path, key_path
                
        # If not found, try traditional node_details search
        node_folders = find_node_folders(base_path)
        for folder_node_id, folder_path in node_folders:
            if folder_node_id == node_id:
                crt_path, key_path = find_crt_key_files(folder_path)
                if crt_path and key_path:
                    logger.debug(f"Found certificates in node folder")
                    return str(crt_path), str(key_path)
    except Exception as e:
        logger.debug(f"Error in node_details search: {str(e)}")
    
    # If we get here, no certificates were found
    error_msg = f"Certificate files not found for node {node_id} in {base_path}"
    error_msg += " (tried both MAC directory and node_details structures)"
    
    logger.debug(error_msg)
    raise FileNotFoundError(error_msg)