# handlers/save.py — warehouse-centric shipment flow with multiple bags per model+color
# -*- coding: utf-8 -*-

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from models.user_data import user_data
from utils.google_sheets import save_to_sheets, GoogleSheetsManager, SIZE_COLS
from utils.validators import validate_date, standardize_date
from datetime import datetime
import pytz
import logging
import secrets
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

# ===================== Conversation state keys ==============================
STATE_KEY = "shipment_state"
STATE_STEP = "step"

STATE_WAREHOUSE  = "warehouse"
STATE_MODELS     = "models"            # list[{model_name, colors{color:[{bag_id, sizes{size:qty}}]}}]
STATE_SHIP_DATE  = "ship_date"
STATE_ETA_DATE   = "eta_date"
CURRENT_MODEL    = "current_model"

# color building substate
CURRENT_COLOR        = "current_color"
CURRENT_BAG_INDEX    = "current_bag_index"  # which bag we're editing within current color
CURRENT_BAGS         = "current_bags"       # list of bags for current color: [{bag_id, sizes{size:qty}}]
AWAITING_SIZE        = "awaiting_size"      # when expecting numeric amount for selected size

STEP_WAREHOUSE = "ask_warehouse"
STEP_MODEL     = "ask_model"
STEP_COLORNAME = "ask_color_name"
STEP_COLORSZ   = "ask_color_sizes"     # size keypad mode
STEP_SHIPDATE  = "ask_shipdate"
STEP_ETADATE   = "ask_etadate"
STEP_CONFIRM   = "confirm"

WAREHOUSES = [
    "Казань", "Краснодар", "Электросталь", "Коледино",
    "Тула", "Невинномысск", "Рязань", "Новосибирск", "Алматы", "Котовск"
]

# ===================== Enhanced ID Generation with Error Handling ========

def _safe_get_sheet_data() -> Tuple[list, dict]:
    """
    Safely retrieve sheet data with comprehensive error handling.
    Returns: (all_values, header_mapping)
    """
    max_retries = 3
    retry_delay = 1  # seconds
    
    for attempt in range(max_retries):
        try:
            sheets_manager = GoogleSheetsManager.get_instance()
            ws = sheets_manager.get_main_worksheet()
            
            # Get all data with timeout protection
            all_values = ws.get_all_values()
            
            if not all_values:
                logger.warning(f"Sheet appears empty on attempt {attempt + 1}")
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
            
            logger.info(f"Successfully retrieved {len(all_values)} rows from sheet")
            return all_values, header_map
            
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed to get sheet data: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
            else:
                raise ShipmentIDError(f"Failed to access sheet after {max_retries} attempts: {e}")

def _extract_shipment_ids(all_values: list, header_map: dict) -> list:
    """
    Extract all shipment IDs from sheet data with validation.
    Returns list of integer shipment IDs.
    """
    shipment_ids = []
    shipment_col_idx = header_map.get('номер отправки')
    
    if shipment_col_idx is None:
        logger.error("Column 'номер отправки' not found in headers")
        logger.debug(f"Available headers: {list(header_map.keys())}")
        raise ShipmentIDError("Shipment ID column not found in sheet headers")
    
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

def _extract_bag_ids_for_shipment(all_values: list, header_map: dict, shipment_id: str) -> list:
    """
    Extract bag numbers for a specific shipment.
    Returns list of integer bag numbers.
    """
    bag_numbers = []
    bag_id_col_idx = header_map.get('номер пакета')
    shipment_col_idx = header_map.get('номер отправки')
    
    if bag_id_col_idx is None:
        raise BagIDError("Bag ID column 'номер пакета' not found in sheet headers")
    
    if shipment_col_idx is None:
        raise BagIDError("Shipment ID column 'номер отправки' not found in sheet headers")
    
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

def _new_shipment_id() -> str:
    """
    Generate next sequential shipment ID with comprehensive error handling.
    Uses thread lock to prevent race conditions.
    """
    with _id_generation_lock:
        try:
            logger.info("Generating new shipment ID...")
            
            # Get sheet data safely
            all_values, header_map = _safe_get_sheet_data()
            
            if not all_values or len(all_values) < 2:
                logger.info("No existing data found, starting with shipment ID 1")
                return "1"
            
            # Extract and validate shipment IDs
            shipment_ids = _extract_shipment_ids(all_values, header_map)
            
            if not shipment_ids:
                logger.info("No valid shipment IDs found, starting with shipment ID 1")
                return "1"
            
            # Find maximum and generate next ID
            max_shipment_id = max(shipment_ids)
            next_id = max_shipment_id + 1
            
            logger.info(f"Generated shipment ID: {next_id} (previous max: {max_shipment_id}, total existing: {len(shipment_ids)})")
            return str(next_id)
            
        except ShipmentIDError:
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            logger.error(f"Unexpected error generating shipment ID: {e}")
            # Fallback to timestamp-based ID to avoid conflicts
            timestamp_id = str(int(time.time()) % 100000)
            logger.warning(f"Using fallback timestamp-based ID: {timestamp_id}")
            return timestamp_id

