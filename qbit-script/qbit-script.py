#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
import time
import logging
import json
import requests
from urllib.parse import urljoin

# Load configuration
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

try:
    with open(CONFIG_FILE, 'r') as f:
        CONFIG = json.load(f)
except FileNotFoundError:
    print(f"Error: Configuration file not found at {CONFIG_FILE}")
    print("Please create a config.json file or copy the example from the README.")
    sys.exit(1)
except json.JSONDecodeError:
    print(f"Error: Configuration file at {CONFIG_FILE} is not valid JSON")
    sys.exit(1)

# Configure logging
log_level = getattr(logging, CONFIG.get('logging', {}).get('log_level', 'INFO'))
log_file = CONFIG.get('logging', {}).get('log_file', 'qbit-rclone.log')

logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# qBittorrent API configuration
QBIT_CONFIG = CONFIG.get('qbittorrent', {})
QBIT_HOST = QBIT_CONFIG.get('host', 'http://localhost:8080')
QBIT_USERNAME = QBIT_CONFIG.get('username', 'admin')
QBIT_PASSWORD = QBIT_CONFIG.get('password', 'adminadmin')

# OneDrive configuration
ONEDRIVE_CONFIG = CONFIG.get('onedrive', {})
REMOTE_NAME = ONEDRIVE_CONFIG.get('remote_name', 'onedrive')
TARGET_PATH = ONEDRIVE_CONFIG.get('target_path', 'Torrents')

# Rclone configuration
RCLONE_CONFIG = CONFIG.get('rclone', {})
RCLONE_OPTIONS = RCLONE_CONFIG.get('options', ['--progress'])

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Upload completed torrents to OneDrive using rclone.')
    parser.add_argument('-name', required=True, help='Name of the torrent')
    parser.add_argument('-hash', required=True, help='Hash of the torrent')
    parser.add_argument('-lcp', required=True, help='Local content path')
    parser.add_argument('-config', help='Path to custom config file')
    
    return parser.parse_args()

def login_to_qbittorrent():
    """Login to qBittorrent API and return a session."""
    session = requests.Session()
    login_url = urljoin(QBIT_HOST, "api/v2/auth/login")
    
    try:
        response = session.post(login_url, data={"username": QBIT_USERNAME, "password": QBIT_PASSWORD})
        if response.status_code == 200:
            logger.info("Successfully logged in to qBittorrent API")
            return session
        else:
            logger.error(f"Failed to login to qBittorrent API: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error connecting to qBittorrent: {e}")
        return None

def delete_from_qbittorrent(session, torrent_hash):
    """Delete a torrent from qBittorrent by its hash."""
    if not session:
        logger.error("No active qBittorrent session")
        return False
    
    delete_url = urljoin(QBIT_HOST, "api/v2/torrents/delete")
    data = {
        "hashes": torrent_hash,
        "deleteFiles": False  # We already deleted the files
    }
    
    try:
        response = session.post(delete_url, data=data)
        if response.status_code == 200:
            logger.info(f"Successfully removed torrent {torrent_hash} from qBittorrent")
            return True
        else:
            logger.error(f"Failed to remove torrent from qBittorrent: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Error removing torrent from qBittorrent: {e}")
        return False

def upload_to_onedrive(torrent_name, local_path):
    """Upload content to OneDrive using rclone."""
    target_path = f"{REMOTE_NAME}:{TARGET_PATH}/{torrent_name}"
    
    logger.info(f"Starting upload: {local_path} -> {target_path}")
    
    # Create rclone command with options from config
    rclone_cmd = ["rclone", "copy", local_path, target_path] + RCLONE_OPTIONS
    
    try:
        # Execute rclone command
        process = subprocess.run(rclone_cmd, capture_output=True, text=True)
        
        if process.returncode == 0:
            logger.info(f"Upload successful: {torrent_name}")
            return True
        else:
            logger.error(f"Upload failed: {process.stderr}")
            return False
    except Exception as e:
        logger.error(f"Error during upload: {e}")
        return False

