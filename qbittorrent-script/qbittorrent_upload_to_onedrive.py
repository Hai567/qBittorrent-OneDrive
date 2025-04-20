#!/usr/bin/env python3
"""
qBittorrent Finished Torrent Handler

This script is designed to be executed by qBittorrent when a torrent completes downloading.
It uploads the completed torrent to OneDrive using rclone, verifies the upload,
then deletes the torrent from disk and from qBittorrent.

Usage:
    1. Configure qBittorrent to run this script when a torrent finishes
    2. In qBittorrent, go to Tools > Options > Downloads > Run external program on torrent completion
    3. Enter: python /path/to/qbittorrent_upload_to_onedrive.py "%I" "%N" "%L"

    qBittorrent will pass the following parameters:
    - %I: The torrent hash
    - %N: The torrent name
    - %L: The category/label

Requirements:
    - Python 3.7+
    - requests library
    - rclone configured with OneDrive remote
"""

import os
import sys
import time
import logging
import json
import argparse
import subprocess
import shutil
import requests
import traceback
from typing import Dict, List, Optional, Tuple, Union

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("qbittorrent_onedrive_upload.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class QBittorrentClient:
    """Client for interacting with qBittorrent Web API"""
    
    def __init__(self, host: str = "localhost", port: int = 8080, 
                username: str = "admin", password: str = "adminadmin"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.base_url = f"http://{host}:{port}"
        self.session = requests.Session()
        self.is_authenticated = False
        
    def login(self) -> bool:
        """Login to qBittorrent Web API"""
        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/auth/login",
                data={"username": self.username, "password": self.password},
                timeout=10
            )
            if response.text == "Ok.":
                self.is_authenticated = True
                logger.info("Successfully logged in to qBittorrent")
                return True
            else:
                logger.error(f"Failed to login to qBittorrent: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error connecting to qBittorrent: {e}")
            return False
    
    def get_torrent_info(self, torrent_hash: str) -> Optional[Dict]:
        """Get detailed info about a specific torrent"""
        if not self.is_authenticated and not self.login():
            return None
            
        try:
            response = self.session.get(
                f"{self.base_url}/api/v2/torrents/properties",
                params={"hash": torrent_hash},
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get torrent info: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error getting torrent info: {e}")
            return None
    
    def get_torrent(self, torrent_hash: str) -> Optional[Dict]:
        """Get basic info about a specific torrent"""
        if not self.is_authenticated and not self.login():
            return None
            
        try:
            response = self.session.get(
                f"{self.base_url}/api/v2/torrents/info",
                params={"hashes": torrent_hash},
                timeout=10
            )
            if response.status_code == 200:
                torrents = response.json()
                if torrents and len(torrents) > 0:
                    return torrents[0]
                logger.error("Torrent not found")
                return None
            else:
                logger.error(f"Failed to get torrent: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error getting torrent: {e}")
            return None
    
    def get_torrent_content_path(self, torrent_hash: str, torrent_name: str) -> Optional[str]:
        """Determine the content path for a torrent"""
        if not self.is_authenticated and not self.login():
            return None
            
        torrent = self.get_torrent(torrent_hash)
        if not torrent:
            return None
            
        content_path = torrent.get("content_path", "")
        # First try the content_path if available
        if content_path and os.path.exists(content_path):
            return content_path
            
        # Next, try to construct from save_path and name
        save_path = torrent.get("save_path", "")
        name = torrent.get("name", "")
        
        if save_path and name:
            constructed_path = os.path.join(save_path, name)
            if os.path.exists(constructed_path):
                return constructed_path
                
        # As a last resort, use the provided torrent name and try to find it
        if save_path and torrent_name:
            constructed_path = os.path.join(save_path, torrent_name)
            if os.path.exists(constructed_path):
                return constructed_path
                
        logger.error(f"Could not determine content path for torrent: {torrent_name}")
        return None
    
    def delete_torrent(self, torrent_hash: str, delete_files: bool = False) -> bool:
        """Delete a torrent from qBittorrent, optionally with its files"""
        if not self.is_authenticated and not self.login():
            return False
            
        try:
            logger.info(f"Deleting torrent with hash {torrent_hash} (delete_files={delete_files})")
            response = self.session.post(
                f"{self.base_url}/api/v2/torrents/delete",
                data={"hashes": torrent_hash, "deleteFiles": str(delete_files).lower()},
                timeout=10
            )
            if response.status_code == 200:
                logger.info(f"Successfully deleted torrent with hash {torrent_hash}")
                return True
            else:
                logger.error(f"Failed to delete torrent: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error deleting torrent: {e}")
            return False


class RcloneUploader:
    """Handles uploads to cloud storage using rclone"""
    
    def __init__(self, remote_name: str = "onedrive", remote_path: str = "Torrents"):
        self.remote_name = remote_name
        self.remote_path = remote_path
        self.rclone_path = self._find_rclone()
        self.last_error = None
        
    def _find_rclone(self) -> Optional[str]:
        """Find rclone executable in PATH"""
        if os.name == "nt":  # Windows
            rclone_cmd = "rclone.exe"
        else:  # Linux, macOS
            rclone_cmd = "rclone"
            
        # Check if rclone is in PATH
        rclone_path = shutil.which(rclone_cmd)
        if rclone_path:
            logger.info(f"Found rclone in PATH: {rclone_path}")
            return rclone_path
            
        # Check common installation locations
        common_paths = [
            r"C:\Program Files\rclone\rclone.exe",
            r"C:\rclone\rclone.exe",
            os.path.expanduser("~/.local/bin/rclone"),
            "/usr/local/bin/rclone",
            "/usr/bin/rclone"
        ]
        
        for path in common_paths:
            if os.path.isfile(path):
                logger.info(f"Found rclone at: {path}")
                return path
                
        error_msg = "rclone executable not found. Please install rclone or ensure it's in your PATH"
        self.last_error = error_msg
        logger.error(error_msg)
        return None
        
    def check_rclone_config(self) -> bool:
        """Check if rclone is configured with the specified remote"""
        if not self.rclone_path:
            return False
            
        try:
            result = subprocess.run(
                [self.rclone_path, "listremotes"],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0:
                remotes = result.stdout.splitlines()
                remote_with_colon = f"{self.remote_name}:"
                
                if remote_with_colon in remotes:
                    logger.info(f"Found configured remote: {self.remote_name}")
                    return True
                else:
                    logger.error(f"Remote '{self.remote_name}' not found in rclone config")
                    logger.error(f"Available remotes: {remotes}")
                    return False
            else:
                logger.error(f"Error checking rclone config: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Error checking rclone config: {e}")
            return False
    
    def upload_file(self, local_path: str, remote_subpath: str = "") -> bool:
        """Upload a file to cloud storage via rclone"""
        if not self.rclone_path:
            error_msg = "rclone not found, cannot upload"
            self.last_error = error_msg
            logger.error(error_msg)
            return False
            
        if not os.path.exists(local_path):
            error_msg = f"Local path does not exist: {local_path}"
            self.last_error = error_msg
            logger.error(error_msg)
            return False
            
        # Construct the remote path
        remote_full_path = f"{self.remote_name}:{self.remote_path}"
        if remote_subpath:
            remote_full_path = os.path.join(remote_full_path, remote_subpath)
        else:
            # Only append local basename if remote_subpath is not provided
            local_basename = os.path.basename(os.path.normpath(local_path))
            if local_basename:
                remote_full_path = os.path.join(remote_full_path, local_basename)
        
        # Run rclone copy command
        try:
            logger.info(f"Starting upload: {local_path} -> {remote_full_path}")
            
            # Get file/directory size before upload
            try:
                if os.path.isfile(local_path):
                    size_mb = os.path.getsize(local_path) / (1024 * 1024)
                    item_type = "file"
                else:
                    size_mb = sum(os.path.getsize(os.path.join(dirpath, filename)) 
                               for dirpath, _, filenames in os.walk(local_path) 
                               for filename in filenames) / (1024 * 1024)
                    item_type = "directory"
                    
                logger.info(f"Uploading {item_type} of size {size_mb:.2f} MB")
            except Exception as e:
                logger.warning(f"Could not calculate size of {local_path}: {e}")
            
            # Run the rclone copy command
            result = subprocess.run(
                [
                    self.rclone_path, "copy", local_path, remote_full_path,
                    "--progress",  # Show progress
                    "-v"           # Verbose output
                ],
                capture_output=True, text=True
            )
            
            if result.returncode == 0:
                logger.info(f"Upload successful: {local_path} -> {remote_full_path}")
                self.last_error = None
                return True
            else:
                error_msg = f"Upload failed: {result.stderr}"
                self.last_error = error_msg
                logger.error(error_msg)
                return False
                
        except Exception as e:
            error_msg = f"Error during upload: {str(e)}"
            self.last_error = error_msg
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            return False
    
    def verify_upload(self, local_path: str, remote_subpath: str = "") -> bool:
        """Verify that files/folders were uploaded correctly using rclone check"""
        if not self.rclone_path:
            error_msg = "rclone not found, cannot verify"
            self.last_error = error_msg
            logger.error(error_msg)
            return False
            
        if not os.path.exists(local_path):
            error_msg = f"Local path does not exist: {local_path}"
            self.last_error = error_msg
            logger.error(error_msg)
            return False
            
        # Construct the remote path
        remote_full_path = f"{self.remote_name}:{self.remote_path}"
        if remote_subpath:
            remote_full_path = os.path.join(remote_full_path, remote_subpath)
        else:
            # Only append local basename if remote_subpath is not provided
            local_basename = os.path.basename(os.path.normpath(local_path))
            if local_basename:
                remote_full_path = os.path.join(remote_full_path, local_basename)
        
        # Run rclone check command to verify the upload
        try:
            logger.info(f"Verifying upload: {local_path} -> {remote_full_path}")
            
            # Run the rclone check command
            result = subprocess.run(
                [
                    self.rclone_path, "check", local_path, remote_full_path,
                    "--one-way",   # Only check that source files exist in destination
                    "--size-only"  # Faster check based on sizes only
                ],
                capture_output=True, text=True, timeout=300
            )
            
            # Check if verification was successful
            if result.returncode == 0:
                logger.info(f"Upload verification successful for {local_path}")
                self.last_error = None
                return True
            else:
                # If the check failed, log the errors
                error_msg = f"Upload verification failed: {result.stderr}"
                self.last_error = error_msg
                logger.error(error_msg)
                
                # Log specific file differences if available
                if result.stdout:
                    logger.error(f"Differences detected: {result.stdout}")
                
                return False
                
        except subprocess.TimeoutExpired:
            error_msg = f"Verification timed out after 300 seconds"
            self.last_error = error_msg
            logger.error(error_msg)
            return False
        except Exception as e:
            error_msg = f"Error during verification: {str(e)}"
            self.last_error = error_msg
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            return False


def delete_content(content_path: str) -> bool:
    """Delete content folder/file from the filesystem"""
    if not content_path or not os.path.exists(content_path):
        logger.warning(f"Cannot delete nonexistent path: {content_path}")
        return False
        
    try:
        logger.info(f"Deleting content: {content_path}")
        
        if os.path.isdir(content_path):
            shutil.rmtree(content_path)
            logger.info(f"Successfully deleted directory: {content_path}")
        else:
            os.remove(content_path)
            logger.info(f"Successfully deleted file: {content_path}")
            
        return True
    except Exception as e:
        logger.error(f"Error deleting content {content_path}: {e}")
        logger.error(traceback.format_exc())
        return False


def load_config() -> Dict:
    """Load configuration from config.json"""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    
    default_config = {
        "qbittorrent": {
            "host": "localhost",
            "port": 8080,
            "username": "admin",
            "password": "adminadmin"
        },
        "rclone": {
            "remote_name": "onedrive",
            "remote_path": "Torrents"
        },
        "auto_delete": {
            "delete_from_client": True,
            "delete_content": True
        }
    }
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
            logger.info("Loaded configuration from config.json")
            return config
        except Exception as e:
            logger.error(f"Error loading config.json: {e}, using defaults")
            return default_config
    else:
        logger.info("config.json not found, using default configuration")
        return default_config


def main():
    """Main function to handle finished torrent uploads"""
    parser = argparse.ArgumentParser(description="Upload finished qBittorrent torrent to OneDrive and clean up")
    parser.add_argument("hash", help="Torrent hash (passed by qBittorrent as %%I)")
    parser.add_argument("name", help="Torrent name (passed by qBittorrent as %%N)")
    parser.add_argument("category", nargs="?", default="", help="Torrent category/label (passed by qBittorrent as %%L)")
    args = parser.parse_args()

    logger.info(f"=== Starting upload for torrent: {args.name} (hash: {args.hash}) ===")
    
    # Load configuration
    config = load_config()
    
    # Initialize clients
    qbit_client = QBittorrentClient(
        host=config.get("qbittorrent", {}).get("host", "localhost"),
        port=config.get("qbittorrent", {}).get("port", 8080),
        username=config.get("qbittorrent", {}).get("username", "admin"),
        password=config.get("qbittorrent", {}).get("password", "adminadmin")
    )
    
    rclone = RcloneUploader(
        remote_name=config.get("rclone", {}).get("remote_name", "onedrive"),
        remote_path=config.get("rclone", {}).get("remote_path", "Torrents")
    )
    
    # Check if rclone is configured
    if not rclone.check_rclone_config():
        logger.error("rclone is not properly configured. Please set up the remote first.")
        sys.exit(1)
    
    # Get torrent content path
    content_path = qbit_client.get_torrent_content_path(args.hash, args.name)
    if not content_path:
        logger.error(f"Could not determine content path for torrent: {args.name}")
        sys.exit(1)
    
    logger.info(f"Content path: {content_path}")
    
    # Use category as subpath if available
    remote_subpath = args.category if args.category else args.name
    
    # Upload the content
    logger.info(f"Uploading torrent: {args.name}")
    upload_success = rclone.upload_file(content_path, remote_subpath)
    
    if upload_success:
        # Verify the upload
        logger.info(f"Verifying upload for: {args.name}")
        verify_success = rclone.verify_upload(content_path, remote_subpath)
        
        if verify_success:
            logger.info(f"Upload verified successfully: {args.name}")
            
            # Delete the torrent from qBittorrent
            delete_from_client = config.get("auto_delete", {}).get("delete_from_client", True)
            if delete_from_client:
                logger.info(f"Deleting torrent from qBittorrent: {args.name}")
                delete_success = qbit_client.delete_torrent(args.hash, delete_files=False)
                if not delete_success:
                    logger.error(f"Failed to delete torrent from qBittorrent: {args.name}")
            
            # Delete the content from filesystem
            delete_content_setting = config.get("auto_delete", {}).get("delete_content", True)
            if delete_content_setting:
                logger.info(f"Deleting content files: {args.name}")
                delete_content(content_path)
            
            logger.info(f"=== Successfully processed torrent: {args.name} ===")
        else:
            logger.error(f"Upload verification failed for: {args.name}")
            sys.exit(1)
    else:
        logger.error(f"Failed to upload torrent: {args.name}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1) 