# handlers/save.py
from telebot import TeleBot
from constants import PROMPTS, STEPS
from models.user_data import user_data
from utils.validators import validate_date, validate_amount, validate_size_amounts, parse_size_amounts, standardize_date
from utils.google_sheets import save_to_sheets
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
                        save_to_sheets(bot, message)
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

    @bot.message_handler(commands=['cancel'])
    def cancel_save_process(message):
        """Cancel the save process"""
        user_id = message.from_user.id
        if user_data.has_user(user_id):
            user_data.clear_user_data(user_id)
            bot.reply_to(message, "✖️ Процесс заполнения отменен.")
        else:
            bot.reply_to(message, "Нет активного процесса для отмены.")