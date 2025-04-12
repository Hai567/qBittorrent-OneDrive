#!/usr/bin/env python3
"""
qBittorrent to OneDrive Mover
This script monitors qBittorrent downloads and moves completed downloads to OneDrive using rclone.
"""

import os
import sys
import time
import logging
import json
import argparse
import subprocess
from datetime import datetime
import requests
import shutil
import socket
import traceback
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("qbit_rclone.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Decorator for retry logic
def retry(max_tries: int = 3, delay_seconds: int = 5, 
          backoff_factor: int = 2, exceptions: tuple = (requests.RequestException,)):
    """
    Retry decorator with exponential backoff for functions
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            mtries, mdelay = max_tries, delay_seconds
            last_exception = None
            
            while mtries > 0:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    mtries -= 1
                    if mtries == 0:
                        logger.error(f"All {max_tries} retries failed for {func.__name__}. Last error: {str(e)}")
                        last_exception = e
                        break
                        
                    logger.warning(f"Retry {max_tries - mtries} for {func.__name__} failed with {str(e)}. "
                                    f"Retrying in {mdelay} seconds...")
                    time.sleep(mdelay)
                    mdelay *= backoff_factor
            
            if last_exception:
                raise last_exception
        return wrapper
    return decorator

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
        self.connection_error = None
        
    @retry(max_tries=3, delay_seconds=3)
    def login(self) -> bool:
        """Login to qBittorrent Web API with retry"""
        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/auth/login",
                data={"username": self.username, "password": self.password},
                timeout=10  # Add timeout
            )
            if response.text == "Ok.":
                self.is_authenticated = True
                self.connection_error = None
                logger.info("Successfully logged in to qBittorrent")
                return True
            else:
                error_msg = f"Failed to login to qBittorrent: {response.text}"
                self.connection_error = error_msg
                logger.error(error_msg)
                return False
        except (requests.exceptions.RequestException, socket.error) as e:
            error_msg = f"Error connecting to qBittorrent: {e}"
            self.connection_error = error_msg
            logger.error(error_msg)
            raise
    
    def ensure_connected(func):
        """Decorator to ensure client is connected before making API calls"""
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if not self.is_authenticated and not self.login():
                logger.error(f"Cannot execute {func.__name__}: Not authenticated to qBittorrent")
                return [] if func.__name__ in ["get_torrents", "get_torrent_content"] else None
            return func(self, *args, **kwargs)
        return wrapper

    @ensure_connected
    @retry(max_tries=3, delay_seconds=2)
    def get_torrents(self, filter: str = "completed") -> List[Dict]:
        """Get list of torrents with specified filter"""
        try:
            response = self.session.get(
                f"{self.base_url}/api/v2/torrents/info",
                params={"filter": filter},
                timeout=15  # Increased timeout for potentially large responses
            )
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get torrents: {response.text}")
                return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting torrents: {e}")
            raise
            
    @ensure_connected
    @retry(max_tries=3, delay_seconds=2)
    def get_torrent_info(self, torrent_hash: str) -> Optional[Dict]:
        """Get detailed info about a specific torrent"""
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
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting torrent info: {e}")
            raise
    
    @ensure_connected
    @retry(max_tries=3, delay_seconds=2)
    def get_torrent_content(self, torrent_hash: str) -> List[Dict]:
        """Get content files of a specific torrent"""
        try:
            response = self.session.get(
                f"{self.base_url}/api/v2/torrents/files",
                params={"hash": torrent_hash},
                timeout=15  # Increased timeout for potentially large responses
            )
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get torrent content: {response.text}")
                return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting torrent content: {e}")
            raise

    def get_connection_status(self) -> Tuple[bool, Optional[str]]:
        """Return connection status and any error message"""
        if self.is_authenticated:
            return True, None
        else:
            return False, self.connection_error


class RcloneUploader:
    """Handles moving files/folders to cloud storage using rclone"""
    
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
    
    @retry(max_tries=2, delay_seconds=2, exceptions=(subprocess.SubprocessError, OSError))
    def check_rclone_config(self) -> bool:
        """Check if rclone is configured properly"""
        if not self.rclone_path:
            error_msg = "rclone not found"
            self.last_error = error_msg
            logger.error(error_msg)
            return False
            
        try:
            result = subprocess.run(
                [self.rclone_path, "listremotes"],
                capture_output=True, text=True, check=True,
                timeout=30  # Add timeout to prevent hanging
            )
            remotes = result.stdout.strip().split('\n')
            
            if f"{self.remote_name}:" in remotes:
                logger.info(f"Found {self.remote_name} remote in rclone configuration")
                self.last_error = None
                return True
            else:
                error_msg = f"{self.remote_name} remote not found in rclone configuration"
                self.last_error = error_msg
                logger.error(error_msg)
                return False
        except subprocess.SubprocessError as e:
            error_msg = f"Error checking rclone config: {e}"
            self.last_error = error_msg
            logger.error(error_msg)
            raise
    
    @retry(max_tries=2, delay_seconds=10, exceptions=(subprocess.SubprocessError, OSError, IOError))
    def upload_file(self, local_path: str, remote_subpath: str = "") -> bool:
        """Move a file/folder to cloud storage via rclone with retry"""
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
            
        # Validate the local path to ensure it's accessible
        try:
            if os.path.isdir(local_path):
                # Check if directory is readable
                os.listdir(local_path)
            else:
                # Check if file is readable
                with open(local_path, 'rb') as f:
                    f.read(1)  # Just read 1 byte to test access
        except (PermissionError, IOError) as e:
            error_msg = f"Cannot access local path {local_path}: {e}"
            self.last_error = error_msg
            logger.error(error_msg)
            return False
            
        # Construct the remote path
        remote_full_path = f"{self.remote_name}:{self.remote_path}"
        if remote_subpath:
            remote_full_path = os.path.join(remote_full_path, remote_subpath)
        
        # Run rclone move command
        try:
            logger.info(f"Starting move: {local_path} -> {remote_full_path}")
            
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
                    
                logger.info(f"Moving {item_type} of size {size_mb:.2f} MB")
            except (PermissionError, OSError) as e:
                logger.warning(f"Could not calculate size of {local_path}: {e}")
                # Continue with move operation despite size calculation failure
            
            # Execute the rclone command with progress monitoring
            process = subprocess.Popen(
                [
                    self.rclone_path, "move", local_path, remote_full_path,
                    "--progress", "--stats-one-line", "--stats=15s",  # Progress every 15 seconds
                    "--checksum",  # Use checksum for file verification
                    "--log-file=rclone-log.txt",  # Output detailed logs to file
                    "--retries", "3",  # Built-in retries for rclone itself
                    "--low-level-retries", "10",
                    "--tpslimit", "10"  # Limit transactions per second to avoid API rate limits
                ],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1
            )
            
            # Monitor and log the progress
            last_log_time = time.time()
            for line in process.stdout:
                # Limit logging frequency to avoid flooding logs
                current_time = time.time()
                if "Transferred:" in line and (current_time - last_log_time) >= 60:
                    logger.info(line.strip())
                    last_log_time = current_time
                
            process.wait()
            
            if process.returncode == 0:
                logger.info(f"Successfully moved to {remote_full_path}")
                self.last_error = None
                return True
            else:
                error_msg = f"Failed to move to {remote_full_path}"
                self.last_error = error_msg
                logger.error(error_msg)
                return False
                
        except Exception as e:
            error_msg = f"Error during move operation: {str(e)}"
            self.last_error = error_msg
            logger.error(error_msg)
            logger.error(traceback.format_exc())  # Print full traceback
            raise

class QBittorrentRcloneManager:
    """Main class to manage qBittorrent downloads and rclone moves to OneDrive"""

    def check_and_move_completed(self) -> None:
        """Check for completed torrents and move them to OneDrive"""
        logger.info("Checking for completed torrents...")
        
        try:
            # Get completed torrents
            completed_torrents = self.qbit_client.get_torrents(filter="completed")
            logger.info(f"Found {len(completed_torrents)} completed torrents")
            
            # Check for any failed operations to retry
            self._retry_failed_operations()
            
            for torrent in completed_torrents:
                try:
                    torrent_hash = torrent.get("hash")
                    torrent_name = torrent.get("name")
                    
                    if not torrent_hash or not torrent_name:
                        logger.warning("Found torrent with missing hash or name, skipping")
                        continue
                    
                    # Skip if already processed
                    if torrent_hash in self.processed_torrents:
                        logger.debug(f"Skipping already processed torrent: {torrent_name}")
                        continue
                        
                    # Check if this torrent has failed too many times
                    if (torrent_hash in self.failed_uploads and 
                            self.failed_uploads[torrent_hash].get("failures", 0) >= self.max_failures):
                        logger.warning(f"Skipping torrent that failed {self.max_failures} times: {torrent_name}")
                        continue
                    
                    # Get content path
                    content_path = self._get_torrent_content_path(torrent)
                    
                    if not content_path or not os.path.exists(content_path):
                        logger.warning(f"Cannot find content path for torrent: {torrent_name}")
                        continue
                        
                    # Create category-based folder structure if applicable
                    remote_subpath = ""
                    category = torrent.get("category", "")
                    if category and self.config.get("use_categories", True):
                        remote_subpath = category
                    
                    # Move the completed download
                    logger.info(f"Moving torrent: {torrent_name}")
                    success = self.rclone.upload_file(content_path, remote_subpath)
                    
                    if success:
                        # Mark as processed
                        self.processed_torrents[torrent_hash] = {
                            "name": torrent_name,
                            "moved_at": datetime.now().isoformat(),
                            "path": content_path
                        }
                        self._save_processed_torrents()
                        
                        # Remove from failed operations if it was there
                        if torrent_hash in self.failed_uploads:
                            del self.failed_uploads[torrent_hash]
                            self._save_failed_uploads()
                            
                        logger.info(f"Successfully processed torrent: {torrent_name}")
                    else:
                        # Track failure
                        self._record_move_failure(torrent_hash, torrent_name, content_path, 
                                                   self.rclone.last_error)
                        logger.error(f"Failed to move torrent: {torrent_name}")
                except Exception as e:
                    logger.error(f"Error processing torrent: {e}")
                    logger.error(traceback.format_exc())
        except Exception as e:
            logger.error(f"Error in check_and_move_completed cycle: {e}")
            logger.error(traceback.format_exc())
            # Continue despite errors

    def _retry_failed_operations(self) -> None:
        """Retry previously failed move operations"""
        if not self.failed_uploads:
            return
            
        logger.info(f"Checking {len(self.failed_uploads)} failed operations for retry")
        
        # Create a copy of the keys since we might modify the dictionary
        failed_hashes = list(self.failed_uploads.keys())
        
        for torrent_hash in failed_hashes:
            failed_info = self.failed_uploads[torrent_hash]
            
            # Skip if too many failures
            if failed_info.get("failures", 0) >= self.max_failures:
                logger.debug(f"Skipping retry for {failed_info['name']} - too many failures")
                continue
                
            # Check if path still exists
            content_path = failed_info.get("path")
            if not content_path or not os.path.exists(content_path):
                logger.warning(f"Content no longer exists for failed operation: {failed_info['name']}")
                del self.failed_uploads[torrent_hash]
                self._save_failed_uploads()
                continue
                
            # Attempt to move
            logger.info(f"Retrying move operation for: {failed_info['name']}")
            success = self.rclone.upload_file(content_path, "")
            
            if success:
                # Mark as processed and remove from failures
                self.processed_torrents[torrent_hash] = {
                    "name": failed_info["name"],
                    "moved_at": datetime.now().isoformat(),
                    "path": content_path,
                    "retries": failed_info.get("failures", 0)
                }
                self._save_processed_torrents()
                
                del self.failed_uploads[torrent_hash]
                self._save_failed_uploads()
                
                logger.info(f"Successfully moved previously failed torrent: {failed_info['name']}")
            else:
                # Update failure count
                self._record_move_failure(torrent_hash, failed_info["name"], 
                                          content_path, self.rclone.last_error)
                logger.error(f"Retry failed for torrent: {failed_info['name']}")

    def _record_move_failure(self, torrent_hash: str, torrent_name: str, 
                              content_path: str, error_message: Optional[str]) -> None:
        """Record a failed move operation attempt for retry later"""
        if torrent_hash not in self.failed_uploads:
            self.failed_uploads[torrent_hash] = {
                "name": torrent_name,
                "path": content_path,
                "first_failure": datetime.now().isoformat(),
                "last_failure": datetime.now().isoformat(),
                "failures": 1,
                "last_error": error_message or "Unknown error"
            }
        else:
            self.failed_uploads[torrent_hash]["failures"] += 1
            self.failed_uploads[torrent_hash]["last_failure"] = datetime.now().isoformat()
            self.failed_uploads[torrent_hash]["last_error"] = error_message or "Unknown error"
            
        self._save_failed_uploads()

    def run(self) -> bool:
        """Run the main manager loop"""
        # Health checks
        health_check_success = True
        
        # Check if rclone is configured
        if not self.rclone.check_rclone_config():
            logger.error("rclone is not properly configured. Please set up the remote first.")
            health_check_success = False
            
        # Check if we can connect to qBittorrent
        qbit_status, qbit_error = self.qbit_client.get_connection_status()
        if not qbit_status and not self.qbit_client.login():
            logger.error(f"Cannot connect to qBittorrent: {qbit_error}")
            health_check_success = False
            
        # Decide whether to continue based on config
        if not health_check_success and not self.config.get("continue_on_errors", False):
            logger.error("Health checks failed. Set 'continue_on_errors' to true in config to run anyway.")
            return False
            
        logger.info("Starting qBittorrent to OneDrive mover service")
        
        # Main loop
        try:
            while True:
                try:
                    self.check_and_move_completed()
                except Exception as e:
                    logger.error(f"Error in check_and_move_completed cycle: {e}")
                    logger.error(traceback.format_exc())
                    # Continue despite errors
                    
                interval = self.config.get("check_interval", 300)  # Default: 5 minutes
                logger.debug(f"Sleeping for {interval} seconds")
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Service stopped by user")
        except Exception as e:
            logger.error(f"Fatal error in main loop: {e}")
            logger.error(traceback.format_exc())
            return False
            
        return True