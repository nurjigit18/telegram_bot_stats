# -*- coding: utf-8 -*-
# handlers/factories.py
"""
Factory selection flow:
- Shows only factories assigned to the current Telegram user (by user_id)
- Stores the picked factory in user_data[user_id]['factory'] = {id, name, sheet}
- Forwards to the requested next_action: 'save' | 'status' | 'edit'
"""

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from models.user_data import user_data  # adjust import path if yours is utils.user_data
from utils.google_sheets import get_user_factories, ensure_worksheet_exists
import logging

logger = logging.getLogger(__name__)

# Callback data format: "factory:choose:<next_action>:<factory_id>"
CB_PREFIX = "factory:choose:"

def _kb_factories(factories, next_action: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    for f in factories:
        cb = f"{CB_PREFIX}{next_action}:{f['id']}"
        kb.add(InlineKeyboardButton(text=f["name"], callback_data=cb))
    return kb

def ask_factory(bot, message, next_action: str):
    """Entry: call this at the start of /save, /status, /edit."""
    user_id = getattr(getattr(message, "from_user", None), "id", None) or getattr(getattr(message, "chat", None), "id", None)
    if not user_id:
        bot.reply_to(message, "Не удалось определить пользователя.")
        return

    factories = get_user_factories(user_id)
    if not factories:
        bot.reply_to(message, "Для вашего аккаунта не назначены фабрики. Обратитесь к администратору.")
        return

    # Keep next_action in volatile state; actual flow resumes after selection.
    state = user_data.setdefault(user_id, {})
    state["pending_next_action"] = next_action

    kb = _kb_factories(factories, next_action)
    bot.send_message(message.chat.id, "Выберите фабрику:", reply_markup=kb)

def register_handlers(bot, save_start_fn, status_start_fn, edit_start_fn):
    """
    Hook into TeleBot. You pass references to your existing flow starters:
      - save_start_fn(message)
      - status_start_fn(message)
      - edit_start_fn(message)
    We will call the appropriate one after a factory is chosen.
    """

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith(CB_PREFIX))
    def _on_factory_chosen(call: CallbackQuery):
        try:
            _, _, rest = call.data.partition(CB_PREFIX)  # rest = "<next_action>:<factory_id>"
            next_action, _, factory_id = rest.partition(":")
            user_id = call.from_user.id

            factories = get_user_factories(user_id)
            factory = next((f for f in factories if f["id"] == factory_id), None)
            if not factory:
                bot.answer_callback_query(call.id, "Недоступно.")
                return

            # Persist selection to user_data, enforce worksheet presence
            st = user_data.setdefault(user_id, {})
            st["factory"] = factory  # {id, name, sheet}
            ensure_worksheet_exists(factory["sheet"])

            # Clean up pending action if any
            st.pop("pending_next_action", None)

            bot.answer_callback_query(call.id, f"Фабрика: {factory['name']}")
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

            # Route to the respective flow
            if next_action == "save":
                save_start_fn(call.message)
            elif next_action == "status":
                status_start_fn(call.message)
            elif next_action == "edit":
                edit_start_fn(call.message)
            else:
                bot.send_message(call.message.chat.id, "Неизвестное действие.")
        except Exception as e:
            logger.exception("Factory selection error")
            bot.answer_callback_query(call.id, "Ошибка выбора фабрики.")
