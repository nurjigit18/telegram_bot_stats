# handlers/save.py — warehouse-centric shipment flow with bag_id and new columns
# -*- coding: utf-8 -*-

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from models.user_data import user_data
from utils.google_sheets import save_to_sheets, GoogleSheetsManager
from utils.validators import validate_date, standardize_date
from datetime import datetime
import pytz
import re
import logging
import secrets

logger = logging.getLogger(__name__)

# ===================== Parsing utilities (colors → sizes) ====================
SIZE_MAP = {
    'XS':'XS','S':'S','M':'M','L':'L','XL':'XL','XXL':'XXL',
    '2XL':'2XL','3XL':'3XL','4XL':'4XL','5XL':'5XL','6XL':'6XL','7XL':'7XL',
    # Cyrillic equivalents
    'ХС':'XS','С':'S','М':'M','Л':'L','ХЛ':'XL',
    'ХХL':'XXL','ХXL':'XXL',  # tolerant XXL variants
    '2ХЛ':'2XL','3ХЛ':'3XL','4ХЛ':'4XL','5ХЛ':'5XL','6ХЛ':'6XL','7ХЛ':'7XL',
    # Optional synonym
    'XXXL':'3XL'
}

DASH_PATTERN = r"[-–—:]"
SIZE_PAIR_RE = re.compile(rf"([A-Za-zА-Яа-я0-9]+)\s*{DASH_PATTERN}\s*(\d+)")
COLOR_BLOCK_RE = re.compile(r"(?P<color>[^,:;\n]+?)\s*:\s*(?P<sizes>.*?)(?=(?:[^,:;\n]+?\s*:)|$)")


def _normalize_colors_input(s: str) -> str:
    if not s:
        return ''
    s = s.strip()
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"\s*;\s*", "; ", s)
    s = s.replace('—','-').replace('–','-')
    # Unstick pairs like "S-10M-20" -> "S-10 M-20"
    prev = None
    for _ in range(20):
        if prev == s:
            break
        prev = s
        s = re.sub(r"([A-Za-zА-Яа-я0-9]+)-(\d+)([A-Za-zА-Яа-я0-9]+)-(\d+)", r"\1-\2 \3-\4", s)
    return s


def _canon_size(raw: str):
    key = raw.strip().upper()
    return SIZE_MAP.get(key, key if key in SIZE_MAP.values() else None)


def parse_colors_and_sizes(input_text: str):
    """Parse 'Цвет: size-qty …, Цвет2: …' into { color: {size: qty} }.
       Returns (data: dict, errors: list[str], normalized_preview: str)"""
    errors = []
    if not input_text or not input_text.strip():
        return None, ["Строка с расцветками пуста."], ''

    text = _normalize_colors_input(input_text)
    result = {}

    for m in COLOR_BLOCK_RE.finditer(text):
        color = m.group('color').strip()
        sizes_str = m.group('sizes').strip()
        if not color:
            errors.append("Найден пустой заголовок расцветки (до двоеточия).")
            continue

        size_map = {}
        for size_raw, qty_raw in SIZE_PAIR_RE.findall(sizes_str):
            c = _canon_size(size_raw)
            if not c:
                errors.append(f"Неизвестный размер ‘{size_raw}’ у ‘{color}’. Пропущено.")
                continue
            try:
                q = int(qty_raw)
                if q <= 0:
                    errors.append(f"Невалидное количество для {c} у ‘{color}’: {qty_raw}. Пропущено.")
                    continue
            except ValueError:
                errors.append(f"Невалидное количество для {c} у ‘{color}’: {qty_raw}. Пропущено.")
                continue
            size_map[c] = size_map.get(c, 0) + q

        if not size_map:
            errors.append(f"Не найдено валидных пар размер-количество для ‘{color}’.")
        else:
            result[color] = size_map

    if not result:
        return None, errors or ["Не удалось распознать ни одной расцветки."], ''

    # Build normalized preview
    order = {"XS":0,"S":1,"M":2,"L":3,"XL":4,"XXL":5}
    def size_key(k: str):
        if k in order: return (0, order[k])
        if k.endswith("XL") and k[:-2].isdigit():  # 2XL..7XL
            return (1, int(k[:-2]))
        return (2, 0)

    parts = []
    for color, smap in result.items():
        pairs = [f"{k}-{smap[k]}" for k in sorted(smap.keys(), key=size_key)]
        parts.append(f"{color}: " + " ".join(pairs))
    preview = ", ".join(parts)
    return result, errors, preview

