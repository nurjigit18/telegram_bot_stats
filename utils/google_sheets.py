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
            # Define the scope
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

            # Retrieve credentials from environment variable
            creds_data = os.getenv('GOOGLE_CREDS_JSON')
            if not creds_data:
                raise ValueError("Environment variable 'GOOGLE_CREDS_JSON' is not set.")

            # Handle both file path (local) and JSON string (production)
            if os.path.isfile(creds_data):
                # Local development: read from file
                with open(creds_data, 'r') as f:
                    creds_dict = json.load(f)
                logger.info("Loaded Google credentials from file (local development)")
            else:
                # Production: parse JSON string directly
                creds_dict = json.loads(creds_data)
                logger.info("Loaded Google credentials from environment variable (production)")

            # Create credentials from the dictionary
            credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)

            # Authorize the client
            gc = gspread.authorize(credentials)

            # Retrieve Google Sheet ID from environment variable
            sheet_id = os.getenv("SHEET_ID")
            if not sheet_id:
                raise ValueError("Environment variable 'SHEET_ID' is not set.")

            # Open the Google Sheet
            self._spreadsheet = gc.open_by_key(sheet_id)
            self.main_worksheet = self._spreadsheet.sheet1

            # Try to get or create Users worksheet
            try:
                self.users_worksheet = self._spreadsheet.worksheet("Users")
            except gspread.WorksheetNotFound:
                self.users_worksheet = self._spreadsheet.add_worksheet("Users", 1000, 3)
                # Add headers
                self.users_worksheet.update('A1:C1', [['chat_id', 'username', 'registration_date']])

            logger.info(f"Connected to Google Sheet with ID: {sheet_id}")
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

    # Retrieve credentials from environment variable
    creds_data = os.getenv('GOOGLE_CREDS_JSON')
    if not creds_data:
        raise ValueError("Environment variable 'GOOGLE_CREDS_JSON' is not set.")

    try:
        # Handle both file path (local) and JSON string (production)
        if os.path.isfile(creds_data):
            # Local development: read from file
            with open(creds_data, 'r') as f:
                creds_dict = json.load(f)
        else:
            # Production: parse JSON string directly
            creds_dict = json.loads(creds_data)

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
        # Get the worksheet
        worksheet = sheets_manager.get_main_worksheet()
        
        # Define expected headers - make sure they match your sheet structure
        expected_headers = [
            'timestamp', 'user_id', 'username', 'product_name', 'shipment_date', 
            'estimated_arrival', 'actual_arrival', 'product_color', 'total_amount', 
            'warehouse', 'XS', 'S', 'M', 'L', 'XL', 'XXL', '2XL', '3XL', '4XL', '5XL', '6XL', '7XL'
        ]
        
        # Check if headers exist in row 1
        try:
            current_headers = worksheet.row_values(1)
            logger.info(f"Current headers: {current_headers}")
        except:
            current_headers = []
        
        # Only update headers if they don't exist or are incomplete
        if not current_headers or len(current_headers) < len(expected_headers):
            # Clear the first row completely and set new headers
            worksheet.clear()
            worksheet.update('A1', [expected_headers])
            logger.info("Updated worksheet headers")
        
        # Prepare timestamp
        timestamp = datetime.now(pytz.timezone('Asia/Bishkek')).strftime("%Y-%m-%d %H:%M:%S")
        
        # Prepare size data - extract individual size values from form_data
        size_columns = ['XS', 'S', 'M', 'L', 'XL', 'XXL', '2XL', '3XL', '4XL', '5XL', '6XL', '7XL']
        size_values = []
        
        for size in size_columns:
            size_value = form_data.get(size, 0)  # Default to 0 if size not found
            size_values.append(size_value if size_value else 0)
        
        # Log the sizes being saved for debugging
        sizes_debug = {size: form_data.get(size, 0) for size in size_columns if form_data.get(size, 0)}
        logger.info(f"Saving sizes for user {username}: {sizes_debug}")
        
        # Prepare row data - make sure it matches the expected headers exactly
        row_data = [
            timestamp,
            user_id,
            username,
            form_data.get("product_name", ""),
            form_data.get("shipment_date", ""),
            form_data.get("estimated_arrival", ""),
            "",  # Actual arrival date (empty initially)
            form_data.get("product_color", ""),
            form_data.get("total_amount", ""),
            form_data.get("warehouse", "")
        ] + size_values  # Add the size values as separate columns

        # Get the next available row
        all_values = worksheet.get_all_values()
        next_row = len(all_values) + 1
        
        # Use update instead of append_row to ensure data goes to the correct position
        range_name = f'A{next_row}:{chr(ord("A") + len(row_data) - 1)}{next_row}'
        worksheet.update(range_name, [row_data])
        
        logger.info(f"Saved product data from {username} to Google Sheets at row {next_row}")
        logger.info(f"Row data: {row_data}")
        logger.info(f"Range used: {range_name}")

        # Send success message to user
        bot.send_message(message.chat.id, "✅ Данные сохранены в Google Таблице!")

        # Return the row index for admin notifications
        return next_row

    except Exception as e:
        logger.error(f"Error saving to Google Sheets: {str(e)}")
        logger.error(f"Form data was: {form_data}")
        bot.send_message(message.chat.id, f"❌ Ошибка при сохранении данных: {str(e)}")
        raise  # Re-raise the exception so the calling function can handle it
