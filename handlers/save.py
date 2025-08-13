from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from constants import PROMPTS, STEPS
from models.user_data import user_data
from utils.validators import validate_date, validate_amount, validate_size_amounts, parse_size_amounts, standardize_date, validate_warehouse_sizes
from utils.google_sheets import save_to_sheets, GoogleSheetsManager
from utils.openai_parser import openai_parser
from config import ADMIN_USER_USERNAMES, OPENAI_ENABLED
from datetime import datetime
import logging
import re
import pytz

logger = logging.getLogger(__name__)

def parse_warehouse_sizes(warehouse_sizes_str):
    """
    Parse warehouse and sizes string into structured data with robust input handling
    
    Formats supported:
    - Single warehouse: "Казань: S-50 M-25 L-25" or "Казань:S-50 M-25 L-25"
    - Multiple warehouses: "Казань: S-30 M-40 , Москва: L-50 XL-80" or "Казань:S-30 M-40,Москва:L-50 XL-80"
    - Handles missing spaces after colons and commas
    - Handles missing spaces between sizes
    - Case insensitive size names
    - Handles mixed Latin/Cyrillic characters in warehouse names
    
    Returns: List of tuples [(warehouse_name, {size: quantity})]
    """
    try:
        # Step 1: Clean and normalize the input string
        cleaned_str = normalize_warehouse_input(warehouse_sizes_str)
        
        warehouse_data = []
        
        # Step 2: Split by comma for multiple warehouses (now properly spaced)
        warehouse_parts = [part.strip() for part in cleaned_str.split(',') if part.strip()]
        
        for warehouse_part in warehouse_parts:
            if ':' not in warehouse_part:
                return None  # Invalid format
            
            # Step 3: Split warehouse name and sizes
            warehouse_name, sizes_str = warehouse_part.split(':', 1)
            warehouse_name = warehouse_name.strip()
            sizes_str = sizes_str.strip()
            
            # Step 4: Parse sizes with robust splitting
            sizes = parse_sizes_string(sizes_str)
            if not sizes:
                return None  # Invalid sizes format
            
            warehouse_data.append((warehouse_name, sizes))
        
        return warehouse_data if warehouse_data else None
        
    except Exception as e:
        logger.error(f"Error parsing warehouse sizes: {e}")
        return None
    
def normalize_warehouse_input(input_str):
    """
    Normalize warehouse input string by adding missing spaces and cleaning format
    Handles both Latin and Cyrillic characters with improved regex patterns
    """
    # Remove extra whitespace
    cleaned = re.sub(r'\s+', ' ', input_str.strip())
    
    # Add space after colon if missing: "Склад:размеры" -> "Склад: размеры"
    # Handle both Latin and Cyrillic characters
    cleaned = re.sub(r'([^\s:]):([^\s])', r'\1: \2', cleaned)
    
    # Add space after comma if missing: "размеры,Склад" -> "размеры, Склад"
    cleaned = re.sub(r'([^\s,]),([^\s])', r'\1, \2', cleaned)
    
    # Fix cases where sizes are stuck together with warehouse names or other sizes
    # This handles cases like "Tyлa: XS-47 S-80" or "XS-52S-37M-34"
    # First, handle sizes stuck to warehouse names after colon
    cleaned = re.sub(r'(:)([A-Za-zА-Яа-я0-9]+)(-\d+)([A-Za-zА-Яа-я0-9]+)(-\d+)', r'\1\2\3 \4\5', cleaned)
    
    # Then handle multiple consecutive stuck sizes
    # Keep applying the fix until no more changes are made
    prev_cleaned = ""
    max_iterations = 20  # Prevent infinite loops
    iteration = 0
    
    while prev_cleaned != cleaned and iteration < max_iterations:
        prev_cleaned = cleaned
        # Handle pattern like "XS-52S-37M-34L-36XL-20"
        cleaned = re.sub(r'([A-Za-zА-Яа-я0-9]+)-(\d+)([A-Za-zА-Яа-я0-9]+)-(\d+)', r'\1-\2 \3-\4', cleaned)
        iteration += 1
    
    return cleaned