# ===================== Conversation state keys ==============================
STATE_KEY = "shipment_state"
STATE_STEP = "step"
STATE_WAREHOUSE = "warehouse"
STATE_MODELS = "models"            # list[{model_name, colors{color:{size:qty}}}]
STATE_SHIP_DATE = "ship_date"
STATE_ETA_DATE = "eta_date"
CURRENT_MODEL = "current_model"

STEP_WAREHOUSE = "ask_warehouse"
STEP_MODEL = "ask_model"
STEP_COLORS = "ask_colors"
STEP_SHIPDATE = "ask_shipdate"
STEP_ETADATE = "ask_etadate"
STEP_CONFIRM = "confirm"

# ===================== Helpers ==============================================

def _kb_confirm():
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("💾 Сохранить данные", callback_data="ship_save_all"))
    m.add(InlineKeyboardButton("➕ Добавить модель", callback_data="ship_add_model"))
    m.add(InlineKeyboardButton("❌ Отмена", callback_data="ship_cancel"))
    return m


def _format_confirmation(state: dict) -> str:
    wh = state.get(STATE_WAREHOUSE, "—")
    ship = state.get(STATE_SHIP_DATE, "—")
    eta = state.get(STATE_ETA_DATE, "—")

    lines = [
        "Проверьте правильность данных:",
        f"Склад: {wh}",
    ]
    total_all = 0

    for item in state.get(STATE_MODELS, []):
        model = item.get("model_name", "—")
        colors = item.get("colors", {})
        color_parts = []
        for color, sizes in colors.items():
            qty = sum(sizes.values())
            total_all += qty
            spairs = " ".join([f"{k}-{v}" for k, v in sizes.items()])
            color_parts.append(f"{color}: {spairs}")
        color_preview = ", ".join(color_parts) if color_parts else "—"
        lines.append(f"Модель: {model}")
        lines.append(f"Расцветки и размеры: {color_preview}")
        lines.append("")

    lines.append(f"📊 Общее количество: {total_all} шт")
    lines.append(f"Дата отправки: {ship}")
    lines.append(f"Дата прибытия (примерное): {eta}")

    return "\n".join(lines)


def _new_bag_id(user_id: int) -> str:
    """Generate a unique bag/shipment ID"""
    return f"BAG-{secrets.token_hex(3)}"


