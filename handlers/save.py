from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from models.user_data import user_data
from models.factory_data import factory_manager
from handlers.factory_selection import prompt_factory_selection, handle_factory_selection
from utils.google_sheets import GoogleSheetsManager, SIZE_COLS
from utils.validators import validate_date, standardize_date
from utils.factory_helpers import _new_shipment_id_for_factory, _generate_bag_id_factory
from utils.formatting_helpers import _format_bag_preview, _format_confirmation
from datetime import datetime
import pytz
import logging
import secrets
import time
import threading
from typing import Optional, Tuple, Dict, List

logger = logging.getLogger(__name__)

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

# ===================== Keyboard Helpers ==================================

def _kb_warehouses_for_factory(factory_tab_name: str) -> InlineKeyboardMarkup:
    """Inline keyboard to choose a warehouse for specific factory."""
    try:
        # Get factory-specific warehouses
        warehouses = factory_manager.get_factory_warehouses(factory_tab_name)
        
        m = InlineKeyboardMarkup(row_width=3)
        buttons = [InlineKeyboardButton(w, callback_data=f"wh_{w}") for w in warehouses]
        
        # Add buttons in rows of 3
        for i in range(0, len(buttons), 3):
            row = buttons[i:i+3]
            m.row(*row)
        
        return m
        
    except Exception as e:
        logger.error(f"Error creating warehouse keyboard for factory {factory_tab_name}: {e}")
        # Fallback to default warehouses
        default_warehouses = [
            "Казань", "Краснодар", "Электросталь", "Коледино",
            "Тула", "Невинномысск", "Рязань", "Новосибирск", 
            "Алматы", "Котовск"
        ]
        m = InlineKeyboardMarkup(row_width=3)
        buttons = [InlineKeyboardButton(w, callback_data=f"wh_{w}") for w in default_warehouses]
        for i in range(0, len(buttons), 3):
            row = buttons[i:i+3]
            m.row(*row)
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
    m.add(InlineKeyboardButton("❌ Отмена", callback_data="ship_cancel"))
    return m



