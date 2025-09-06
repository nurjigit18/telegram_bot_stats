import gspread
import logging
import os
import json
import pytz
import gspread
from telebot import TeleBot
from oauth2client.service_account import ServiceAccountCredentials
from config import GOOGLE_CREDS_FILE, SHEET_ID
from datetime import datetime
from models.user_data import user_data
from google.oauth2.service_account import Credentials


logger = logging.getLogger(__name__)

SIZE_COLS = ["XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL", "5XL", "6XL", "7XL"]

EXPECTED_HEADERS = [
    "время", "user_id", "username", "номер пакета", "склад",
    "модель", "цвет", "дата отправки", "примерная дата прибытия",
    "факт. дата прибытия", "Общее количество",
] + SIZE_COLS + ["Статус"]

class GoogleSheetsManager:
    _instance = None
    _spreadsheet = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        self._spreadsheet = None
        self.main_worksheet = None
        self.users_worksheet = None
        self.connect()
        
    def get_main_worksheet(self):
        return self.main_worksheet

    def get_users_worksheet(self):
        return self.users_worksheet

    def connect(self):
        """Connect to Google Sheets and set up worksheets."""
        try:
            scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ]

            creds_data = os.getenv('GOOGLE_CREDS_JSON')
            if not creds_data:
                raise ValueError("Environment variable 'GOOGLE_CREDS_JSON' is not set or empty.")

            looks_like_json = creds_data.strip().startswith('{')

            if looks_like_json:
                logger.info("Loading Google credentials from inline JSON (env).")
                try:
                    creds_dict = json.loads(creds_data)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Inline GOOGLE_CREDS_JSON is not valid JSON: {e}")
            else:
                # Treat as a file path (absolute or relative)
                creds_path = os.path.abspath(creds_data) if not os.path.isabs(creds_data) else creds_data
                if not os.path.isfile(creds_path):
                    raise FileNotFoundError(f"GOOGLE_CREDS_JSON points to a file that does not exist: {creds_path}")
                logger.info(f"Loading Google credentials from file: {creds_path}")
                with open(creds_path, 'r', encoding='utf-8') as fh:
                    try:
                        creds_dict = json.load(fh)
                    except json.JSONDecodeError as e:
                        raise ValueError(f"Credentials file is not valid JSON: {e}")

            credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)
            gc = gspread.authorize(credentials)

            sheet_id = os.getenv("SHEET_ID")
            if not sheet_id:
                raise ValueError("Environment variable 'SHEET_ID' is not set.")

            self._spreadsheet = gc.open_by_key(sheet_id)

            # Main worksheet: first tab by default
            self.main_worksheet = self._spreadsheet.worksheet('нарселя')

            # Ensure headers are present in the main worksheet
            headers = []
            try:
                headers = self.main_worksheet.row_values(1)
            except Exception:
                pass
            if headers != EXPECTED_HEADERS:
                self.main_worksheet.clear()
                self.main_worksheet.update('A1', [EXPECTED_HEADERS])

            # Users worksheet
            try:
                self.users_worksheet = self._spreadsheet.worksheet("Users")
            except gspread.WorksheetNotFound:
                self.users_worksheet = self._spreadsheet.add_worksheet("Users", 1000, 3)
                self.users_worksheet.update('A1', [['chat_id', 'username', 'registration_date']])

            logger.info(f"Google Sheets connected. Service account: {creds_dict.get('client_email', '?')}")
        except Exception as e:
            logger.error(f"Failed to connect to Google Sheets: {e}")
            raise


    def get_main_worksheet(self):
        if self.main_worksheet is None:
            self.connect()
        return self.main_worksheet

    def get_users_worksheet(self):
        if self.users_worksheet is None:
            self.connect()
        return self.users_worksheet

