from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from constants import PROMPTS, STEPS
from models.user_data import user_data
from utils.validators import validate_date, validate_amount, validate_size_amounts, parse_size_amounts, standardize_date, validate_warehouse_sizes
from utils.google_sheets import save_to_sheets, GoogleSheetsManager
from config import ADMIN_USER_USERNAMES
from datetime import datetime
import logging
import re
import pytz

logger = logging.getLogger(__name__)

def parse_warehouse_sizes(warehouse_sizes_str):
    """
    Parse warehouse and sizes string into structured data
    
    Formats supported:
    - Single warehouse: "Казань: S-50 M-25 L-25"
    - Multiple warehouses: "Казань: S-30 M-40 , Москва: L-50 XL-80"
    
    Returns: List of tuples [(warehouse_name, {size: quantity})]
    """
    try:
        warehouse_data = []
        
        # Split by , for multiple warehouses
        warehouse_parts = [part.strip() for part in warehouse_sizes_str.split(',')]
        
        for warehouse_part in warehouse_parts:
            if ':' not in warehouse_part:
                return None  # Invalid format
            
            warehouse_name, sizes_str = warehouse_part.split(':', 1)
            warehouse_name = warehouse_name.strip()
            sizes_str = sizes_str.strip()
            
            # Parse sizes (format: S-50 M-25 L-25)
            sizes = {}
            size_parts = sizes_str.split()
            
            for size_part in size_parts:
                if '-' not in size_part:
                    return None  # Invalid format
                
                size, quantity_str = size_part.split('-', 1)
                size = size.strip().upper()
                
                try:
                    quantity = int(quantity_str.strip())
                    if quantity <= 0:
                        return None  # Invalid quantity
                    sizes[size] = quantity
                except ValueError:
                    return None  # Invalid number
            
            if not sizes:
                return None  # No sizes found
            
            warehouse_data.append((warehouse_name, sizes))
        
        return warehouse_data if warehouse_data else None
        
    except Exception:
        return None

