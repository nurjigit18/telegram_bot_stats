from telebot import TeleBot
from models.user_data import user_data

def setup_help_handler(bot: TeleBot):
    @bot.message_handler(commands=['help'])
    def send_help(message):
        """Handle start and help commands"""
        user_id = message.from_user.id
        
        # Add user's command to context
        user_data.add_message_to_context(user_id, "user", "/help")
        
        help_text = (
            "💾 Нажмите /save чтобы ввести данные изделия.\n"
            "📝 Нажмите /edit чтобы редактировать данные.\n"
            "🪪 Нажмите /status чтобы проверить статус вашего изделия\nи обновить фактическую дату прибытия\n"
            "🧾 Нажмите /payment чтобы отправить чек оплаты.\n"
            "ℹ️ Нажмите /help для подробной информации.\n\n"
        )
        bot.reply_to(message, help_text)
        
        # Add bot's response to context
        user_data.add_message_to_context(user_id, "assistant", help_text)
