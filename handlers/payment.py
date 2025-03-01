# from telebot import TeleBot

# def setup_payment_handler(bot: TeleBot):
#     @bot.message_handler(commands=['payment'])
#     def send_help(message):
#         """Handle payment requests"""
#         payment_text = (
#             "Данные реквизитов для переводов.\n\n"
#             "Mbank: \n"
#             "Optima: \n"
#             "СберБанк: \n"
#             "DemirBank: \n"
#         )
#         bot.reply_to(message, payment_text)