def _get_next_bag_number_for_shipment(shipment_id: str) -> int:
    """
    Get next bag number for a specific shipment with comprehensive error handling.
    Uses thread lock to prevent race conditions.
    """
    with _id_generation_lock:
        try:
            logger.info(f"Getting next bag number for shipment {shipment_id}...")
            
            # Validate input
            if not shipment_id or not shipment_id.strip():
                raise BagIDError("Shipment ID cannot be empty")
            
            shipment_id = shipment_id.strip()
            
            # Get sheet data safely
            all_values, header_map = _safe_get_sheet_data()
            
            if not all_values or len(all_values) < 2:
                logger.info(f"No existing data found, starting with bag number 1 for shipment {shipment_id}")
                return 1
            
            # Extract bag numbers for this shipment
            bag_numbers = _extract_bag_ids_for_shipment(all_values, header_map, shipment_id)
            
            if not bag_numbers:
                logger.info(f"No existing bags found for shipment {shipment_id}, starting with bag number 1")
                return 1
            
            # Find maximum and generate next bag number
            max_bag_number = max(bag_numbers)
            next_bag_number = max_bag_number + 1
            
            logger.info(f"Generated bag number {next_bag_number} for shipment {shipment_id} (previous max: {max_bag_number})")
            return next_bag_number
            
        except BagIDError:
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting bag number for shipment {shipment_id}: {e}")
            # Fallback to bag number 1
            logger.warning(f"Using fallback bag number 1 for shipment {shipment_id}")
            return 1

def _generate_bag_id(shipment_id: str, bag_number: Optional[int] = None) -> str:
    """
    Generate bag ID with error handling and validation.
    If bag_number is not provided, gets next available number.
    """
    try:
        # Validate shipment ID
        if not shipment_id or not shipment_id.strip():
            raise BagIDError("Shipment ID cannot be empty")
        
        shipment_id = shipment_id.strip()
        
        # Get bag number if not provided
        if bag_number is None:
            bag_number = _get_next_bag_number_for_shipment(shipment_id)
        
        # Validate bag number
        if not isinstance(bag_number, int) or bag_number < 1:
            raise BagIDError(f"Invalid bag number: {bag_number}. Must be positive integer.")
        
        bag_id = f"{shipment_id}-{bag_number}"
        logger.debug(f"Generated bag ID: {bag_id}")
        return bag_id
        
    except Exception as e:
        logger.error(f"Error generating bag ID: {e}")
        # Fallback to timestamp-based ID
        fallback_id = f"{shipment_id}-{int(time.time()) % 1000}"
        logger.warning(f"Using fallback bag ID: {fallback_id}")
        return fallback_id

def _validate_shipment_integrity(shipment_id: str) -> dict:
    """
    Validate shipment data integrity and return diagnostic information.
    Useful for debugging and monitoring.
    """
    try:
        all_values, header_map = _safe_get_sheet_data()
        
        if not all_values:
            return {
                "valid": True,
                "message": "No data to validate",
                "shipment_exists": False,
                "bag_count": 0,
                "bags": []
            }
        
        # Find all records for this shipment
        shipment_col_idx = header_map.get('номер отправки')
        bag_col_idx = header_map.get('номер пакета')
        
        if shipment_col_idx is None or bag_col_idx is None:
            return {
                "valid": False,
                "message": "Required columns not found",
                "error": "Missing shipment or bag ID columns"
            }
        
        shipment_records = []
        for row_idx, row in enumerate(all_values[1:], start=2):
            if (len(row) > max(shipment_col_idx, bag_col_idx) and 
                row[shipment_col_idx].strip() == shipment_id):
                shipment_records.append({
                    "row": row_idx,
                    "bag_id": row[bag_col_idx].strip(),
                    "data": row
                })
        
        return {
            "valid": True,
            "shipment_exists": len(shipment_records) > 0,
            "bag_count": len(shipment_records),
            "bags": [r["bag_id"] for r in shipment_records],
            "records": shipment_records
        }
        
    except Exception as e:
        logger.error(f"Error validating shipment {shipment_id}: {e}")
        return {
            "valid": False,
            "message": f"Validation error: {e}",
            "error": str(e)
        }

# ===================== Keyboard Helpers ==================================

def _kb_warehouses() -> InlineKeyboardMarkup:
    """Inline keyboard to choose a warehouse."""
    m = InlineKeyboardMarkup(row_width=3)
    buttons = [InlineKeyboardButton(w, callback_data=f"wh_{w}") for w in WAREHOUSES]
    m.add(*buttons)
    return m

