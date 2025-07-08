from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from models.user_data import user_data
from utils.keyboards import show_product_selection
from utils.validators import validate_date, standardize_date, validate_amount, validate_size_amounts, parse_size_amounts
from utils.google_sheets import GoogleSheetsManager
import math
import logging

logger = logging.getLogger(__name__)

# Pagination settings
ITEMS_PER_PAGE = 5  # Number of items to show per page

def parse_new_size_format(size_input):
    """
    Parse size input in format: S-10, XL-20, 7XL-30
    Returns dictionary with size as key and amount as value
    """
    sizes = {}
    try:
        # Split by comma and process each size-amount pair
        pairs = [pair.strip() for pair in size_input.split(',')]
        for pair in pairs:
            if '-' not in pair:
                continue
            size, amount = pair.split('-', 1)  # Split only on first dash
            size = size.strip().upper()
            amount = int(amount.strip())
            sizes[size] = amount
        return sizes
    except (ValueError, AttributeError):
        return None

def validate_new_size_format(size_input):
    """
    Validate size input format: S-10, XL-20, 7XL-30
    """
    if not size_input or not isinstance(size_input, str):
        return False
    
    try:
        pairs = [pair.strip() for pair in size_input.split(',')]
        for pair in pairs:
            if '-' not in pair:
                return False
            size, amount = pair.split('-', 1)
            size = size.strip()
            amount = amount.strip()
            
            # Check if size is not empty and amount is a valid integer
            if not size or not amount.isdigit():
                return False
        return True
    except:
        return False

def get_size_column_mapping():
    """
    Returns mapping of size names to column numbers (starting from column 10)
    Adjust this mapping based on your actual Google Sheets column layout
    """
    return {
        'XS': 10,
        'S': 11, 
        'M': 12,
        'L': 13,
        'XL': 14,
        '2XL': 15,
        '3XL': 16,
        '4XL': 17,
        '5XL': 18,
        '6XL': 19,
        '7XL': 20,
        # Add more sizes as needed
    }


