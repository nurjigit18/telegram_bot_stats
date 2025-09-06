# handlers/save.py — warehouse-centric shipment flow with bag_id + BUTTON sizes UI
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

logger = logging.getLogger(__name__)

# ===================== Conversation state keys ==============================
STATE_KEY = "shipment_state"
STATE_STEP = "step"

STATE_WAREHOUSE  = "warehouse"
STATE_MODELS     = "models"            # list[{model_name, colors{color:{size:qty}}}]
STATE_SHIP_DATE  = "ship_date"
STATE_ETA_DATE   = "eta_date"
CURRENT_MODEL    = "current_model"

# color building substate
CURRENT_COLOR        = "current_color"
CURRENT_COLOR_SIZES  = "current_color_sizes"  # dict size->qty
AWAITING_SIZE        = "awaiting_size"        # when expecting numeric amount for selected size

STEP_WAREHOUSE = "ask_warehouse"
STEP_MODEL     = "ask_model"
STEP_COLORNAME = "ask_color_name"
STEP_COLORSZ   = "ask_color_sizes"     # size keypad mode
STEP_SHIPDATE  = "ask_shipdate"
STEP_ETADATE   = "ask_etadate"
STEP_CONFIRM   = "confirm"

WAREHOUSES = [
    "Казань", "Краснодар", "Электросталь", "Коледино",
    "Тула", "Невинномысск", "Рязань", "Новосибирск", "Алматы"
]

# ===================== Helpers ==============================================
# --- sequential bag id generator (ID-000, ID-001, ...)
_bag_seq_counter = None  # lazy-initialized from Sheets

def _new_bag_id(_: int | None = None) -> str:
    """
    Generate sequential bag/shipment ID like ID-000, ID-001, ...
    Initializes from the max existing value in the 'bag_id' column (if present),
    then increments in memory for subsequent calls.
    The optional arg is ignored so existing calls _new_bag_id(uid) keep working.
    """
    global _bag_seq_counter
    if _bag_seq_counter is None:
        # Initialize from Google Sheets once
        try:
            sheets_manager = GoogleSheetsManager.get_instance()
            ws = sheets_manager.get_main_worksheet()

            # Find 'bag_id' header column (1-based index for gspread)
            headers = ws.row_values(1)
            bag_col_idx = headers.index('bag_id') + 1 if 'bag_id' in headers else None

            max_num = -1
            if bag_col_idx:
                for val in ws.col_values(bag_col_idx):
                    if isinstance(val, str) and val.startswith("ID-"):
                        try:
                            n = int(val.split("-", 1)[1])
                            if n > max_num:
                                max_num = n
                        except Exception:
                            pass
            _bag_seq_counter = max_num + 1
        except Exception:
            # If headers/Sheet not ready, start from 0; you can re-init later if needed
            _bag_seq_counter = 0

    bag_id = f"{_bag_seq_counter:03d}"
    _bag_seq_counter += 1
    return bag_id



def _kb_warehouses() -> InlineKeyboardMarkup:
    """Inline keyboard to choose a warehouse."""
    m = InlineKeyboardMarkup(row_width=3)
    buttons = [InlineKeyboardButton(w, callback_data=f"wh_{w}") for w in WAREHOUSES]
    # add() respects row_width
    m.add(*buttons)
    return m

def _kb_sizepad(current_color: str, sizes: dict) -> InlineKeyboardMarkup:
    """
    Inline keyboard with size buttons + control rows:
    - size buttons (✓ mark when filled)
    - ➕ Добавить расцветку
    - ✅ Закончить модель
    - 🗑 Очистить расцветку / ↩ Назад к моделям
    """
    m = InlineKeyboardMarkup()
    row = []
    for i, s in enumerate(SIZE_COLS, 1):
        mark = "✓" if sizes.get(s, 0) > 0 else ""
        row.append(InlineKeyboardButton(f"{s}{mark}", callback_data=f"cset_{s}"))
        if i % 4 == 0:
            m.row(*row)
            row = []
    if row:
        m.row(*row)

    # requested controls
    m.row(InlineKeyboardButton("➕ Добавить расцветку", callback_data="cadd_color"))
    m.row(InlineKeyboardButton("✅ Закончить модель", callback_data="cfinish_model"))

    # utility controls
    m.row(
        InlineKeyboardButton("🗑 Очистить расцветку", callback_data="cclr"),
        InlineKeyboardButton("↩ Назад к моделям", callback_data="cback"),
    )
    return m

