#!/usr/bin/env python3
import os
import time
import subprocess
import logging
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/watchdog.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Constants
HEARTBEAT_FILE = 'heartbeat.txt'
BOT_SCRIPT = 'main.py'
MAX_HEARTBEAT_AGE = 10 * 60  # 10 minutes
CHECK_INTERVAL = 5 * 60  # 5 minutes

def is_bot_running():
    """Check if the bot is running by verifying the heartbeat file"""
    try:
        # Check if heartbeat file exists
        if not os.path.exists(HEARTBEAT_FILE):
            logger.warning("Heartbeat file does not exist")
            return False
        
        # Check heartbeat file age
        file_stat = os.stat(HEARTBEAT_FILE)
        file_age = time.time() - file_stat.st_mtime
        
        if file_age > MAX_HEARTBEAT_AGE:
            logger.warning(f"Heartbeat file is too old: {file_age:.1f} seconds")
            return False
            
        # Read the heartbeat file
        with open(HEARTBEAT_FILE, 'r') as f:
            content = f.read()
            
        # Check if the content looks valid
        if "Bot alive at:" not in content:
            logger.warning("Heartbeat file content is invalid")
            return False
            
        logger.info("Bot appears to be running correctly")
        return True
    except Exception as e:
        logger.error(f"Error checking bot status: {e}")
        return False

def start_bot():
    """Start the bot script"""
    try:
        # Kill any existing bot processes
        try:
            subprocess.run("pkill -f '" + BOT_SCRIPT + "'", shell=True)
            logger.info("Killed existing bot processes")
        except Exception as e:
            logger.warning(f"Failed to kill existing processes: {e}")
        
        # Start the bot as a background process
        command = f"nohup python3 {BOT_SCRIPT} > logs/bot_stdout.log 2> logs/bot_stderr.log &"
        subprocess.run(command, shell=True)
        logger.info(f"Started bot: {command}")
        
        # Give the bot time to initialize
        time.sleep(10)
        
        # Verify the bot started successfully
        if is_bot_running():
            logger.info("Bot started successfully")
            return True
        else:
            logger.error("Bot failed to start properly")
            return False
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        return False

def main():
    """Main watchdog function"""
    logger.info("Watchdog started")
    
    os.makedirs('logs', exist_ok=True)
    
    while True:
        if not is_bot_running():
            logger.warning("Bot is not running, attempting to restart")
            start_bot()
        
        # Log watchdog status
        logger.info("Watchdog check completed")
        
        # Sleep between checks
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()