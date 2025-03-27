import sys
import os
import logging
import threading
import time
import signal
import traceback
import fcntl
import gc
import psutil
from datetime import datetime
from telebot import TeleBot
from config import BOT_TOKEN
from utils.google_sheets import GoogleSheetsManager
from utils.google_sheets import connect_to_google_sheets
from handlers.start import setup_start_handler
from handlers.save import setup_save_handler
from handlers.edit import setup_edit_handler
from handlers.admin import setup_admin_handler
from handlers.status import setup_status_handler
from handlers.default import setup_default_handler
from handlers.announcements import setup_announcement_handlers
from handlers.deletion import setup_deletion_handlers
from handlers.help import setup_help_handler
from handlers.sender import setup_file_sender_handlers

# Configure logging with rotation
import logging.handlers

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

# Set up rotating file handler
log_handler = logging.handlers.RotatingFileHandler(
    'logs/bot.log',
    maxBytes=1024 * 1024,  # 1MB
    backupCount=5,  # Keep more backups
    encoding='utf-8'
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[log_handler]
)

# Reduce logging from telegram library
logging.getLogger('telebot').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Constants
HEARTBEAT_FILE = 'heartbeat.txt'
LOCK_FILE = 'bot.lock'
MEMORY_LIMIT_MB = 400 
MEMORY_CHECK_INTERVAL = 900  # Check memory every 15 minutes
MAX_RUNTIME_SECONDS = 48000  # Restart after ~8hours

# Global state tracking
class BotState:
    running = True
    last_activity = time.time()
    errors_count = 0
    last_reconnect = None
    start_time = time.time()

state = BotState()


def acquire_lock():
    """
    Ensure only one instance of the bot is running using file locking.
    Returns True if lock acquired, False otherwise.
    """
    try:
        # Check if the lock file exists and if the process is still running
        if os.path.exists(LOCK_FILE):
            try:
                with open(LOCK_FILE, 'r') as f:
                    old_pid = int(f.read().strip())

                # Check if process with this PID exists
                try:
                    os.kill(old_pid, 0)
                    # If we get here, process exists
                    logger.error(f"Another instance is already running (PID: {old_pid})")
                    return False
                except OSError:
                    # Process doesn't exist, we can remove the stale lock
                    logger.warning(f"Removing stale lock file from PID {old_pid}")
                    os.remove(LOCK_FILE)
            except (ValueError, FileNotFoundError):
                # Invalid PID or file disappeared, remove it
                if os.path.exists(LOCK_FILE):
                    os.remove(LOCK_FILE)

        # Open the lock file
        lock_file_fd = open(LOCK_FILE, 'w')

        # Try to acquire an exclusive lock (non-blocking)
        fcntl.flock(lock_file_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # Store the file descriptor to keep the lock
        state.lock_file_fd = lock_file_fd

        # Write PID to lock file
        lock_file_fd.write(str(os.getpid()))
        lock_file_fd.flush()

        logger.info(f"Lock acquired by PID {os.getpid()}")
        return True

    except IOError:
        # Another instance has the lock
        try:
            with open(LOCK_FILE, 'r') as f:
                pid = f.read().strip()
                logger.error(f"Another instance is already running (PID: {pid})")
        except:
            logger.error("Another instance is already running")

        return False

def release_lock():
    """Release the lock file"""
    if hasattr(state, 'lock_file_fd'):
        try:
            # Release the lock and close the file
            fcntl.flock(state.lock_file_fd, fcntl.LOCK_UN)
            state.lock_file_fd.close()

            # Remove the lock file
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)

            logger.info("Lock released and file removed")
        except Exception as e:
            logger.error(f"Error releasing lock: {e}")

def get_memory_usage():
    """Get current memory usage in MB"""
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    return memory_info.rss / 1024 / 1024  # Convert to MB

def update_heartbeat():
    """Update the heartbeat file to indicate the bot is alive"""
    try:
        memory_usage = get_memory_usage()
        runtime = time.time() - state.start_time

        with open(HEARTBEAT_FILE, 'w') as f:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"Bot alive at: {now}\n")
            f.write(f"PID: {os.getpid()}\n")
            f.write(f"Memory usage: {memory_usage:.2f} MB\n")
            f.write(f"Uptime: {runtime:.1f} seconds\n")
            f.write(f"Errors count: {state.errors_count}\n")
            f.write(f"Last reconnect: {state.last_reconnect}\n")

        logger.info(f"Memory usage: {memory_usage:.2f} MB, Uptime: {runtime:.1f} seconds")
    except Exception as e:
        logger.error(f"Failed to update heartbeat: {e}")