def _kb_sizepad(current_color: str, current_bag: dict, bag_index: int, total_bags: int) -> InlineKeyboardMarkup:
    """
    Inline keyboard with size buttons + control rows:
    - size buttons (✓ mark when filled)
    - ➕ Добавить пакет
    - ➕ Добавить расцветку
    - ✅ Закончить модель
    - 🗑 Очистить пакет / ↩ Назад к моделям
    """
    m = InlineKeyboardMarkup()
    
    # Size buttons
    sizes = current_bag.get('sizes', {})
    row = []
    for i, s in enumerate(SIZE_COLS, 1):
        mark = "✓" if sizes.get(s, 0) > 0 else ""
        row.append(InlineKeyboardButton(f"{s}{mark}", callback_data=f"cset_{s}"))
        if i % 4 == 0:
            m.row(*row)
            row = []
    if row:
        m.row(*row)

    # Add bag button
    m.row(InlineKeyboardButton("➕ Добавить пакет", callback_data="cadd_bag"))
    
    # Other controls
    m.row(InlineKeyboardButton("➕ Добавить расцветку", callback_data="cadd_color"))
    m.row(InlineKeyboardButton("✅ Закончить модель", callback_data="cfinish_model"))

    # Utility controls
    m.row(
        InlineKeyboardButton("🗑 Очистить пакет", callback_data="cclr"),
        InlineKeyboardButton("↩ Назад к моделям", callback_data="cback"),
    )
    return m

def _kb_finish_models() -> InlineKeyboardMarkup:
    """Final summary controls: add another model or finish (save)."""
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("➕ Добавить модель", callback_data="ship_add_model"))
    m.add(InlineKeyboardButton("✅ Закончить отправку", callback_data="ship_finish_all"))
    m.add(InlineKeyboardButton("⌫ Отмена", callback_data="ship_cancel"))
    return m

# ===================== Formatting Helpers ================================

def _format_bag_preview(color: str, current_bag: dict, bag_index: int, total_bags: int) -> str:
    """Format current bag preview with sizes"""
    sizes = current_bag.get('sizes', {})
    pairs = [f"{k}-{sizes[k]}" for k in SIZE_COLS if sizes.get(k, 0) > 0]
    body = " ".join(pairs) if pairs else "—"
    bag_id = current_bag.get('bag_id', f'пакет {bag_index + 1}')
    return f"Текущая расцветка: {color}\nПакет: {bag_id} ({bag_index + 1}/{total_bags})\nРазмеры: {body}\n\n"

def _format_confirmation(state: dict) -> str:
    """Format confirmation message showing all data"""
    wh = state.get(STATE_WAREHOUSE, "—")
    ship = state.get(STATE_SHIP_DATE, "—")
    eta = state.get(STATE_ETA_DATE, "—")
    
    lines = ["Проверьте правильность данных:", f"Склад: {wh}"]
    total_all = 0
    total_bags = 0
    
    for item in state.get(STATE_MODELS, []):
        model = item.get("model_name", "—")
        colors = item.get("colors", {})
        lines.append(f"Модель: {model}")
        
        for color, bags in colors.items():
            lines.append(f"  Расцветка: {color}")
            for bag in bags:
                bag_id = bag.get('bag_id', '—')
                sizes = bag.get('sizes', {})
                qty = sum(int(v or 0) for v in sizes.values())
                total_all += qty
                total_bags += 1
                pairs = [f"{k}-{sizes.get(k,0)}" for k in SIZE_COLS if sizes.get(k,0) > 0]
                size_text = " ".join(pairs) if pairs else "—"
                lines.append(f"    {bag_id}: {size_text} (всего: {qty})")
        lines.append("")
    
    lines.append(f"📊 Общее количество: {total_all} шт")
    lines.append(f"📦 Общее количество пакетов: {total_bags}")
    lines.append(f"Дата отправки: {ship}")
    lines.append(f"Дата прибытия (примерное): {eta}")
    return "\n".join(lines)

def _notify_admins_about_new_record(bot: TeleBot, row_index: int, source_username: str):
    """Notify admins using updated column schema with shipment_id and bag_id"""
    try:
        sheets_manager = GoogleSheetsManager.get_instance()
        ws = sheets_manager.get_main_worksheet()
        record = ws.row_values(row_index)

        hi = GoogleSheetsManager.header_index()

        def get(name, default="-"):
            idx = hi.get(name)
            if idx is not None and len(record) > idx:
                return record[idx]
            return default

        product_name = get('product_name')
        color = get('color')
        shipment = get('shipment_date')
        eta = get('estimated_arrival')
        warehouse = get('warehouse')
        total_amt = get('total_amount', "0")
        shipment_id = get('shipment_id')
        bag_id = get('bag_id')
        status = get('Статус')

        sizes_text = []
        for k in SIZE_COLS:
            val = get(k)
            if val and str(val).strip() not in ("", "0"):
                sizes_text.append(f"{k}({val})")
        sizes_text = ", ".join(sizes_text) if sizes_text else "—"

        text = (
            f"🆕 Новая запись добавлена в таблицу\n\n"
            f"Пользователь: @{source_username}\n"
            f"Отправка: {shipment_id}\n"
            f"Пакет: {bag_id}\n"
            f"Склад: {warehouse}\n"
            f"Модель: {product_name}\n"
            f"Цвет: {color}\n"
            f"Дата отправки: {shipment}\n"
            f"Примерная дата прибытия: {eta}\n"
            f"Общее количество: {total_amt}\n"
            f"Размеры: {sizes_text}\n"
            f"Статус: {status}\n"
            f"Дата добавления: {datetime.now(pytz.timezone('Asia/Bishkek')).strftime('%Y-%m-%d %H:%M:%S')}"
        )

        try:
            users_ws = sheets_manager.get_users_worksheet()
            all_users = users_ws.get_all_values()
        except Exception as e:
            logger.error(f"Error getting users worksheet: {e}")
            all_users = []

        from config import ADMIN_USER_USERNAMES
        for admin_username in ADMIN_USER_USERNAMES:
            admin_chat_id = None
            for row in all_users[1:]:
                if len(row) > 1 and row[1] == admin_username:
                    try:
                        admin_chat_id = int(row[0])
                        break
                    except Exception as e:
                        logger.error(f"Error parsing admin chat ID: {e}")
                        pass
            if admin_chat_id:
                try:
                    bot.send_message(admin_chat_id, text)
                except Exception as e:
                    logger.warning(f"Failed to notify admin {admin_username}: {e}")
    except Exception as e:
        logger.error(f"Admin notify error: {e}")

