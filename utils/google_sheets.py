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
import re


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
            creds_json = os.getenv('GOOGLE_CREDS_JSON')
            if not creds_json:
                raise ValueError("Environment variable 'GOOGLE_CREDS_JSON' is not set.")

            # Parse JSON string into a dictionary
            creds_dict = json.loads(creds_json)

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


def parse_sizes_data(sizes_data_str):
    """
    Parse sizes data string into structured format
    Input: "Казань: S-30 M-40 | Москва: L-50 XL-80"
    Output: [
        {"warehouse": "Казань", "sizes": {"S": 30, "M": 40}},
        {"warehouse": "Москва", "sizes": {"L": 50, "XL": 80}}
    ]
    """
    if not sizes_data_str:
        return []
    
    warehouses = []
    
    # Split by | to get each warehouse
    warehouse_parts = sizes_data_str.split('|')
    
    for part in warehouse_parts:
        part = part.strip()
        if ':' not in part:
            continue
            
        warehouse_name, sizes_str = part.split(':', 1)
        warehouse_name = warehouse_name.strip()
        sizes_str = sizes_str.strip()
        
        # Parse sizes: "S-30 M-40" -> {"S": 30, "M": 40}
        sizes = {}
        size_parts = sizes_str.split()
        
        for size_part in size_parts:
            if '-' in size_part:
                size_name, quantity = size_part.split('-', 1)
                try:
                    sizes[size_name.strip()] = int(quantity.strip())
                except ValueError:
                    logger.warning(f"Could not parse quantity: {quantity}")
        
        if sizes:  # Only add if we have valid sizes
            warehouses.append({
                "warehouse": warehouse_name,
                "sizes": sizes
            })
    
    return warehouses


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
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Parse the sizes data
        sizes_data_str = form_data.get("sizes_data", "")
        parsed_warehouses = parse_sizes_data(sizes_data_str)
        
        if not parsed_warehouses:
            logger.error(f"Could not parse sizes data: {sizes_data_str}")
            bot.send_message(message.chat.id, "❌ Ошибка при разборе данных о размерах.")
            return
        
        records_created = 0
        worksheet = sheets_manager.get_main_worksheet()
        
        # Create a separate row for each warehouse
        for warehouse_data in parsed_warehouses:
            warehouse_name = warehouse_data["warehouse"]
            sizes = warehouse_data["sizes"]
            
            # Calculate total quantity for this warehouse
            warehouse_total = sum(sizes.values())
            
            # Format sizes as string: "S: 30, M: 40"
            sizes_formatted = ", ".join([f"{size}: {qty}" for size, qty in sizes.items()])
            
            # Prepare row data for this warehouse
            row_data = [
                timestamp,
                user_id,
                username,
                form_data.get("product_name"),
                form_data.get("shipment_date"),
                form_data.get("estimated_arrival"),
                "",  # Actual arrival date (empty initially)
                form_data.get("product_color"),
                warehouse_total,  # Total for this warehouse
                warehouse_name,   # Warehouse name
                sizes_formatted   # Formatted sizes for this warehouse
            ]
            
            # Save to Google Sheets
            worksheet.append_row(row_data)
            records_created += 1
            logger.info(f"Saved warehouse '{warehouse_name}' data from {username} to Google Sheets")
        
        # Send success message
        success_message = f"✅ Данные успешно сохранены!\n"
        success_message += f"📦 Название изделия: {form_data.get('product_name')}\n"
        success_message += f"🎨 Цвет изделия: {form_data.get('product_color')}\n"
        success_message += f"📊 Общее количество: {form_data.get('total_amount')} шт\n"
        
        # Add warehouse details
        for warehouse_data in parsed_warehouses:
            warehouse_name = warehouse_data["warehouse"]
            sizes = warehouse_data["sizes"]
            sizes_str = ", ".join([f"{size}: {qty}" for size, qty in sizes.items()])
            success_message += f"🏪 {warehouse_name}: {sizes_str}\n"
        
        success_message += f"📅 Дата отправки: {form_data.get('shipment_date')}\n"
        success_message += f"📅 Дата прибытия: {form_data.get('estimated_arrival')}\n"
        success_message += f"Создано записей: {records_created}"
        
        bot.send_message(message.chat.id, success_message)

        # Clear user data using the UserData class method
        user_data.clear_user_data(user_id)

    except Exception as e:
        logger.error(f"Error saving to Google Sheets: {str(e)}")
        bot.send_message(message.chat.id, "❌ Ошибка при сохранении данных. Попробуйте еще раз с помощью /save")
        user_data.clear_user_data(user_id)  # Clear user data in case of error