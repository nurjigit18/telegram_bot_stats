from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from models.user_data import user_data
from utils.google_sheets import GoogleSheetsManager
import logging
from config import ADMIN_USER_USERNAMES
from utils.keyboards import show_product_selection
from datetime import datetime
import math
import pytz

logger = logging.getLogger(__name__)

# Pagination settings
ITEMS_PER_PAGE = 5  # Number of items to show per page

def setup_status_handler(bot: TeleBot):
    @bot.message_handler(commands=['status'])
    def check_status(message):
        """Allow users to check status of their shipments"""
        user_id = message.from_user.id

        # Show only user's products with pagination
        try:
            sheets_manager = GoogleSheetsManager.get_instance()
            worksheet = sheets_manager.get_main_worksheet()

            # Get all records
            all_records = worksheet.get_all_values()
            if len(all_records) <= 1:  # Only header exists
                bot.send_message(message.chat.id, "Нет доступных записей для просмотра.")
                return

            # Filter records by user_id
            user_records = []
            for idx, row in enumerate(all_records[1:], start=2):  # start=2 because row 1 is header
                # Filter by user_id (assuming user_id is in column 2)
                if row[1] == str(user_id):
                    user_records.append((idx, row))

            if not user_records:  # No products found for the user
                bot.send_message(message.chat.id, "Нет доступных записей для просмотра.")
                return

            # Store user_records in user_data
            user_data.initialize_user(user_id)
            user_data.update_user_data(user_id, "user_records", user_records)
            user_data.update_user_data(user_id, "current_page", 0)  # Start from page 0

            # Show first page
            show_status_list_paginated(bot, message.chat.id, user_records, 0)

        except Exception as e:
            logger.error(f"Error showing product selection: {str(e)}")
            bot.send_message(message.chat.id, "Произошла ошибка при загрузке списка записей.")

    def show_status_list_paginated(bot, chat_id, user_records, page, message_id=None):
        """Display paginated list of user records"""
        total_items = len(user_records)
        total_pages = math.ceil(total_items / ITEMS_PER_PAGE)
        
        if page < 0:
            page = 0
        elif page >= total_pages:
            page = total_pages - 1

        start_idx = page * ITEMS_PER_PAGE
        end_idx = min(start_idx + ITEMS_PER_PAGE, total_items)
        page_records = user_records[start_idx:end_idx]

        markup = InlineKeyboardMarkup()
        
        # Add product buttons for current page
        for idx, record in page_records:
            product_info = f"{record[3]} - {record[7]} ({record[4]})"  # product_name - color (date)
            markup.add(InlineKeyboardButton(
                text=product_info,
                callback_data=f"view_status_{idx}"
            ))

        # Add pagination buttons if needed
        if total_pages > 1:
            nav_buttons = []
            
            # Previous button
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("⬅️ Предыдущая", callback_data=f"page_{page-1}"))
            
            # Page indicator
            nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="current_page"))
            
            # Next button
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton("Следующая ➡️", callback_data=f"page_{page+1}"))
            
            markup.row(*nav_buttons)

        # Add cancel button
        markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_edit"))

        message_text = f"Выберите изделие для просмотра статуса:\n\nСтраница {page+1} из {total_pages} (всего записей: {total_items})"

        if message_id:
            bot.edit_message_text(
                message_text,
                chat_id,
                message_id,
                reply_markup=markup
            )
        else:
            bot.send_message(
                chat_id,
                message_text,
                reply_markup=markup
            )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("page_"))
    def handle_page_navigation(call):
        """Handle page navigation"""
        try:
            bot.answer_callback_query(call.id)
            user_id = call.from_user.id
            page = int(call.data.split("_")[1])
            
            # Get stored user records
            user_records = user_data.get_user_data(user_id).get("user_records")
            if not user_records:
                bot.edit_message_text(
                    "❌ Ошибка: список записей не найден.",
                    call.message.chat.id,
                    call.message.message_id
                )
                return

            # Update current page in user data
            user_data.update_user_data(user_id, "current_page", page)
            
            # Show the requested page
            show_status_list_paginated(bot, call.message.chat.id, user_records, page, call.message.message_id)

        except Exception as e:
            logger.error(f"Error handling page navigation: {str(e)}")
            bot.edit_message_text(
                "❌ Ошибка при навигации по страницам.",
                call.message.chat.id,
                call.message.message_id
            )

    @bot.callback_query_handler(func=lambda call: call.data == "current_page")
    def handle_current_page_click(call):
        """Handle click on page indicator (no action needed)"""
        bot.answer_callback_query(call.id, "Текущая страница")

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

            # Retrieve the stored user_records and current page from user_data
            user_records = user_data.get_user_data(user_id).get("user_records")
            current_page = user_data.get_user_data(user_id).get("current_page", 0)

            if not user_records:
                bot.send_message(call.message.chat.id, "❌ Ошибка: список записей не найден.")
                return

            # Re-display the status list using the stored user_records and current page
            show_status_list_paginated(bot, call.message.chat.id, user_records, current_page, call.message.message_id)

        except Exception as e:
            logger.error(f"Error handling back to status list: {str(e)}")
            bot.send_message(call.message.chat.id, "❌ Ошибка при возврате к списку статусов.")

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
                "✏️ Введите новый статус для записи, например (В производстве, Отправлено из цеха, В пути, Отгружено):",
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
            user_id = message.from_user.id
            username = message.from_user.first_name or f"User ID: {user_id}"
            row_index = user_data.get_row_index(user_id)
            new_status = message.text

            # Get the sheet manager and worksheet
            sheets_manager = GoogleSheetsManager.get_instance()
            worksheet = sheets_manager.get_main_worksheet()

            # Get the current record to include in the notification
            record = worksheet.row_values(row_index)
            product_name = record[3] if len(record) > 3 else "Unknown product"
            product_color = record[7] if len(record) > 7 else "Unknown color"

            # Update status in column 12
            worksheet.update_cell(row_index, 12, new_status)

            # Prepare response for the user
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("К списку статусов", callback_data="back_to_status_list"))
            bot.send_message(message.chat.id, f"✅ Статус изменен на: {new_status}", reply_markup=markup)

            # Send notifications to all admins
            notification_text = (
                f"🔔 Уведомление об изменении статуса\n\n"
                f"Пользователь: @{username}\n"
                f"Изделие: {product_name}\n"
                f"Цвет: {product_color}\n"
                f"Новый статус: {new_status}\n"
                f"Дата изменения: {datetime.now(pytz.timezone('Asia/Bishkek')).strftime('%Y-%m-%d %H:%M:%S')}"
            )

            # Send notification to each admin
            for admin_username in ADMIN_USER_USERNAMES:
                try:
                    # We need to get the admin's chat_id from the users worksheet
                    users_worksheet = sheets_manager.get_users_worksheet()
                    all_users = users_worksheet.get_all_values()

                    # Find admin's chat_id by username
                    admin_chat_id = None
                    for user_row in all_users[1:]:  # Skip header
                        if len(user_row) > 1 and user_row[1] == admin_username:
                            admin_chat_id = int(user_row[0])
                            break

                    if admin_chat_id:
                        bot.send_message(admin_chat_id, notification_text)
                        logger.info(f"Notification sent to admin {admin_username}")
                    else:
                        logger.warning(f"Admin {admin_username} not found in users worksheet")
                except Exception as admin_error:
                    logger.error(f"Failed to notify admin {admin_username}: {str(admin_error)}")

            # Clear stored row index
            user_data.set_row_index(user_id, None)

        except Exception as e:
            logger.error(f"Error updating status: {str(e)}")
            bot.send_message(message.chat.id, "❌ Ошибка при обновлении статуса.")
            # Still clear the row index in case of error
            user_data.set_row_index(message.from_user.id, None)