# ===================== Entry point ==========================================

def setup_save_handler(bot: TeleBot):

    @bot.message_handler(commands=['save'])
    def start_flow(message):
        uid = message.from_user.id
        try:
            user_data.initialize_user(uid)
            
            # Generate shipment ID with error handling
            try:
                shipment_id = _new_shipment_id()
                user_data.update_user_data(uid, "current_shipment_id", shipment_id)
                logger.info(f"User {uid} started new shipment {shipment_id}")
            except ShipmentIDError as e:
                logger.error(f"Failed to generate shipment ID for user {uid}: {e}")
                bot.reply_to(message, "❌ Ошибка при создании номера отправки. Попробуйте позже или обратитесь к администратору.")
                return
            except Exception as e:
                logger.error(f"Unexpected error generating shipment ID for user {uid}: {e}")
                bot.reply_to(message, "❌ Произошла неожиданная ошибка. Попробуйте позже.")
                return

            st = {
                STATE_STEP: STEP_WAREHOUSE,
                STATE_WAREHOUSE: None,
                STATE_MODELS: [],
                STATE_SHIP_DATE: None,
                STATE_ETA_DATE: None,
                CURRENT_MODEL: None,
                CURRENT_COLOR: None,
                CURRENT_BAG_INDEX: 0,
                CURRENT_BAGS: [],
                AWAITING_SIZE: None,
            }
            user_data.update_user_data(uid, STATE_KEY, st)
            
            save_text = (
                f"Пожалуйста введите данные об отправке №{shipment_id}. "
                f"Форма предназначена для одной модели с несколькими расцветками и размерами. "
                f"Введите данные по порядку. Вы можете добавить модели по очереди.\n\n"
                f"Нажмите /cancel для отмены\n\n"
                f"Пожалуйста, введите склад:"
            )
            bot.reply_to(message, save_text, reply_markup=_kb_warehouses())
            
        except Exception as e:
            logger.error(f"Error in start_flow for user {uid}: {e}")
            bot.reply_to(message, "❌ Ошибка при инициализации. Попробуйте позже.")

    @bot.message_handler(func=lambda m: user_data.get_user_data(m.from_user.id) and user_data.get_user_data(m.from_user.id).get(STATE_KEY) is not None)
    def handle_text(message):
        uid = message.from_user.id
        try:
            st = user_data.get_user_data(uid).get(STATE_KEY, {})
            step = st.get(STATE_STEP)
            text = (message.text or "").strip()

            # Cancel
            if text.lower() in {"/cancel", "отмена"}:
                user_data.update_user_data(uid, STATE_KEY, None)
                bot.reply_to(message, "✖️ Процесс отменён.")
                return

            # When awaiting numeric amount for a size during size keypad
            if step == STEP_COLORSZ and st.get(AWAITING_SIZE):
                size = st.get(AWAITING_SIZE)
                try:
                    qty = int(text)
                    if qty < 0:
                        raise ValueError("Negative quantity")
                except Exception as e:
                    logger.warning(f"Invalid quantity input '{text}' for size {size} by user {uid}: {e}")
                    bot.reply_to(message, f"Введите количество числом для размера {size}.")
                    return
                
                # Update current bag sizes
                current_bags = st.get(CURRENT_BAGS, [])
                bag_index = st.get(CURRENT_BAG_INDEX, 0)
                if bag_index < len(current_bags):
                    current_bags[bag_index]['sizes'][size] = qty
                    st[CURRENT_BAGS] = current_bags
                    st[AWAITING_SIZE] = None
                    user_data.update_user_data(uid, STATE_KEY, st)

                    # Re-render keypad with updated preview
                    current_bag = current_bags[bag_index]
                    preview = _format_bag_preview(st.get(CURRENT_COLOR), current_bag, bag_index, len(current_bags))
                    bot.send_message(message.chat.id, preview + "Выберите следующий размер или используйте кнопки ниже.",
                                   reply_markup=_kb_sizepad(st.get(CURRENT_COLOR), current_bag, bag_index, len(current_bags)))
                return

            # Normal step progression
            if step == STEP_WAREHOUSE:
                bot.reply_to(message, "Выберите склад с помощью кнопок ниже.", reply_markup=_kb_warehouses())
                return

            if step == STEP_MODEL:
                if not text:
                    bot.reply_to(message, "Название модели не может быть пустым. Введите модель:")
                    return
                st[CURRENT_MODEL] = text
                st[STATE_STEP] = STEP_COLORNAME
                user_data.update_user_data(uid, STATE_KEY, st)
                bot.reply_to(message, "Введите название расцветки:")
                return

            if step == STEP_COLORNAME:
                if not text:
                    bot.reply_to(message, "Название расцветки не может быть пустым. Введите расцветку:")
                    return
                
                st[CURRENT_COLOR] = text
                
                # Initialize first bag for this color with error handling
                try:
                    shipment_id = user_data.get_user_data(uid).get("current_shipment_id", "1")
                    bag_id = _generate_bag_id(shipment_id, 1)
                    first_bag = {'bag_id': bag_id, 'sizes': {}}
                    
                    st[CURRENT_BAGS] = [first_bag]
                    st[CURRENT_BAG_INDEX] = 0
                    st[AWAITING_SIZE] = None
                    st[STATE_STEP] = STEP_COLORSZ
                    user_data.update_user_data(uid, STATE_KEY, st)

                    preview = _format_bag_preview(st.get(CURRENT_COLOR), first_bag, 0, 1)
                    bot.reply_to(message, preview + "Выберите размер (кнопка) и укажите количество, затем нажмите одну из кнопок управления.",
                                 reply_markup=_kb_sizepad(st.get(CURRENT_COLOR), first_bag, 0, 1))
                    
                except BagIDError as e:
                    logger.error(f"Failed to generate bag ID for user {uid}: {e}")
                    bot.reply_to(message, "❌ Ошибка при создании номера пакета. Попробуйте позже.")
                    return
                except Exception as e:
                    logger.error(f"Unexpected error creating bag for user {uid}: {e}")
                    bot.reply_to(message, "❌ Произошла ошибка при создании пакета. Попробуйте позже.")
                    return

            # Date handling
            if step == STEP_SHIPDATE:
                if not validate_date(text):
                    bot.reply_to(message, "⌫ Некорректный формат даты. Используйте дд.мм.гггг или дд/мм/гггг")
                    return
                st[STATE_SHIP_DATE] = standardize_date(text)
                st[STATE_STEP] = STEP_ETADATE
                user_data.update_user_data(uid, STATE_KEY, st)
                bot.reply_to(message, "Введите примерную дату прибытия, пример (дд.мм.гггг или дд/мм/гггг):")
                return

            if step == STEP_ETADATE:
                if not validate_date(text):
                    bot.reply_to(message, "⌫ Некорректный формат даты. Используйте дд.мм.гггг или дд/мм/гггг")
                    return
                st[STATE_ETA_DATE] = standardize_date(text)
                st[STATE_STEP] = STEP_CONFIRM
                user_data.update_user_data(uid, STATE_KEY, st)
                bot.send_message(message.chat.id, _format_confirmation(st), reply_markup=_kb_finish_models())
                return

            if step == STEP_CONFIRM:
                bot.send_message(message.chat.id, "Пожалуйста, используйте кнопки ниже.", reply_markup=_kb_finish_models())
                return
                
        except Exception as e:
            logger.error(f"Error in handle_text for user {uid}: {e}")
            bot.reply_to(message, "❌ Произошла ошибка при обработке сообщения. Попробуйте позже.")

    # Size pad callbacks
    @bot.callback_query_handler(func=lambda c: c.data.startswith("cset_") or c.data in {"cadd_bag", "cadd_color", "cfinish_model", "cclr", "cback"})
    def on_sizepad(call):
        uid = call.from_user.id
        try:
            st = user_data.get_user_data(uid).get(STATE_KEY)
            if not st or st.get(STATE_STEP) != STEP_COLORSZ:
                bot.answer_callback_query(call.id, "Сессия истекла. Начните заново с /save")
                return

            bot.answer_callback_query(call.id)
            data = call.data

            current_bags = st.get(CURRENT_BAGS, [])
            bag_index = st.get(CURRENT_BAG_INDEX, 0)
            
            if bag_index >= len(current_bags):
                bot.send_message(call.message.chat.id, "❌ Ошибка: пакет не найден. Начните заново с /save")
                return
            
            current_bag = current_bags[bag_index]

            # Choose size → ask amount
            if data.startswith("cset_"):
                size = data.split("_", 1)[1]
                st[AWAITING_SIZE] = size
                user_data.update_user_data(uid, STATE_KEY, st)
                try:
                    bot.edit_message_text(
                        _format_bag_preview(st.get(CURRENT_COLOR), current_bag, bag_index, len(current_bags)) +
                        f"Введите количество для размера {size}:",
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=None
                    )
                except Exception as e:
                    logger.warning(f"Failed to edit message for user {uid}: {e}")
                    bot.send_message(call.message.chat.id, f"Введите количество для размера {size}:")
                return

            # Add bag
            if data == "cadd_bag":
                # Check if current bag has any sizes
                if not any(current_bag.get('sizes', {}).values()):
                    bot.answer_callback_query(call.id, "Добавьте хотя бы один размер в текущий пакет.")
                    return
                
                # Create new bag with error handling
                try:
                    shipment_id = user_data.get_user_data(uid).get("current_shipment_id", "1")
                    new_bag_number = len(current_bags) + 1
                    new_bag_id = _generate_bag_id(shipment_id, new_bag_number)
                    new_bag = {'bag_id': new_bag_id, 'sizes': {}}
                    
                    current_bags.append(new_bag)
                    st[CURRENT_BAGS] = current_bags
                    st[CURRENT_BAG_INDEX] = len(current_bags) - 1  # Switch to new bag
                    user_data.update_user_data(uid, STATE_KEY, st)
                    
                    try:
                        bot.edit_message_text(
                            _format_bag_preview(st.get(CURRENT_COLOR), new_bag, len(current_bags) - 1, len(current_bags)) +
                            "Новый пакет создан. Выберите размер и укажите количество.",
                            call.message.chat.id,
                            call.message.message_id,
                            reply_markup=_kb_sizepad(st.get(CURRENT_COLOR), new_bag, len(current_bags) - 1, len(current_bags))
                        )
                    except Exception as e:
                        logger.warning(f"Failed to edit message for user {uid}: {e}")
                        bot.send_message(call.message.chat.id,
                                       _format_bag_preview(st.get(CURRENT_COLOR), new_bag, len(current_bags) - 1, len(current_bags)) +
                                       "Новый пакет создан. Выберите размер и укажите количество.",
                                       reply_markup=_kb_sizepad(st.get(CURRENT_COLOR), new_bag, len(current_bags) - 1, len(current_bags)))
                    return
                    
                except BagIDError as e:
                    logger.error(f"Failed to generate bag ID for user {uid}: {e}")
                    bot.answer_callback_query(call.id, "❌ Ошибка при создании пакета. Попробуйте позже.")
                    return
                except Exception as e:
                    logger.error(f"Unexpected error creating new bag for user {uid}: {e}")
                    bot.answer_callback_query(call.id, "❌ Ошибка при создании пакета.")
                    return

            # Clear current bag sizes
            if data == "cclr":
                current_bag['sizes'] = {}
                st[CURRENT_BAGS] = current_bags
                st[AWAITING_SIZE] = None
                user_data.update_user_data(uid, STATE_KEY, st)
                try:
                    bot.edit_message_text(
                        _format_bag_preview(st.get(CURRENT_COLOR), current_bag, bag_index, len(current_bags)) +
                        "Выберите размер и укажите количество.",
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=_kb_sizepad(st.get(CURRENT_COLOR), current_bag, bag_index, len(current_bags))
                    )
                except Exception as e:
                    logger.warning(f"Failed to edit message for user {uid}: {e}")
                    bot.send_message(call.message.chat.id,
                                   _format_bag_preview(st.get(CURRENT_COLOR), current_bag, bag_index, len(current_bags)) +
                                   "Выберите размер и укажите количество.",
                                   reply_markup=_kb_sizepad(st.get(CURRENT_COLOR), current_bag, bag_index, len(current_bags)))
                return

            # Back to models
            if data == "cback":
                st[CURRENT_COLOR] = None
                st[CURRENT_BAGS] = []
                st[CURRENT_BAG_INDEX] = 0
                st[AWAITING_SIZE] = None
                st[STATE_STEP] = STEP_MODEL
                user_data.update_user_data(uid, STATE_KEY, st)
                try:
                    bot.edit_message_text("Пожалуйста, введите название модели в пакете (только одну модель за раз):",
                                          call.message.chat.id, call.message.message_id)
                except Exception as e:
                    logger.warning(f"Failed to edit message for user {uid}: {e}")
                    bot.send_message(call.message.chat.id, "Пожалуйста, введите название модели в пакете (только одну модель за раз):")
                return

            # Save current color and ask for next color name
            if data == "cadd_color":
                # Validate that at least one bag has sizes
                if not any(any(bag.get('sizes', {}).values()) for bag in current_bags):
                    bot.answer_callback_query(call.id, "Добавьте хотя бы один размер в один из пакетов.")
                    return
                
                # Save current color with all its bags
                models = st.get(STATE_MODELS) or []
                if not models or models[-1].get("model_name") != st.get(CURRENT_MODEL):
                    models.append({"model_name": st.get(CURRENT_MODEL), "colors": {}})
                models[-1]["colors"][st.get(CURRENT_COLOR)] = current_bags
                st[STATE_MODELS] = models

                # Reset color state
                st[CURRENT_COLOR] = None
                st[CURRENT_BAGS] = []
                st[CURRENT_BAG_INDEX] = 0
                st[AWAITING_SIZE] = None
                st[STATE_STEP] = STEP_COLORNAME
                user_data.update_user_data(uid, STATE_KEY, st)
                
                try:
                    bot.edit_message_text("Введите следующую расцветку:", call.message.chat.id, call.message.message_id)
                except Exception as e:
                    logger.warning(f"Failed to edit message for user {uid}: {e}")
                    bot.send_message(call.message.chat.id, "Введите следующую расцветку:")
                return

            # Finish model
            if data == "cfinish_model":
                # Save current color if it has any filled bags
                if current_bags and any(any(bag.get('sizes', {}).values()) for bag in current_bags):
                    models = st.get(STATE_MODELS) or []
                    if not models or models[-1].get("model_name") != st.get(CURRENT_MODEL):
                        models.append({"model_name": st.get(CURRENT_MODEL), "colors": {}})
                    models[-1]["colors"][st.get(CURRENT_COLOR)] = current_bags
                    st[STATE_MODELS] = models
                
                # Clear current state
                st[CURRENT_COLOR] = None
                st[CURRENT_BAGS] = []
                st[CURRENT_BAG_INDEX] = 0
                st[AWAITING_SIZE] = None

                # Proceed to dates or summary
                if not st.get(STATE_SHIP_DATE):
                    st[STATE_STEP] = STEP_SHIPDATE
                    user_data.update_user_data(uid, STATE_KEY, st)
                    try:
                        bot.edit_message_text("Введите дату отправки, пример (дд.мм.гггг или дд/мм/гггг):",
                                              call.message.chat.id, call.message.message_id)
                    except Exception as e:
                        logger.warning(f"Failed to edit message for user {uid}: {e}")
                        bot.send_message(call.message.chat.id, "Введите дату отправки, пример (дд.мм.гггг или дд/мм/гггг):")
                elif not st.get(STATE_ETA_DATE):
                    st[STATE_STEP] = STEP_ETADATE
                    user_data.update_user_data(uid, STATE_KEY, st)
                    try:
                        bot.edit_message_text("Введите примерную дату прибытия, пример (дд.мм.гггг или дд/мм/гггг):",
                                              call.message.chat.id, call.message.message_id)
                    except Exception as e:
                        logger.warning(f"Failed to edit message for user {uid}: {e}")
                        bot.send_message(call.message.chat.id, "Введите примерную дату прибытия, пример (дд.мм.гггг или дд/мм/гггг):")
                else:
                    st[STATE_STEP] = STEP_CONFIRM
                    user_data.update_user_data(uid, STATE_KEY, st)
                    try:
                        bot.edit_message_text(_format_confirmation(st), call.message.chat.id, call.message.message_id,
                                              reply_markup=_kb_finish_models())
                    except Exception as e:
                        logger.warning(f"Failed to edit message for user {uid}: {e}")
                        bot.send_message(call.message.chat.id, _format_confirmation(st), reply_markup=_kb_finish_models())
                return
                
        except Exception as e:
            logger.error(f"Error in on_sizepad for user {uid}: {e}")
            bot.answer_callback_query(call.id, "❌ Произошла ошибка. Попробуйте позже.")

    # Final action callbacks
    @bot.callback_query_handler(func=lambda c: c.data in {"ship_add_model", "ship_cancel", "ship_finish_all"})
    def on_actions(call):
        uid = call.from_user.id
        try:
            st = user_data.get_user_data(uid).get(STATE_KEY)
            if not st:
                bot.answer_callback_query(call.id, "Сессия истекла. Начните заново с /save")
                try:
                    bot.edit_message_text("Сессия не найдена. Начните заново командой /save",
                                          call.message.chat.id, call.message.message_id)
                except Exception:
                    bot.send_message(call.message.chat.id, "Сессия не найдена. Начните заново командой /save")
                return

            bot.answer_callback_query(call.id)
            data = call.data

            if data == "ship_cancel":
                user_data.update_user_data(uid, STATE_KEY, None)
                try:
                    bot.edit_message_text("✖️ Процесс отменён.", call.message.chat.id, call.message.message_id)
                except Exception:
                    bot.send_message(call.message.chat.id, "✖️ Процесс отменён.")
                return

            if data == "ship_add_model":
                # Ask next model
                st[CURRENT_MODEL] = None
                st[STATE_STEP] = STEP_MODEL
                user_data.update_user_data(uid, STATE_KEY, st)
                try:
                    bot.edit_message_text("Пожалуйста, введите название модели в пакете (только одну модель за раз):",
                                          call.message.chat.id, call.message.message_id)
                except Exception:
                    bot.send_message(call.message.chat.id, "Пожалуйста, введите название модели в пакете (только одну модель за раз):")
                return

            if data == "ship_finish_all":
                # Validate shipment integrity before saving
                try:
                    shipment_id = user_data.get_user_data(uid).get("current_shipment_id", "1")
                    integrity_check = _validate_shipment_integrity(shipment_id)
                    logger.info(f"Shipment {shipment_id} integrity check: {integrity_check}")
                except Exception as e:
                    logger.error(f"Error validating shipment integrity: {e}")

                # Save every (model × color × bag) row
                try:
                    saved = 0
                    errors = 0
                    src_username = call.from_user.username or call.from_user.first_name or str(call.from_user.id)
                    shipment_id = user_data.get_user_data(uid).get("current_shipment_id", "1")
                    warehouse_name = st.get(STATE_WAREHOUSE)
                    ship_date = st.get(STATE_SHIP_DATE)
                    eta_date = st.get(STATE_ETA_DATE)

                    for item in st.get(STATE_MODELS, []):
                        model_name = item.get("model_name")
                        for color, bags in (item.get("colors") or {}).items():
                            for bag in bags:
                                try:
                                    bag_id = bag.get('bag_id')
                                    sizes = bag.get('sizes', {})
                                    total_amount = sum(int(v or 0) for v in sizes.values())
                                    
                                    # Skip empty bags
                                    if total_amount == 0:
                                        logger.debug(f"Skipping empty bag {bag_id}")
                                        continue
                                    
                                    # Initialize form data
                                    user_data.initialize_form_data(uid)
                                    user_data.update_form_data(uid, 'shipment_id', shipment_id)
                                    user_data.update_form_data(uid, 'bag_id', bag_id)
                                    user_data.update_form_data(uid, 'warehouse', warehouse_name)
                                    user_data.update_form_data(uid, 'product_name', model_name)
                                    user_data.update_form_data(uid, 'color', color)
                                    user_data.update_form_data(uid, 'shipment_date', ship_date)
                                    user_data.update_form_data(uid, 'estimated_arrival', eta_date)
                                    user_data.update_form_data(uid, 'actual_arrival', '')
                                    user_data.update_form_data(uid, 'total_amount', total_amount)
                                    user_data.update_form_data(uid, 'status', 'в обработке')
                                    
                                    # Set size quantities
                                    for sz, qty in sizes.items():
                                        user_data.update_form_data(uid, sz, int(qty))
                                    
                                    # Save to sheets
                                    row_index = save_to_sheets(bot, call.message)
                                    
                                    # Notify admins
                                    try:
                                        _notify_admins_about_new_record(bot, row_index, src_username)
                                    except Exception as notify_error:
                                        logger.warning(f"Failed to notify admins about new record: {notify_error}")
                                    
                                    saved += 1
                                    logger.info(f"Successfully saved record for bag {bag_id}")
                                    
                                except Exception as save_error:
                                    errors += 1
                                    logger.error(f"Error saving bag {bag.get('bag_id', 'unknown')}: {save_error}")
                                    continue

                    # Final status message
                    if errors == 0:
                        success_message = f"✅ Данные сохранены успешно. Создано записей: {saved}"
                        logger.info(f"Shipment {shipment_id} saved successfully: {saved} records")
                    else:
                        success_message = f"⚠️ Сохранено записей: {saved}. Ошибок: {errors}. Обратитесь к администратору."
                        logger.warning(f"Shipment {shipment_id} saved with errors: {saved} successful, {errors} failed")

                    try:
                        bot.edit_message_text(success_message, call.message.chat.id, call.message.message_id)
                    except Exception:
                        bot.send_message(call.message.chat.id, success_message)
                        
                except Exception as e:
                    logger.error(f"Critical error saving shipment for user {uid}: {e}")
                    error_message = f"⌫ Ошибка при сохранении данных: {e}"
                    try:
                        bot.edit_message_text(error_message, call.message.chat.id, call.message.message_id)
                    except Exception:
                        bot.send_message(call.message.chat.id, error_message)
                finally:
                    # Always clean up user state
                    user_data.update_user_data(uid, STATE_KEY, None)
                return
                
        except Exception as e:
            logger.error(f"Error in on_actions for user {uid}: {e}")
            bot.answer_callback_query(call.id, "❌ Произошла ошибка. Попробуйте позже.")

    # Cancel command
    @bot.message_handler(commands=['cancel'])
    def cancel_save_process(message):
        uid = message.from_user.id
        try:
            if user_data.get_user_data(uid) and user_data.get_user_data(uid).get(STATE_KEY):
                user_data.update_user_data(uid, STATE_KEY, None)
                bot.reply_to(message, "✖️ Процесс отменён.")
            else:
                bot.reply_to(message, "Нет активного процесса для отмены.")
        except Exception as e:
            logger.error(f"Error in cancel_save_process for user {uid}: {e}")
            bot.reply_to(message, "❌ Ошибка при отмене процесса.")
            
    # Warehouse selection callback
    @bot.callback_query_handler(func=lambda c: c.data.startswith("wh_"))
    def on_choose_warehouse(call):
        uid = call.from_user.id
        try:
            st = user_data.get_user_data(uid).get(STATE_KEY) if user_data.get_user_data(uid) else None
            if not st or st.get(STATE_STEP) != STEP_WAREHOUSE:
                bot.answer_callback_query(call.id, "Сессия истекла. Начните заново с /save")
                return

            warehouse = call.data[3:]  # after "wh_"
            st[STATE_WAREHOUSE] = warehouse
            st[STATE_STEP] = STEP_MODEL
            user_data.update_user_data(uid, STATE_KEY, st)

            bot.answer_callback_query(call.id)
            try:
                bot.edit_message_text(
                    f"✅ Склад выбран: {warehouse}\n\nПожалуйста, введите название модели в пакете (только одну модель за раз):",
                    call.message.chat.id,
                    call.message.message_id
                )
            except Exception as e:
                logger.warning(f"Failed to edit message for user {uid}: {e}")
                bot.send_message(
                    call.message.chat.id,
                    f"✅ Склад выбран: {warehouse}\n\nПожалуйста, введите название модели в пакете (только одну модель за раз):"
                )
        except Exception as e:
            logger.error(f"Error in on_choose_warehouse for user {uid}: {e}")
            bot.answer_callback_query(call.id, "❌ Произошла ошибка при выборе склада.")