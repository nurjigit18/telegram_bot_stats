# handlers/start.py
from telebot import TeleBot
from utils.google_sheets import GoogleSheetsManager
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def setup_start_handler(bot: TeleBot):
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        user_id = message.from_user.id
        username = message.from_user.username or "Unknown"
        first_name = message.from_user.first_name or ""

        try:
            sheets_manager = GoogleSheetsManager.get_instance()
            users_sheet = sheets_manager.get_users_worksheet()
            
            # Check if user already exists
            user_exists = False
            try:
                user_cells = users_sheet.findall(str(user_id))
                user_exists = len(user_cells) > 0
            except:
                user_exists = False
            
            if not user_exists:
                # Add registration date
                registration_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                users_sheet.append_row([user_id, username, first_name, registration_date])
                logger.info(f"Saved user {username} with ID {user_id} to Google Sheets")

        except Exception as e:
            logger.error(f"Error saving user to Google Sheets: {str(e)}")

        welcome_text = (
            "👋 Welcome to the Product Tracking Bot!\n\n"
            "Нажмите /save чтобы ввести данные изделия.\n"
            "Нажмите /edit чтобы редактировать данные.\n"
            "Нажмите /status чтобы проверить статус вашего изделия.\n"
            "Нажмите /payment чтобы отправить чек опалыт.\n"
            "Нажмите /help для подробной информации.\n\n"
            "Пожалуйста введите все данные при заполнение."
        )
        bot.reply_to(message, welcome_text)