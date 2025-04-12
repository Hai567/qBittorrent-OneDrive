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
        """Copy a file/folder to cloud storage via rclone and delete locally only after verification"""
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
                logger.info(f"Preparing to copy entire folder: {local_path}")
            else:
                # Check if file is readable
                with open(local_path, 'rb') as f:
                    f.read(1)  # Just read 1 byte to test access
                logger.info(f"Preparing to copy file: {local_path}")
        except (PermissionError, IOError) as e:
            error_msg = f"Cannot access local path {local_path}: {e}"
            self.last_error = error_msg
            logger.error(error_msg)
            return False
            
        # Construct the remote path
        remote_full_path = f"{self.remote_name}:{self.remote_path}"
        if remote_subpath:
            remote_full_path = os.path.join(remote_full_path, remote_subpath)
        
        # Make sure destination folder includes the source folder name when moving a directory
        if os.path.isdir(local_path) and not local_path.endswith(os.sep):
            folder_name = os.path.basename(local_path)
            remote_full_path = os.path.join(remote_full_path, folder_name)
            logger.info(f"Copying entire folder to: {remote_full_path}")
        
        # Step 1: Copy files to remote
        try:
            logger.info(f"Starting copy: {local_path} -> {remote_full_path}")
            
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
                    
                logger.info(f"Copying {item_type} of size {size_mb:.2f} MB")
            except (PermissionError, OSError) as e:
                logger.warning(f"Could not calculate size of {local_path}: {e}")
                # Continue with copy operation despite size calculation failure
            
            # Build rclone command for COPY (not move)
            rclone_copy_cmd = [
                self.rclone_path, "copy", local_path, remote_full_path,
                "--checksum",  # Use checksum for file verification
                "--log-file=rclone-copy-log.txt",  # Output detailed logs to file
                "--retries", "5",
                "--low-level-retries", "10",
            ]
            
            # Execute the rclone copy command with progress monitoring
            logger.info("STEP 1/3: Copying files to remote destination")
            process = subprocess.Popen(
                rclone_copy_cmd,
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
            
            if process.returncode != 0:
                error_msg = f"Failed to copy to {remote_full_path} (exit code: {process.returncode})"
                self.last_error = error_msg
                logger.error(error_msg)
                return False
                
            logger.info("STEP 2/3: Verifying files were copied successfully")
            # Step 2: Verify the files were copied successfully
            rclone_check_cmd = [
                self.rclone_path, "check", local_path, remote_full_path,
                "--one-way",  # Only check if local files exist at remote destination
            ]
            
            check_process = subprocess.run(
                rclone_check_cmd, 
                capture_output=True, 
                text=True
            )
            
            if check_process.returncode != 0:
                # Files don't match or other error
                error_msg = f"Verification failed: {check_process.stderr or check_process.stdout}"
                self.last_error = error_msg
                logger.error(error_msg)
                return False
            
            logger.info("Files successfully verified on remote destination")
            
            # Step 3: Delete the local files now that we've confirmed the copy worked
            logger.info("STEP 3/3: Deleting local files")
            if os.path.isfile(local_path):
                os.remove(local_path)
            else:
                shutil.rmtree(local_path)
                
            logger.info(f"Successfully moved to {remote_full_path} (copy + verify + delete)")
            self.last_error = None
            return True
                
        except Exception as e:
            error_msg = f"Error during move operation: {str(e)}"
            self.last_error = error_msg
            logger.error(error_msg)
            logger.error(traceback.format_exc())  # Print full traceback
            raise

class QBittorrentRcloneManager:
    """Main class to manage qBittorrent downloads and rclone moves to OneDrive"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.qbit_client = QBittorrentClient(
            host=config.get("qbittorrent", {}).get("host", "localhost"),
            port=config.get("qbittorrent", {}).get("port", 8080),
            username=config.get("qbittorrent", {}).get("username", "admin"),
            password=config.get("qbittorrent", {}).get("password", "adminadmin")
        )
        self.rclone = RcloneUploader(
            remote_name=config.get("rclone", {}).get("remote_name", "onedrive"),
            remote_path=config.get("rclone", {}).get("remote_path", "Torrents")
        )
        self.processed_torrents = self._load_processed_torrents()
        self.failed_uploads = self._load_failed_uploads()
        self.max_failures = config.get("max_upload_failures", 3)
        
    def _load_processed_torrents(self) -> Dict:
        """Load list of already processed torrents"""
        return self._load_json_file("processed_torrents.json")
            
    def _load_failed_uploads(self) -> Dict:
        """Load list of failed uploads to manage retries"""
        return self._load_json_file("failed_uploads.json")
    
    def _load_json_file(self, filename: str) -> Dict:
        """Generic JSON file loader with error handling"""
        try:
            if os.path.exists(filename):
                with open(filename, "r") as f:
                    return json.load(f)
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing {filename}: {e}")
            # Create backup of corrupted file
            if os.path.exists(filename):
                backup_name = f"{filename}.{int(time.time())}.bak"
                try:
                    shutil.copy2(filename, backup_name)
                    logger.info(f"Created backup of corrupted file: {backup_name}")
                except Exception as backup_err:
                    logger.error(f"Failed to create backup of corrupted file: {backup_err}")
            return {}
        except Exception as e:
            logger.error(f"Error loading {filename}: {e}")
            return {}
            
    def _save_processed_torrents(self) -> bool:
        """Save list of processed torrents to avoid re-uploading"""
        return self._save_json_file("processed_torrents.json", self.processed_torrents)
            
    def _save_failed_uploads(self) -> bool:
        """Save list of failed uploads for retry tracking"""
        return self._save_json_file("failed_uploads.json", self.failed_uploads)
    
    def _save_json_file(self, filename: str, data: Dict) -> bool:
        """Generic JSON file saver with error handling"""
        try:
            # First write to a temporary file, then rename for atomicity
            temp_filename = f"{filename}.tmp"
            with open(temp_filename, "w") as f:
                json.dump(data, f, indent=2)
            
            # Replace the original file with the temp file
            if os.path.exists(filename):
                os.replace(temp_filename, filename)
            else:
                os.rename(temp_filename, filename)
            return True
        except Exception as e:
            logger.error(f"Error saving {filename}: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def _get_torrent_content_path(self, torrent: Dict) -> Optional[str]:
        """Determine the content path for a torrent with fallback methods"""
        content_path = torrent.get("content_path", "")
        
        # First try the content_path if available
        if content_path and os.path.exists(content_path):
            return content_path
            
        # Next, try to construct from save_path and name
        save_path = torrent.get("save_path", "")
        return save_path
        
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

def create_default_config() -> Dict:
    """Create a default configuration file"""
    config = {
        "qbittorrent": {
            "host": "localhost",
            "port": 8080,
            "username": "admin",
            "password": "adminadmin",
        },
        "rclone": {
            "remote_name": "onedrive",
            "remote_path": "Torrents"
        },
        "check_interval": 300,  # 5 minutes
        "use_categories": True,
        "max_upload_failures": 3,
        "continue_on_errors": False
    }
    
    try:
        # First write to temp file, then move (atomic operation)
        temp_file = "config.json.tmp"
        with open(temp_file, "w") as f:
            json.dump(config, f, indent=4)
        
        # Move temp file to actual config file
        if os.path.exists("config.json"):
            os.replace(temp_file, "config.json")
        else:
            os.rename(temp_file, "config.json")
            
        logger.info("Created default configuration file: config.json")
        return config
    except Exception as e:
        logger.error(f"Error creating default configuration: {e}")
        logger.error(traceback.format_exc())
        return config


def load_config() -> Dict:
    """Load configuration from file or create default"""
    try:
        if os.path.exists("config.json"):
            with open("config.json", "r") as f:
                config = json.load(f)
            logger.info("Loaded configuration from config.json")
            return config
        else:
            logger.info("Configuration file not found, creating default")
            return create_default_config()
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config.json: {e}")
        # Create backup of invalid config
        try:
            backup_name = f"config.json.{int(time.time())}.bak"
            shutil.copy2("config.json", backup_name)
            logger.info(f"Created backup of invalid config as {backup_name}")
        except Exception as backup_err:
            logger.error(f"Failed to backup invalid config: {backup_err}")
        # Create a fresh config
        return create_default_config()
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        logger.error(traceback.format_exc())
        return create_default_config()


def validate_config(config: Dict) -> bool:
    """Validate configuration parameters"""
    # List of required fields
    required_fields = [
        ("qbittorrent", dict),
        ("qbittorrent.host", str),
        ("qbittorrent.port", int),
        ("qbittorrent.username", str),
        ("qbittorrent.password", str),
        ("rclone", dict),
        ("rclone.remote_name", str),
        ("rclone.remote_path", str)
    ]
    
    valid = True
    for field_path, expected_type in required_fields:
        # Split path components
        components = field_path.split(".")
        
        # Navigate to the specified config item
        current = config
        for component in components:
            if isinstance(current, dict) and component in current:
                current = current[component]
            else:
                logger.error(f"Missing required config field: {field_path}")
                valid = False
                break
                
        # Check type if we found the item
        if isinstance(current, dict) and len(components) > 1:
            if not isinstance(current, expected_type):
                logger.error(f"Config field {field_path} should be {expected_type.__name__}, got {type(current).__name__}")
                valid = False
    
    # Check specific value constraints
    if valid:
        # Port should be a valid number
        port = config.get("qbittorrent", {}).get("port", 0)
        if not isinstance(port, int) or port <= 0 or port > 65535:
            logger.error(f"Invalid port number: {port}")
            valid = False
            
        # Check interval (must be positive)
        interval = config.get("check_interval", 0)
        if not isinstance(interval, int) or interval <= 0:
            logger.error(f"Invalid check_interval: {interval} (should be positive integer)")
            valid = False
    
    return valid


def main() -> None:
    """Main entry point"""
    parser = argparse.ArgumentParser(description="qBittorrent to OneDrive Mover")
    parser.add_argument("--config", help="Path to configuration file")
    parser.add_argument("--setup", action="store_true", help="Create default configuration file and exit")
    parser.add_argument("--validate", action="store_true", help="Validate configuration and exit")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                       default="INFO", help="Set the logging level")
    args = parser.parse_args()
    
    # Set log level based on argument
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    # Create default config and exit if --setup is provided
    if args.setup:
        create_default_config()
        print("Created default configuration file: config.json")
        print("Please edit this file with your qBittorrent and rclone settings")
        return
    
    # Load configuration
    config_file = args.config if args.config else "config.json"
    if args.config and os.path.exists(args.config):
        try:
            with open(args.config, "r") as f:
                config = json.load(f)
        except Exception as e:
            logger.error(f"Error reading config file {args.config}: {e}")
            sys.exit(1)
    else:
        config = load_config()
    
    # Validate configuration if requested
    if args.validate or config.get("validate_on_start", False):
        if validate_config(config):
            print("Configuration validation successful")
            if args.validate:
                return
        else:
            print("Configuration validation failed. See log for details.")
            if args.validate:
                sys.exit(1)
    
    # Create and run manager
    try:
        manager = QBittorrentRcloneManager(config)
        success = manager.run()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nService stopped by user")
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}")
        logger.critical(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Fatal unhandled exception: {e}")
        logger.critical(traceback.format_exc())
        sys.exit(1)