def setup_edit_handlers(bot: TeleBot):
    @bot.callback_query_handler(func=lambda call: call.data.startswith("edit_") or call.data == "cancel_edit" or call.data.startswith("product_"))
    def handle_edit_query(call):
        user_id = call.from_user.id

        # Initialize user_data for editing if not exists
        if not user_data.has_user(user_id):
            user_data.initialize_user(user_id)
            user_data.update_user_data(user_id, "editing_row", None)

        if call.data == "edit_shipment_date":
            bot.answer_callback_query(call.id)
            user_data.set_current_action(user_id, "editing_shipment_date")
            show_product_selection(bot, call.message.chat.id, "Выберите изделие для редактирования даты отправки:")

        elif call.data == "edit_estimated_arrival":
            bot.answer_callback_query(call.id)
            user_data.set_current_action(user_id, "editing_estimated_arrival")
            show_product_selection(bot, call.message.chat.id, "Выберите изделие для редактирования ожидаемой даты прибытия:")

        elif call.data == "add_actual_arrival":
            bot.answer_callback_query(call.id)
            user_data.set_current_action(user_id, "adding_actual_arrival")
            show_product_selection(bot, call.message.chat.id, "Выберите изделие для добавления фактической даты прибытия:")

        elif call.data == "edit_color":
            bot.answer_callback_query(call.id)
            user_data.set_current_action(user_id, "editing_color")
            show_product_selection(bot, call.message.chat.id, "Выберите изделие для редактирования цвета:")

        elif call.data == "edit_amount":
            bot.answer_callback_query(call.id)
            user_data.set_current_action(user_id, "editing_amount")
            show_product_selection(bot, call.message.chat.id, "Выберите изделие для редактирования количества:")

        elif call.data == "edit_sizes":
            bot.answer_callback_query(call.id)
            user_data.set_current_action(user_id, "editing_sizes")
            show_product_selection(bot, call.message.chat.id, "Выберите изделие для редактирования размеров:")

        elif call.data == "cancel_edit":
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, "Редактирование отменено.")
            user_data.clear_user_data(user_id)

        elif call.data.startswith("product_"):
            bot.answer_callback_query(call.id)
            row_index = int(call.data.split("_")[1])

            # Save selected row for editing
            user_data.update_user_data(user_id, "editing_row", row_index)
            current_action = user_data.get_current_action(user_id)

            if current_action == "editing_shipment_date":
                bot.send_message(call.message.chat.id, "Введите новую дату отправки (дд/мм/гггг):")
            elif current_action == "editing_estimated_arrival":
                bot.send_message(call.message.chat.id, "Введите новую ожидаемую дату прибытия (дд/мм/гггг):")
            elif current_action == "adding_actual_arrival":
                bot.send_message(call.message.chat.id, "Введите фактическую дату прибытия (дд/мм/гггг):")
            elif current_action == "editing_color":
                bot.send_message(call.message.chat.id, "Введите новый цвет изделия:")
            elif current_action == "editing_amount":
                bot.send_message(call.message.chat.id, "Введите новое общее количество (шт):")
            elif current_action == "editing_sizes":
                bot.send_message(call.message.chat.id, "Введите новое распределение по размерам (например: S-10, XL-20, 7XL-30):")
                bot.register_next_step_handler(call.message, handle_sizes_input)


    @bot.message_handler(func=lambda message: user_data.has_user(message.from_user.id) and
                                            user_data.get_user_data(message.from_user.id).get("editing_row") and
                                            user_data.get_current_action(message.from_user.id) == "editing_sizes")
    def handle_sizes_input(message):
        try:
            user_id = message.from_user.id
            row_index = user_data.get_user_data(user_id).get("editing_row")
            size_input = message.text.strip()

            if not validate_new_size_format(size_input):
                bot.reply_to(message, "❌ Некорректный формат размеров. Используйте формат: S-10, XL-20, 7XL-30")
                return

            # Parse the new size format
            sizes = parse_new_size_format(size_input)
            if not sizes:
                bot.reply_to(message, "❌ Ошибка при обработке размеров. Проверьте формат ввода.")
                return

            # Get size to column mapping
            size_columns = get_size_column_mapping()
            
            # Update values in Google Sheets
            sheets_manager = GoogleSheetsManager.get_instance()
            worksheet = sheets_manager.get_main_worksheet()
            
            # First, clear all existing size columns for this row (set to 0 or empty)
            for size, col_num in size_columns.items():
                worksheet.update_cell(row_index, col_num, "0")
            
            # Then update with new values
            updated_sizes = []
            for size, amount in sizes.items():
                if size in size_columns:
                    col_num = size_columns[size]
                    worksheet.update_cell(row_index, col_num, str(amount))
                    updated_sizes.append(f"{size}: {amount}")
                else:
                    bot.reply_to(message, f"⚠️ Размер '{size}' не найден в системе. Доступные размеры: {', '.join(size_columns.keys())}")
                    return

            success_message = f"✅ Размеры успешно обновлены!\nОбновленные размеры: {', '.join(updated_sizes)}"
            bot.reply_to(message, success_message)
            user_data.clear_user_data(user_id)

        except Exception as e:
            logger.error(f"Error handling sizes input: {str(e)}")
            bot.reply_to(message, f"❌ Ошибка при обновлении размеров: {str(e)}")
            user_data.clear_user_data(user_id)