def _kb_finish_models() -> InlineKeyboardMarkup:
    """Final summary controls: add another model or finish (save)."""
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("➕ Добавить модель", callback_data="ship_add_model"))
    m.add(InlineKeyboardButton("✅ Закончить пакет", callback_data="ship_finish_all"))
    m.add(InlineKeyboardButton("❌ Отмена", callback_data="ship_cancel"))
    return m

def _format_color_preview(color: str, sizes: dict) -> str:
    pairs = [f"{k}-{sizes[k]}" for k in SIZE_COLS if sizes.get(k, 0) > 0]
    body = " ".join(pairs) if pairs else "—"
    return f"Текущая расцветка: {color}\nРазмеры: {body}\n\n"

def _format_confirmation(state: dict) -> str:
    wh   = state.get(STATE_WAREHOUSE, "—")
    ship = state.get(STATE_SHIP_DATE, "—")
    eta  = state.get(STATE_ETA_DATE, "—")

    lines = ["Проверьте правильность данных:", f"Склад: {wh}"]
    total_all = 0
    for item in state.get(STATE_MODELS, []):
        model  = item.get("model_name", "—")
        colors = item.get("colors", {})
        lines.append(f"Модель: {model}")
        color_parts = []
        for color, sizes in colors.items():
            qty = sum(int(v or 0) for v in sizes.values())
            total_all += qty
            pairs = [f"{k}-{sizes.get(k,0)}" for k in SIZE_COLS if sizes.get(k,0) > 0]
            color_parts.append(f"{color}: " + (" ".join(pairs) if pairs else "—"))
        lines.append("Расцветки и размеры: " + (", ".join(color_parts) if color_parts else "—"))
        lines.append("")
    lines.append(f"📊 Общее количество: {total_all} шт")
    lines.append(f"Дата отправки: {ship}")
    lines.append(f"Дата прибытия (примерное): {eta}")
    return "\n".join(lines)