def connect_to_google_sheets():
    # Define the scope
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]

    # Retrieve credentials from environment variable
    creds_json = os.getenv('GOOGLE_CREDS_JSON')
    if not creds_json:
        raise ValueError("Environment variable 'GOOGLE_CREDS_JSON' is not set.")

    try:
        # Parse JSON string into a dictionary
        creds_dict = json.loads(creds_json)

        # Create credentials from the dictionary
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)

        # Authorize the client
        client = gspread.authorize(creds)

        # Open the Google Sheet
        sheet_id = os.getenv("SHEET_ID")
        if not sheet_id:
            raise ValueError("SHEET_ID environment variable is not set.")

        sheet = client.open_by_key(sheet_id)
        return sheet

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in 'GOOGLE_CREDS_JSON': {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to connect to Google Sheets: {e}")
    
def get_all_user_chat_ids():
    """Fetch all user chat IDs from Google Sheets"""
    sheets_manager = GoogleSheetsManager.get_instance()
    try:
        users_sheet = sheets_manager.get_users_worksheet()
        user_data = users_sheet.get_all_values()
        if len(user_data) <= 1:  # Only headers exist
            return []

        # Skip header row and extract chat IDs
        chat_ids = [int(row[0]) for row in user_data[1:]]
        return chat_ids
    except Exception as e:
        logger.error(f"Error fetching user chat IDs: {str(e)}")
        return []

def save_to_sheets(bot, message):
    """
    Append one row to the main worksheet using data from user_data.form_data.
    Returns the row index (int) of the row that was appended.
    """
    try:
        # Derive user_id and username from the chat (works for messages and callbacks in private chats)
        # In private chats, chat.id == user_id
        user_id = getattr(getattr(message, "chat", None), "id", None)
        if user_id is None:
            # Fallback to message.from_user.id if available
            user_id = getattr(getattr(message, "from_user", None), "id", None)

        if user_id is None:
            raise ValueError("Unable to determine user_id from message/chat.")

        chat_username = getattr(getattr(message, "chat", None), "username", None)
        from_username = getattr(getattr(message, "from_user", None), "username", None)
        first_name = getattr(getattr(message, "from_user", None), "first_name", None)
        username = chat_username or from_username or first_name or str(user_id)

        form_data = user_data.get_form_data(user_id)
        if not form_data or not isinstance(form_data, dict):
            logger.error(f"No form data found for user_id: {user_id}")
            bot.send_message(message.chat.id, "❌ Данные пользователя не найдены. Повторите ввод.")
            raise RuntimeError("Form data missing")

        # Ensure headers are present (idempotent)
        sheets_manager = GoogleSheetsManager.get_instance()
        worksheet = sheets_manager.get_main_worksheet()
        try:
            headers = worksheet.row_values(1)
        except Exception:
            headers = []
        if headers != EXPECTED_HEADERS:
            worksheet.clear()
            worksheet.update('A1', [EXPECTED_HEADERS])

        # Timestamp in Asia/Bishkek
        timestamp = datetime.now(pytz.timezone('Asia/Bishkek')).strftime("%Y-%m-%d %H:%M:%S")

        # Build row to EXACTLY match EXPECTED_HEADERS
        row = [
            timestamp,
            user_id,
            username,
            form_data.get('bag_id', ''),
            form_data.get('warehouse', ''),
            form_data.get('product_name', ''),
            form_data.get('color', ''),
            form_data.get('shipment_date', ''),
            form_data.get('estimated_arrival', ''),
            form_data.get('actual_arrival', ''),
            int(form_data.get('total_amount') or 0),
        ] + [int(form_data.get(k) or 0) for k in SIZE_COLS] + [
            form_data.get('status', 'в обработке')
        ]

        # Append
        worksheet.append_row(row, value_input_option='USER_ENTERED')

        # Last non-empty row index after append
        all_values = worksheet.get_all_values()
        last_row = len(all_values)

        logger.info(f"Saved row #{last_row} for user {username} (ID {user_id})")
        try:
            bot.send_message(message.chat.id, "✅ Данные сохранены в Google Таблице!")
        except Exception:
            pass

        # Persist the last row index for admin notifications
        user_data.set_row_index(user_id, last_row)
        return last_row

    except Exception as e:
        logger.error(f"Error in save_to_sheets: {e}")
        raise
