from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from constants import PROMPTS, STEPS
from models.user_data import user_data
from utils.validators import validate_date, validate_amount, validate_size_amounts, parse_size_amounts, standardize_date
from utils.google_sheets import save_to_sheets, GoogleSheetsManager
from config import ADMIN_USER_USERNAMES
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def setup_save_handler(bot: TeleBot):
    @bot.message_handler(commands=['save'])
    def start_save_process(message):
        """Start the product data collection process"""
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
        """Handle input for the form when saving new data"""
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
            total_amount = record[6] if len(record) > 6 else "Unknown amount"

            # Prepare notification text
            notification_text = (
                f"🆕 Новая запись добавлена в таблицу\n\n"
                f"Пользователь: @{username}\n"
                f"Изделие: {product_name}\n"
                f"Цвет: {product_color}\n"
                f"Дата отправки: {shipment_date}\n"
                f"Примерная дата прибытия: {estimated_arrival}\n"
                f"Общее количество: {total_amount}\n"
                f"Дата добавления: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
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