def _notify_admins_about_new_record(bot: TeleBot, row_index: int, source_username: str):
    """Notify admins using the new column indexes."""
    try:
        sheets_manager = GoogleSheetsManager.get_instance()
        ws = sheets_manager.get_main_worksheet()
        record = ws.row_values(row_index)

        # Column indexes with your schema
        # 0:timestamp 1:user_id 2:username 3:bag_id 4:warehouse 5:product_name 6:color
        # 7:shipment_date 8:estimated_arrival 9:actual_arrival 10:total_amount
        # 11:XS 12:S 13:M 14:L 15:XL 16:XXL 17:2XL 18:3XL 19:4XL 20:5XL 21:6XL 22:7XL
        # 23:Статус
        try:
            product_name = record[5]
        except Exception:
            product_name = "-"
        try:
            color = record[6]
        except Exception:
            color = "-"
        try:
            shipment = record[7]
        except Exception:
            shipment = "-"
        try:
            eta = record[8]
        except Exception:
            eta = "-"
        try:
            warehouse = record[4]
        except Exception:
            warehouse = "-"
        try:
            total_amt = record[10]
        except Exception:
            total_amt = "0"
        try:
            bag_id = record[3]
        except Exception:
            bag_id = "-"
        status = record[23] if len(record) > 23 else "-"

        size_map_idx = {
            11:'XS', 12:'S', 13:'M', 14:'L', 15:'XL', 16:'XXL',
            17:'2XL', 18:'3XL', 19:'4XL', 20:'5XL', 21:'6XL', 22:'7XL'
        }
        sizes_text = []
        for idx, name in size_map_idx.items():
            if len(record) > idx and record[idx] and str(record[idx]).strip() not in ("", "0"):
                sizes_text.append(f"{name}({record[idx]})")
        sizes_text = ", ".join(sizes_text) if sizes_text else "—"

        text = (
            f"🆕 Новая запись добавлена в таблицу\n\n"
            f"Пользователь: @{source_username}\n"
            f"Пакет: {bag_id}\n"
            f"Склад: {warehouse}\n"
            f"Изделие: {product_name}\n"
            f"Цвет: {color}\n"
            f"Дата отправки: {shipment}\n"
            f"Примерная дата прибытия: {eta}\n"
            f"Общее количество: {total_amt}\n"
            f"Размеры: {sizes_text}\n"
            f"Статус: {status}\n"
            f"Дата добавления: {datetime.now(pytz.timezone('Asia/Bishkek')).strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # Resolve admin chat ids
        try:
            users_ws = sheets_manager.get_users_worksheet()
            all_users = users_ws.get_all_values()
        except Exception:
            all_users = []

        from config import ADMIN_USER_USERNAMES
        for admin_username in ADMIN_USER_USERNAMES:
            admin_chat_id = None
            for row in all_users[1:]:
                if len(row) > 1 and row[1] == admin_username:
                    try:
                        admin_chat_id = int(row[0])
                        break
                    except Exception:
                        pass
            if admin_chat_id:
                try:
                    bot.send_message(admin_chat_id, text)
                except Exception as e:
                    logger.warning(f"Failed to notify admin {admin_username}: {e}")
    except Exception as e:
        logger.error(f"Admin notify error: {e}")


# ===================== Main handler (replaces previous /save) ===============

def setup_save_handler(bot: TeleBot):
    @bot.message_handler(commands=['save'])
    def start_flow(message):
        uid = message.from_user.id
        user_data.initialize_user(uid)
        # Generate per-session bag_id
        bag_id = _new_bag_id(uid)
        user_data.update_user_data(uid, "current_bag_id", bag_id)
        save_text = ("""Пожалуйста введите данные об отправке пакета. Форма предназначена для одной модели с несколькими расцветками и размерами. Введите данные по порядку. Вы можете добавить модели по очереди.

Нажмите /cancel для отмены

Пожалуйста, введите склад:""")
        bot.reply_to(message, save_text)
        
        st = {
            STATE_STEP: STEP_WAREHOUSE,
            STATE_WAREHOUSE: None,
            STATE_MODELS: [],
            STATE_SHIP_DATE: None,
            STATE_ETA_DATE: None,
        }
        user_data.update_user_data(uid, STATE_KEY, st)

    @bot.message_handler(func=lambda m: user_data.get_user_data(m.from_user.id) and user_data.get_user_data(m.from_user.id).get(STATE_KEY) is not None)
    def handle_text(message):
        uid = message.from_user.id
        st = user_data.get_user_data(uid).get(STATE_KEY, {})
        step = st.get(STATE_STEP)
        text = (message.text or '').strip()

        # Allow cancel
        if text.lower() in {"/cancel", "отмена"}:
            user_data.update_user_data(uid, STATE_KEY, None)
            bot.reply_to(message, "✖️ Процесс отменён.")
            return

        if step == STEP_WAREHOUSE:
            if not text:
                bot.reply_to(message, "Склад не может быть пустым. Введите склад:")
                return
            st[STATE_WAREHOUSE] = text
            st[STATE_STEP] = STEP_MODEL
            user_data.update_user_data(uid, STATE_KEY, st)
            bot.reply_to(message, "Пожалуйста, введите название модели в пакете (только одну за раз):")
            return

        if step == STEP_MODEL:
            if not text:
                bot.reply_to(message, "Название модели не может быть пустым. Введите модель:")
                return
            st[CURRENT_MODEL] = text
            st[STATE_STEP] = STEP_COLORS
            user_data.update_user_data(uid, STATE_KEY, st)
            bot.reply_to(message, "Пожалуйста введите размеры на каждую расцветку, пример: Шоколад: S-10 XL-10 3XL-20, Красный: M-10 xl-20")
            return

        if step == STEP_COLORS:
            colors, errs, preview = parse_colors_and_sizes(text)
            if not colors:
                err = "\n".join(["❌ Ошибки распознавания:"] + errs + ["\nПовторите ввод расцветок и размеров по примеру."])
                bot.reply_to(message, err)
                return
            st.setdefault(STATE_MODELS, []).append({
                "model_name": st.get(CURRENT_MODEL),
                "colors": colors,
            })
            if not st.get(STATE_SHIP_DATE):
                st[STATE_STEP] = STEP_SHIPDATE
                user_data.update_user_data(uid, STATE_KEY, st)
                bot.reply_to(message, "Введите дату отправки, пример (дд.мм.гггг или дд/мм/гггг):")
                return
            st[STATE_STEP] = STEP_CONFIRM
            user_data.update_user_data(uid, STATE_KEY, st)
            bot.send_message(message.chat.id, _format_confirmation(st), reply_markup=_kb_confirm())
            return

        if step == STEP_SHIPDATE:
            if not validate_date(text):
                bot.reply_to(message, "❌ Некорректный формат даты. Используйте дд.мм.гггг или дд/мм/гггг")
                return
            st[STATE_SHIP_DATE] = standardize_date(text)
            st[STATE_STEP] = STEP_ETADATE
            user_data.update_user_data(uid, STATE_KEY, st)
            bot.reply_to(message, "Введите примерную дату отправки, пример (дд.мм.гггг или дд/мм/гггг):")
            return

        if step == STEP_ETADATE:
            if not validate_date(text):
                bot.reply_to(message, "❌ Некорректный формат даты. Используйте дд.мм.гггг или дд/мм/гггг")
                return
            st[STATE_ETA_DATE] = standardize_date(text)
            st[STATE_STEP] = STEP_CONFIRM
            user_data.update_user_data(uid, STATE_KEY, st)
            bot.send_message(message.chat.id, _format_confirmation(st), reply_markup=_kb_confirm())
            return

        if step == STEP_CONFIRM:
            bot.send_message(message.chat.id, "Пожалуйста, используйте кнопки ниже.", reply_markup=_kb_confirm())
            return

    @bot.callback_query_handler(func=lambda c: c.data in {"ship_save_all","ship_add_model","ship_cancel"})
    def on_cb(call):
        uid = call.from_user.id
        st = user_data.get_user_data(uid).get(STATE_KEY)
        if not st:
            bot.answer_callback_query(call.id)
            try:
                bot.edit_message_text("Сессия не найдена. Начните заново командой /save", call.message.chat.id, call.message.message_id)
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
            st.pop(CURRENT_MODEL, None)
            st[STATE_STEP] = STEP_MODEL
            user_data.update_user_data(uid, STATE_KEY, st)
            try:
                bot.edit_message_text("Пожалуйста, введите название модели в пакете (только одну за раз):", call.message.chat.id, call.message.message_id)
            except Exception:
                bot.send_message(call.message.chat.id, "Пожалуйста, введите название модели в пакете (только одну за раз):")
            return

        if data == "ship_save_all":
            try:
                saved = 0
                src_username = call.from_user.username or call.from_user.first_name or str(call.from_user.id)
                bag_id = user_data.get_user_data(uid).get("current_bag_id", "")
                warehouse_name = st.get(STATE_WAREHOUSE)
                ship_date = st.get(STATE_SHIP_DATE)
                eta_date = st.get(STATE_ETA_DATE)

                for item in st.get(STATE_MODELS, []):
                    model_name = item.get("model_name")
                    for color, sizes in item.get("colors", {}).items():
                        total_amount = sum(sizes.values())
                        # Prepare form_data for save_to_sheets
                        user_data.initialize_form_data(uid)
                        user_data.update_form_data(uid, 'bag_id', bag_id)
                        user_data.update_form_data(uid, 'warehouse', warehouse_name)
                        user_data.update_form_data(uid, 'product_name', model_name)
                        user_data.update_form_data(uid, 'color', color)
                        user_data.update_form_data(uid, 'shipment_date', ship_date)
                        user_data.update_form_data(uid, 'estimated_arrival', eta_date)
                        user_data.update_form_data(uid, 'actual_arrival', '')
                        user_data.update_form_data(uid, 'total_amount', total_amount)
                        user_data.update_form_data(uid, 'status', 'в обработке')
                        for sz, qty in sizes.items():
                            user_data.update_form_data(uid, sz, qty)
                        row_index = save_to_sheets(bot, call.message)
                        _notify_admins_about_new_record(bot, row_index, src_username)
                        saved += 1

                try:
                    bot.edit_message_text(f"✅ Данные сохранены. Создано записей: {saved}", call.message.chat.id, call.message.message_id)
                except Exception:
                    bot.send_message(call.message.chat.id, f"✅ Данные сохранены. Создано записей: {saved}")
            except Exception as e:
                logger.error(f"Error saving shipment: {e}")
                try:
                    bot.edit_message_text(f"❌ Ошибка при сохранении данных: {e}", call.message.chat.id, call.message.message_id)
                except Exception:
                    bot.send_message(call.message.chat.id, f"❌ Ошибка при сохранении данных: {e}")
            finally:
                user_data.update_user_data(uid, STATE_KEY, None)
            return

    @bot.message_handler(commands=['cancel'])
    def cancel_save_process(message):
        uid = message.from_user.id
        if user_data.get_user_data(uid) and user_data.get_user_data(uid).get(STATE_KEY):
            user_data.update_user_data(uid, STATE_KEY, None)
            bot.reply_to(message, "✖️ Процесс отменён.")
        else:
            bot.reply_to(message, "Нет активного процесса для отмены.")
