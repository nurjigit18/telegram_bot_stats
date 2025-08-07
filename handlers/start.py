from telebot import TeleBot, types
from utils.google_sheets import GoogleSheetsManager
import logging
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

def setup_start_handler(bot: TeleBot):
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        user_id = message.from_user.id
        username = message.from_user.username or "Unknown"
        first_name = message.from_user.first_name or ""

        try:
            sheets_manager = GoogleSheetsManager.get_instance()
            users_sheet = sheets_manager.get_users_worksheet()
            user_exists = False
            try:
                user_cells = users_sheet.findall(str(user_id))
                user_exists = len(user_cells) > 0
            except:
                user_exists = False

            if not user_exists:
                registration_date = datetime.now(pytz.timezone('Asia/Bishkek')).strftime("%Y-%m-%d %H:%M:%S")
                users_sheet.append_row([user_id, username, first_name, registration_date])
                logger.info(f"Saved user {username} with ID {user_id} to Google Sheets")
        except Exception as e:
            logger.error(f"Error saving user to Google Sheets: {str(e)}")

        welcome_text = (
            """Добро пожаловать! 
            
Вы на связи с личным ботом от Алины Курмановой и команды Nova Eris.

Этот бот создан для наших поставщиков.

Здесь вы можете:

▶️ Вводить и отслеживать отправки изделий это помогает нам видеть, на какой стадии находится производство.

⭐️Получать уведомления об оплате наших услуг,

💸 Получать ежемесячный фин. отчёт от Wildberries,

✉️Следить за важными новостями и обновлениями от нашей команды.

Всё просто, удобно и в одном месте!\n\n"""
            "Нажмите кнопку ниже чтобы выбрать действие.\n"
            "Пожалуйста введите все данные при заполнении."
        )

        # ----------- Inline Main Menu Keyboard -----------
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            types.InlineKeyboardButton("Сохранить запись", callback_data='mainmenu_save'),
            types.InlineKeyboardButton("Изменить запись", callback_data='mainmenu_edit'),
            types.InlineKeyboardButton("Запись и статус записи", callback_data='mainmenu_status'),
            types.InlineKeyboardButton("Отправить чек", callback_data='mainmenu_payment')
        )

        bot.send_message(message.chat.id, welcome_text, reply_markup=keyboard)

    # ----------- Inline Button Handlers -----------
    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith('mainmenu_'))
    def handle_menu_buttons(call):
        if call.data == 'mainmenu_save':
            bot.send_message(call.message.chat.id, "📝 Пожалуйста, введите данные для сохранения изделия.")
        elif call.data == 'mainmenu_edit':
            bot.send_message(call.message.chat.id, "✏️ Введите ID записи для изменения.")
        elif call.data == 'mainmenu_status':
            bot.send_message(call.message.chat.id, "📋 Введите ID изделия для проверки статуса.")
        elif call.data == 'mainmenu_payment':
            bot.send_message(call.message.chat.id, "💸 Пожалуйста, отправьте фото чека или PDF.")

        bot.answer_callback_query(call.id)
