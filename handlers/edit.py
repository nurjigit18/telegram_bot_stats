from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from models.user_data import user_data
from utils.keyboards import show_product_selection
from utils.validators import validate_date, standardize_date, validate_amount, validate_size_amounts, parse_size_amounts
from utils.google_sheets import GoogleSheetsManager

import logging

logger = logging.getLogger(__name__)

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
                bot.send_message(call.message.chat.id, "Введите новое распределение по размерам (S: 50 M: 25 L: 50):")
                bot.register_next_step_handler(call.message, handle_sizes_input)


    @bot.message_handler(func=lambda message: user_data.has_user(message.from_user.id) and
                                            user_data.get_user_data(message.from_user.id).get("editing_row") and
                                            user_data.get_current_action(message.from_user.id) == "editing_sizes")
    def handle_sizes_input(message):
        try:
            user_id = message.from_user.id
            row_index = user_data.get_user_data(user_id).get("editing_row")
            size_amounts = message.text.strip()

            if not validate_size_amounts(size_amounts):
                bot.reply_to(message, "❌ Некорректный формат размеров. Используйте 'S: 50 M: 25 L: 50'.")
                return

            s_amount, m_amount, l_amount = parse_size_amounts(size_amounts)

            # Update values in Google Sheets
            sheets_manager = GoogleSheetsManager.get_instance()
            sheets_manager.get_main_worksheet().update_cell(row_index, 11, str(s_amount)) # Column 11 is 'S'
            sheets_manager.get_main_worksheet().update_cell(row_index, 12, str(m_amount)) # Column 12 is 'M'
            sheets_manager.get_main_worksheet().update_cell(row_index, 13, str(l_amount)) # Column 13 is 'L'

            bot.reply_to(message, "✅ Размеры успешно обновлены!")
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

            # Show the record selection menu
            show_record_selection_menu(bot, message.chat.id, user_records)

        except Exception as e:
            logger.error(f"Error handling edit command: {str(e)}")
            bot.reply_to(message, "❌ Произошла ошибка при получении списка записей.")

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
            fields = [
                # ("Изделие", "product_name", 3),
                # ("Цвет", "product_color", 7),
                # ("Дата отправки", "shipment_date", 4),
                # ("Ожидаемая дата прибытия", "estimated_arrival", 5),
                ("Фактическая дата прибытия", "actual_arrival", 6),
                # ("Склад", "warehouse", 9),
                # ("Общее количество", "total_amount", 8),
                # ("Количество S", "s_amount", 10),
                # ("Количество M", "m_amount", 11),
                # ("Количество L", "l_amount", 12)
            ]

            for field_name, field_id, col_index in fields:
                current_value = record[col_index] if len(record) > col_index else "Не указано"
                button_text = f"Изменить {field_name} ({current_value})"
                # Use a simpler callback data format
                logger.info(f"Creating callback data: row_index={row_index}, field_id={field_id}, col_index={col_index}")
                markup.add(InlineKeyboardButton(
                    button_text,
                    callback_data=f"field_edit_{row_index}_{field_id}_{col_index}"
                ))

            # Add buttons: Done, Back, and Cancel
            markup.add(InlineKeyboardButton("✅ Готово", callback_data="edit_done"))
            markup.add(InlineKeyboardButton("⬅️ Назад", callback_data="back_to_record_selection"))
            markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_edit_operation"))

            current_values = (
                f"📝 Текущие значения:\n\n"
                f"Изделие: {record[3]}\n"
                f"Цвет: {record[7]}\n"
                f"Дата отправки: {record[4]}\n"
                f"Ожидаемая дата прибытия: {record[5]}\n"
                f"Фактическая дата прибытия: {record[6] or 'Не указано'}\n"
                f"Склад: {record[9]}\n"
                f"Общее количество: {record[8]}\n"
                f"Размеры: {record[10]}\n"
                f"\n\nВыберите поле для редактирования:"
            )

            bot.edit_message_text(
                current_values,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )

        except Exception as e:
            logger.error(f"Error handling edit selection: {str(e)}")
            bot.edit_message_text(
                "❌ Ошибка при получении информации о записи.",
                call.message.chat.id,
                call.message.message_id
            )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("field_edit_"))
    def handle_edit_field_selection(call):
        try:
            bot.answer_callback_query(call.id)

            # Parse the callback data correctly
            parts = call.data.split("_")

            # Debug logging to understand the actual format
            logger.info(f"Parsing callback data: {call.data}, parts: {parts}")

            # The expected format is "field_edit_2_product_name_3"
            # So parts would be ["field", "edit", "2", "product", "name", "3"] for product_name
            # Or ["field", "edit", "2", "warehouse", "9"] for warehouse

            # Extract row index (always at position 2)
            row_index = int(parts[2])

            # For fields with underscores in their names (like product_name),
            # we need to reconstruct the field_id
            if len(parts) > 5:  # If there are more parts, it might be a field with underscore
                if parts[3] == "product" and parts[4] == "name":
                    field_id = "product_name"
                    col_index = int(parts[5])
                elif parts[3] == "product" and parts[4] == "color":
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
                elif parts[3] == "s" and parts[4] == "amount":
                    field_id = "s_amount"
                    col_index = int(parts[5])
                elif parts[3] == "m" and parts[4] == "amount":
                    field_id = "m_amount"
                    col_index = int(parts[5])
                elif parts[3] == "l" and parts[4] == "amount":
                    field_id = "l_amount"
                    col_index = int(parts[5])
                else:
                    # If we don't recognize the pattern, log error and return
                    logger.error(f"Unrecognized field pattern in callback data: {call.data}")
                    bot.send_message(call.message.chat.id, "❌ Ошибка формата данных.")
                    return
            else:
                # Simple field like "warehouse"
                field_id = parts[3]
                col_index = int(parts[4])

            # Store editing state in user_data
            user_id = call.from_user.id
            user_data.initialize_user(user_id)
            user_data.update_user_data(user_id, "editing_row", row_index)
            user_data.update_user_data(user_id, "editing_field", field_id)
            user_data.update_user_data(user_id, "editing_col", col_index)

            field_names = {
                "product_name": "название изделия",
                "product_color": "цвет",
                "shipment_date": "дату отправки",
                "estimated_arrival": "ожидаемую дату прибытия",
                "actual_arrival": "фактическую дату прибытия",
                "warehouse": "склад",
                "total_amount": "общее количество",
                "s_amount": "количество размера S",
                "m_amount": "количество размера M",
                "l_amount": "количество размера L"
            }

            # Get the current value from Google Sheets
            sheets_manager = GoogleSheetsManager.get_instance()
            try:
                current_value = sheets_manager.get_main_worksheet().cell(row_index, col_index+1).value
            except Exception as e:
                logger.error(f"Error getting current value: {str(e)}")
                current_value = "Не указано"
            if current_value == None:
                current_value = "Не указано"
            prompt = f"Введите новое {field_names.get(field_id, 'значение (ДД/ММ/ГГГГ)')} (ДД/ММ/ГГГГ):\n(Текущее значение: {current_value})"
            msg = bot.send_message(
                call.message.chat.id,
                prompt,
                reply_markup=ForceReply()
            )

            # Log success for debugging
            logger.info(f"Edit field prompt sent successfully for field {field_id}, row {row_index}, col {col_index}")

        except Exception as e:
            logger.error(f"Error handling edit field selection: {str(e)}")
            bot.send_message(
                call.message.chat.id,
                f"❌ Ошибка при выборе поля для редактирования: {str(e)}"
            )

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

            # Apply specific validation based on field type
            if field_id in ["shipment_date", "estimated_arrival", "actual_arrival"]:
                # Validate date format
                if not validate_date(new_value):
                    bot.reply_to(message, "❌ Некорректный формат даты. Используйте дд/мм/гггг.")
                    return
                new_value = standardize_date(new_value)
            elif field_id in ["total_amount", "s_amount", "m_amount", "l_amount"]:
                # Validate numeric values
                if not validate_amount(new_value):
                    bot.reply_to(message, "❌ Некорректное количество. Введите целое число.")
                    return
                # Ensure it's stored as a string
                new_value = str(int(new_value))
            #PRODUCT NAME AND COLOR VALIDATION
            elif field_id in ["product_name", "product_color", "warehouse"]:
                new_value = str(new_value)

            # Log for debugging
            logger.info(f"Updating cell at row {row_index}, col {col_index} with value '{new_value}'")

            # Update the value in Google Sheets
            sheets_manager = GoogleSheetsManager.get_instance()
            sheets_manager.get_main_worksheet().update_cell(row_index, int(col_index)+1, new_value)

            # Don't clear editing state yet, keep user_records for potential back navigation
            user_data.update_user_data(user_id, "editing_field", None)
            user_data.update_user_data(user_id, "editing_col", None)

            # Show success message and updated record
            bot.reply_to(message, "✅ Значение успешно обновлено!")

            # Retrieve the updated record
            try:
                record = sheets_manager.get_main_worksheet().row_values(row_index)

                # Make sure we handle potential missing values
                updated_values = (
                    f"📝 Обновленные значения:\n\n"
                    f"Изделие: {record[3] if len(record) > 3 else 'Не указано'}\n"
                    f"Цвет: {record[7] if len(record) > 7 else 'Не указано'}\n"
                    f"Дата отправки: {record[4] if len(record) > 4 else 'Не указано'}\n"
                    f"Ожидаемая дата прибытия: {record[5] if len(record) > 5 else 'Не указано'}\n"
                    f"Фактическая дата прибытия: {record[6] if len(record) > 6 and record[6] else 'Не указано'}\n"
                    f"Склад: {record[9] if len(record) > 9 and record[9] else 'Не указано'}\n"
                    f"Общее количество: {record[8] if len(record) > 8 else 'Не указано'}\n"
                    f"Размеры: {record[10] if len(record) > 10 and record[10] else '0'}\n"
                    f"Статус: {record[11] if len(record) > 11 and record[11] else 'Ну указан'}\n"
                )

                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("📝 Продолжить редактирование",
                                            callback_data=f"edit_record_{row_index}"))
                markup.add(InlineKeyboardButton("✅ Завершить",
                                            callback_data="edit_done"))

                bot.send_message(
                    message.chat.id,
                    updated_values,
                    reply_markup=markup
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

            # Get the stored user records
            user_records = user_data.get_user_data(user_id).get("user_records")

            if not user_records:
                bot.send_message(call.message.chat.id, "❌ Ошибка: список записей не найден.")
                return

            # Show the record selection menu again
            show_record_selection_menu(bot, call.message.chat.id, user_records, call.message.message_id)

        except Exception as e:
            logger.error(f"Error handling back to record selection: {str(e)}")
            bot.send_message(call.message.chat.id, "❌ Ошибка при возврате к выбору записи.")

    def show_record_selection_menu(bot, chat_id, user_records, message_id=None):
        """Helper function to show the record selection menu"""
        markup = InlineKeyboardMarkup()
        for idx, record in user_records:
            product_name = record[3] if len(record) > 3 else "Unknown"
            product_color = record[7] if len(record) > 7 else "Unknown"
            button_text = f"{product_name} - {product_color}"
            markup.add(InlineKeyboardButton(
                button_text,
                callback_data=f"edit_record_{idx}"
            ))

        # Add cancel button
        markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_edit_operation"))

        if message_id:
            # Edit existing message
            bot.edit_message_text(
                "📋 Выберите запись для редактирования:",
                chat_id,
                message_id,
                reply_markup=markup
            )
        else:
            # Send new message
            bot.send_message(
                chat_id,
                "📋 Выберите запись для редактирования:",
                reply_markup=markup
            )