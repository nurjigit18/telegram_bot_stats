import os
import logging
from telebot import TeleBot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime
from utils.google_sheets import GoogleSheetsManager
from models.user_data import user_data
import pytz

ITEMS_PER_PAGE = 9  # Number of items to show per page

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Track users who have used the payment command
payment_status = {}
# Track users who clicked the "Отправить чек" button and can send files
ready_to_send_file = {}
# Track pending files waiting for confirmation
pending_files = {}

def setup_file_sender_handlers(bot):
    """
    Sets up all handlers related to file sending functionality from users to admins.
    
    Args:
        bot: The TeleBot instance
    """
    @bot.message_handler(commands=['payment'])
    def handle_payment_command(message):
        """Handler for the /payment command"""
        user_id = message.from_user.id
        username = message.from_user.username or f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()
        
        # Initialize user data if not already done
        if not user_data.has_user(user_id):
            user_data.initialize_user(user_id)
        
        # Mark user as having used the payment command
        payment_status[user_id] = {
            'status': True,
            'username': username,
            'timestamp': datetime.now(pytz.timezone('Asia/Bishkek')).strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # Also save to Google Sheets Users worksheet
        try:
            sheets_manager = GoogleSheetsManager.get_instance()
            users_worksheet = sheets_manager.get_users_worksheet()
            
            # Check if user already exists
            user_exists = False
            try:
                cell = users_worksheet.find(str(user_id))
                if cell:
                    user_exists = True
            except:
                pass
            
            # If user doesn't exist, add them
            if not user_exists:
                users_worksheet.append_row([
                    str(user_id),
                    username,
                    datetime.now(pytz.timezone('Asia/Bishkek')).strftime("%Y-%m-%d %H:%M:%S")
                ])
                logger.info(f"User {username} (ID: {user_id}) added to Users worksheet")
        except Exception as e:
            logger.error(f"Failed to save user to Google Sheets: {str(e)}")
        
        # Create inline keyboard with "Отправить чек" button
        keyboard = InlineKeyboardMarkup()
        send_receipt_button = InlineKeyboardButton(text="Отправить чек", callback_data="send_receipt")
        keyboard.add(send_receipt_button)
        
        # Send message with bank account details and the button
        bank_details = ("Реквизиты для оплаты💸:\n\n"
                        "Mbank: 0703268727\n"
                        "Optima Bank: 0703268726\n"
                        )
        bot.send_message(
            message.chat.id,
            f"{bank_details}\n\nНажмите кнопку ниже, чтобы отправить чек 🧾 об оплате.",
            reply_markup=keyboard
        )

    @bot.callback_query_handler(func=lambda call: call.data == "send_receipt")
    def send_receipt_callback(call):
        """Handle the 'Отправить чек' button click"""
        user_id = call.from_user.id
        username = call.from_user.username or f"{call.from_user.first_name} {call.from_user.last_name or ''}".strip()
        
        # Mark user as ready to send a file
        ready_to_send_file[user_id] = True
        
        # Answer the callback to remove the "loading" state of the button
        bot.answer_callback_query(call.id)
        
        # Update the message or send a new one
        bot.send_message(
            call.message.chat.id,
            "Теперь вы можете отправить фотографию или документ с чеком об оплате."
        )
        
        # Log the action
        logger.info(f"User {username} (ID: {user_id}) clicked 'Отправить чек' button")

    @bot.message_handler(content_types=['photo', 'document'])
    def handle_file(message):
        """Handle files sent by users and show confirmation buttons"""
        user_id = message.from_user.id
        username = message.from_user.username or f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()
        
        # Check if user has used the payment command
        if user_id not in payment_status or not payment_status[user_id]['status']:
            bot.reply_to(message, "Пожалуйста, сначала используйте команду /payment, прежде чем отправлять файлы.")
            return
        
        # Check if user has clicked the "Отправить чек" button
        if user_id not in ready_to_send_file or not ready_to_send_file[user_id]:
            keyboard = InlineKeyboardMarkup()
            send_receipt_button = InlineKeyboardButton(text="Отправить чек", callback_data="send_receipt")
            keyboard.add(send_receipt_button)
            
            bot.reply_to(
                message, 
                "Пожалуйста, нажмите кнопку 'Отправить чек', прежде чем отправлять файлы.",
                reply_markup=keyboard
            )
            return
        
        # Store the file information for confirmation
        file_info = {
            'message': message,
            'user_id': user_id,
            'username': username,
            'timestamp': datetime.now(pytz.timezone('Asia/Bishkek')).strftime("%Y-%m-%d %H:%M:%S"),
            'file_type': 'photo' if message.photo else 'document'
        }
        
        # Store with unique key (user_id + timestamp)
        file_key = f"{user_id}_{int(datetime.now().timestamp())}"
        pending_files[file_key] = file_info
        
        # Create confirmation keyboard
        keyboard = InlineKeyboardMarkup()
        confirm_button = InlineKeyboardButton(
            text="✅ Отправить менеджеру", 
            callback_data=f"confirm_file_{file_key}"
        )
        cancel_button = InlineKeyboardButton(
            text="❌ Отменить", 
            callback_data=f"cancel_file_{file_key}"
        )
        keyboard.add(confirm_button, cancel_button)
        
        # Determine file type and size for confirmation message
        if message.photo:
            file_description = "📸 Фотография"
        else:
            file_name = message.document.file_name or "документ"
            file_size = message.document.file_size
            if file_size:
                file_size_mb = file_size / (1024 * 1024)
                file_description = f"📄 {file_name} ({file_size_mb:.1f} МБ)"
            else:
                file_description = f"📄 {file_name}"
        
        caption_text = f"\n📝 Подпись: {message.caption}" if message.caption else ""
        
        # Send confirmation message
        confirmation_text = (
            f"Получен файл:\n"
            f"{file_description}{caption_text}\n\n"
            f"Отправить этот чек менеджеру для проверки?"
        )
        
        bot.send_message(
            message.chat.id,
            confirmation_text,
            reply_markup=keyboard
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_file_"))
    def confirm_file_callback(call):
        """Handle file confirmation"""
        user_id = call.from_user.id
        file_key = call.data.replace("confirm_file_", "")
        
        # Answer the callback
        bot.answer_callback_query(call.id)
        
        # Check if file still exists in pending
        if file_key not in pending_files:
            bot.edit_message_text(
                "❌ Файл больше не доступен. Попробуйте отправить его заново.",
                call.message.chat.id,
                call.message.message_id
            )
            return
        
        file_info = pending_files[file_key]
        message = file_info['message']
        username = file_info['username']
        
        # Process the file
        success = process_and_forward_file(bot, message, user_id, username)
        
        if success:
            # Update the confirmation message
            bot.edit_message_text(
                "✅ Ваш чек был успешно отправлен менеджеру. Спасибо!",
                call.message.chat.id,
                call.message.message_id
            )
            # Reset the ready_to_send_file status after successful submission
            ready_to_send_file[user_id] = False
        else:
            bot.edit_message_text(
                "❌ Не удалось отправить ваш файл. Пожалуйста, повторите попытку позже.",
                call.message.chat.id,
                call.message.message_id
            )
        
        # Clean up pending file
        del pending_files[file_key]

    @bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_file_"))
    def cancel_file_callback(call):
        """Handle file cancellation"""
        file_key = call.data.replace("cancel_file_", "")
        
        # Answer the callback
        bot.answer_callback_query(call.id)
        
        # Update the message
        bot.edit_message_text(
            "❌ Отправка файла отменена. Вы можете отправить другой файл.",
            call.message.chat.id,
            call.message.message_id
        )
        
        # Clean up pending file if it exists
        if file_key in pending_files:
            del pending_files[file_key]

    # Handle text messages to prevent confusion
    @bot.message_handler(content_types=['text'])
    def handle_text_when_expecting_file(message):
        """Handle text messages from users who might be expecting to send files"""
        user_id = message.from_user.id
        
        # Skip if it's a command (handled by other handlers)
        if message.text.startswith('/'):
            return
        
        # If user is ready to send files but sent text instead
        if (user_id in ready_to_send_file and 
            ready_to_send_file[user_id] and 
            user_id in payment_status and 
            payment_status[user_id]['status']):
            
            bot.reply_to(
                message, 
                "Я ожидаю получить фотографию или документ с чеком. "
                "Пожалуйста, отправьте файл, а не текстовое сообщение."
            )

def process_and_forward_file(bot, message, user_id, username):
    """
    Process the file and forward it to admins
    
    Args:
        bot: The TeleBot instance
        message: The message containing the file
        user_id: User ID
        username: Username
        
    Returns:
        bool: True if successful, False otherwise
    """
    # Get admin IDs
    admin_ids = get_admin_ids()
    if not admin_ids:
        return False
    
    # Track this file submission in Google Sheets
    try:
        # Create a new worksheet for file tracking if it doesn't exist
        sheets_manager = GoogleSheetsManager.get_instance()
        try:
            files_worksheet = sheets_manager._spreadsheet.worksheet("Files")
        except:
            # Create the worksheet
            files_worksheet = sheets_manager._spreadsheet.add_worksheet("Files", 1000, 5)
            # Add headers
            files_worksheet.update('A1:E1', [['timestamp', 'user_id', 'username', 'file_type', 'caption']])
        
        # Determine file type
        file_type = "photo" if message.photo else "document"
        if file_type == "document" and message.document.mime_type:
            file_type = message.document.mime_type
        
        # Add file record
        timestamp = datetime.now(pytz.timezone('Asia/Bishkek')).strftime("%Y-%m-%d %H:%M:%S")
        caption = message.caption or ""
        
        files_worksheet.append_row([
            timestamp,
            str(user_id),
            username,
            file_type,
            caption
        ])
        
        logger.info(f"Tracked file submission from {username} (ID: {user_id})")
    except Exception as e:
        logger.error(f"Failed to track file in Google Sheets: {str(e)}")
    
    # Get user info for the forwarding message
    user_info = f"Файл получен от {username} (ID: {user_id})"
    
    # Send the file to all admins
    success_count = 0
    for admin_id in admin_ids:
        try:
            # Forward with custom caption including original caption and user info
            original_caption = message.caption or ""
            new_caption = f"{original_caption}\n\n{user_info}"
            
            if len(new_caption) > 1024:  # Telegram caption limit
                new_caption = new_caption[:1021] + "..."
            
            if message.photo:
                bot.send_photo(
                    chat_id=admin_id,
                    photo=message.photo[-1].file_id,
                    caption=new_caption
                )
                success_count += 1
            elif message.document:
                bot.send_document(
                    chat_id=admin_id,
                    document=message.document.file_id,
                    caption=new_caption
                )
                success_count += 1
        except Exception as e:
            logger.error(f"Failed to send file to admin {admin_id}: {e}")
    
    return success_count > 0

def notify_admins(bot, message_text):
    """
    Send a notification message to all admins.
    
    Args:
        bot: The TeleBot instance
        message_text: The text message to send to admins
    """
    admin_ids = get_admin_ids()
    for admin_id in admin_ids:
        try:
            bot.send_message(admin_id, message_text)
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

def get_admin_ids():
    """
    Get list of admin user IDs.
    
    Returns:
        list: List of admin user IDs as integers
    """
    # Get admin IDs from environment variable
    admin_ids_str = os.getenv('ADMIN_1', 'ADMIN_2')
    admin_ids = []
    
    # Parse admin IDs
    for id_str in admin_ids_str.split(','):
        id_str = id_str.strip()
        if id_str and id_str.isdigit():
            admin_ids.append(int(id_str))
    
    return admin_ids