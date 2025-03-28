import os
import logging
from telebot import TeleBot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime
from utils.google_sheets import GoogleSheetsManager
from models.user_data import user_data

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
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ])
                logger.info(f"User {username} (ID: {user_id}) added to Users worksheet")
        except Exception as e:
            logger.error(f"Failed to save user to Google Sheets: {str(e)}")
        
        # Create inline keyboard with "Отправить чек" button
        keyboard = InlineKeyboardMarkup()
        send_receipt_button = InlineKeyboardButton(text="Отправить чек", callback_data="send_receipt")
        keyboard.add(send_receipt_button)
        
        # Send message with bank account details and the button
        bank_details = ("Реквизиты для оплаты:\n\n"
                        "Mbank: 1234567890\n"
                        "Optima Bank: Example Bank\n"
                        "Demir Bank: Example Company")
        bot.send_message(
            message.chat.id,
            f"{bank_details}\n\nНажмите кнопку ниже, чтобы отправить чек об оплате.",
            reply_markup=keyboard
        )
        
        # Notify admins that a new user has registered for payments
        # notify_admins(bot, f"Пользователь {username} (ID: {user_id}) зарегистрировался для платежей.")

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
        """Handle files sent by users and forward them to admins"""
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
        
        # Get admin IDs
        admin_ids = get_admin_ids()
        if not admin_ids:
            bot.reply_to(message, "Нет настроенных администраторов для получения вашего файла. Пожалуйста, свяжитесь с поддержкой.")
            return
        
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
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
        
        if success_count > 0:
            bot.reply_to(message, "Ваш чек был успешно отправлен менеджеру. Спасибо!")
            # Reset the ready_to_send_file status after successful submission
            ready_to_send_file[user_id] = False
        else:
            bot.reply_to(message, "Не удалось отправить ваш файл. Пожалуйста, повторите попытку позже или обратитесь в службу поддержки.")

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
    admin_ids_str = os.getenv('ADMIN_1', 'ADMIN_2', 'ADMIN_3')
    admin_ids = []
    
    # Parse admin IDs
    for id_str in admin_ids_str.split(','):
        id_str = id_str.strip()
        if id_str and id_str.isdigit():
            admin_ids.append(int(id_str))
    
    return admin_ids