def memory_monitor():
    """Monitor memory usage and restart if necessary"""
    while state.running:
        try:
            memory_usage = get_memory_usage()
            runtime = time.time() - state.start_time

            # Check if we should restart due to memory usage
            if memory_usage > MEMORY_LIMIT_MB:
                logger.warning(f"Memory usage too high ({memory_usage:.2f} MB). Initiating restart.")
                state.running = False
                break

            # Check if we should restart due to runtime
            if runtime > MAX_RUNTIME_SECONDS:
                logger.warning(f"Runtime too long ({runtime:.1f} seconds). Initiating restart.")
                state.running = False
                break

            # Force garbage collection to reduce memory usage
            collected = gc.collect()
            if collected > 0:
                logger.info(f"Garbage collector: collected {collected} objects")

        except Exception as e:
            logger.error(f"Error in memory monitor: {e}")

        # Sleep to reduce CPU usage
        time.sleep(MEMORY_CHECK_INTERVAL)

def initialize_google_sheets():
    """Initialize Google Sheets with error handling"""
    try:
        logger.info("Connecting to Google Sheets...")
        sheets_manager = GoogleSheetsManager.get_instance()
        logger.info("Google Sheets connection successful")
        return sheets_manager
    except Exception as e:
        state.errors_count += 1
        error_msg = f"Failed to initialize Google Sheets: {e}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        return None

def graceful_shutdown(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    state.running = False
    release_lock()
    # Give threads time to clean up
    time.sleep(2)
    sys.exit(0)

def bot_polling(bot):
    """Function to run the bot with robust error handling"""
    consecutive_errors = 0
    while state.running:
        try:
            logger.info("Bot is starting polling...")
            # Use conservative settings to avoid conflicts
            bot.infinity_polling(
                timeout=10,
                long_polling_timeout=30,
                none_stop=True,
                interval=30,  # Poll every 30 seconds to reduce CPU usage
                allowed_updates=["message", "callback_query", "inline_query"]  # Only listen for needed updates
            )
        except Exception as e:
            state.errors_count += 1
            consecutive_errors += 1

            # Calculate backoff time based on consecutive errors
            backoff_time = min(60, 2 ** consecutive_errors)

            error_msg = f"Bot polling error: {e}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())

            logger.info(f"Restarting polling in {backoff_time} seconds... (Attempt {consecutive_errors})")
            time.sleep(backoff_time)

            # If too many consecutive errors, try to reset the bot connection
            if consecutive_errors >= 5:
                logger.warning("Too many consecutive errors, resetting bot connection")
                return False
        else:
            # Reset error counter on successful polling
            consecutive_errors = 0

    return True

def main():
    """Main function with single-instance locking"""
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    # Check for existing instances
    if not acquire_lock():
        logger.error("Failed to acquire lock. Exiting.")
        sys.exit(1)

    try:
        # Record startup
        logger.info(f"Bot starting up... PID: {os.getpid()}")
        state.last_reconnect = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state.start_time = time.time()

        # Initialize memory monitor
        memory_thread = threading.Thread(target=memory_monitor, daemon=True)
        memory_thread.start()

        # Update heartbeat immediately
        update_heartbeat()

        # Initialize heartbeat monitor (less frequent updates)
        heartbeat_thread = threading.Thread(target=lambda:
            [update_heartbeat() or time.sleep(300) for _ in iter(int, 1) if state.running],
            daemon=True)
        heartbeat_thread.start()

        # Initialize Google Sheets
        sheets_manager = initialize_google_sheets()
        if sheets_manager is None:
            logger.error("Could not initialize Google Sheets. Exiting.")
            release_lock()
            sys.exit(1)

        # Initialize bot
        bot = TeleBot(BOT_TOKEN)

        # Set up handlers
        handlers = [
            setup_start_handler,
            setup_save_handler,
            setup_help_handler,
            setup_edit_handler,
            setup_admin_handler,
            setup_status_handler,
            setup_file_sender_handlers,
            setup_default_handler,
            setup_announcement_handlers,
            setup_deletion_handlers
        ]

        for handler in handlers:
            try:
                handler(bot)
            except Exception as handler_error:
                logger.error(f"Error setting up handler {handler.__name__}: {handler_error}")

        # Run the bot with polling
        while state.running:
            success = bot_polling(bot)
            if not success and state.running:
                logger.info("Reinitializing bot after polling failure...")
                time.sleep(5)
                # Create a new bot instance
                bot = TeleBot(BOT_TOKEN)
                # Re-setup all handlers
                for handler in handlers:
                    try:
                        handler(bot)
                    except Exception as handler_error:
                        logger.error(f"Error setting up handler {handler.__name__}: {handler_error}")

    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        logger.critical(traceback.format_exc())

    finally:
        # Always release the lock when exiting
        release_lock()

        # If we're exiting due to memory/runtime limits, exit with code 0
        # so the watchdog can restart us cleanly
        if not state.running:
            logger.info("Exiting for planned restart")
            sys.exit(0)
        else:
            sys.exit(1)

if __name__ == "__main__":
    main()
