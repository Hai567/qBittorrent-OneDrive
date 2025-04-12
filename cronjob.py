import schedule
import time
import subprocess
import logging
import os
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('conjob.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('git-cronjob')

def run_git_commands():
    try:
        logger.info("Starting git commit and push job")
        
        # Change to the directory containing the script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        os.chdir(script_dir)
        
        # Run git commands
        commands = [
            ["git", "add", "."],
            ["git", "commit", "-m", "[bot] update crawling data"],
            ["git", "push", "origin", "master"]
        ]
        
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
    
    # Schedule the job to run every 5 minutes
    schedule.every(5).minutes.do(run_git_commands)
    
    # Run the job once immediately when the script starts
    run_git_commands()
    
    # Keep the script running
    logger.info("Scheduler running. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()