def _notify_admins_about_new_record(bot: TeleBot, row_index: int, source_username: str):
    """Notify admins using your current column schema."""
    try:
        sheets_manager = GoogleSheetsManager.get_instance()
        ws = sheets_manager.get_main_worksheet()
        record = ws.row_values(row_index)

        # header-index helper (cached on class)
        hi = GoogleSheetsManager.header_index()

        def get(name, default="-"):
            idx = hi[name]
            return record[idx] if len(record) > idx else default

        product_name = get('product_name')
        color        = get('color')
        shipment     = get('shipment_date')
        eta          = get('estimated_arrival')
        warehouse    = get('warehouse')
        total_amt    = get('total_amount', "0")
        bag_id       = get('bag_id')
        status       = get('Статус')

        sizes_text = []
        for k in SIZE_COLS:
            idx = hi[k]
            if len(record) > idx and str(record[idx]).strip() not in ("", "0"):
                sizes_text.append(f"{k}({record[idx]})")
        sizes_text = ", ".join(sizes_text) if sizes_text else "—"

        text = (
            f"🆕 Новая запись добавлена в таблицу\n\n"
            f"Пользователь: @{source_username}\n"
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

# ===================== Entry point ==========================================
def setup_save_handler(bot: TeleBot):

    @bot.message_handler(commands=['save'])
    def start_flow(message):
        uid = message.from_user.id
        user_data.initialize_user(uid)
        # per-session bag_id
        bag_id = _new_bag_id(uid)
        user_data.update_user_data(uid, "current_bag_id", bag_id)

        st = {
            STATE_STEP:     STEP_WAREHOUSE,
            STATE_WAREHOUSE: None,
            STATE_MODELS:    [],
            STATE_SHIP_DATE: None,
            STATE_ETA_DATE:  None,
            CURRENT_MODEL:   None,
            CURRENT_COLOR:   None,
            CURRENT_COLOR_SIZES: {},
            AWAITING_SIZE:   None,
        }
        user_data.update_user_data(uid, STATE_KEY, st)
        save_text = ("""Пожалуйста введите данные об отправке пакета. Форма предназначена для одной модели с несколькими расцветками и размерами. Введите данные по порядку. Вы можете добавить модели по очереди.

Нажмите /cancel для отмены

Пожалуйста, введите склад:""")
        bot.reply_to(message, save_text, reply_markup=_kb_warehouses())

    # ===================== Free-text steps: warehouse, model, dates ==========
    @bot.message_handler(func=lambda m: user_data.get_user_data(m.from_user.id) and user_data.get_user_data(m.from_user.id).get(STATE_KEY) is not None)
    def handle_text(message):
        uid = message.from_user.id
        st  = user_data.get_user_data(uid).get(STATE_KEY, {})
        step = st.get(STATE_STEP)
        text = (message.text or "").strip()

        # cancel
        if text.lower() in {"/cancel", "отмена"}:
            user_data.update_user_data(uid, STATE_KEY, None)
            bot.reply_to(message, "✖️ Процесс отменён.")
            return

        # When awaiting numeric amount for a size during size keypad
        if step == STEP_COLORSZ and st.get(AWAITING_SIZE):
            size = st.get(AWAITING_SIZE)
            # accept integer only
            try:
                qty = int(text)
                if qty < 0:
                    raise ValueError
            except Exception:
                bot.reply_to(message, f"Введите количество числом для размера {size}.")
                return
            # update current color sizes
            current_sizes = st.get(CURRENT_COLOR_SIZES, {}) or {}
            current_sizes[size] = qty
            st[CURRENT_COLOR_SIZES] = current_sizes
            st[AWAITING_SIZE] = None
            user_data.update_user_data(uid, STATE_KEY, st)

            # re-render keypad with updated preview
            preview = _format_color_preview(st.get(CURRENT_COLOR), current_sizes)
            bot.send_message(message.chat.id, preview + "Выберите следующий размер или используйте кнопки ниже.",
                             reply_markup=_kb_sizepad(st.get(CURRENT_COLOR), current_sizes))
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
            st[CURRENT_COLOR_SIZES] = {}
            st[AWAITING_SIZE] = None
            st[STATE_STEP] = STEP_COLORSZ
            user_data.update_user_data(uid, STATE_KEY, st)

            preview = _format_color_preview(st.get(CURRENT_COLOR), st.get(CURRENT_COLOR_SIZES))
            bot.reply_to(message, preview + "Выберите размер (кнопка) и укажите количество, затем нажмите «➕ Добавить расцветку» или «✅ Закончить модель».",
                         reply_markup=_kb_sizepad(st.get(CURRENT_COLOR), st.get(CURRENT_COLOR_SIZES)))
            return

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
            bot.send_message(message.chat.id, _format_confirmation(st), reply_markup=_kb_finish_models())
            return

        if step == STEP_CONFIRM:
            bot.send_message(message.chat.id, "Пожалуйста, используйте кнопки ниже.", reply_markup=_kb_finish_models())
            return

    # ===================== Callbacks: size keypad & flow control =============
    @bot.callback_query_handler(func=lambda c: c.data.startswith("cset_") or c.data in {"cadd_color", "cfinish_model", "cclr", "cback"})
    def on_sizepad(call):
        uid = call.from_user.id
        st = user_data.get_user_data(uid).get(STATE_KEY)
        if not st or st.get(STATE_STEP) != STEP_COLORSZ:
            bot.answer_callback_query(call.id)
            return

        bot.answer_callback_query(call.id)
        data = call.data

        # choose size → ask amount
        if data.startswith("cset_"):
            size = data.split("_", 1)[1]
            st[AWAITING_SIZE] = size
            user_data.update_user_data(uid, STATE_KEY, st)
            try:
                bot.edit_message_text(
                    _format_color_preview(st.get(CURRENT_COLOR), st.get(CURRENT_COLOR_SIZES)) +
                    f"Введите количество для размера {size}:",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=None
                )
            except Exception:
                bot.send_message(call.message.chat.id, f"Введите количество для размера {size}:")
            return

        # clear current color sizes
        if data == "cclr":
            st[CURRENT_COLOR_SIZES] = {}
            st[AWAITING_SIZE] = None
            user_data.update_user_data(uid, STATE_KEY, st)
            try:
                bot.edit_message_text(
                    _format_color_preview(st.get(CURRENT_COLOR), st.get(CURRENT_COLOR_SIZES)) +
                    "Выберите размер и укажите количество.",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=_kb_sizepad(st.get(CURRENT_COLOR), st.get(CURRENT_COLOR_SIZES))
                )
            except Exception:
                bot.send_message(call.message.chat.id,
                                 _format_color_preview(st.get(CURRENT_COLOR), st.get(CURRENT_COLOR_SIZES)) +
                                 "Выберите размер и укажите количество.",
                                 reply_markup=_kb_sizepad(st.get(CURRENT_COLOR), st.get(CURRENT_COLOR_SIZES)))
            return

        # back to models (discard current color if empty)
        if data == "cback":
            st[CURRENT_COLOR] = None
            st[CURRENT_COLOR_SIZES] = {}
            st[AWAITING_SIZE] = None
            st[STATE_STEP] = STEP_MODEL
            user_data.update_user_data(uid, STATE_KEY, st)
            try:
                bot.edit_message_text("Пожалуйста, введите название модели в пакете (только одну модель за раз):",
                                      call.message.chat.id, call.message.message_id)
            except Exception:
                bot.send_message(call.message.chat.id, "Пожалуйста, введите название модели в пакете (только одну модель за раз):")
            return

        # save current color and ask for next color name
        if data == "cadd_color":
            color = st.get(CURRENT_COLOR)
            sizes = st.get(CURRENT_COLOR_SIZES) or {}
            if not color or sum(int(v or 0) for v in sizes.values()) <= 0:
                bot.answer_callback_query(call.id, "Добавьте хотя бы один размер для текущей расцветки.")
                return
            models = st.get(STATE_MODELS) or []
            if not models or models[-1].get("model_name") != st.get(CURRENT_MODEL):
                models.append({"model_name": st.get(CURRENT_MODEL), "colors": {}})
            models[-1]["colors"][color] = sizes
            st[STATE_MODELS] = models

            # reset color and ask next color name
            st[CURRENT_COLOR] = None
            st[CURRENT_COLOR_SIZES] = {}
            st[AWAITING_SIZE] = None
            st[STATE_STEP] = STEP_COLORNAME
            user_data.update_user_data(uid, STATE_KEY, st)
            try:
                bot.edit_message_text("Введите следующую расцветку:", call.message.chat.id, call.message.message_id)
            except Exception:
                bot.send_message(call.message.chat.id, "Введите следующую расцветку:")
            return

        # finish model: store current color (if any), then proceed to dates or summary
        if data == "cfinish_model":
            # store current color if filled
            color = st.get(CURRENT_COLOR)
            sizes = st.get(CURRENT_COLOR_SIZES) or {}
            if color and sum(int(v or 0) for v in sizes.values()) > 0:
                models = st.get(STATE_MODELS) or []
                if not models or models[-1].get("model_name") != st.get(CURRENT_MODEL):
                    models.append({"model_name": st.get(CURRENT_MODEL), "colors": {}})
                models[-1]["colors"][color] = sizes
                st[STATE_MODELS] = models
            # clear current color state
            st[CURRENT_COLOR] = None
            st[CURRENT_COLOR_SIZES] = {}
            st[AWAITING_SIZE] = None

            # if no dates yet → ask them; else show summary with (Добавить модель / Закончить)
            if not st.get(STATE_SHIP_DATE):
                st[STATE_STEP] = STEP_SHIPDATE
                user_data.update_user_data(uid, STATE_KEY, st)
                try:
                    bot.edit_message_text("Введите дату отправки, пример (дд.мм.гггг или дд/мм/гггг):",
                                          call.message.chat.id, call.message.message_id)
                except Exception:
                    bot.send_message(call.message.chat.id, "Введите дату отправки, пример (дд.мм.гггг или дд/мм/гггг):")
            elif not st.get(STATE_ETA_DATE):
                st[STATE_STEP] = STEP_ETADATE
                user_data.update_user_data(uid, STATE_KEY, st)
                try:
                    bot.edit_message_text("Введите примерную дату прибытия, пример (дд.мм.гггг или дд/мм/гггг):",
                                          call.message.chat.id, call.message.message_id)
                except Exception:
                    bot.send_message(call.message.chat.id, "Введите примерную дату прибытия, пример (дд.мм.гггг или дд/мм/гггг):")
            else:
                st[STATE_STEP] = STEP_CONFIRM
                user_data.update_user_data(uid, STATE_KEY, st)
                try:
                    bot.edit_message_text(_format_confirmation(st), call.message.chat.id, call.message.message_id,
                                          reply_markup=_kb_finish_models())
                except Exception:
                    bot.send_message(call.message.chat.id, _format_confirmation(st), reply_markup=_kb_finish_models())
            return

    # ===================== Save / add model / cancel / finish-all callbacks ==
    @bot.callback_query_handler(func=lambda c: c.data in {"ship_add_model", "ship_cancel", "ship_finish_all"})
    def on_actions(call):
        uid = call.from_user.id
        st = user_data.get_user_data(uid).get(STATE_KEY)
        if not st:
            bot.answer_callback_query(call.id)
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
            # ask next model, then color name again
            st[CURRENT_MODEL] = None
            st[STATE_STEP] = STEP_MODEL
            user_data.update_user_data(uid, STATE_KEY, st)
            try:
                bot.edit_message_text("Пожалуйста, введите название модели в пакете (только одну модель за раз), пример: \n **Шоколад: S-10 XL-10 3XL-20, Красный: M-10 xl-20**",
                                      call.message.chat.id, call.message.message_id, parse_mode=telegram.constants.ParseMode.MARKDOWN_V2)
            except Exception:
                bot.send_message(call.message.chat.id, "Пожалуйста, введите название модели в пакете (только одну модель за раз):")
            return

        if data == "ship_finish_all":
            # save every (model × color) row
            try:
                saved = 0
                src_username = call.from_user.username or call.from_user.first_name or str(call.from_user.id)
                bag_id = user_data.get_user_data(uid).get("current_bag_id", "")
                warehouse_name = st.get(STATE_WAREHOUSE)
                ship_date = st.get(STATE_SHIP_DATE)
                eta_date = st.get(STATE_ETA_DATE)

                for item in st.get(STATE_MODELS, []):
                    model_name = item.get("model_name")
                    for color, sizes in (item.get("colors") or {}).items():
                        total_amount = sum(int(v or 0) for v in sizes.values())
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
                            user_data.update_form_data(uid, sz, int(qty))
                        row_index = save_to_sheets(bot, call.message)
                        _notify_admins_about_new_record(bot, row_index, src_username)
                        saved += 1

                try:
                    bot.edit_message_text(f"✅ Данные сохранены. Создано записей: {saved}",
                                          call.message.chat.id, call.message.message_id)
                except Exception:
                    bot.send_message(call.message.chat.id, f"✅ Данные сохранены. Создано записей: {saved}")
            except Exception as e:
                logger.error(f"Error saving shipment: {e}")
                try:
                    bot.edit_message_text(f"❌ Ошибка при сохранении данных: {e}",
                                          call.message.chat.id, call.message.message_id)
                except Exception:
                    bot.send_message(call.message.chat.id, f"❌ Ошибка при сохранении данных: {e}")
            finally:
                user_data.update_user_data(uid, STATE_KEY, None)
            return

    # optional explicit cancel command
    @bot.message_handler(commands=['cancel'])
    def cancel_save_process(message):
        uid = message.from_user.id
        if user_data.get_user_data(uid) and user_data.get_user_data(uid).get(STATE_KEY):
            user_data.update_user_data(uid, STATE_KEY, None)
            bot.reply_to(message, "✖️ Процесс отменён.")
        else:
            bot.reply_to(message, "Нет активного процесса для отмены.")
            
    @bot.callback_query_handler(func=lambda c: c.data.startswith("wh_"))
    def on_choose_warehouse(call):
        uid = call.from_user.id
        st = user_data.get_user_data(uid).get(STATE_KEY) if user_data.get_user_data(uid) else None
        if not st or st.get(STATE_STEP) != STEP_WAREHOUSE:
            # ignore stale or out-of-flow clicks
            bot.answer_callback_query(call.id)
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
        except Exception:
            bot.send_message(
                call.message.chat.id,
                f"✅ Склад выбран: {warehouse}\n\nПожалуйста, введите название модели в пакете (только одну модель за раз):"
            )
