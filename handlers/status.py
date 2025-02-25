from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from models.user_data import user_data
from utils.google_sheets import GoogleSheetsManager
import logging
from config import ADMIN_USER_USERNAMES
from utils.keyboards import show_product_selection

logger = logging.getLogger(__name__)

def setup_status_handler(bot: TeleBot):
    @bot.message_handler(commands=['status'])
    def check_status(message):
        """Allow users to check status of their shipments"""
        user_id = message.from_user.id
        
        # Show only user's products
        try:
            sheets_manager = GoogleSheetsManager.get_instance()
            worksheet = sheets_manager.get_main_worksheet()
            
            # Get all records
            all_records = worksheet.get_all_values()
            if len(all_records) <= 1:  # Only header exists
                bot.send_message(message.chat.id, "Нет доступных записей для просмотра.")
                return

            markup = InlineKeyboardMarkup()
            # Start from 1 to skip header row
            for idx, row in enumerate(all_records[1:], start=2):  # start=2 because row 1 is header
                # Filter by user_id (assuming user_id is in column 2)
                if row[1] == str(user_id):
                    product_info = f"{row[3]} - {row[7]} ({row[4]})"  # product_name - color (date)
                    markup.add(InlineKeyboardButton(
                        text=product_info,
                        callback_data=f"view_status_{idx}"
                    ))
            
            if not markup.keyboard:  # No products found for the user
                bot.send_message(message.chat.id, "Нет доступных записей для просмотра.")
                return
            
            # Add cancel button
            markup.add(InlineKeyboardButton("Отмена", callback_data="cancel_edit"))
            
            bot.send_message(message.chat.id, "Выберите изделие для просмотра статуса:", reply_markup=markup)
        except Exception as e:
            logger.error(f"Error showing product selection: {str(e)}")
            bot.send_message(message.chat.id, "Произошла ошибка при загрузке списка записей.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("view_status_"))
    def handle_status_selection(call):
        try:
            bot.answer_callback_query(call.id)
            row_index = int(call.data.split("_")[2])
            
            sheets_manager = GoogleSheetsManager.get_instance()
            record = sheets_manager.get_main_worksheet().row_values(row_index)
            
            # Display two buttons
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("Информация об изделие", callback_data=f"info_{row_index}"))
            markup.add(InlineKeyboardButton("Изменить статус изделия", callback_data=f"change_status_{row_index}"))
            
            bot.edit_message_text(
                f"Выберите действие для записи {record[3]}",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"Error handling status selection: {str(e)}")
            bot.edit_message_text(
                "❌ Ошибка при получении информации о записи.",
                call.message.chat.id,
                call.message.message_id
            )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("info_"))
    def show_product_info(call):
        try:
            bot.answer_callback_query(call.id)
            row_index = int(call.data.split("_")[1])
            
            sheets_manager = GoogleSheetsManager.get_instance()
            record = sheets_manager.get_main_worksheet().row_values(row_index)
            
            # Check if status is empty
            status = record[13] if len(record) > 13 and record[13] else "Статус не установлен"
            
            status_message = (
                f"📦 Информация о заказе:\n\n"
                f"Изделие: {record[3]}\n"
                f"Цвет: {record[7]}\n"
                f"Дата отправки: {record[4]}\n"
                f"Ожидаемая дата прибытия: {record[5]}\n"
                f"Фактическая дата прибытия: {record[6] or 'Не указано'}\n"
                f"Склад: {record[9]}\n"
                f"Общее количество: {record[8]} шт\n"
                f"Размеры:\n"
                f"S: {record[10]}\n"
                f"M: {record[11]}\n"
                f"L: {record[12]}\n"
                f"Статус: {status}"
            )
            
            bot.edit_message_text(
                status_message,
                call.message.chat.id,
                call.message.message_id
            )
        except Exception as e:
            logger.error(f"Error retrieving product info: {str(e)}")
            bot.edit_message_text(
                "❌ Ошибка при получении информации о записи.",
                call.message.chat.id,
                call.message.message_id
            )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("change_status_"))
    def change_product_status(call):
        try:
            bot.answer_callback_query(call.id)
            row_index = int(call.data.split("_")[2])
            
            # Prompt user to enter new status
            user_data.set_row_index(call.from_user.id, row_index)
            bot.send_message(
                call.message.chat.id,
                "Введите новый статус для записи:",
                reply_markup=None
            )
        except Exception as e:
            logger.error(f"Error changing product status: {str(e)}")
            bot.send_message(
                call.message.chat.id,
                "❌ Ошибка при изменении статуса.",
                reply_markup=None
            )

    @bot.message_handler(func=lambda message: user_data.get_row_index(message.from_user.id) is not None)
    def update_status(message):
        try:
            row_index = user_data.get_row_index(message.from_user.id)
            new_status = message.text
            
            sheets_manager = GoogleSheetsManager.get_instance()
            worksheet = sheets_manager.get_main_worksheet()
            worksheet.update_cell(row_index, 14, new_status)  # Update status in column 14
            
            bot.send_message(message.chat.id, f"Статус изменен на: {new_status}")
            user_data.set_row_index(message.from_user.id, None)  # Clear stored row index
        except Exception as e:
            logger.error(f"Error updating status: {str(e)}")
            bot.send_message(message.chat.id, "❌ Ошибка при обновлении статуса.")

def setup_status_handlers(bot: TeleBot):
    @bot.message_handler(commands=['status'])
    def handle_status_command(message):
        # This function is redundant with setup_status_handler's functionality.
        # You can either remove this or merge the functionality.
        pass

    # If you want to keep some functionality from setup_status_handlers,
    # you can add it here. Otherwise, you can remove this function.

# Ensure that setup_status_handler is called to register the handlers.
# setup_status_handlers can be removed or modified based on your needs.