def parse_sizes_string(sizes_str):
    """
    Parse sizes string into dictionary with robust handling.
    Handles formats like: "S-50 M-25 L-25" or "s-50m-25l-25" or "S-50M-25L-25"
    Supports both Latin and Cyrillic characters, case insensitive.
    """
    sizes = {}

    # Regex finds all size-quantity pairs like 'xs-52', '2xl-1', etc.
    pattern = r'([a-zA-Zа-яА-Я0-9]+)-(\d+)'
    matches = re.findall(pattern, sizes_str)
    if not matches:
        return None

    valid_sizes = {
        # English sizes
        'XS': 'XS', 'S': 'S', 'M': 'M', 'L': 'L', 'XL': 'XL',
        '2XL': '2XL', '3XL': '3XL', '4XL': '4XL', '5XL': '5XL',
        '6XL': '6XL', '7XL': '7XL',
        # Russian equivalents
        'ХС': 'XS', 'С': 'S', 'М': 'M', 'Л': 'L', 'ХЛ': 'XL',
        '2ХЛ': '2XL', '3ХЛ': '3XL', '4ХЛ': '4XL', '5ХЛ': '5XL',
        '6ХЛ': '6XL', '7ХЛ': '7XL',
        # Mixed common variations
        'XС': 'XS', 'СS': 'S', 'ХS': 'XS', 'XЛ': 'XL', 'ЛL': 'L',
        'XXL': 'XL', 'XXXL': '3XL'
    }

    for size, qty in matches:
        size = size.strip().upper()
        if size in valid_sizes:
            std_size = valid_sizes[size]
            try:
                quantity = int(qty)
                if quantity > 0:
                    sizes[std_size] = quantity
            except ValueError:
                continue  # skip invalid quantities
        else:
            continue  # skip unknown sizes

    return sizes if sizes else None


def validate_warehouse_sizes_enhanced(warehouse_sizes_str):
    """
    Enhanced validation for warehouse sizes string with better error reporting
    """
    if not warehouse_sizes_str or not warehouse_sizes_str.strip():
        return False, "Строка складов и размеров пуста"
    
    try:
        # Try to parse the warehouse sizes
        parsed_data = parse_warehouse_sizes(warehouse_sizes_str)
        if parsed_data is None:
            return False, "Не удалось разобрать формат складов и размеров"
        if len(parsed_data) == 0:
            return False, "Не найдено ни одного склада"
        
        # Additional validation: check if all warehouses have valid sizes
        for warehouse_name, sizes in parsed_data:
            if not sizes:
                return False, f"Склад '{warehouse_name}' не имеет допустимых размеров"
        
        return True, None
    except Exception as e:
        return False, f"Ошибка при разборе: {str(e)}"

