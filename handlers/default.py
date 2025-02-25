from telebot import TeleBot

def setup_default_handler(bot: TeleBot):
    @bot.message_handler(func=lambda message: True)
    def default_response(message):
        """Handle any other messages"""
        # Ensure the message is not from an admin action or a recognized command
        if message.text not in ["/save", "/help", "Новое обьявление", "Изменить статус изделия", "/status"]:
            bot.reply_to(message, "Нажмите /save чтобы ввести данные изделия или /help для помоши.")
