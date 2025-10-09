from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from models.user_data import user_data
from models.factory_data import factory_manager
from handlers.factory_selection import prompt_factory_selection
from utils.google_sheets import GoogleSheetsManager, SIZE_COLS
from utils.validators import validate_date, standardize_date
from datetime import datetime
import pytz
import logging
import time
import threading
from typing import Optional, Tuple, Dict, List

logger = logging.getLogger(__name__)

# ===================== Thread Safety =====================================
_id_generation_lock = threading.Lock()

# ===================== Custom Exceptions =================================
class ShipmentIDError(Exception):
    """Custom exception for shipment ID generation errors"""
    pass

class BagIDError(Exception):
    """Custom exception for bag ID generation errors"""
    pass

def _safe_get_factory_sheet_data(tab_name: str) -> Tuple[list, dict]:
    """
    Safely retrieve factory sheet data with comprehensive error handling.
    Returns: (all_values, header_mapping)
    """
    max_retries = 3
    retry_delay = 1  # seconds
    
    for attempt in range(max_retries):
        try:
            ws = factory_manager.get_factory_worksheet(tab_name)
            
            # Get all data with timeout protection
            all_values = ws.get_all_values()
            
            if not all_values:
                logger.warning(f"Factory sheet {tab_name} appears empty on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                return [], {}
            
            # Create header mapping for easier column access
            headers = all_values[0] if all_values else []
            header_map = {}
            for i, header in enumerate(headers):
                clean_header = header.lower().strip()
                header_map[clean_header] = i
            
            logger.info(f"Successfully retrieved {len(all_values)} rows from factory sheet {tab_name}")
            return all_values, header_map
            
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed to get factory sheet data for {tab_name}: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
            else:
                raise ShipmentIDError(f"Failed to access factory sheet {tab_name} after {max_retries} attempts: {e}")

def _extract_shipment_ids_from_factory(all_values: list, header_map: dict) -> list:
    """
    Extract all shipment IDs from factory sheet data with validation.
    Returns list of integer shipment IDs.
    """
    shipment_ids = []
    shipment_col_idx = header_map.get('номер отправки')
    
    if shipment_col_idx is None:
        logger.error("Column 'номер отправки' not found in factory sheet headers")
        logger.debug(f"Available headers: {list(header_map.keys())}")
        raise ShipmentIDError("Shipment ID column not found in factory sheet headers")
    
    # Process data rows (skip header)
    for row_idx, row in enumerate(all_values[1:], start=2):
        if len(row) <= shipment_col_idx:
            continue
            
        shipment_value = row[shipment_col_idx].strip() if row[shipment_col_idx] else ""
        
        if not shipment_value:
            continue
            
        try:
            shipment_num = int(shipment_value)
            if shipment_num > 0:  # Only accept positive integers
                shipment_ids.append(shipment_num)
            else:
                logger.warning(f"Invalid shipment ID '{shipment_value}' in row {row_idx} (non-positive)")
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid shipment ID '{shipment_value}' in row {row_idx}: {e}")
            continue
    
    return shipment_ids

def _extract_bag_ids_for_shipment_factory(all_values: list, header_map: dict, shipment_id: str) -> list:
    """
    Extract bag numbers for a specific shipment from factory worksheet.
    Returns list of integer bag numbers.
    """
    bag_numbers = []
    bag_id_col_idx = header_map.get('номер пакета')
    shipment_col_idx = header_map.get('номер отправки')
    
    if bag_id_col_idx is None:
        raise BagIDError("Bag ID column 'номер пакета' not found in factory sheet headers")
    
    if shipment_col_idx is None:
        raise BagIDError("Shipment ID column 'номер отправки' not found in factory sheet headers")
    
    for row_idx, row in enumerate(all_values[1:], start=2):
        if len(row) <= max(bag_id_col_idx, shipment_col_idx):
            continue
            
        # Check if this row belongs to our shipment
        row_shipment_id = row[shipment_col_idx].strip() if row[shipment_col_idx] else ""
        if row_shipment_id != shipment_id:
            continue
            
        bag_id = row[bag_id_col_idx].strip() if row[bag_id_col_idx] else ""
        if not bag_id:
            continue
            
        # Extract bag number from format "shipment_id-bag_number"
        try:
            if "-" in bag_id:
                parts = bag_id.split("-")
                if len(parts) >= 2 and parts[0] == shipment_id:
                    bag_num = int(parts[1])
                    if bag_num > 0:
                        bag_numbers.append(bag_num)
                    else:
                        logger.warning(f"Invalid bag number '{bag_num}' in row {row_idx}")
                else:
                    logger.warning(f"Bag ID format mismatch in row {row_idx}: expected '{shipment_id}-X', got '{bag_id}'")
            else:
                logger.warning(f"Invalid bag ID format in row {row_idx}: '{bag_id}' (missing hyphen)")
        except (ValueError, TypeError) as e:
            logger.warning(f"Error parsing bag ID '{bag_id}' in row {row_idx}: {e}")
            continue
    
    return bag_numbers

def _new_shipment_id_for_factory(tab_name: str) -> str:
    """
    Generate next sequential shipment ID for specific factory with comprehensive error handling.
    Uses thread lock to prevent race conditions.
    """
    with _id_generation_lock:
        try:
            logger.info(f"Generating new shipment ID for factory {tab_name}...")
            
            # Get factory sheet data safely
            all_values, header_map = _safe_get_factory_sheet_data(tab_name)
            
            if not all_values or len(all_values) < 2:
                logger.info(f"No existing data found for factory {tab_name}, starting with shipment ID 1")
                return "1"
            
            # Extract and validate shipment IDs
            shipment_ids = _extract_shipment_ids_from_factory(all_values, header_map)
            
            if not shipment_ids:
                logger.info(f"No valid shipment IDs found for factory {tab_name}, starting with shipment ID 1")
                return "1"
            
            # Find maximum and generate next ID
            max_shipment_id = max(shipment_ids)
            next_id = max_shipment_id + 1
            
            logger.info(f"Generated shipment ID: {next_id} for factory {tab_name} (previous max: {max_shipment_id})")
            return str(next_id)
            
        except ShipmentIDError:
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            logger.error(f"Unexpected error generating shipment ID for factory {tab_name}: {e}")
            # Fallback to timestamp-based ID to avoid conflicts
            timestamp_id = str(int(time.time()) % 100000)
            logger.warning(f"Using fallback timestamp-based ID for factory {tab_name}: {timestamp_id}")
            return timestamp_id

def _get_next_bag_number_for_shipment_factory(tab_name: str, shipment_id: str) -> int:
    """
    Get next bag number for a specific shipment in factory with comprehensive error handling.
    Uses thread lock to prevent race conditions.
    """
    with _id_generation_lock:
        try:
            logger.info(f"Getting next bag number for shipment {shipment_id} in factory {tab_name}...")
            
            # Validate input
            if not shipment_id or not shipment_id.strip():
                raise BagIDError("Shipment ID cannot be empty")
            
            shipment_id = shipment_id.strip()
            
            # Get factory sheet data safely
            all_values, header_map = _safe_get_factory_sheet_data(tab_name)
            
            if not all_values or len(all_values) < 2:
                logger.info(f"No existing data found for factory {tab_name}, starting with bag number 1 for shipment {shipment_id}")
                return 1
            
            # Extract bag numbers for this shipment
            bag_numbers = _extract_bag_ids_for_shipment_factory(all_values, header_map, shipment_id)
            
            if not bag_numbers:
                logger.info(f"No existing bags found for shipment {shipment_id} in factory {tab_name}, starting with bag number 1")
                return 1
            
            # Find maximum and generate next bag number
            max_bag_number = max(bag_numbers)
            next_bag_number = max_bag_number + 1
            
            logger.info(f"Generated bag number {next_bag_number} for shipment {shipment_id} in factory {tab_name}")
            return next_bag_number
            
        except BagIDError:
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting bag number for shipment {shipment_id} in factory {tab_name}: {e}")
            # Fallback to bag number 1
            logger.warning(f"Using fallback bag number 1 for shipment {shipment_id} in factory {tab_name}")
            return 1

def _generate_bag_id_factory(tab_name: str, shipment_id: str, bag_number: Optional[int] = None) -> str:
    """
    Generate bag ID for factory with error handling and validation.
    If bag_number is not provided, gets next available number.
    """
    try:
        # Validate shipment ID
        if not shipment_id or not shipment_id.strip():
            raise BagIDError("Shipment ID cannot be empty")
        
        shipment_id = shipment_id.strip()
        
        # Get bag number if not provided
        if bag_number is None:
            bag_number = _get_next_bag_number_for_shipment_factory(tab_name, shipment_id)
        
        # Validate bag number
        if not isinstance(bag_number, int) or bag_number < 1:
            raise BagIDError(f"Invalid bag number: {bag_number}. Must be positive integer.")
        
        bag_id = f"{shipment_id}-{bag_number}"
        logger.debug(f"Generated bag ID: {bag_id} for factory {tab_name}")
        return bag_id
        
    except Exception as e:
        logger.error(f"Error generating bag ID for factory {tab_name}: {e}")
        # Fallback to timestamp-based ID
        fallback_id = f"{shipment_id}-{int(time.time()) % 1000}"
        logger.warning(f"Using fallback bag ID for factory {tab_name}: {fallback_id}")
        return fallback_id
