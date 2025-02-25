# utils/announcements.py
from telebot import TeleBot
from utils.google_sheets import get_all_user_chat_ids
import logging

logger = logging.getLogger(__name__)

def send_announcement_to_all_users(bot: TeleBot, message, announcement: str):
    """Send an announcement to all users."""
    chat_ids = get_all_user_chat_ids()
    if not chat_ids:
        bot.reply_to(message, "Не был найден ни один пользователь.")
        return
    
    success_count = 0
    failure_count = 0
    
    for chat_id in chat_ids:
        try:
            bot.send_message(chat_id, announcement)
            success_count += 1
        except Exception as e:
            logger.error(f"Отказано в отправке {chat_id}: {str(e)}")
            failure_count += 1
    
    # Notify the admin of the result
    result_message = (
        f"Обьявление отправлено {success_count} пользователям.\n"
        f"Ошибка отправки {failure_count} пользователям."
    )
    bot.reply_to(message, result_message)

def send_announcement_to_user(bot: TeleBot, user_id: int, announcement: str):
    """Send an announcement to a specific user."""
    try:
        bot.send_message(user_id, announcement)
    except Exception as e:
        logger.error(f"Error sending message to user {user_id}: {str(e)}")
        raise
    
def process_news_announcement(bot, message):
    announcement = message.text
    send_announcement_to_all_users(bot, message, announcement)

def send_photo_to_all_users(bot: TeleBot, message, photo_file_id: str):
    """Send a photo to all users."""
    chat_ids = get_all_user_chat_ids()
    if not chat_ids:
        bot.reply_to(message, "Не был найден ни один пользователь.")
        return
    
    success_count = 0
    failure_count = 0
    
    for chat_id in chat_ids:
        try:
            bot.send_photo(chat_id, photo_file_id)
            success_count += 1
        except Exception as e:
            logger.error(f"Отказано в отправке {chat_id}: {str(e)}")
            failure_count += 1
    
    # Notify the admin of the result
    result_message = (
        f"Фото отправлено {success_count} пользователям.\n"
        f"Ошибка отправки {failure_count} пользователям."
    )
    bot.reply_to(message, result_message)

def send_photo_to_user(bot: TeleBot, user_id: int, photo_file_id: str):
    """Send a photo to a specific user."""
    try:
        bot.send_photo(user_id, photo_file_id)
    except Exception as e:
        logger.error(f"Error sending photo to user {user_id}: {str(e)}")
        raise

def send_file_to_all_users(bot: TeleBot, message, file_id: str):
    """Send a file to all users."""
    chat_ids = get_all_user_chat_ids()
    if not chat_ids:
        bot.reply_to(message, "Не был найден ни один пользователь.")
        return
    
    success_count = 0
    failure_count = 0
    
    for chat_id in chat_ids:
        try:
            bot.send_document(chat_id, file_id)
            success_count += 1
        except Exception as e:
            logger.error(f"Отказано в отправке {chat_id}: {str(e)}")
            failure_count += 1
    
    # Notify the admin of the result
    result_message = (
        f"Файл отправлен {success_count} пользователям.\n"
        f"Ошибка отправки {failure_count} пользователям."
    )
    bot.reply_to(message, result_message)

def send_file_to_user(bot: TeleBot, user_id: int, file_id: str):
    """Send a file to a specific user."""
    try:
        bot.send_document(user_id, file_id)
    except Exception as e:
        logger.error(f"Error sending file to user {user_id}: {str(e)}")
        raise