def setup_save_handler(bot: TeleBot):
    @bot.message_handler(commands=['save'])
    def start_save_process(message):
        """Start the product data collection process with single message input"""
        user_id = message.from_user.id

        # Initialize user data
        user_data.initialize_user(user_id)
        user_data.set_current_action(user_id, "saving_new_single")
        user_data.initialize_form_data(user_id)

        # Add bot's instruction message to context
        if OPENAI_ENABLED:
            sample_format = (
                "🤖 Теперь вы можете вводить данные в свободной форме!\n\n"
                "💬 Просто опишите товар естественным языком, например:\n"
                "\"Привет! красныe рубашки, 100 штук, Казань: 50S, 25M, 25L. 12/12/2025 - 15/12/2025.\"\n\n"

                "Нажмите /cancel для отмены заполнения."
            )
        else:
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
                "• Разделитель складов: , (запятая)\n"
                "• Разделитель размеров: - (дефис)\n"
                "• Поддерживаются размеры: XS, S, M, L, XL, 2XL, 3XL, 4XL, 5XL, 6XL, 7XL\n\n"
                "Нажмите /cancel для отмены заполнения."
            )
        
        # Add the /save command to context
        user_data.add_message_to_context(user_id, "user", "/save")
        # Add bot's response to context
        user_data.add_message_to_context(user_id, "assistant", sample_format)
        
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
        
        # Add user's message to context
        user_data.add_message_to_context(user_id, "user", message.text)
        
        try:
            # Try OpenAI parsing first if enabled
            if OPENAI_ENABLED:
                processing_msg = "🤖 Обрабатываю ваш запрос с помощью ИИ..."
                bot.reply_to(message, processing_msg)
                user_data.add_message_to_context(user_id, "assistant", processing_msg)
                
                success, parsed_data, error_msg = openai_parser.parse_product_data(message.text, user_id=user_id)
                
                logger.info(f"OpenAI parsing result: success={success}, parsed_data={parsed_data}")
                
                if success and parsed_data:
                    # Check if we have ALL required fields with valid data
                    required_fields = ['product_name', 'product_color', 'total_amount', 'warehouse_sizes', 'shipment_date', 'estimated_arrival']
                    all_fields_present = all(
                        field in parsed_data and 
                        parsed_data[field] is not None and 
                        str(parsed_data[field]).strip() != '' 
                        for field in required_fields
                    )
                    
                    if all_fields_present:
                        # Process OpenAI-extracted data
                        product_name = parsed_data['product_name']
                        product_color = parsed_data['product_color']
                        total_amount = parsed_data['total_amount']
                        warehouse_sizes_str = parsed_data['warehouse_sizes']
                        shipment_date_str = parsed_data['shipment_date']
                        estimated_arrival_str = parsed_data['estimated_arrival']
                        
                        # Show what was extracted for confirmation
                        confirmation_msg = (
                            "🤖 ИИ извлек следующие данные:\n\n"
                            f"📦 Название изделия: {product_name}\n"
                            f"🎨 Цвет изделия: {product_color}\n"
                            f"📊 Количество: {total_amount} шт\n"
                            f"🏪 Склады и размеры: {warehouse_sizes_str}\n"
                            f"📅 Дата отправки: {shipment_date_str}\n"
                            f"📅 Дата прибытия: {estimated_arrival_str}\n\n"
                            "✅ Проверяю данные..."
                        )
                        bot.reply_to(message, confirmation_msg)
                        user_data.add_message_to_context(user_id, "assistant", confirmation_msg)
                        
                        # Validate OpenAI-extracted data
                        validation_errors = validate_extracted_data(
                            product_name, product_color, total_amount, 
                            warehouse_sizes_str, shipment_date_str, estimated_arrival_str
                        )
                        
                        if validation_errors:
                            # Show validation errors for OpenAI data
                            error_message = "❌ Найдены следующие ошибки в извлеченных данных:\n\n" + "\n".join(validation_errors)
                            error_message += "\n\nПожалуйста, исправьте данные и отправьте заново."
                            bot.reply_to(message, error_message)
                            user_data.add_message_to_context(user_id, "assistant", error_message)
                            return
                        
                        # If validation passed, proceed to save
                        save_data_to_sheets(bot, message, user_id, product_name, product_color, 
                                          total_amount, warehouse_sizes_str, 
                                          standardize_date(shipment_date_str), 
                                          standardize_date(estimated_arrival_str))
                        return
                        
                    else:
                        # Some fields are missing - generate friendly request
                        friendly_request = openai_parser.generate_missing_data_request(message.text, parsed_data)
                        bot.reply_to(message, friendly_request)
                        user_data.add_message_to_context(user_id, "assistant", friendly_request)
                        return
                else:
                    # OpenAI parsing failed - fall back to strict format
                    logger.warning(f"OpenAI parsing failed: {error_msg}")
                    fallback_msg = f"🤖 Не удалось обработать запрос через ИИ\n\n📋 Попробую обработать как строгий формат..."
                    bot.reply_to(message, fallback_msg)
                    user_data.add_message_to_context(user_id, "assistant", fallback_msg)
            
            # Fall back to strict format parsing if OpenAI failed or is disabled
            handle_strict_format_input(bot, message, user_id)
            
        except Exception as e:
            logger.error(f"Error in handle_single_save_input: {str(e)}")
            bot.reply_to(message, f"❌ Произошла ошибка при обработке данных: {str(e)}. Попробуйте еще раз.")
            user_data.clear_user_data(user_id)

    def validate_extracted_data(product_name, product_color, total_amount, warehouse_sizes_str, shipment_date_str, estimated_arrival_str):
        """Validate extracted data and return list of errors"""
        errors = []

        # Validate product name
        if not product_name or not product_name.strip():
            errors.append("• Название изделия не может быть пустым")

        # Validate product color
        if not product_color or not product_color.strip():
            errors.append("• Цвет изделия не может быть пустым")

        # Validate total amount
        if not isinstance(total_amount, int) or total_amount <= 0:
            errors.append("• Неверное количество. Должно быть положительным числом")

        # Validate warehouse and sizes format
        is_valid, error_msg = validate_warehouse_sizes_enhanced(warehouse_sizes_str)
        if not is_valid:
            errors.append(f"• {error_msg}")
        else:
            warehouse_data = parse_warehouse_sizes(warehouse_sizes_str)
            if not warehouse_data:
                errors.append("• Ошибка при разборе складов и размеров")
            else:
                # Validate that total amounts match
                calculated_total = sum(sum(sizes.values()) for _, sizes in warehouse_data)
                if calculated_total != total_amount:
                    errors.append(f"• Сумма размеров ({calculated_total}) не совпадает с общим количеством ({total_amount})")
                    
                    # Provide detailed breakdown for debugging
                    breakdown = []
                    for warehouse_name, sizes in warehouse_data:
                        warehouse_total = sum(sizes.values())
                        size_details = ", ".join([f"{size}:{qty}" for size, qty in sizes.items()])
                        breakdown.append(f"  {warehouse_name}: {size_details} = {warehouse_total}")
                    
                    errors.append("Разбивка по складам:\n" + "\n".join(breakdown))

        # Validate shipment date
        if not validate_date(shipment_date_str):
            errors.append("• Неверный формат даты отправки. Используйте дд/мм/гггг или дд.мм.гггг")

        # Validate estimated arrival date
        if not validate_date(estimated_arrival_str):
            errors.append("• Неверный формат даты прибытия. Используйте дд/мм/гггг или дд.мм.гггг")

        return errors

    def save_data_to_sheets(bot, message, user_id, product_name, product_color, total_amount, warehouse_sizes_str, shipment_date, estimated_arrival):
        """Save validated data to Google Sheets"""
        try:
            warehouse_data = parse_warehouse_sizes(warehouse_sizes_str)
            saved_records = 0
            warehouse_records = []
            
            for warehouse_name, sizes in warehouse_data:
                # Clear previous form data
                user_data.initialize_form_data(user_id)
                
                # Set form data for this warehouse
                user_data.update_form_data(user_id, 'product_name', product_name)
                user_data.update_form_data(user_id, 'product_color', product_color)
                user_data.update_form_data(user_id, 'total_amount', sum(sizes.values()))
                user_data.update_form_data(user_id, 'warehouse', warehouse_name)
                user_data.update_form_data(user_id, 'shipment_date', shipment_date)
                user_data.update_form_data(user_id, 'estimated_arrival', estimated_arrival)

                # Add size amounts
                for size_key, size_value in sizes.items():
                    user_data.update_form_data(user_id, size_key, size_value)

                # Save to sheets
                row_index = save_to_sheets(bot, message)
                saved_records += 1
                warehouse_records.append((warehouse_name, sizes))
                
                notify_admins_about_new_record(bot, message, row_index)
                logger.info(f"Successfully saved record for warehouse {warehouse_name}")

            # Show success confirmation
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
            user_data.add_message_to_context(user_id, "assistant", confirmation_msg)
            
            # Clear user data after success
            user_data.clear_user_data(user_id)
            
        except Exception as e:
            logger.error(f"Error saving to sheets: {str(e)}")
            bot.reply_to(message, f"❌ Ошибка при сохранении: {str(e)}")
            user_data.clear_user_data(user_id)

    def handle_strict_format_input(bot, message, user_id):
        """Handle strict format input as fallback"""
        lines = [line.strip() for line in message.text.strip().split('\n') if line.strip()]
        
        expected_fields = 6
        if len(lines) != expected_fields:
            if OPENAI_ENABLED:
                error_msg = (
                    f"❌ Не удалось обработать ни через ИИ, ни через строгий формат.\n\n"
                    f"Для строгого формата ожидается {expected_fields} строк, получено {len(lines)}.\n\n"
                    "Убедитесь, что вы заполнили все поля в правильном порядке:\n"
                    "1. Название изделия\n"
                    "2. Цвет изделия\n"
                    "3. Количество (шт)\n"
                    "4. Склады и размеры\n"
                    "5. Дата отправки\n"
                    "6. Дата возможного прибытия\n\n"
                    "Или попробуйте описать товар естественным языком."
                )
            else:
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
            user_data.add_message_to_context(user_id, "assistant", error_msg)
            return

        # Extract fields
        product_name = lines[0]
        product_color = lines[1]
        total_amount_str = lines[2]
        warehouse_sizes_str = lines[3]
        shipment_date_str = lines[4]
        estimated_arrival_str = lines[5]
        
        # Convert total_amount to int for validation
        if not validate_amount(total_amount_str):
            bot.reply_to(message, "❌ Неверное количество. Введите положительное число.")
            return
        
        total_amount = int(total_amount_str)
        
        # Validate and save
        validation_errors = validate_extracted_data(
            product_name, product_color, total_amount,
            warehouse_sizes_str, shipment_date_str, estimated_arrival_str
        )
        
        if validation_errors:
            error_message = "❌ Найдены следующие ошибки:\n\n" + "\n".join(validation_errors)
            error_message += "\n\nПожалуйста, исправьте ошибки и отправьте данные заново."
            bot.reply_to(message, error_message)
            user_data.add_message_to_context(user_id, "assistant", error_message)
            return
        
        # Save data
        save_data_to_sheets(bot, message, user_id, product_name, product_color,
                           total_amount, warehouse_sizes_str,
                           standardize_date(shipment_date_str),
                           standardize_date(estimated_arrival_str))

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
