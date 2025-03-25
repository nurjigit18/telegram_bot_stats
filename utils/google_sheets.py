import gspread
from telebot import TeleBot
from oauth2client.service_account import ServiceAccountCredentials
from config import GOOGLE_CREDS_FILE, SHEET_ID
import logging
from datetime import datetime
from models.user_data import user_data
import os
import json
import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

class GoogleSheetsManager:
    _instance = None
    _spreadsheet = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.main_worksheet = None
        self.users_worksheet = None
        self.connect()

    def connect(self):
        try:
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            credentials = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS_FILE, scope)
            gc = gspread.authorize(credentials)
            self._spreadsheet = gc.open_by_key(SHEET_ID)
            self.main_worksheet = self._spreadsheet.sheet1
            # Try to get or create Users worksheet
            try:
                self.users_worksheet = self._spreadsheet.worksheet("Users")
            except gspread.WorksheetNotFound:
                self.users_worksheet = self._spreadsheet.add_worksheet("Users", 1000, 3)
                # Add headers
                self.users_worksheet.update('A1:C1', [['chat_id', 'username', 'registration_date']])

            logger.info(f"Connected to Google Sheet with ID: {SHEET_ID}")
        except Exception as e:
            logger.error(f"Failed to connect to Google Sheets: {str(e)}")
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

    # Get absolute path to credentials file
    creds_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'spheric-keel-430513-g9-f3948761d754.json')

    # Check if file exists
    if not os.path.exists(creds_file):
        raise FileNotFoundError(f"Google credentials file not found: {creds_file}")

    try:
        # Create credentials from service account file
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS_FILE, scope)

        # Authorize the client
        client = gspread.authorize(creds)

        # Open the Google Sheet
        sheet_id = os.getenv("SHEET_ID")
        if not sheet_id:
            raise ValueError("SHEET_ID environment variable is not set")

        sheet = client.open_by_key(sheet_id)
        return sheet

    except Exception as e:
        logging.error(f"Failed to connect to Google Sheets: {str(e)}")
        raise

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
    """Save completed form data to Google Sheets"""
    sheets_manager = GoogleSheetsManager.get_instance()
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"

    # Use the UserData class method to get form data
    form_data = user_data.get_form_data(user_id)

    if not form_data:
        logger.error(f"No form data found for user_id: {user_id}")
        bot.send_message(message.chat.id, "❌ Данные пользователя не найдены.")
        return

    try:
        # Prepare row data
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row_data = [
            timestamp,
            user_id,
            username,
            form_data.get("product_name"),
            form_data.get("shipment_date"),
            form_data.get("estimated_arrival"),
            "",  # Actual arrival date (empty initially)
            form_data.get("product_color"),
            form_data.get("total_amount"),
            form_data.get("warehouse"),
            form_data.get("sizes_data")  # All sizes in one column
        ]

        # Save to Google Sheets
        sheets_manager.get_main_worksheet().append_row(row_data)
        logger.info(f"Saved product data from {username} to Google Sheets")

        # Send confirmation and summary
        summary = (
            "✅ Данные записаны!\n\n"
            f"Изделие: {form_data.get('product_name')}\n"
            f"Цвет: {form_data.get('product_color')}\n"
            f"Дата отправки: {form_data.get('shipment_date')}\n"
            f"Дата возможного прибытия: {form_data.get('estimated_arrival')}\n"
            f"Склад: {form_data.get('warehouse')}\n"
            f"Общее количество: {form_data.get('total_amount')} шт\n"
            f"Размеры: {form_data.get('sizes_data')}"
        )
        bot.send_message(message.chat.id, summary)

        # Clear user data using the UserData class method
        user_data.clear_user_data(user_id)

    except Exception as e:
        logger.error(f"Error saving to Google Sheets: {str(e)}")
        bot.send_message(message.chat.id, "❌ Ошибка при сохранении данных. Попробуйте еще раз с помощью /save")
        user_data.clear_user_data(user_id)  # Clear user data in case of error