from telebot import TeleBot

def setup_help_handler(bot: TeleBot):
    @bot.message_handler(commands=['help'])
    def send_help(message):
        """Handle start and help commands"""
        help_text = (
            "💾 Нажмите /save чтобы ввести данные изделия.\n"
            "📝 Нажмите /edit чтобы редактировать данные.\n"
            "🪪 Нажмите /status чтобы проверить статус вашего изделия\nи обновить фактическую дату прибытия\n"
            "ℹ️ Нажмите /help для подробной информации.\n\n"
        )
        bot.reply_to(message, help_text)
