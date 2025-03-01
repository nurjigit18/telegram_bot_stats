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
            user_records = []  # Store records for the user
            for idx, row in enumerate(all_records[1:], start=2):  # start=2 because row 1 is header
                # Filter by user_id (assuming user_id is in column 2)
                if row[1] == str(user_id):
                    product_info = f"{row[3]} - {row[7]} ({row[4]})"  # product_name - color (date)
                    markup.add(InlineKeyboardButton(
                        text=product_info,
                        callback_data=f"view_status_{idx}"
                    ))
                    user_records.append((idx, row))  # Store the record

            if not markup.keyboard:  # No products found for the user
                bot.send_message(message.chat.id, "Нет доступных записей для просмотра.")
                return

            # Store user_records in user_data
            user_data.initialize_user(user_id)
            user_data.update_user_data(user_id, "user_records", user_records)  # Store for later

            # Add cancel button
            markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_edit"))

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
            markup.add(InlineKeyboardButton("📋 Информация об изделие", callback_data=f"info_{row_index}"))
            markup.add(InlineKeyboardButton("✏️ Изменить статус изделия", callback_data=f"change_status_{row_index}"))

            # Add Back button
            markup.add(InlineKeyboardButton("⬅️ Назад", callback_data="back_to_status_list"))

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

    @bot.callback_query_handler(func=lambda call: call.data == "back_to_status_list")
    def back_to_status_list(call):
        try:
            user_id = call.from_user.id

            # Retrieve the stored user_records from user_data
            user_records = user_data.get_user_data(user_id).get("user_records")

            if not user_records:
                bot.send_message(call.message.chat.id, "❌ Ошибка: список записей не найден.")
                return

            # Re-display the status list using the stored user_records
            show_status_list(bot, call.message.chat.id, user_records, call.message.message_id)

        except Exception as e:
            logger.error(f"Error handling back to status list: {str(e)}")
            bot.send_message(call.message.chat.id, "❌ Ошибка при возврате к списку статусов.")

    def show_status_list(bot, chat_id, user_records, message_id=None):
        markup = InlineKeyboardMarkup()
        for idx, record in user_records:
            product_info = f"{record[3]} - {record[7]} ({record[4]})"  # product_name - color (date)
            markup.add(InlineKeyboardButton(
                text=product_info,
                callback_data=f"view_status_{idx}"
            ))

        # Add cancel button
        markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_edit"))

        if message_id:
            bot.edit_message_text(
                "Выберите изделие для просмотра статуса:",
                chat_id,
                message_id,
                reply_markup=markup
            )
        else:
            bot.send_message(
                chat_id,
                "Выберите изделие для просмотра статуса:",
                reply_markup=markup
            )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("info_"))
    def show_product_info(call):
        try:
            bot.answer_callback_query(call.id)
            row_index = int(call.data.split("_")[1])

            sheets_manager = GoogleSheetsManager.get_instance()
            record = sheets_manager.get_main_worksheet().row_values(row_index)

            # Check if status is empty
            status = record[11] if len(record) > 11 and record[11] else "Статус не установлен"

            # Get sizes from column 10 (previously scattered across multiple columns)
            sizes_data = record[10] if len(record) > 10 else "Не указано"

            status_message = (
                f"📦 Информация о заказе:\n\n"
                f"Изделие: {record[3]}\n"
                f"Цвет: {record[7]}\n"
                f"Дата отправки: {record[4]}\n"
                f"Ожидаемая дата прибытия: {record[5]}\n"
                f"Фактическая дата прибытия: {record[6] or 'Не указано'}\n"
                f"Склад: {record[9]}\n"
                f"Общее количество: {record[8]} шт\n"
                f"Размеры: {sizes_data}\n"
                f"Статус: {status}"
            )

            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("⬅️ Назад", callback_data=f"view_status_{row_index}"))  # Back to status options

            bot.edit_message_text(
                status_message,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
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

            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("⬅️ Назад", callback_data=f"view_status_{row_index}"))  # Back to status options

            bot.send_message(
                call.message.chat.id,
                "✏️ Введите новый статус для записи:",
                reply_markup=markup
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
            worksheet.update_cell(row_index, 12, new_status)  # Update status in column 12 (adjusted from 14)

            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("К списку статусов", callback_data="back_to_status_list"))

            bot.send_message(message.chat.id, f"Статус изменен на: {new_status}", reply_markup=markup)
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
