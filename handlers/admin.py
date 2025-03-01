from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import ADMIN_USER_USERNAMES
from models.user_data import user_data
from utils.keyboards import show_product_selection
from handlers.deletion import show_delete_confirmation
from utils.google_sheets import GoogleSheetsManager

from utils.announcements import process_news_announcement
import logging

logger = logging.getLogger(__name__)


def setup_admin_handler(bot):
    @bot.message_handler(commands=['admin'])
    def handle_admin_command(message):
        user_username = message.from_user.username
        if user_username not in ADMIN_USER_USERNAMES:
            bot.reply_to(message, "У вас недостаточно прав для этого действия.")
            return
        
        # Display admin options
        admin_markup = InlineKeyboardMarkup()
        admin_markup.row(
            InlineKeyboardButton("🔔 Новое обьявление", callback_data="admin_new_announce"),
        )
        admin_markup.row(
            InlineKeyboardButton("🗑️ Удалить запись", callback_data="admin_delete_record")
        )
        # Add cancel button
        admin_markup.row(
            InlineKeyboardButton("❌ Отмена", callback_data="admin_cancel")
        )
        bot.send_message(message.chat.id, "Выберите действие:", reply_markup=admin_markup)

    @bot.callback_query_handler(func=lambda call: call.data == "admin_cancel")
    def handle_admin_cancel(call):
        try:
            bot.answer_callback_query(call.id)
            bot.edit_message_text(
                "🚫 Действие администратора отменено.",
                call.message.chat.id,
                call.message.message_id
            )
        except Exception as e:
            logger.error(f"Error handling admin cancel: {str(e)}")
            bot.send_message(call.message.chat.id, "❌ Ошибка при отмене операции.")
        
def setup_admin_handlers(bot: TeleBot):
    @bot.callback_query_handler(func=lambda call: call.data.startswith("admin_") or call.data.startswith("delete_") or call.data.startswith("confirm_delete_") or call.data.startswith("cancel_delete_"))
    def handle_admin_actions(call):
        if call.data == "admin_new_announce":
            bot.answer_callback_query(call.id)
            
            #Add cancel button
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("Отмена", callback_data="admin_cancel_announce"))
            bot.send_message(call.message.chat.id, "Пожалуйста введите новое обьявление:", reply_markup=markup)
            bot.register_next_step_handler(call.message, process_news_announcement)

        elif call.data == "admin_delete_record":
            bot.answer_callback_query(call.id)
            show_product_selection(bot, call.message.chat.id, "Выберите запись для удаления:", "delete_")

        elif call.data.startswith("delete_"):
            bot.answer_callback_query(call.id)
            row_index = int(call.data.split("_")[1])

            # Show confirmation dialog
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("Подтвердить", callback_data=f"confirm_delete_{row_index}"))
            markup.add(InlineKeyboardButton("Отмена", callback_data=f"cancel_delete_{row_index}"))
            bot.edit_message_text(
                "Вы уверены, что хотите удалить эту запись?",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        
        elif call.data.startswith("confirm_delete_"):
            bot.answer_callback_query(call.id)
            row_index = int(call.data.split("_")[2])
            try:
                # Get product info before deletion for confirmation message
                sheets_manager = GoogleSheetsManager.get_instance()
                row_data = sheets_manager.get_main_worksheet().row_values(row_index)
                product_name = row_data[3] if len(row_data) > 3 else "Unknown"
                product_color = row_data[7] if len(row_data) > 7 else "Unknown"
                
                # Delete the row
                sheets_manager = GoogleSheetsManager.get_instance()
                sheets_manager.get_main_worksheet().delete_rows(row_index)
                bot.edit_message_text(
                    f"✅ Запись удалена успешно!\nИзделие: {product_name}\nЦвет: {product_color}",
                    call.message.chat.id,
                    call.message.message_id
                )
            except Exception as e:
                logger.error(f"Error deleting row {row_index}: {str(e)}")
                bot.edit_message_text(
                    f"❌ Ошибка при удалении записи. Пожалуйста, попробуйте позже.",
                    call.message.chat.id,
                    call.message.message_id
                )
        
        elif call.data.startswith("cancel_delete_"):
            bot.answer_callback_query(call.id)
            bot.edit_message_text(
                "🚫 Удаление отменено.",
                call.message.chat.id,
                call.message.message_id
            )

    @bot.callback_query_handler(func=lambda call: call.data == "admin_cancel_announce")
    def handle_admin_cancel_announce(call):
        try:
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, "🚫 Добавление объявления отменено.")
        except Exception as e:
            logger.error(f"Error handling cancel announce: {str(e)}")
            bot.send_message(call.message.chat.id, "❌ Ошибка при отмене операции.")
