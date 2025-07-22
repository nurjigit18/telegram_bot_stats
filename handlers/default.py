from telebot import TeleBot
from models.user_data import user_data

def setup_default_handler(bot: TeleBot):
    @bot.message_handler(func=lambda message: True)
    def default_response(message):
        """Handle any other messages"""
        user_id = message.from_user.id
        
        # Ensure the message is not from an admin action or a recognized command
        if message.text not in ["/save", "/help", "Новое обьявление", "Изменить статус изделия", "/status"]:
            # Add user's message to context
            user_data.add_message_to_context(user_id, "user", message.text)
            
            response_msg = "Нажмите /save чтобы ввести данные изделия или /help для помоши."
            bot.reply_to(message, response_msg)
            
            # Add bot's response to context
            user_data.add_message_to_context(user_id, "assistant", response_msg)