def setup_edit_handler(bot: TeleBot):
    @bot.message_handler(commands=['edit'])
    def handle_edit_command(message):
        try:
            user_id = message.from_user.id
            sheets_manager = GoogleSheetsManager.get_instance()
            records = sheets_manager.get_main_worksheet().get_all_values()

            if len(records) <= 1:
                bot.reply_to(message, "📝 Нет доступных записей для редактирования.")
                return

            # Filter records to show only those created by the current user
            user_records = []
            for idx, record in enumerate(records[1:], start=2):
                # Check if the record has a user_id field (column 1) and it matches current user
                if len(record) > 1 and record[1] == str(user_id):
                    user_records.append((idx, record))

            if not user_records:
                bot.reply_to(message, "📝 У вас пока нет созданных записей для редактирования.")
                return

            # Store the list of user records in user_data for later use when returning to this menu
            user_data.initialize_user(user_id)
            user_data.update_user_data(user_id, "user_records", user_records)
            user_data.update_user_data(user_id, "current_page", 0)  # Start from page 0

            # Show the record selection menu with pagination
            show_record_selection_menu_paginated(bot, message.chat.id, user_records, 0)

        except Exception as e:
            logger.error(f"Error handling edit command: {str(e)}")
            bot.reply_to(message, "❌ Произошла ошибка при получении списка записей.")

    def show_record_selection_menu_paginated(bot, chat_id, user_records, page, message_id=None):
        """Helper function to show the paginated record selection menu"""
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
            product_name = record[3] if len(record) > 3 else "Unknown"
            product_color = record[7] if len(record) > 7 else "Unknown"
            shipment_date = record[4] if len(record) > 4 else "Unknown"
            warehouse_name = record[9] if len(record) > 9 else "Unknown"
            button_text = f"({warehouse_name}) {product_name} - {product_color}"
            markup.add(InlineKeyboardButton(
                button_text,
                callback_data=f"edit_record_{idx}"
            ))

        # Add pagination buttons if needed
        if total_pages > 1:
            nav_buttons = []
            
            # Previous button
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("⬅️ Предыдущая", callback_data=f"edit_page_{page-1}"))
            
            # Page indicator
            nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="edit_current_page"))
            
            # Next button
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton("Следующая ➡️", callback_data=f"edit_page_{page+1}"))
            
            markup.row(*nav_buttons)

        # Add cancel button
        markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_edit_operation"))

        message_text = f"📋 Выберите запись для редактирования:\n\nСтраница {page+1} из {total_pages} (всего записей: {total_items})"

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

    @bot.callback_query_handler(func=lambda call: call.data.startswith("edit_page_"))
    def handle_edit_page_navigation(call):
        """Handle page navigation for edit records"""
        try:
            bot.answer_callback_query(call.id)
            user_id = call.from_user.id
            page = int(call.data.split("_")[2])
            
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
            show_record_selection_menu_paginated(bot, call.message.chat.id, user_records, page, call.message.message_id)

        except Exception as e:
            logger.error(f"Error handling edit page navigation: {str(e)}")
            bot.edit_message_text(
                "❌ Ошибка при навигации по страницам.",
                call.message.chat.id,
                call.message.message_id
            )

    @bot.callback_query_handler(func=lambda call: call.data == "edit_current_page")
    def handle_edit_current_page_click(call):
        """Handle click on page indicator (no action needed)"""
        bot.answer_callback_query(call.id, "Текущая страница")

    @bot.callback_query_handler(func=lambda call: call.data == "cancel_edit_operation")
    def handle_cancel_edit_operation(call):
        try:
            bot.answer_callback_query(call.id)
            bot.edit_message_text(
                "❌ Операция редактирования отменена.",
                call.message.chat.id,
                call.message.message_id
            )
            # Clear any user data related to editing
            user_id = call.from_user.id
            user_data.clear_user_data(user_id)
        except Exception as e:
            logger.error(f"Error handling cancel edit operation: {str(e)}")
            bot.send_message(call.message.chat.id, "❌ Ошибка при отмене операции.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("edit_record_"))
    def handle_edit_selection(call):
        try:
            bot.answer_callback_query(call.id)
            parts = call.data.split("_")
            row_index = int(parts[2])

            # Get the current record data
            sheets_manager = GoogleSheetsManager.get_instance()
            record = sheets_manager.get_main_worksheet().row_values(row_index)

            # Create markup for editable fields
            markup = InlineKeyboardMarkup()
            
            # Define all editable fields with their column indices
            # Adjust these column indices based on your actual Google Sheets structure
            fields = [
                ("Название изделия", "product_name", 3),
                ("Цвет", "product_color", 7),
                ("Дата отправки", "shipment_date", 4),
                ("Ожидаемая дата прибытия", "estimated_arrival", 5),
                ("Фактическая дата прибытия", "actual_arrival", 6),
                ("Общее количество", "total_amount", 8),
                ("Склад", "warehouse", 9),
                ("Размеры", "sizes", 10),  # This will use the new size format
            ]

            for field_name, field_id, col_index in fields:
                # Get current value, handling potential missing data
                if col_index < len(record) and record[col_index]:
                    current_value = record[col_index]
                else:
                    current_value = "Не указано"
                
                # For sizes, show a more readable format
                if field_id == "sizes":
                    # Get all size columns and create a readable display
                    size_columns = get_size_column_mapping()
                    size_display = []
                    for size, col_num in size_columns.items():
                        if col_num < len(record) and record[col_num] and int(record[col_num] or 0) > 0:
                            size_display.append(f"{size}-{record[col_num]}")
                    
                    if size_display:
                        current_value = ", ".join(size_display)
                    else:
                        current_value = "Не указано"
                
                # Truncate long values for button display
                display_value = current_value
                if len(display_value) > 20:
                    display_value = display_value[:17] + "..."
                
                button_text = f"📝 {field_name}"
                if current_value != "Не указано":
                    button_text += f" ({display_value})"
                
                logger.info(f"Creating callback data: row_index={row_index}, field_id={field_id}, col_index={col_index}")
                markup.add(InlineKeyboardButton(
                    button_text,
                    callback_data=f"field_edit_{row_index}_{field_id}_{col_index}"
                ))

            # Add navigation buttons
            markup.add(InlineKeyboardButton("✅ Готово", callback_data="edit_done"))
            markup.add(InlineKeyboardButton("⬅️ Назад к списку", callback_data="back_to_record_selection"))
            markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_edit_operation"))

            # Create a comprehensive display of current values
            # Get size information for display
            size_columns = get_size_column_mapping()
            size_info = []
            total_sizes = 0
            for size, col_num in size_columns.items():
                if col_num < len(record) and record[col_num]:
                    amount = int(record[col_num] or 0)
                    if amount > 0:
                        size_info.append(f"{size}: {amount}")
                        total_sizes += amount
            
            size_display = ", ".join(size_info) if size_info else "Не указано"

            current_values = (
                f"📋 **Редактирование записи**\n\n"
                f"🏷️ **Изделие:** {record[3] if len(record) > 3 else 'Не указано'}\n"
                f"🎨 **Цвет:** {record[7] if len(record) > 7 else 'Не указано'}\n"
                f"📦 **Склад:** {record[9] if len(record) > 9 else 'Не указано'}\n\n"
                f"📅 **Дата отправки:** {record[4] if len(record) > 4 else 'Не указано'}\n"
                f"📅 **Ожидаемая дата прибытия:** {record[5] if len(record) > 5 else 'Не указано'}\n"
                f"📅 **Фактическая дата прибытия:** {record[6] if len(record) > 6 and record[6] else 'Не указано'}\n\n"
                f"📊 **Общее количество:** {record[8] if len(record) > 8 else 'Не указано'}\n"
                f"📏 **Размеры:** {size_display}\n"
                f"📈 **Всего по размерам:** {total_sizes}\n\n"
                f"👆 **Выберите поле для редактирования:**"
            )

            bot.edit_message_text(
                current_values,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup,
                parse_mode='Markdown'
            )

        except Exception as e:
            logger.error(f"Error handling edit selection: {str(e)}")
            bot.edit_message_text(
                "❌ Ошибка при получении информации о записи.",
                call.message.chat.id,
                call.message.message_id
            )

# REPLACE the existing handle_edit_selection function with this enhanced version:

    @bot.callback_query_handler(func=lambda call: call.data.startswith("edit_record_"))
    def handle_edit_selection(call):
        try:
            bot.answer_callback_query(call.id)
            parts = call.data.split("_")
            row_index = int(parts[2])

            # Get the current record data
            sheets_manager = GoogleSheetsManager.get_instance()
            record = sheets_manager.get_main_worksheet().row_values(row_index)

            # Create markup for editable fields
            markup = InlineKeyboardMarkup()
            
            # Define all editable fields with their column indices
            # Adjust these column indices based on your actual Google Sheets structure
            fields = [
                ("Название изделия", "product_name", 3),
                ("Цвет", "product_color", 7),
                ("Дата отправки", "shipment_date", 4),
                ("Ожидаемая дата прибытия", "estimated_arrival", 5),
                ("Фактическая дата прибытия", "actual_arrival", 6),
                ("Общее количество", "total_amount", 8),
                ("Склад", "warehouse", 9),
                ("Размеры", "sizes", 10),  # This will use the new size format
            ]

            for field_name, field_id, col_index in fields:
                # Get current value, handling potential missing data
                if col_index < len(record) and record[col_index]:
                    current_value = record[col_index]
                else:
                    current_value = "Не указано"
                
                # For sizes, show a more readable format
                if field_id == "sizes":
                    # Get all size columns and create a readable display
                    size_columns = get_size_column_mapping()
                    size_display = []
                    for size, col_num in size_columns.items():
                        if col_num < len(record) and record[col_num] and int(record[col_num] or 0) > 0:
                            size_display.append(f"{size}-{record[col_num]}")
                    
                    if size_display:
                        current_value = ", ".join(size_display)
                    else:
                        current_value = "Не указано"
                
                # Truncate long values for button display
                display_value = current_value
                if len(display_value) > 20:
                    display_value = display_value[:17] + "..."
                
                button_text = f"📝 {field_name}"
                if current_value != "Не указано":
                    button_text += f" ({display_value})"
                
                logger.info(f"Creating callback data: row_index={row_index}, field_id={field_id}, col_index={col_index}")
                markup.add(InlineKeyboardButton(
                    button_text,
                    callback_data=f"field_edit_{row_index}_{field_id}_{col_index}"
                ))

            # Add navigation buttons
            markup.add(InlineKeyboardButton("✅ Готово", callback_data="edit_done"))
            markup.add(InlineKeyboardButton("⬅️ Назад к списку", callback_data="back_to_record_selection"))
            markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_edit_operation"))

            # Create a comprehensive display of current values
            # Get size information for display
            size_columns = get_size_column_mapping()
            size_info = []
            total_sizes = 0
            for size, col_num in size_columns.items():
                if col_num < len(record) and record[col_num]:
                    amount = int(record[col_num] or 0)
                    if amount > 0:
                        size_info.append(f"{size}: {amount}")
                        total_sizes += amount
            
            size_display = ", ".join(size_info) if size_info else "Не указано"

            current_values = (
                f"📋 **Редактирование записи**\n\n"
                f"🏷️ **Изделие:** {record[3] if len(record) > 3 else 'Не указано'}\n"
                f"🎨 **Цвет:** {record[7] if len(record) > 7 else 'Не указано'}\n"
                f"📦 **Склад:** {record[9] if len(record) > 9 else 'Не указано'}\n\n"
                f"📅 **Дата отправки:** {record[4] if len(record) > 4 else 'Не указано'}\n"
                f"📅 **Ожидаемая дата прибытия:** {record[5] if len(record) > 5 else 'Не указано'}\n"
                f"📅 **Фактическая дата прибытия:** {record[6] if len(record) > 6 and record[6] else 'Не указано'}\n\n"
                f"📊 **Общее количество:** {record[8] if len(record) > 8 else 'Не указано'}\n"
                f"📏 **Размеры:** {size_display}\n"
                f"📈 **Всего по размерам:** {total_sizes}\n\n"
                f"👆 **Выберите поле для редактирования:**"
            )

            bot.edit_message_text(
                current_values,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup,
                parse_mode='Markdown'
            )

        except Exception as e:
            logger.error(f"Error handling edit selection: {str(e)}")
            bot.edit_message_text(
                "❌ Ошибка при получении информации о записи.",
                call.message.chat.id,
                call.message.message_id
            )

# ALSO UPDATE the handle_edit_field_selection function to handle the new fields:

    @bot.callback_query_handler(func=lambda call: call.data.startswith("field_edit_"))
    def handle_edit_field_selection(call):
        try:
            bot.answer_callback_query(call.id)

            # Parse the callback data
            parts = call.data.split("_")
            logger.info(f"Parsing callback data: {call.data}, parts: {parts}")

            # Extract row index (always at position 2)
            row_index = int(parts[2])

            # Handle different field types
            if len(parts) >= 5:
                field_id = parts[3]
                if field_id in ["product", "shipment", "estimated", "actual", "total"]:
                    # Handle compound field names
                    if parts[3] == "product" and len(parts) > 4:
                        if parts[4] == "name":
                            field_id = "product_name"
                            col_index = int(parts[5])
                        elif parts[4] == "color":
                            field_id = "product_color"
                            col_index = int(parts[5])
                    elif parts[3] == "shipment" and parts[4] == "date":
                        field_id = "shipment_date"
                        col_index = int(parts[5])
                    elif parts[3] == "estimated" and parts[4] == "arrival":
                        field_id = "estimated_arrival"
                        col_index = int(parts[5])
                    elif parts[3] == "actual" and parts[4] == "arrival":
                        field_id = "actual_arrival"
                        col_index = int(parts[5])
                    elif parts[3] == "total" and parts[4] == "amount":
                        field_id = "total_amount"
                        col_index = int(parts[5])
                    else:
                        logger.error(f"Unrecognized compound field pattern: {call.data}")
                        bot.send_message(call.message.chat.id, "❌ Ошибка формата данных.")
                        return
                else:
                    # Simple field names
                    col_index = int(parts[4])
            else:
                logger.error(f"Invalid callback data format: {call.data}")
                bot.send_message(call.message.chat.id, "❌ Ошибка формата данных.")
                return

            # Store editing state in user_data
            user_id = call.from_user.id
            user_data.initialize_user(user_id)
            user_data.update_user_data(user_id, "editing_row", row_index)
            user_data.update_user_data(user_id, "editing_field", field_id)
            user_data.update_user_data(user_id, "editing_col", col_index)

            # Define field-specific prompts and examples
            field_prompts = {
                "product_name": ("название изделия", "например: Футболка базовая"),
                "product_color": ("цвет", "например: Красный, Синий, Черный"),
                "shipment_date": ("дату отправки", "формат: ДД/ММ/ГГГГ, например: 15/12/2024"),
                "estimated_arrival": ("ожидаемую дату прибытия", "формат: ДД/ММ/ГГГГ, например: 20/12/2024"),
                "actual_arrival": ("фактическую дату прибытия", "формат: ДД/ММ/ГГГГ, например: 18/12/2024"),
                "warehouse": ("склад", "например: Склад А, Основной склад"),
                "total_amount": ("общее количество", "например: 100"),
                "sizes": ("размеры", "формат: S-10, XL-20, 7XL-30")
            }

            field_name, example = field_prompts.get(field_id, ("значение", ""))

            # Get current value from Google Sheets
            sheets_manager = GoogleSheetsManager.get_instance()
            try:
                if field_id == "sizes":
                    # For sizes, show current distribution
                    size_columns = get_size_column_mapping()
                    current_sizes = []
                    record = sheets_manager.get_main_worksheet().row_values(row_index)
                    for size, col_num in size_columns.items():
                        if col_num < len(record) and record[col_num] and int(record[col_num] or 0) > 0:
                            current_sizes.append(f"{size}-{record[col_num]}")
                    current_value = ", ".join(current_sizes) if current_sizes else "Не указано"
                else:
                    current_value = sheets_manager.get_main_worksheet().cell(row_index, col_index).value
                    if not current_value:
                        current_value = "Не указано"
            except Exception as e:
                logger.error(f"Error getting current value: {str(e)}")
                current_value = "Не указано"

            prompt = (
                f"✏️ **Редактирование поля**\n\n"
                f"Введите новое **{field_name}**:\n"
                f"({example})\n\n"
                f"📝 Текущее значение: `{current_value}`"
            )

            bot.send_message(
                call.message.chat.id,
                prompt,
                reply_markup=ForceReply(),
                parse_mode='Markdown'
            )

            logger.info(f"Edit field prompt sent for field {field_id}, row {row_index}, col {col_index}")

        except Exception as e:
            logger.error(f"Error handling edit field selection: {str(e)}")
            bot.send_message(
                call.message.chat.id,
                f"❌ Ошибка при выборе поля для редактирования: {str(e)}"
            )


# REPLACE the existing handle_edit_field_input function with this enhanced version:

    @bot.message_handler(func=lambda message: user_data.has_user(message.from_user.id) and
                    user_data.get_user_data(message.from_user.id).get("editing_row"))
    def handle_edit_field_input(message):
        try:
            user_id = message.from_user.id
            user_data_dict = user_data.get_user_data(user_id)

            if not user_data_dict:
                bot.reply_to(message, "❌ Ошибка: сессия редактирования не найдена.")
                return

            row_index = user_data_dict.get("editing_row")
            col_index = user_data_dict.get("editing_col")
            field_id = user_data_dict.get("editing_field")
            new_value = message.text.strip()

            sheets_manager = GoogleSheetsManager.get_instance()
            worksheet = sheets_manager.get_main_worksheet()

            # Handle different field types with specific validation
            if field_id == "sizes":
                # Handle the new size format
                if not validate_new_size_format(new_value):
                    bot.reply_to(message, "❌ Некорректный формат размеров. Используйте формат: S-10, XL-20, 7XL-30")
                    return

                # Parse the new size format
                sizes = parse_new_size_format(new_value)
                if not sizes:
                    bot.reply_to(message, "❌ Ошибка при обработке размеров. Проверьте формат ввода.")
                    return

                # Get size to column mapping
                size_columns = get_size_column_mapping()
                
                # Clear all existing size columns for this row
                for size, col_num in size_columns.items():
                    worksheet.update_cell(row_index, col_num, "0")
                
                # Update with new values
                updated_sizes = []
                total_amount = 0
                for size, amount in sizes.items():
                    if size in size_columns:
                        col_num = size_columns[size]
                        worksheet.update_cell(row_index, col_num, str(amount))
                        updated_sizes.append(f"{size}: {amount}")
                        total_amount += amount
                    else:
                        bot.reply_to(message, f"⚠️ Размер '{size}' не найден в системе. Доступные размеры: {', '.join(size_columns.keys())}")
                        return

                # Update total amount in column 8 (if that's where total is stored)
                worksheet.update_cell(row_index, 8, str(total_amount))
                
                success_message = f"✅ Размеры успешно обновлены!\n📏 Обновленные размеры: {', '.join(updated_sizes)}\n📊 Общее количество: {total_amount}"
                
            elif field_id in ["shipment_date", "estimated_arrival", "actual_arrival"]:
                # Validate date format
                if not validate_date(new_value):
                    bot.reply_to(message, "❌ Некорректный формат даты. Используйте дд/мм/гггг (например: 15/12/2024).")
                    return
                new_value = standardize_date(new_value)
                worksheet.update_cell(row_index, col_index, new_value)
                success_message = f"✅ Дата успешно обновлена: {new_value}"
                
            elif field_id == "total_amount":
                # Validate numeric values
                if not validate_amount(new_value):
                    bot.reply_to(message, "❌ Некорректное количество. Введите целое число.")
                    return
                new_value = str(int(new_value))
                worksheet.update_cell(row_index, col_index, new_value)
                success_message = f"✅ Количество успешно обновлено: {new_value}"
                
            elif field_id in ["product_name", "product_color", "warehouse"]:
                # Text fields - basic validation
                if not new_value or len(new_value.strip()) == 0:
                    bot.reply_to(message, "❌ Значение не может быть пустым.")
                    return
                
                # Limit length to prevent issues
                if len(new_value) > 100:
                    bot.reply_to(message, "❌ Значение слишком длинное (максимум 100 символов).")
                    return
                    
                worksheet.update_cell(row_index, col_index, new_value)
                field_names = {
                    "product_name": "Название изделия", 
                    "product_color": "Цвет",
                    "warehouse": "Склад"
                }
                success_message = f"✅ {field_names[field_id]} успешно обновлено: {new_value}"
                
            else:
                # Generic field update
                worksheet.update_cell(row_index, col_index, new_value)
                success_message = f"✅ Значение успешно обновлено: {new_value}"

            # Log for debugging
            logger.info(f"Updated field {field_id} at row {row_index}, col {col_index} with value '{new_value}'")

            # Don't clear editing state yet, keep user_records for potential back navigation
            user_data.update_user_data(user_id, "editing_field", None)
            user_data.update_user_data(user_id, "editing_col", None)

            # Show success message
            bot.reply_to(message, success_message)

            # Retrieve and show the updated record
            try:
                record = worksheet.row_values(row_index)

                # Get updated size information
                size_columns = get_size_column_mapping()
                size_info = []
                total_sizes = 0
                for size, col_num in size_columns.items():
                    if col_num < len(record) and record[col_num]:
                        amount = int(record[col_num] or 0)
                        if amount > 0:
                            size_info.append(f"{size}: {amount}")
                            total_sizes += amount
                
                size_display = ", ".join(size_info) if size_info else "Не указано"

                updated_values = (
                    f"📋 **Обновленная запись:**\n\n"
                    f"🏷️ **Изделие:** {record[3] if len(record) > 3 else 'Не указано'}\n"
                    f"🎨 **Цвет:** {record[7] if len(record) > 7 else 'Не указано'}\n"
                    f"📦 **Склад:** {record[9] if len(record) > 9 else 'Не указано'}\n\n"
                    f"📅 **Дата отправки:** {record[4] if len(record) > 4 else 'Не указано'}\n"
                    f"📅 **Ожидаемая дата прибытия:** {record[5] if len(record) > 5 else 'Не указано'}\n"
                    f"📅 **Фактическая дата прибытия:** {record[6] if len(record) > 6 and record[6] else 'Не указано'}\n\n"
                    f"📊 **Общее количество:** {record[8] if len(record) > 8 else 'Не указано'}\n"
                    f"📏 **Размеры:** {size_display}\n"
                    f"📈 **Всего по размерам:** {total_sizes}"
                )

                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("📝 Продолжить редактирование",
                                            callback_data=f"edit_record_{row_index}"))
                markup.add(InlineKeyboardButton("✅ Завершить",
                                            callback_data="edit_done"))

                bot.send_message(
                    message.chat.id,
                    updated_values,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Error fetching updated record: {str(e)}")
                bot.send_message(
                    message.chat.id,
                    "✅ Значение успешно обновлено, но не удалось получить обновленную запись."
                )

        except Exception as e:
            logger.error(f"Error handling edit field input: {str(e)}")
            bot.reply_to(message, f"❌ Ошибка при обновлении значения: {str(e)}")
            user_data.clear_user_data(message.from_user.id)

    @bot.callback_query_handler(func=lambda call: call.data == "edit_done")
    def handle_edit_done(call):
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, "Редактирование завершено.")
            # Clear user data when editing is complete
            user_id = call.from_user.id
            user_data.clear_user_data(user_id)
        except Exception as e:
            logger.error(f"Error handling edit done: {str(e)}")

    @bot.callback_query_handler(func=lambda call: call.data == "back_to_record_selection")
    def handle_back_to_record_selection(call):
        try:
            bot.answer_callback_query(call.id)
            user_id = call.from_user.id

            # Get the stored user records and current page
            user_data_dict = user_data.get_user_data(user_id)
            user_records = user_data_dict.get("user_records") if user_data_dict else None
            current_page = user_data_dict.get("current_page", 0) if user_data_dict else 0

            if not user_records:
                bot.send_message(call.message.chat.id, "❌ Ошибка: список записей не найден.")
                return

            # Show the record selection menu again with pagination
            show_record_selection_menu_paginated(bot, call.message.chat.id, user_records, current_page, call.message.message_id)

        except Exception as e:
            logger.error(f"Error handling back to record selection: {str(e)}")
            bot.send_message(call.message.chat.id, "❌ Ошибка при возврате к выбору записи.")

    def show_record_selection_menu(bot, chat_id, user_records, message_id=None):
        """Helper function to show the record selection menu (backward compatibility)"""
        show_record_selection_menu_paginated(bot, chat_id, user_records, 0, message_id)