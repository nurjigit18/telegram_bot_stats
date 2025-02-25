from telebot import TeleBot
from models.user_data import user_data

def setup_cancel_handler(bot: TeleBot):
    @bot.message_handler(commands=['cancel'])
    def cancel_process(message):
        """Cancel the current data entry process"""
        user_id = message.from_user.id
        if user_id in user_data:
            del user_data.get_user_data(user_id)
            bot.send_message(message.chat.id, "Заполнение отмененно. Нажмите /save для заполнения данных.")
        else:
            bot.send_message(message.chat.id, "Нажмите /save для начала заполнения данных.")