def _notify_admins_about_new_record_factory(bot: TeleBot, row_index: int, source_username: str, factory_name: str, tab_name: str):
    """Notify admins using updated column schema with shipment_id and bag_id for factory"""
    try:
        worksheet = factory_manager.get_factory_worksheet(tab_name)
        record = worksheet.row_values(row_index)

        # Create header mapping for factory worksheet
        headers = worksheet.row_values(1)
        hi = {header: idx for idx, header in enumerate(headers)}

        def get(name, default="-"):
            idx = hi.get(name)
            if idx is not None and len(record) > idx:
                return record[idx]
            return default

        product_name = get('модель')
        color = get('цвет')
        shipment = get('дата отправки')
        eta = get('примерная дата прибытия')
        warehouse = get('склад')
        total_amt = get('Общее количество', "0")
        shipment_id = get('номер отправки')
        bag_id = get('номер пакета')
        status = get('Статус')

        sizes_text = []
        for k in SIZE_COLS:
            val = get(k)
            if val and str(val).strip() not in ("", "0"):
                sizes_text.append(f"{k}({val})")
        sizes_text = ", ".join(sizes_text) if sizes_text else "—"

        text = (
            f"🆕 Новая запись добавлена в фабрику {factory_name}\n\n"
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
            sheets_manager = GoogleSheetsManager.get_instance()
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
        logger.error(f"Admin notify error for factory {factory_name}: {e}")

def save_to_sheets_factory(bot, message):
    """
    Append one row to the factory worksheet using data from user_data.form_data.
    Returns the row index (int) of the row that was appended.
    """
    try:
        # Derive user_id and username from the chat
        user_id = getattr(getattr(message, "chat", None), "id", None)
        if user_id is None:
            user_id = getattr(getattr(message, "from_user", None), "id", None)

        if user_id is None:
            raise ValueError("Unable to determine user_id from message/chat.")

        # Get current factory info
        current_factory = user_data.get_user_data(user_id).get("current_factory")
        if not current_factory:
            raise ValueError("No factory selected for this session.")

        # Get factory-specific worksheet
        worksheet = factory_manager.get_factory_worksheet(current_factory['tab_name'])

        chat_username = getattr(getattr(message, "chat", None), "username", None)
        from_username = getattr(getattr(message, "from_user", None), "username", None)
        first_name = getattr(getattr(message, "from_user", None), "first_name", None)
        username = chat_username or from_username or first_name or str(user_id)

        form_data = user_data.get_form_data(user_id)
        if not form_data or not isinstance(form_data, dict):
            logger.error(f"No form data found for user_id: {user_id}")
            bot.send_message(message.chat.id, "❌ Данные пользователя не найдены. Повторите ввод.")
            raise RuntimeError("Form data missing")

        # Ensure headers are present in factory worksheet
        from utils.google_sheets import EXPECTED_HEADERS
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
            form_data.get('shipment_id', ''),  # NEW: shipment ID
            form_data.get('bag_id', ''),       # NEW: bag ID
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

        logger.info(f"Saved row #{last_row} for user {username} (ID {user_id}) to factory {current_factory['name']}")
        try:
            bot.send_message(message.chat.id, f"✅ Данные сохранены в фабрику {current_factory['name']}!")
        except Exception:
            pass

        # Persist the last row index for admin notifications
        user_data.set_row_index(user_id, last_row)
        return last_row

    except Exception as e:
        logger.error(f"Error in save_to_sheets_factory: {e}")
        raise

# ===================== Entry point ==========================================

def setup_save_handler(bot: TeleBot):
    """Set up save handler with factory support - FIXED VERSION"""

    @bot.message_handler(commands=['save'])
    def start_flow(message):
        """Start save flow with factory selection - FIXED"""
        uid = message.from_user.id
        
        # Set pending action for factory selection
        user_data.initialize_user(uid)
        user_data.update_user_data(uid, "pending_action", "save")
        
        logger.info(f"User {uid} started save flow")
        
        # First, prompt for factory selection
        should_wait_for_selection = prompt_factory_selection(bot, message, "save")
        
        if should_wait_for_selection:
            # Either factory selection menu was shown, or user has no factories
            logger.info(f"User {uid}: Waiting for factory selection or has no factories")
            return
        
        # If we reach here, user has only one factory and it was auto-selected
        logger.info(f"User {uid}: Single factory auto-selected, continuing with save flow")
        
        # Get the auto-selected factory from user data
        factory_info = user_data.get_user_data(uid).get("selected_factory")
        
        if not factory_info:
            logger.error(f"User {uid}: Factory should have been auto-selected but not found in user data")
            bot.send_message(message.chat.id, "❌ Ошибка при автовыборе фабрики. Попробуйте позже.")
            return
        
        logger.info(f"User {uid}: Starting save flow with factory {factory_info['name']}")
        start_save_flow_with_factory(bot, message, uid)
        
    def generate_shipment_id(factory_tab_name):
        """Generate unique shipment ID for factory - Column D (index 3)"""
        try:
            logger.info(f"Generating new shipment ID for factory {factory_tab_name}...")
            
            # Get the factory worksheet
            worksheet = factory_manager.get_factory_worksheet(factory_tab_name)
            all_data = worksheet.get_all_values()
            
            if len(all_data) <= 1:  # Only headers or empty
                logger.info(f"Factory sheet {factory_tab_name} is empty, starting with ID 1")
                return 1
            
            logger.info(f"Successfully retrieved {len(all_data)} rows from factory sheet {factory_tab_name}")
            
            max_id = 0
            for i, row in enumerate(all_data[1:], start=2):  # Skip header
                if row and len(row) > 3:  # Make sure column D exists
                    try:
                        shipment_id = int(row[3])  # Column D (index 3)
                        if shipment_id > 0:  # Valid positive ID
                            max_id = max(max_id, shipment_id)
                    except (ValueError, IndexError):
                        logger.warning(f"Invalid shipment ID '{row[3] if len(row) > 3 else 'missing'}' in row {i}, column D")
                        continue
            
            new_id = max_id + 1
            logger.info(f"Generated shipment ID: {new_id} for factory {factory_tab_name} (previous max: {max_id})")
            return new_id
            
        except Exception as e:
            logger.error(f"Error generating shipment ID for factory {factory_tab_name}: {e}")
            return 1


    def start_save_flow_with_factory(bot, message, override_user_id=None):
        """Start save flow after factory is selected - FIXED VERSION"""
        try:
            # CRITICAL FIX: Use override_user_id if provided (from callback context)
            user_id = override_user_id or message.from_user.id
            logger.info(f"User {user_id}: Starting save flow with factory")
            
            # Get the selected factory from user data
            user_session = user_data.get_user_data(user_id)
            if not user_session or "selected_factory" not in user_session:
                bot.send_message(message.chat.id, "❌ Фабрика не выбрана. Попробуйте снова.")
                logger.error(f"User {user_id}: No selected factory found")
                return
            
            factory_info = user_session["selected_factory"]
            logger.info(f"User {user_id}: Using factory info: {factory_info}")
            
            # Store factory info in current_factory for the save process
            user_data.update_user_data(user_id, "current_factory", factory_info)
            logger.info(f"User {user_id}: Set current_factory to {factory_info}")
            
            # Ensure the factory worksheet exists
            try:
                factory_manager.ensure_factory_worksheet(factory_info['tab_name'])
                logger.info(f"User {user_id}: Using existing factory worksheet {factory_info['tab_name']}")
            except Exception as e:
                logger.error(f"Error ensuring factory worksheet: {e}")
                bot.send_message(message.chat.id, f"❌ Ошибка доступа к фабрике {factory_info['name']}")
                return
            
            # Generate shipment ID for this specific factory
            try:
                shipment_id = _new_shipment_id_for_factory(factory_info['tab_name'])
                user_data.update_form_data(user_id, "shipment_id", shipment_id)
                logger.info(f"User {user_id}: Generated shipment ID {shipment_id} for factory {factory_info['name']}")
            except Exception as e:
                logger.error(f"Error generating shipment ID: {e}")
                bot.send_message(message.chat.id, "❌ Ошибка генерации ID поставки")
                return
            
            user_data.update_user_data(user_id, "current_shipment_id", str(shipment_id))
            # Initialize form data
            user_data.initialize_form_data(user_id)
            user_data.set_current_step(user_id, 1)
            
            # Start the warehouse selection
            # Start the warehouse selection using existing system
            st = {
                STATE_STEP: STEP_WAREHOUSE,
                STATE_MODELS: [],
                "current_shipment_id": str(shipment_id)  # Store shipment ID in state
            }
            user_data.update_user_data(user_id, STATE_KEY, st)

            def start_warehouse_selection_for_factory(bot, message, user_id, factory_info):
                """Start warehouse selection with factory-specific warehouses"""
                try:
                    factory_tab_name = factory_info['tab_name']
                    
                    # Get warehouses for this factory
                    warehouses = factory_manager.get_factory_warehouses(factory_tab_name)
                    
                    if not warehouses:
                        bot.send_message(
                            message.chat.id,
                            f"❌ Нет доступных складов для фабрики {factory_info['name']}. Обратитесь к администратору."
                        )
                        return False
                    
                    # Create keyboard with factory-specific warehouses
                    keyboard = _kb_warehouses_for_factory(factory_tab_name)
                    
                    bot.send_message(
                        message.chat.id,
                        f"🏭 Выберите склад для фабрики {factory_info['name']}:",
                        reply_markup=keyboard
                    )
                    
                    logger.info(f"Showed {len(warehouses)} warehouses for factory {factory_info['name']} to user {user_id}")
                    return True
                    
                except Exception as e:
                    logger.error(f"Error starting warehouse selection for factory {factory_info['name']}: {e}")
                    bot.send_message(
                        message.chat.id,
                        "❌ Ошибка загрузки складов. Попробуйте позже."
                    )
                    return False
            
            if not start_warehouse_selection_for_factory(bot, message, user_id, factory_info):
                return  # Error occurred, stop the flow

            logger.info(f"User {user_id}: Save flow started successfully")
            
        except Exception as e:
            logger.error(f"Error starting save flow for user {user_id}: {e}")
            
            bot.send_message(message.chat.id, "❌ Ошибка запуска процесса сохранения")
            
    # Factory selection callback handler for save
    @bot.callback_query_handler(func=lambda c: c.data.startswith("select_factory:"))
    def on_factory_selection_save(call):
        """Handle factory selection callbacks - FIXED USER CONTEXT"""
        try:
            # CRITICAL FIX: Always use call.from_user.id for callbacks
            user_id = call.from_user.id
            logger.info(f"Factory selection callback: user_id={user_id}, data={call.data}")
            
            user_session = user_data.get_user_data(user_id)
            
            if not user_session:
                bot.answer_callback_query(call.id, "Сессия не найдена")
                logger.error(f"No session found for user {user_id}")
                return
            
            pending_action = user_session.get("current_action")
            logger.info(f"Pending action for user {user_id}: {pending_action}")
            
            # Handle the factory selection with the CORRECT user_id
            factory_info = handle_factory_selection(bot, call, pending_action or "unknown")
            
            if factory_info:
                logger.info(f"Factory selected successfully: {factory_info}")
                
                if pending_action == "save":
                    # Update the message to show factory selection
                    try:
                        bot.edit_message_text(
                            f"✅ Выбрана фабрика: {factory_info['name']}\n\nНачинаем процесс сохранения...",
                            call.message.chat.id,
                            call.message.message_id
                        )
                    except Exception:
                        bot.send_message(call.message.chat.id, 
                                    f"✅ Выбрана фабрика: {factory_info['name']}\n\nНачинаем процесс сохранения...")
                    
                    # CRITICAL: Pass the correct user_id context
                    start_save_flow_with_factory(bot, call.message, user_id)
                
        except Exception as e:
            logger.error(f"Error in factory selection callback: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка")



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
                user_data.update_user_data(uid, "pending_action", None)
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
                    current_factory = user_data.get_user_data(uid).get("current_factory")
                    shipment_id = user_data.get_user_data(uid).get("current_shipment_id")
                    if not shipment_id:
                        # Fallback: get from form data
                        form_data = user_data.get_form_data(uid)
                        shipment_id = form_data.get('shipment_id') if form_data else "1"
                    bag_id = _generate_bag_id_factory(current_factory['tab_name'], shipment_id, 1)
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
                    bot.reply_to(message, "❌ Некорректный формат даты. Используйте дд.мм.гггг или дд/мм/гггг")
                    return
                st[STATE_SHIP_DATE] = standardize_date(text)
                st[STATE_STEP] = STEP_ETADATE
                user_data.update_user_data(uid, STATE_KEY, st)
                bot.reply_to(message, "Введите примерную дату прибытия, пример (дд.мм.гггг или дд/мм/гггг):")
                return

            if step == STEP_ETADATE:
                if not validate_date(text):
                    bot.reply_to(message, "❌ Некорректный формат даты. Используйте дд.мм.гггг или дд/мм/гггг")
                    return
                st[STATE_ETA_DATE] = standardize_date(text)
                st[STATE_STEP] = STEP_CONFIRM
                user_data.update_user_data(uid, STATE_KEY, st)
                
                # Get factory info for confirmation
                factory_info = user_data.get_user_data(uid).get("current_factory")
                factory_name = factory_info['name'] if factory_info else "Неизвестная фабрика"
                
                bot.send_message(message.chat.id, _format_confirmation(st, factory_name), reply_markup=_kb_finish_models())
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
                    current_factory = user_data.get_user_data(uid).get("current_factory")
                    shipment_id = user_data.get_user_data(uid).get("current_shipment_id", "1")
                    new_bag_number = len(current_bags) + 1
                    new_bag_id = _generate_bag_id_factory(current_factory['tab_name'], shipment_id, new_bag_number)
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
                    
                    # Get factory info for confirmation
                    factory_info = user_data.get_user_data(uid).get("current_factory")
                    factory_name = factory_info['name'] if factory_info else "Неизвестная фабрика"
                    
                    try:
                        bot.edit_message_text(_format_confirmation(st, factory_name), call.message.chat.id, call.message.message_id,
                                              reply_markup=_kb_finish_models())
                    except Exception as e:
                        logger.warning(f"Failed to edit message for user {uid}: {e}")
                        bot.send_message(call.message.chat.id, _format_confirmation(st, factory_name), reply_markup=_kb_finish_models())
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
                user_data.update_user_data(uid, "pending_action", None)
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
                # Save every (model × color × bag) row
                try:
                    saved = 0
                    errors = 0
                    src_username = call.from_user.username or call.from_user.first_name or str(call.from_user.id)
                    shipment_id = user_data.get_user_data(uid).get("current_shipment_id", "1")
                    factory_info = user_data.get_user_data(uid).get("current_factory")
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
                                    
                                    # Save to factory sheets
                                    row_index = save_to_sheets_factory(bot, call.message)
                                    
                                    # Notify admins
                                    try:
                                        _notify_admins_about_new_record_factory(bot, row_index, src_username, 
                                                                               factory_info['name'], factory_info['tab_name'])
                                    except Exception as notify_error:
                                        logger.warning(f"Failed to notify admins about new record: {notify_error}")
                                    
                                    saved += 1
                                    logger.info(f"Successfully saved record for bag {bag_id} to factory {factory_info['name']}")
                                    
                                except Exception as save_error:
                                    errors += 1
                                    logger.error(f"Error saving bag {bag.get('bag_id', 'unknown')}: {save_error}")
                                    continue

                    # Final status message
                    if errors == 0:
                        success_message = f"✅ Данные сохранены успешно в фабрику {factory_info['name']}. Создано записей: {saved}"
                        logger.info(f"Shipment {shipment_id} saved successfully to factory {factory_info['name']}: {saved} records")
                    else:
                        success_message = f"⚠️ Сохранено записей: {saved}. Ошибок: {errors}. Обратитесь к администратору."
                        logger.warning(f"Shipment {shipment_id} saved with errors to factory {factory_info['name']}: {saved} successful, {errors} failed")

                    try:
                        bot.edit_message_text(success_message, call.message.chat.id, call.message.message_id)
                    except Exception:
                        bot.send_message(call.message.chat.id, success_message)
                        
                except Exception as e:
                    logger.error(f"Critical error saving shipment for user {uid}: {e}")
                    error_message = f"❌ Ошибка при сохранении данных: {e}"
                    try:
                        bot.edit_message_text(error_message, call.message.chat.id, call.message.message_id)
                    except Exception:
                        bot.send_message(call.message.chat.id, error_message)
                finally:
                    # Always clean up user state
                    user_data.update_user_data(uid, STATE_KEY, None)
                    user_data.update_user_data(uid, "pending_action", None)
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
                user_data.update_user_data(uid, "pending_action", None)
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
            
    @bot.callback_query_handler(func=lambda c: c.data.startswith("warehouse_"))
    def on_warehouse_selection(call):
        """Handle warehouse selection - FIXED USER CONTEXT"""
        try:
            # CRITICAL FIX: Always use callback user_id
            user_id = call.from_user.id
            logger.info(f"Warehouse selection callback: user_id={user_id}, data={call.data}")
            
            # Validate user session exists
            user_session = user_data.get_user_data(user_id)
            if not user_session:
                bot.answer_callback_query(call.id, "Сессия истекла. Начните заново с /save")
                logger.error(f"No session found for user {user_id}")
                return
            
            # Check if user has current_factory set
            if "current_factory" not in user_session:
                bot.answer_callback_query(call.id, "Сессия истекла. Фабрика не выбрана.")
                logger.error(f"User {user_id}: No current_factory in session")
                return
            
            warehouse_map = {
                "warehouse_factory": "Фабричный склад",
                "warehouse_shipping": "Склад отправки", 
                "warehouse_central": "Центральный склад",
                "warehouse_retail": "Розничный склад"
            }
            
            warehouse_name = warehouse_map.get(call.data)
            if not warehouse_name:
                bot.answer_callback_query(call.id, "Неизвестный склад")
                return
            
            # Store warehouse selection for the correct user
            user_data.update_form_data(user_id, "warehouse", warehouse_name)
            
            bot.answer_callback_query(call.id, f"Выбран склад: {warehouse_name}")
            logger.info(f"User {user_id}: Selected warehouse: {warehouse_name}")
            
            # Update message
            try:
                bot.edit_message_text(
                    f"✅ Склад: {warehouse_name}\n\nТеперь введите название товара:",
                    call.message.chat.id,
                    call.message.message_id
                )
            except Exception:
                bot.send_message(call.message.chat.id, f"✅ Склад: {warehouse_name}\n\nТеперь введите название товара:")
            
            # Move to next step
            user_data.set_current_step(user_id, 2)
            
        except Exception as e:
            logger.error(f"Error in warehouse selection for user {user_id}: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка")
            