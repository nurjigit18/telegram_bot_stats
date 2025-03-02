import sys
import os
import logging
from flask import Flask
from telebot import TeleBot
from config import BOT_TOKEN
from utils.google_sheets import connect_to_google_sheets
from handlers.start import setup_start_handler
from handlers.save import setup_save_handler
from handlers.edit import setup_edit_handler
from handlers.admin import setup_admin_handler
from handlers.status import setup_status_handler
# from handlers.payment import setup_payment_handler
from handlers.default import setup_default_handler
from handlers.announcements import setup_announcement_handlers
from handlers.status import setup_status_handlers
from handlers.deletion import setup_deletion_handlers
from handlers.help import setup_help_handler
from handlers.sender import setup_file_sender_handlers
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def bot_polling():
    """Function to run the bot in a separate thread"""
    logger.info("Starting Product Tracking Bot...")
    try:
        # Start the bot
        logger.info("Bot is running...")
        bot.infinity_polling()
    except Exception as e:
        logger.error(f"Bot polling error: {str(e)}")

# Ensure proper path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Initialize Google Sheets
try:
    sheets_manager = connect_to_google_sheets()
except Exception as e:
    logger.error(f"Failed to initialize Google Sheets: {str(e)}")
    sys.exit(1)

# Initialize bot
bot = TeleBot(BOT_TOKEN)

# Set up handlers
setup_start_handler(bot)
setup_save_handler(bot)
setup_help_handler(bot)
setup_edit_handler(bot)
setup_admin_handler(bot)
setup_status_handler(bot)
setup_file_sender_handlers(bot)
# setup_payment_handler(bot)
setup_default_handler(bot)
setup_announcement_handlers(bot)
setup_status_handlers(bot)
setup_deletion_handlers(bot)

# Start the bot in a separate thread
bot_thread = threading.Thread(target=bot_polling)
bot_thread.daemon = True
bot_thread.start()

if __name__ == "__main__":
    # Get port from environment variable or use default
    port = int(os.environ.get("PORT", 8080))
    # Run the Flask app
    app.run(host='0.0.0.0', port=port)