def setup_save_handler(bot: TeleBot):
    @bot.message_handler(commands=['save'])
    def start_save_process(message):
        """Start the product data collection process with single message input"""
        user_id = message.from_user.id

        # Initialize user data
        user_data.initialize_user(user_id)
        user_data.set_current_action(user_id, "saving_new_single")
        user_data.initialize_form_data(user_id)

        # Send sample format
        sample_format = (
            "Заполните все данные одним сообщением в следующем формате:\n\n"
            "📋 Образец заполнения:\n"
            "Название изделия:\n"
            "Цвет изделия:\n"
            "Количество (шт):\n"
            "Склады и размеры:\n"
            "Дата отправки (дд/мм/гггг):\n"
            "Дата возможного прибытия (дд/мм/гггг):\n\n"
            "💡 Примеры:\n\n"
            "🔹 Один склад:\n"
            "рубашка\n"
            "красный\n"
            "100\n"
            "Казань: S-50 M-25 L-25\n"
            "12.12.2021\n"
            "15/12/2021\n\n"
            "🔹 Несколько складов:\n"
            "рубашка\n"
            "синий\n"
            "200\n"
            "Казань: S-30 M-40 , Москва: L-50 XL-80\n"
            "12.12.2021\n"
            "15/12/2021\n\n"
            "📝 Формат складов и размеров:\n"
            "• Один склад: Склад: размер-количество размер-количество\n"
            "• Несколько складов: Склад1: размеры , Склад2: размеры\n"
            "• Разделитель складов: , (вертикальная черта)\n"
            "• Разделитель размеров: - (дефис)\n\n"
            "Нажмите /cancel для отмены заполнения."
        )
        bot.reply_to(message, sample_format)

    @bot.message_handler(func=lambda message:
        user_data.has_user(message.from_user.id) and
        user_data.get_current_action(message.from_user.id) == "saving_new_single")
    def handle_single_save_input(message):
        """Handle single message input for all form data"""
        if message.text.startswith('/'):  # Skip if it's a command
            if message.text == '/cancel':
                user_data.clear_user_data(message.from_user.id)
                bot.reply_to(message, "✖️ Процесс заполнения отменен.")
            return

        user_id = message.from_user.id
        
        try:
            # Parse the input message
            lines = [line.strip() for line in message.text.strip().split('\n') if line.strip()]
            
            # Check if we have the correct number of lines
            expected_fields = 6  # Changed from 7 to 6 (removed separate warehouse and size fields)
            if len(lines) != expected_fields:
                error_msg = (
                    f"❌ Неверное количество полей. Ожидается {expected_fields} строк, получено {len(lines)}.\n\n"
                    "Убедитесь, что вы заполнили все поля в правильном порядке:\n"
                    "1. Название изделия\n"
                    "2. Цвет изделия\n"
                    "3. Количество (шт)\n"
                    "4. Склады и размеры\n"
                    "5. Дата отправки\n"
                    "6. Дата возможного прибытия"
                )
                bot.reply_to(message, error_msg)
                return

            # Extract and validate each field
            product_name = lines[0]
            product_color = lines[1]
            total_amount_str = lines[2]
            warehouse_sizes_str = lines[3]  # Combined warehouse and sizes
            shipment_date_str = lines[4]    # Updated index
            estimated_arrival_str = lines[5]  # Updated index

            errors = []

            # Validate product name
            if not product_name:
                errors.append("• Название изделия не может быть пустым")

            # Validate product color
            if not product_color:
                errors.append("• Цвет изделия не может быть пустым")

            # Validate total amount
            if not validate_amount(total_amount_str):
                errors.append("• Неверное количество. Введите положительное число")
            else:
                total_amount = int(total_amount_str)

            # Validate warehouse and sizes format
            if not validate_warehouse_sizes(warehouse_sizes_str):
                errors.append("• Неверный формат складов и размеров. Используйте формат 'Склад1: S-50 M-25 , Склад2: L-30'")
            else:
                warehouse_data = parse_warehouse_sizes(warehouse_sizes_str)
                if not warehouse_data:
                    errors.append("• Ошибка при разборе складов и размеров")
                else:
                    # Validate that total amounts match
                    calculated_total = sum(sum(sizes.values()) for _, sizes in warehouse_data)
                    if calculated_total != total_amount:
                        errors.append(f"• Сумма размеров ({calculated_total}) не совпадает с общим количеством ({total_amount})")

            # Validate shipment date
            if not validate_date(shipment_date_str):
                errors.append("• Неверный формат даты отправки. Используйте дд/мм/гггг или дд.мм.гггг")
            else:
                shipment_date = standardize_date(shipment_date_str)

            # Validate estimated arrival date
            if not validate_date(estimated_arrival_str):
                errors.append("• Неверный формат даты прибытия. Используйте дд/мм/гггг или дд.мм.гггг")
            else:
                estimated_arrival = standardize_date(estimated_arrival_str)

            # If there are validation errors, send them back
            if errors:
                error_message = "❌ Найдены следующие ошибки:\n\n" + "\n".join(errors)
                error_message += "\n\nПожалуйста, исправьте ошибки и отправьте данные заново."
                bot.reply_to(message, error_message)
                return

            # If validation passed, save the data
            # For multiple warehouses, we'll create multiple records
            saved_records = 0
            warehouse_records = []  # Keep track of what was saved for confirmation
            
            for warehouse_name, sizes in warehouse_data:
                # Clear previous form data to avoid contamination between warehouses
                user_data.initialize_form_data(user_id)
                
                # Set the basic form data for this specific warehouse
                user_data.update_form_data(user_id, 'product_name', product_name)
                user_data.update_form_data(user_id, 'product_color', product_color)
                user_data.update_form_data(user_id, 'total_amount', sum(sizes.values()))  # Amount for this warehouse only
                user_data.update_form_data(user_id, 'warehouse', warehouse_name)
                user_data.update_form_data(user_id, 'shipment_date', shipment_date)
                user_data.update_form_data(user_id, 'estimated_arrival', estimated_arrival)

                # Add size amounts to form data for this specific warehouse
                for size_key, size_value in sizes.items():
                    user_data.update_form_data(user_id, size_key, size_value)

                # Save to Google Sheets for this warehouse
                try:
                    row_index = save_to_sheets(bot, message)
                    saved_records += 1
                    warehouse_records.append((warehouse_name, sizes))
                    
                    # Notify admins about the new record
                    notify_admins_about_new_record(bot, message, row_index)
                    
                    logger.info(f"Successfully saved record for warehouse {warehouse_name} with sizes: {sizes}")
                    
                except Exception as e:
                    logger.error(f"Error saving warehouse {warehouse_name}: {str(e)}")
                    bot.reply_to(message, f"❌ Ошибка при сохранении данных для склада {warehouse_name}: {str(e)}")
                    user_data.clear_user_data(user_id)
                    return

            # Show confirmation message with all saved data
            warehouse_summary = []
            for warehouse_name, sizes in warehouse_records:
                size_str = ", ".join([f"{size}: {qty}" for size, qty in sizes.items()])
                warehouse_summary.append(f"🏪 {warehouse_name}: {size_str}")

            confirmation_msg = (
                "✅ Данные успешно сохранены!\n\n"
                f"📦 Название изделия: {product_name}\n"
                f"🎨 Цвет изделия: {product_color}\n"
                f"📊 Общее количество: {total_amount} шт\n"
                + "\n".join(warehouse_summary) + "\n"
                f"📅 Дата отправки: {shipment_date}\n"
                f"📅 Дата прибытия: {estimated_arrival}\n\n"
                f"Создано записей: {saved_records}"
            )
            bot.reply_to(message, confirmation_msg)

            # Clear user data after successful completion
            user_data.clear_user_data(user_id)

        except Exception as e:
            logger.error(f"Error in handle_single_save_input: {str(e)}")
            bot.reply_to(message, f"❌ Произошла ошибка при обработке данных: {str(e)}. Попробуйте еще раз.")
            user_data.clear_user_data(user_id)


   # Keep the old step-by-step handler for backward compatibility
    @bot.message_handler(commands=['save_step'])
    def start_step_save_process(message):
        """Start the product data collection process (step-by-step)"""
        user_id = message.from_user.id

        # Initialize user data
        user_data.initialize_user(user_id)
        user_data.set_current_action(user_id, "saving_new")
        user_data.set_current_step(user_id, 0)
        user_data.initialize_form_data(user_id)

        # Send initial messages
        cancel_message = "Заполните все данные по порядку. Нажмите или ведите /cancel для отмены заполнения."
        bot.reply_to(message, cancel_message)
        bot.send_message(message.chat.id, PROMPTS[STEPS[0]])

    @bot.message_handler(func=lambda message:
        user_data.has_user(message.from_user.id) and
        user_data.get_current_action(message.from_user.id) == "saving_new")
    def handle_save_input(message):
        """Handle input for the form when saving new data (step-by-step)"""
        if message.text.startswith('/'):  # Skip if it's a command
            if message.text == '/cancel':
                user_data.clear_user_data(message.from_user.id)
                bot.reply_to(message, "✖️ Процесс заполнения отменен.")
            return

        user_id = message.from_user.id
        current_step = user_data.get_current_step(user_id)
        step_name = STEPS[current_step]
        response = message.text.strip()

        # Validate input based on step
        valid = True
        error_msg = None

        try:
            if step_name == "shipment_date" or step_name == "estimated_arrival":
                if not validate_date(response):
                    valid = False
                    error_msg = "Неверный формат даты. Используйте дд/мм/гггг или дд.мм.гггг"
                else:
                    response = standardize_date(response)

            elif step_name == "total_amount":
                if not validate_amount(response):
                    valid = False
                    error_msg = "Неверное количество. Введите положительное число."
                else:
                    response = int(response)

            elif step_name == "size_amounts":
                if not validate_size_amounts(response):
                    valid = False
                    error_msg = "Неверный формат. Используйте формат 'S: 50 M: 25 L: 50'"

            if valid:
                # Save response
                if step_name == "size_amounts":
                    sizes = parse_size_amounts(response)
                    for size_key, size_value in sizes.items():
                        user_data.update_form_data(user_id, size_key, size_value)
                else:
                    user_data.update_form_data(user_id, step_name, response)

                # Move to next step or complete
                next_step = current_step + 1

                if next_step < len(STEPS):
                    # Move to next step
                    user_data.set_current_step(user_id, next_step)
                    next_step_name = STEPS[next_step]
                    bot.send_message(message.chat.id, PROMPTS[next_step_name])
                else:
                    # Complete the process
                    try:
                        row_index = save_to_sheets(bot, message)
                        # After successful save, notify admins about the new record
                        notify_admins_about_new_record(bot, message, row_index)
                    except Exception as e:
                        logger.error(f"Error in save_to_sheets: {str(e)}")
                        bot.reply_to(message, "❌ Произошла ошибка при сохранении данных. Попробуйте еще раз.")
                        user_data.clear_user_data(user_id)
                        return
            else:
                # Send error message and repeat the prompt
                bot.reply_to(message, error_msg)
                bot.send_message(message.chat.id, PROMPTS[step_name])

        except Exception as e:
            logger.error(f"Error in handle_save_input: {str(e)}")
            bot.reply_to(message, "❌ Произошла ошибка при обработке данных. Попробуйте еще раз.")
            user_data.clear_user_data(user_id)

    def notify_admins_about_new_record(bot, message, row_index):
        """Notify all admins about a new record being added to Google Sheets"""
        try:
            user_id = message.from_user.id
            username = message.from_user.username or message.from_user.first_name or f"User ID: {user_id}"

            # Get the sheet manager and worksheet
            sheets_manager = GoogleSheetsManager.get_instance()
            worksheet = sheets_manager.get_main_worksheet()

            # Get the current record to include in the notification
            record = worksheet.row_values(row_index)

            # Extract relevant information
            product_name = record[3] if len(record) > 3 else "Unknown product"
            product_color = record[7] if len(record) > 7 else "Unknown color"
            shipment_date = record[4] if len(record) > 4 else "Unknown date"
            estimated_arrival = record[5] if len(record) > 5 else "Unknown date"
            total_amount = record[8] if len(record) > 8 else "Unknown amount"
            warehouse_name = record[9] if len(record) > 9 else "Unknown warehouse"
            
            # Extract sizes and create compact display
            size_mapping = {10: 'XS', 11: 'S', 12: 'M', 13: 'L', 14: 'XL', 15: '2XL', 16: '3XL', 17: '4XL', 18: '5XL', 19: '6XL', 20: '7XL'}
            active_sizes = []

            for col_idx, size_name in size_mapping.items():
                if len(record) > col_idx and record[col_idx]:
                    qty = str(record[col_idx]).strip()
                    if qty and qty != '0':
                        active_sizes.append(f"{size_name}({qty})")

            sizes_text = ", ".join(active_sizes) if active_sizes else "—"

            notification_text = (
                f"🆕 Новая запись добавлена в таблицу\n\n"
                f"Пользователь: @{username}\n"
                f"Изделие: {product_name}\n"
                f"Цвет: {product_color}\n"
                f"Дата отправки: {shipment_date}\n"
                f"Примерная дата прибытия: {estimated_arrival}\n"
                f"Склад: {warehouse_name}\n"
                f"Общее количество: {total_amount}\n"
                f"Размеры: {sizes_text}\n"
                f"Дата добавления: {datetime.now(pytz.timezone('Asia/Bishkek')).strftime('%Y-%m-%d %H:%M:%S')}"
            )

            # Send notification to each admin
            for admin_username in ADMIN_USER_USERNAMES:
                try:
                    # Get the admin's chat_id from the users worksheet
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
                        logger.info(f"New record notification sent to admin {admin_username}")
                    else:
                        logger.warning(f"Admin {admin_username} not found in users worksheet")
                except Exception as admin_error:
                    logger.error(f"Failed to notify admin {admin_username}: {str(admin_error)}")
        except Exception as e:
            logger.error(f"Error notifying admins about new record: {str(e)}")
            # This error shouldn't prevent the user from completing their task
            # so we just log it and don't send any error message to the user


    @bot.message_handler(commands=['cancel'])
    def cancel_save_process(message):
        """Cancel the save process"""
        user_id = message.from_user.id
        if user_data.has_user(user_id):
            user_data.clear_user_data(user_id)
            bot.reply_to(message, "✖️ Процесс заполнения отменен.")
        else:
            bot.reply_to(message, "Нет активного процесса для отмены.")