import gspread
from telebot import TeleBot
from oauth2client.service_account import ServiceAccountCredentials
from config import GOOGLE_CREDS_FILE, SHEET_ID
import logging
from datetime import datetime, timedelta
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

    def get_spreadsheet(self):
        if self._spreadsheet is None:
            self.connect()
        return self._spreadsheet


def connect_to_google_sheets():
    """Alternative connection method for backward compatibility"""
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
        user_data_list = users_sheet.get_all_values()
        if len(user_data_list) <= 1:  # Only headers exist
            return []

        # Skip header row and extract chat IDs
        chat_ids = [int(row[0]) for row in user_data_list[1:] if row and row[0]]
        return chat_ids
    except Exception as e:
        logger.error(f"Error fetching user chat IDs: {str(e)}")
        return []


def register_user(chat_id, username=None):
    """Register a new user in the Users worksheet"""
    sheets_manager = GoogleSheetsManager.get_instance()
    try:
        users_sheet = sheets_manager.get_users_worksheet()
        
        # Check if user already exists
        existing_chat_ids = get_all_user_chat_ids()
        if chat_id in existing_chat_ids:
            logger.info(f"User {chat_id} already registered")
            return True
        
        # Add new user
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_row = [chat_id, username or "Unknown", timestamp]
        users_sheet.append_row(user_row)
        
        logger.info(f"Registered new user: {chat_id} ({username})")
        return True
        
    except Exception as e:
        logger.error(f"Error registering user {chat_id}: {str(e)}")
        return False


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
        logger.warning("Empty sizes data string")
        return []
    
    warehouses = []
    
    try:
        # Split by | to get each warehouse
        warehouse_parts = sizes_data_str.split('|')
        
        for part in warehouse_parts:
            part = part.strip()
            if ':' not in part:
                logger.warning(f"Invalid warehouse format (no colon): {part}")
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
                else:
                    logger.warning(f"Invalid size format (no dash): {size_part}")
            
            if sizes:  # Only add if we have valid sizes
                warehouses.append({
                    "warehouse": warehouse_name,
                    "sizes": sizes
                })
            else:
                logger.warning(f"No valid sizes found for warehouse: {warehouse_name}")
        
    except Exception as e:
        logger.error(f"Error parsing sizes data '{sizes_data_str}': {str(e)}")
    
    return warehouses


def validate_form_data(form_data):
    """Validate form data before saving"""
    required_fields = [
        "product_name", "shipment_date", "estimated_arrival", 
        "product_color", "total_amount", "sizes_data"
    ]
    
    missing_fields = []
    for field in required_fields:
        if not form_data.get(field):
            missing_fields.append(field)
    
    if missing_fields:
        logger.error(f"Missing required fields: {missing_fields}")
        return False, missing_fields
    
    # Validate dates format (assuming DD/MM/YYYY format)
    try:
        datetime.strptime(form_data["shipment_date"], "%d/%m/%Y")
        datetime.strptime(form_data["estimated_arrival"], "%d/%m/%Y")
    except ValueError as e:
        logger.error(f"Invalid date format: {str(e)}")
        return False, ["date_format"]
    
    # Validate total amount is numeric
    try:
        int(form_data["total_amount"])
    except ValueError:
        logger.error(f"Invalid total amount: {form_data['total_amount']}")
        return False, ["total_amount"]
    
    return True, []


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

    # Validate form data
    is_valid, validation_errors = validate_form_data(form_data)
    if not is_valid:
        logger.error(f"Form validation failed for user {user_id}: {validation_errors}")
        bot.send_message(message.chat.id, f"❌ Ошибка валидации данных: {', '.join(validation_errors)}")
        return

    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Parse the sizes data
        sizes_data_str = form_data.get("sizes_data", "")
        parsed_warehouses = parse_sizes_data(sizes_data_str)
        
        if not parsed_warehouses:
            logger.error(f"Could not parse sizes data: {sizes_data_str}")
            bot.send_message(message.chat.id, "❌ Ошибка при разборе данных о размерах. Проверьте формат: Склад: Размер-Количество")
            return
        
        records_created = 0
        worksheet = sheets_manager.get_main_worksheet()
        
        # Ensure worksheet has headers (add them if they don't exist)
        try:
            headers = worksheet.row_values(1)
            if not headers or len(headers) < 11:
                header_row = [
                    "Timestamp", "User ID", "Username", "Product Name", 
                    "Shipment Date", "Estimated Arrival", "Actual Arrival",
                    "Product Color", "Quantity", "Warehouse", "Sizes"
                ]
                worksheet.update('A1:K1', [header_row])
                logger.info("Added headers to main worksheet")
        except Exception as e:
            logger.warning(f"Could not check/add headers: {str(e)}")
        
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
                str(user_id),
                username,
                form_data.get("product_name"),
                form_data.get("shipment_date"),
                form_data.get("estimated_arrival"),
                "",  # Actual arrival date (empty initially)
                form_data.get("product_color"),
                str(warehouse_total),  # Total for this warehouse
                warehouse_name,        # Warehouse name
                sizes_formatted        # Formatted sizes for this warehouse
            ]
            
            # Save to Google Sheets
            worksheet.append_row(row_data)
            records_created += 1
            logger.info(f"Saved warehouse '{warehouse_name}' data from {username} to Google Sheets")
        
        # Register user if not already registered
        register_user(user_id, username)
        
        # Calculate grand total across all warehouses
        grand_total = sum([sum(w["sizes"].values()) for w in parsed_warehouses])
        
        # Send success message
        success_message = f"✅ Данные успешно сохранены!\n"
        success_message += f"📦 Название изделия: {form_data.get('product_name')}\n"
        success_message += f"🎨 Цвет изделия: {form_data.get('product_color')}\n"
        success_message += f"📊 Общее количество: {grand_total} шт\n"
        
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
        logger.info(f"Successfully processed and saved data for user {user_id}")

    except Exception as e:
        logger.error(f"Error saving to Google Sheets: {str(e)}")
        error_message = "❌ Ошибка при сохранении данных. "
        if "quota" in str(e).lower():
            error_message += "Превышен лимит запросов к Google Sheets. Попробуйте позже."
        elif "permission" in str(e).lower():
            error_message += "Нет прав доступа к таблице."
        else:
            error_message += "Попробуйте еще раз с помощью /save"
        
        bot.send_message(message.chat.id, error_message)
        user_data.clear_user_data(user_id)  # Clear user data in case of error


