# utils/keyboards.py
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils.google_sheets import GoogleSheetsManager
import logging

logger = logging.getLogger(__name__)

def show_product_selection(bot, chat_id, message_text):
    """Display product selection keyboard with products from sheets"""
    try:
        sheets_manager = GoogleSheetsManager.get_instance()
        worksheet = sheets_manager.get_main_worksheet()
        
        # Get all records
        all_records = worksheet.get_all_values()
        if len(all_records) <= 1:  # Only header exists
            bot.send_message(chat_id, "Нет доступных записей для редактирования.")
            return

        markup = InlineKeyboardMarkup()
        # Start from 1 to skip header row
        for idx, row in enumerate(all_records[1:], start=2):  # start=2 because row 1 is header
            # Assuming columns are: timestamp, user_id, username, product_name, etc.
            product_info = f"{row[3]} - {row[7]} ({row[4]})"  # product_name - color (date)
            markup.add(InlineKeyboardButton(
                text=product_info,
                callback_data=f"delete_{idx}"
            ))
        
        # Add cancel button
        markup.add(InlineKeyboardButton("Отмена", callback_data="cancel_edit"))
        
        bot.send_message(chat_id, message_text, reply_markup=markup)
    except Exception as e:
        logger.error(f"Error showing product selection: {str(e)}")
        bot.send_message(chat_id, "Произошла ошибка при загрузке списка записей.")