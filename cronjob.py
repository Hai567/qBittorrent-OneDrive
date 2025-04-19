import schedule
import time
import subprocess
import logging
import os
import json
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cronjob.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('git-cronjob')

def load_config():
    """
    Load configuration from cron_config.json file.
    If the file doesn't exist, default configuration is returned.
    """
    default_config = {
        "interval_minutes": 5,
        "git_commands": [
            ["git", "add", "."],
            ["git", "commit", "-m", "[bot] update crawling data"],
            ["git", "push", "origin", "master"]
        ]
    }
    
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cron_config.json")
    
    try:
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
                logger.info("Configuration loaded from cron_config.json")
                return config
        else:
            logger.info("No cron_config.json found, using default configuration")
            # Create a default config file for future use
            with open(config_file, 'w') as f:
                json.dump(default_config, f, indent=4)
            
            return default_config
    except Exception as e:
        logger.error(f"Error loading configuration: {str(e)}")
        return default_config

def check_for_changes():
    try:
        # Run git status to check for changes
        result = subprocess.run(
            ["git", "status", "--porcelain"], 
            capture_output=True, 
            text=True
        )
        
        # If output is empty, there are no changes
        return bool(result.stdout.strip())
    except Exception as e:
        logger.error(f"Error checking for changes: {str(e)}")
        return False

def run_git_commands(config=None):
    if config is None:
        config = load_config()
        
    try:
        logger.info("Checking for changes in repository")
        
        # Change to the directory containing the script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        os.chdir(script_dir)
        
        # Check if there are changes to commit
        if not check_for_changes():
            logger.info("No changes detected. Skipping commit and push.")
            return
        
        logger.info("Changes detected. Proceeding with commit and push.")
        
        # Use git commands from config
        commands = config.get("git_commands")
        
        for cmd in commands:
            logger.info(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"Success: {result.stdout.strip()}")
            else:
                logger.error(f"Command failed with exit code {result.returncode}")
                logger.error(f"Error message: {result.stderr.strip()}")
                # If any command fails, stop the process
                return
        
        logger.info("Git operations completed successfully")
        
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")

def main():
    logger.info("Starting cronjob scheduler")
    
    # Load configuration
    config = load_config()
    
    # Get interval from config
    interval_minutes = config.get("interval_minutes", 5)
    logger.info(f"Setting job interval to {interval_minutes} minutes")
    
    # Schedule the job to run with the specified interval
    schedule.every(interval_minutes).minutes.do(run_git_commands, config=config)
    
    # Run the job once immediately when the script starts
    run_git_commands(config)
    
    # Keep the script running
    logger.info("Scheduler running. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()