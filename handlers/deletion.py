# handlers/deletion.py
from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from models.user_data import user_data
from utils.google_sheets import GoogleSheetsManager

import logging
from config import ADMIN_USER_USERNAMES
from utils.keyboards import show_product_selection

logger = logging.getLogger(__name__)

def show_delete_confirmation(bot, chat_id, row_index):
    """Display confirmation dialog for record deletion"""
    try:
        # Get product info for confirmation message
        sheets_manager = GoogleSheetsManager.get_instance()
        row_data = sheets_manager.get_main_worksheet().row_values(row_index)
        product_name = row_data[3] if len(row_data) > 3 else "Unknown"
        product_color = row_data[7] if len(row_data) > 7 else "Unknown"
        
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("Да", callback_data=f"confirm_delete_{row_index}"),
            InlineKeyboardButton("Нет", callback_data=f"cancel_delete_{row_index}")
        )
        
        confirmation_message = (
            f"⚠️ Вы уверены, что хотите удалить эту запись?\n\n"
            f"Изделие: {product_name}\n"
            f"Цвет: {product_color}\n\n"
            f"Это действие невозможно отменить."
        )
        
        bot.send_message(chat_id, confirmation_message, reply_markup=markup)
    except Exception as e:
        logger.error(f"Error preparing delete confirmation: {str(e)}")
        bot.send_message(chat_id, "❌ Ошибка при подготовке подтверждения удаления.")

def setup_deletion_handlers(bot: TeleBot):
    @bot.callback_query_handler(func=lambda call: call.data == "admin_delete_record")
    def handle_delete_record(call):
        bot.answer_callback_query(call.id)
        # Removed the fourth argument "delete_"
        show_product_selection(bot, call.message.chat.id, "Выберите запись для удаления:")
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("delete_"))
    def handle_delete_selection(call):
        bot.answer_callback_query(call.id)
        row_index = int(call.data.split("_")[1])
        # Show confirmation dialog
        show_delete_confirmation(bot, call.message.chat.id, row_index)
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_delete_"))
    def handle_delete_confirmation(call):
        bot.answer_callback_query(call.id)
        row_index = int(call.data.split("_")[2])
        try:
            # Get product info before deletion for confirmation message
            sheets_manager = GoogleSheetsManager.get_instance()
            row_data = sheets_manager.get_main_worksheet().row_values(row_index)
            product_name = row_data[3] if len(row_data) > 3 else "Unknown"
            product_color = row_data[7] if len(row_data) > 7 else "Unknown"
            
            # Delete the row
            sheets_manager = GoogleSheetsManager.get_instance()
            sheets_manager.get_main_worksheet().delete_rows(row_index)
            bot.edit_message_text(
                f"✅ Запись удалена успешно!\nИзделие: {product_name}\nЦвет: {product_color}",
                call.message.chat.id,
                call.message.message_id
            )
        except Exception as e:
            logger.error(f"Error deleting row {row_index}: {str(e)}")
            bot.edit_message_text(
                f"❌ Ошибка при удалении записи. Пожалуйста, попробуйте позже.",
                call.message.chat.id,
                call.message.message_id
            )
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_delete_"))
    def handle_delete_cancellation(call):
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            "🚫 Удаление отменено.",
            call.message.chat.id,
            call.message.message_id
        )