def get_user_submissions(user_id, limit=10):
    """Get recent submissions for a specific user"""
    sheets_manager = GoogleSheetsManager.get_instance()
    try:
        worksheet = sheets_manager.get_main_worksheet()
        all_data = worksheet.get_all_values()
        
        if len(all_data) <= 1:  # Only headers or empty
            return []
        
        # Filter submissions by user_id
        user_submissions = []
        for row in all_data[1:]:  # Skip header row
            if len(row) >= 2 and row[1] == str(user_id):  # User ID is in column B (index 1)
                user_submissions.append(row)
        
        # Return most recent submissions (limited)
        return user_submissions[-limit:] if len(user_submissions) > limit else user_submissions
        
    except Exception as e:
        logger.error(f"Error fetching user submissions: {str(e)}")
        return []


def get_warehouse_summary():
    """Get summary of all warehouses and their inventory"""
    sheets_manager = GoogleSheetsManager.get_instance()
    try:
        worksheet = sheets_manager.get_main_worksheet()
        all_data = worksheet.get_all_values()
        
        if len(all_data) <= 1:  # Only headers or empty
            return {}
        
        warehouse_summary = {}
        
        for row in all_data[1:]:  # Skip header row
            if len(row) >= 10:  # Ensure we have warehouse data
                warehouse = row[9]  # Warehouse column
                quantity = row[8]   # Quantity column
                
                try:
                    qty = int(quantity)
                    if warehouse in warehouse_summary:
                        warehouse_summary[warehouse] += qty
                    else:
                        warehouse_summary[warehouse] = qty
                except ValueError:
                    continue
        
        return warehouse_summary
        
    except Exception as e:
        logger.error(f"Error generating warehouse summary: {str(e)}")
        return {}


# Utility functions for data management
def backup_sheet_data():
    """Create a backup of current sheet data"""
    sheets_manager = GoogleSheetsManager.get_instance()
    try:
        worksheet = sheets_manager.get_main_worksheet()
        all_data = worksheet.get_all_values()
        
        # Create backup worksheet with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"Backup_{timestamp}"
        
        spreadsheet = sheets_manager.get_spreadsheet()
        backup_sheet = spreadsheet.add_worksheet(backup_name, len(all_data), len(all_data[0]) if all_data else 10)
        
        if all_data:
            backup_sheet.update(f'A1:{chr(65 + len(all_data[0]) - 1)}{len(all_data)}', all_data)
        
        logger.info(f"Created backup sheet: {backup_name}")
        return backup_name
        
    except Exception as e:
        logger.error(f"Error creating backup: {str(e)}")
        return None


def clear_old_data(days_old=90):
    """Clear data older than specified days (use with caution)"""
    sheets_manager = GoogleSheetsManager.get_instance()
    try:
        worksheet = sheets_manager.get_main_worksheet()
        all_data = worksheet.get_all_values()
        
        if len(all_data) <= 1:
            return 0
        
        cutoff_date = datetime.now() - timedelta(days=days_old)
        rows_to_delete = []
        
        for i, row in enumerate(all_data[1:], start=2):  # Start from row 2 (skip header)
            if len(row) >= 1:
                try:
                    row_date = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                    if row_date < cutoff_date:
                        rows_to_delete.append(i)
                except ValueError:
                    continue
        
        # Delete rows in reverse order to maintain indices
        for row_index in reversed(rows_to_delete):
            worksheet.delete_rows(row_index)
        
        logger.info(f"Deleted {len(rows_to_delete)} old records")
        return len(rows_to_delete)
        
    except Exception as e:
        logger.error(f"Error clearing old data: {str(e)}")
        return 0