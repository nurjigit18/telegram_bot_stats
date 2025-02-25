# handlers/announcements.py
from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from models.user_data import user_data
from utils.announcements import send_announcement_to_all_users, send_announcement_to_user, send_file_to_all_users, send_file_to_user, send_photo_to_all_users, send_photo_to_user
from utils.google_sheets import GoogleSheetsManager, get_all_user_chat_ids
from config import ADMIN_USER_USERNAMES
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()
scheduler.start()

# Centralized function to create a standard menu with Cancel and Back buttons
def create_menu(options, back_callback=None):
    """
    Creates an inline keyboard markup with given options and standard Cancel/Back buttons.

    Args:
        options (list of tuples): List of (button_text, callback_data) tuples.
        back_callback (str, optional): Callback data for the Back button. Defaults to None.

    Returns:
        InlineKeyboardMarkup: The created keyboard markup.
    """
    markup = InlineKeyboardMarkup()
    for button_text, callback_data in options:
        markup.add(InlineKeyboardButton(button_text, callback_data=callback_data))

    if back_callback:
        markup.row(
            InlineKeyboardButton("Назад", callback_data=back_callback)
        )
    markup.row(
        InlineKeyboardButton("Отмена", callback_data="cancel_edit")
    )
    return markup

def setup_announcement_handlers(bot: TeleBot):

    def show_admin_menu(chat_id, message_id=None):
        """Shows the main admin announcement menu."""
        markup = create_menu(
            [
                ("Отправить всем", "announce_all"),
                ("Пользователю", "announce_individual"),
            ],
        )
        if message_id:
            bot.edit_message_text("Выберите тип обьявления:", chat_id, message_id, reply_markup=markup)
        else:
            bot.send_message(chat_id, "Выберите тип обьявления:", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data == "admin_new_announce")
    def handle_announcement_menu(call):
        """Handle the announcement menu callback."""
        user_username = call.from_user.username
        if user_username not in ADMIN_USER_USERNAMES:
            bot.answer_callback_query(call.id, "У вас недостаточно прав для этого действия.")
            return

        bot.answer_callback_query(call.id)

        show_admin_menu(call.message.chat.id, call.message.message_id)

    def show_send_options(bot: TeleBot, chat_id, message_id, content_type, target_type):
        """Shows options to send immediately or schedule."""
        markup = create_menu(
            [
                ("Отправить сейчас", f"send_now_{content_type}_{target_type}"),
                ("Запланировать", f"schedule_{content_type}_{target_type}"),
            ],
            back_callback=f"show_media_options_{target_type}"
        )

        bot.edit_message_text(
            "Выберите опцию:",
            chat_id,
            message_id,
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("send_now_"))
    def handle_send_now(call):
        """Handle the 'send now' callback."""
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        action = call.data.split("_")[2:]  # e.g., ["photo", "all"] or ["message", "individual"]
        content_type = action[0]  # "photo", "file", or "message"
        target_type = action[1]  # "all" or "individual"

        if not user_data.has_user(user_id):
            user_data.initialize_user(user_id)

        # Set the current action
        user_data.set_current_action(user_id, f"sending_{content_type}_to_{target_type}")

        # Ask for the content
        if content_type == "message":
            bot.send_message(call.message.chat.id, "Пожалуйста, введите сообщение:")
            bot.register_next_step_handler(call.message, process_announcement, target_type)
        elif content_type == "photo":
            bot.send_message(call.message.chat.id, "Пожалуйста, отправьте фото:")
            bot.register_next_step_handler(call.message, process_photo, target_type)
        elif content_type == "file":
            bot.send_message(call.message.chat.id, "Пожалуйста, отправьте файл:")
            bot.register_next_step_handler(call.message, process_file, target_type)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("schedule_"))
    def handle_schedule(call):
        """Handle the 'schedule' callback."""
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        action = call.data.split("_")[1:]  # e.g., ["photo", "all"] or ["message", "individual"]
        content_type = action[0]  # "photo", "file", or "message"
        target_type = action[1]  # "all" or "individual"

        if not user_data.has_user(user_id):
            user_data.initialize_user(user_id)

        # Set the current action
        user_data.set_current_action(user_id, f"scheduling_{content_type}_to_{target_type}")

        # Ask for the date and time
        bot.send_message(call.message.chat.id, "Пожалуйста, введите дату и время в формате: ДД.ММ.ГГГГ ЧЧ:ММ")
        bot.register_next_step_handler(call.message, process_schedule_time, content_type, target_type)

    def process_schedule_time(message, content_type, target_type):
        """Process the schedule time input."""
        user_id = message.from_user.id

        if not user_data.has_user(user_id):
            bot.send_message(message.chat.id, "Ошибка: сессия истекла. Пожалуйста, начните сначала.")
            return

        try:
            # Parse the datetime input
            schedule_time = datetime.strptime(message.text, "%d.%m.%Y %H:%M")

            # Save the schedule time in user data
            user_data.update_user_data(user_id, "schedule_time", schedule_time)

            # Ask for the content
            if content_type == "message":
                bot.send_message(message.chat.id, "Пожалуйста, введите сообщение:")
                bot.register_next_step_handler(message, process_scheduled_announcement, content_type, target_type)
            elif content_type == "photo":
                bot.send_message(message.chat.id, "Пожалуйста, отправьте фото:")
                bot.register_next_step_handler(message, process_scheduled_photo, content_type, target_type)
            elif content_type == "file":
                bot.send_message(message.chat.id, "Пожалуйста, отправьте файл:")
                bot.register_next_step_handler(message, process_scheduled_file, content_type, target_type)
        except ValueError:
            bot.send_message(message.chat.id, "❌ Неверный формат даты и времени. Пожалуйста, используйте формат: ДД.ММ.ГГГГ ЧЧ:ММ")

    def process_scheduled_announcement(message, content_type, target_type):
        """Process the scheduled announcement."""
        user_id = message.from_user.id

        if not user_data.has_user(user_id):
            bot.send_message(message.chat.id, "Ошибка: сессия истекла. Пожалуйста, начните сначала.")
            return

        announcement = message.text
        schedule_time = user_data.get_user_data(user_id).get("schedule_time")

        if not schedule_time:
            bot.send_message(message.chat.id, "Ошибка: время отправки не указано.")
            return

        try:
            if target_type == "all":
                # Schedule the announcement for all users
                scheduler.add_job(
                    send_announcement_to_all_users,
                    'date',
                    run_date=schedule_time,
                    args=[bot, message, announcement]
                )
            elif target_type == "individual":
                target_user_id = user_data.get_user_data(user_id).get("target_user_id")
                if not target_user_id:
                    bot.send_message(message.chat.id, "Ошибка: целевой пользователь не выбран.")
                    return

                # Schedule the announcement for the individual user
                scheduler.add_job(
                    send_announcement_to_user,
                    'date',
                    run_date=schedule_time,
                    args=[bot, target_user_id, announcement]
                )

            bot.send_message(message.chat.id, f"✅ Сообщение запланировано на {schedule_time}.")
            # Show admin menu after confirmation
            show_admin_menu(message.chat.id)
        except Exception as e:
            logger.error(f"Error scheduling announcement: {str(e)}")
            bot.send_message(message.chat.id, "❌ Ошибка при планировании сообщения.")

    def process_scheduled_photo(message, content_type, target_type):
        """Process the scheduled photo."""
        user_id = message.from_user.id

        if not user_data.has_user(user_id):
            bot.send_message(message.chat.id, "Ошибка: сессия истекла. Пожалуйста, начните сначала.")
            return

        if message.photo:
            photo_file_id = message.photo[-1].file_id
            schedule_time = user_data.get_user_data(user_id).get("schedule_time")

            if not schedule_time:
                bot.send_message(message.chat.id, "Ошибка: время отправки не указано.")
                return

            try:
                if target_type == "all":
                    # Schedule the photo for all users
                    scheduler.add_job(
                        send_photo_to_all_users,
                        'date',
                        run_date=schedule_time,
                        args=[bot, message, photo_file_id]
                    )
                elif target_type == "individual":
                    target_user_id = user_data.get_user_data(user_id).get("target_user_id")
                    if not target_user_id:
                        bot.send_message(message.chat.id, "Ошибка: целевой пользователь не выбран.")
                        return

                    # Schedule the photo for the individual user
                    scheduler.add_job(
                        send_photo_to_user,
                        'date',
                        run_date=schedule_time,
                        args=[bot, target_user_id, photo_file_id]
                    )

                bot.send_message(message.chat.id, f"✅ Фото запланировано на {schedule_time}.")
                # Show admin menu after confirmation
                show_admin_menu(message.chat.id)
            except Exception as e:
                logger.error(f"Error scheduling photo: {str(e)}")
                bot.send_message(message.chat.id, "❌ Ошибка при планировании фото.")
        else:
            bot.send_message(message.chat.id, "Пожалуйста, отправьте фото.")

    def process_scheduled_file(message, content_type, target_type):
        """Process the scheduled file."""
        user_id = message.from_user.id

        if not user_data.has_user(user_id):
            bot.send_message(message.chat.id, "Ошибка: сессия истекла. Пожалуйста, начните сначала.")
            return

        if message.document:
            file_id = message.document.file_id
            schedule_time = user_data.get_user_data(user_id).get("schedule_time")

            if not schedule_time:
                bot.send_message(message.chat.id, "Ошибка: время отправки не указано.")
                return

            try:
                if target_type == "all":
                    # Schedule the file for all users
                    scheduler.add_job(
                        send_file_to_all_users,
                        'date',
                        run_date=schedule_time,
                        args=[bot, message, file_id]
                    )
                elif target_type == "individual":
                    target_user_id = user_data.get_user_data(user_id).get("target_user_id")
                    if not target_user_id:
                        bot.send_message(message.chat.id, "Ошибка: целевой пользователь не выбран.")
                        return

                    # Schedule the file for the individual user
                    scheduler.add_job(
                        send_file_to_user,
                        'date',
                        run_date=schedule_time,
                        args=[bot, target_user_id, file_id]
                    )

                bot.send_message(message.chat.id, f"✅ Файл запланирован на {schedule_time}.")
                # Show admin menu after confirmation
                show_admin_menu(message.chat.id)
            except Exception as e:
                logger.error(f"Error scheduling file: {str(e)}")
                bot.send_message(message.chat.id, "❌ Ошибка при планировании файла.")
        else:
            bot.send_message(message.chat.id, "Пожалуйста, отправьте файл.")

    def show_media_options(bot: TeleBot, chat_id, message_id, target_type):
        """Show media options by editing the message."""
        markup = create_menu(
            [
                ("Фото", f"show_send_options_photo_{target_type}"),
                ("Файл", f"show_send_options_file_{target_type}"),
                ("Сообщение", f"show_send_options_message_{target_type}"),
            ],
            back_callback="admin_new_announce"  # Back to the main admin menu
        )

        bot.edit_message_text(
            "Выберите тип контента для отправки:",
            chat_id,
            message_id,
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("show_send_options_"))
    def handle_show_send_options(call):
        """Handles showing the send options (now or schedule)."""
        bot.answer_callback_query(call.id)
        action = call.data.split("_")
        content_type = action[3]
        target_type = action[4]
        show_send_options(bot, call.message.chat.id, call.message.message_id, content_type, target_type)

    @bot.callback_query_handler(func=lambda call: call.data == "announce_all")
    def handle_announce_all(call):
        """Handle the 'announce to all' callback."""
        bot.answer_callback_query(call.id)
        show_media_options(bot, call.message.chat.id, call.message.message_id, "all")
        user_id = call.from_user.id

        if not user_data.has_user(user_id):
            user_data.initialize_user(user_id)

        user_data.set_current_action(user_id, "announcing_to_all")
        bot.register_next_step_handler(call.message, process_announcement)

    @bot.callback_query_handler(func=lambda call: call.data == "announce_individual")
    def handle_announce_individual(call):
        """Handle the 'announce to individual user' callback."""
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id

        if not user_data.has_user(user_id):
            user_data.initialize_user(user_id)

        try:
            sheets_manager = GoogleSheetsManager.get_instance()
            users_worksheet = sheets_manager.get_users_worksheet()
            users_data = users_worksheet.get_all_values()

            if len(users_data) <= 1:  # Only headers
                bot.edit_message_text(
                    "Нет доступных пользователей для отправки сообщения.",
                    call.message.chat.id,
                    call.message.message_id
                )
                return

            options = []  # List to store user options

            # Skip header
            for i, user_row in enumerate(users_data[1:], start=2):
                if len(user_row) >= 2:
                    user_id = user_row[0]
                    username = user_row[1]
                    first_name = user_row[2] if len(user_row) > 2 else ""

                    display_name = username
                    if first_name:
                        display_name = f"{first_name} (@{username})"
                    elif username == "Unknown":
                        display_name = f"User {user_id[:4]}..."

                    options.append((display_name, f"user_{user_id}"))
                else:
                    logger.warning(f"Skipping row {i+1} due to insufficient data: {user_row}")

            if not options:
                bot.edit_message_text(
                    "Нет доступных пользователей для отправки сообщения.",
                    call.message.chat.id,
                    call.message.message_id
                )
                return
            # Generate menu with user options
            markup = create_menu(options, back_callback="admin_new_announce")

            bot.edit_message_text(
                "Выберите пользователя для отправки сообщения:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"Error fetching users: {str(e)}")
            bot.edit_message_text(
                "❌ Ошибка при получении списка пользователей. Попробуйте позже.",
                call.message.chat.id,
                call.message.message_id
            )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("user_"))
    def handle_user_selection(call):
        """Handle the user selection callback."""
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        selected_user_id = call.data.split("_")[1]

        if not user_data.has_user(user_id):
            user_data.initialize_user(user_id)

        user_data.update_user_data(user_id, "target_user_id", selected_user_id)
        show_media_options(bot, call.message.chat.id, call.message.message_id, "individual")

    @bot.callback_query_handler(func=lambda call: call.data == "cancel_edit")
    def handle_cancel(call):
        """Handle the cancel callback."""
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id

         # Reset user's state
        if user_data.has_user(user_id):
            user_data.clear_user_data(user_id)

        bot.send_message(call.message.chat.id, "Действие отменено.")

    # Media Sending Handlers (Photo, File, Message) - Immediate Send
    @bot.callback_query_handler(func=lambda call: call.data.startswith("send_photo_"))
    def handle_send_photo(call):
        """Handle sending photo immediately."""
        target_type = call.data.split("_")[2]
        bot.send_message(call.message.chat.id, "Пожалуйста, отправьте фото:")
        bot.register_next_step_handler(call.message, process_photo, target_type)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("send_file_"))
    def handle_send_file(call):
        """Handle sending file immediately."""
        target_type = call.data.split("_")[2]
        bot.send_message(call.message.chat.id, "Пожалуйста, отправьте файл:")
        bot.register_next_step_handler(call.message, process_file, target_type)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("send_message_"))
    def handle_send_message(call):
        """Handle sending message immediately."""
        target_type = call.data.split("_")[2]
        bot.send_message(call.message.chat.id, "Пожалуйста, введите сообщение:")
        bot.register_next_step_handler(call.message, process_announcement, target_type)

    # Process immediate photo
    def process_photo(message, target_type):
        """Process the photo."""
        user_id = message.from_user.id

        if not user_data.has_user(user_id):
            bot.send_message(message.chat.id, "Ошибка: сессия истекла. Пожалуйста, начните сначала.")
            return

        if message.photo:
            photo_file_id = message.photo[-1].file_id
            try:
                if target_type == "all":
                    send_photo_to_all_users(bot, message, photo_file_id)
                elif target_type == "individual":
                    target_user_id = user_data.get_user_data(user_id).get("target_user_id")
                    if not target_user_id:
                        bot.send_message(message.chat.id, "Ошибка: целевой пользователь не выбран.")
                        return
                    send_photo_to_user(bot, target_user_id, photo_file_id)
                bot.send_message(message.chat.id, "✅ Фото отправлено.")
                # Show admin menu after successful photo send
                show_admin_menu(message.chat.id)
            except Exception as e:
                logger.error(f"Error sending photo: {str(e)}")
                bot.send_message(message.chat.id, "❌ Ошибка при отправке фото.")
        else:
            bot.send_message(message.chat.id, "Пожалуйста, отправьте фото.")

    # Process immediate file
    def process_file(message, target_type):
        """Process the file."""
        user_id = message.from_user.id

        if not user_data.has_user(user_id):
            bot.send_message(message.chat.id, "Ошибка: сессия истекла. Пожалуйста, начните сначала.")
            return

        if message.document:
            file_id = message.document.file_id
            try:
                if target_type == "all":
                    send_file_to_all_users(bot, message, file_id)
                elif target_type == "individual":
                    target_user_id = user_data.get_user_data(user_id).get("target_user_id")
                    if not target_user_id:
                        bot.send_message(message.chat.id, "Ошибка: целевой пользователь не выбран.")
                        return
                    send_file_to_user(bot, target_user_id, file_id)
                bot.send_message(message.chat.id, "✅ Файл отправлен.")
                # Show admin menu after successful file send
                show_admin_menu(message.chat.id)
            except Exception as e:
                logger.error(f"Error sending file: {str(e)}")
                bot.send_message(message.chat.id, "❌ Ошибка при отправке файла.")
        else:
            bot.send_message(message.chat.id, "Пожалуйста, отправьте файл.")

    # Process immediate announcement
    def process_announcement(message, target_type):
        """Process the announcement."""
        user_id = message.from_user.id

        if not user_data.has_user(user_id):
            bot.send_message(message.chat.id, "Ошибка: сессия истекла. Пожалуйста, начните сначала.")
            return

        announcement = message.text
        try:
            if target_type == "all":
                send_announcement_to_all_users(bot, message, announcement)
            elif target_type == "individual":
                target_user_id = user_data.get_user_data(user_id).get("target_user_id")
                if not target_user_id:
                    bot.send_message(message.chat.id, "Ошибка: целевой пользователь не выбран.")
                    return
                send_announcement_to_user(bot, target_user_id, announcement)
            bot.send_message(message.chat.id, "✅ Сообщение отправлено.")
            # Show admin menu after successful announcement
            show_admin_menu(message.chat.id)
        except Exception as e:
            logger.error(f"Error sending announcement: {str(e)}")
            bot.send_message(message.chat.id, "❌ Ошибка при отправке сообщения.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_"))
    def cancel_operation(call):
        """Cancels the current operation."""
        user_id = call.from_user.id
        if user_data.has_user(user_id):
            user_data.clear_user_data(user_id)  # Clear user data
        bot.send_message(call.message.chat.id, "Операция отменена.")