def verify_upload(torrent_name):
    """Verify that the content exists on OneDrive."""
    target_path = f"{REMOTE_NAME}:{TARGET_PATH}/{torrent_name}"
    
    logger.info(f"Verifying upload to {target_path}")
    
    # Create rclone command to check if the folder exists
    rclone_cmd = ["rclone", "lsf", target_path]
    
    try:
        # Execute rclone command
        process = subprocess.run(rclone_cmd, capture_output=True, text=True)
        
        if process.returncode == 0:
            logger.info(f"Verification successful: {torrent_name} exists on OneDrive")
            return True
        else:
            logger.error(f"Verification failed: {process.stderr}")
            return False
    except Exception as e:
        logger.error(f"Error during verification: {e}")
        return False

def delete_local_content(local_path):
    """Delete local content after successful upload."""
    logger.info(f"Deleting local content: {local_path}")
    
    try:
        if os.path.isfile(local_path):
            os.remove(local_path)
            logger.info(f"Deleted file: {local_path}")
            return True
        elif os.path.isdir(local_path):
            import shutil
            shutil.rmtree(local_path)
            logger.info(f"Deleted directory: {local_path}")
            return True
        else:
            logger.warning(f"Path does not exist: {local_path}")
            return False
    except Exception as e:
        logger.error(f"Error deleting local content: {e}")
        return False

def main():
    args = parse_arguments()
    
    # If custom config file specified, load it
    if args.config:
        try:
            with open(args.config, 'r') as f:
                custom_config = json.load(f)
                # Update the global config with custom values
                global CONFIG, QBIT_HOST, QBIT_USERNAME, QBIT_PASSWORD, REMOTE_NAME, TARGET_PATH, RCLONE_OPTIONS
                CONFIG.update(custom_config)
                
                # Update variables with new config values
                QBIT_CONFIG = CONFIG.get('qbittorrent', {})
                QBIT_HOST = QBIT_CONFIG.get('host', QBIT_HOST)
                QBIT_USERNAME = QBIT_CONFIG.get('username', QBIT_USERNAME)
                QBIT_PASSWORD = QBIT_CONFIG.get('password', QBIT_PASSWORD)
                
                ONEDRIVE_CONFIG = CONFIG.get('onedrive', {})
                REMOTE_NAME = ONEDRIVE_CONFIG.get('remote_name', REMOTE_NAME)
                TARGET_PATH = ONEDRIVE_CONFIG.get('target_path', TARGET_PATH)
                
                RCLONE_CONFIG = CONFIG.get('rclone', {})
                RCLONE_OPTIONS = RCLONE_CONFIG.get('options', RCLONE_OPTIONS)
                
                logger.info(f"Loaded custom config from {args.config}")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Error loading custom config: {e}")
            sys.exit(1)
    
    torrent_name = args.name
    torrent_hash = args.hash
    local_path = args.lcp
    
    logger.info(f"Processing torrent: {torrent_name}")
    logger.info(f"Hash: {torrent_hash}")
    logger.info(f"Local path: {local_path}")
    
    # Ensure the local path exists
    if not os.path.exists(local_path):
        logger.error(f"Local path does not exist: {local_path}")
        sys.exit(1)
    
    # Upload to OneDrive
    if not upload_to_onedrive(torrent_name, local_path):
        logger.error("Upload failed, exiting")
        sys.exit(1)
    
    # Verify the upload
    if not verify_upload(torrent_name):
        logger.error("Verification failed, exiting")
        sys.exit(1)
    
    # Delete local content
    if not delete_local_content(local_path):
        logger.error("Failed to delete local content")
        # Continue anyway
    
    # Login to qBittorrent
    session = login_to_qbittorrent()
    if session:
        # Delete from qBittorrent
        if not delete_from_qbittorrent(session, torrent_hash):
            logger.error("Failed to delete torrent from qBittorrent")
    else:
        logger.error("Could not connect to qBittorrent")
    
    logger.info(f"Successfully processed torrent: {torrent_name}")

if __name__ == "__main__":
    main() 