# handlers/factory_selection.py - Fixed Factory selection handlers
# -*- coding: utf-8 -*-

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from models.factory_data import factory_manager
from models.user_data import user_data
import logging

logger = logging.getLogger(__name__)

def create_factory_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Create inline keyboard with user's factories"""
    factories = factory_manager.get_user_factories(user_id)
    
    if not factories:
        return None
    
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = []
    
    for factory in factories:
        # Use a safe callback data format
        callback_data = f"select_factory:{factory['tab_name']}"
        buttons.append(InlineKeyboardButton(factory['name'], callback_data=callback_data))
    
    # Add buttons in rows of 2
    for i in range(0, len(buttons), 2):
        row = buttons[i:i+2]
        markup.row(*row)
    
    # Add cancel button
    markup.row(InlineKeyboardButton("❌ Отмена", callback_data="factory_cancel"))
    
    return markup

def handle_factory_selection(bot: TeleBot, call, action_type: str):
    """Handle factory selection callback - FIXED VERSION"""
    try:
        # CRITICAL FIX: Always use call.from_user.id for callbacks
        user_id = call.from_user.id
        logger.info(f"Factory selection callback: user_id={user_id}, data={call.data}")
        
        if call.data == "factory_cancel":
            bot.answer_callback_query(call.id, "Операция отменена")
            # Clear pending action for the correct user
            user_data.update_user_data(user_id, "current_action", None)
            try:
                bot.edit_message_text(
                    "❌ Операция отменена.",
                    call.message.chat.id,
                    call.message.message_id
                )
            except Exception:
                bot.send_message(call.message.chat.id, "❌ Операция отменена.")
            return None
        
        if call.data.startswith("select_factory:"):
            tab_name = call.data[15:]  # Remove "select_factory:" prefix
            
            # CRITICAL: Find factory info by tab_name for the CORRECT user
            factories = factory_manager.get_user_factories(user_id)
            factory_info = None
            for factory in factories:
                if factory['tab_name'] == tab_name:
                    factory_info = factory
                    break
            
            if not factory_info:
                bot.answer_callback_query(call.id, "Фабрика не найдена")
                logger.error(f"Factory with tab_name {tab_name} not found for user {user_id}")
                return None
            
            # CRITICAL: Store factory for the CORRECT user_id
            user_data.initialize_user(user_id)  # Ensure user exists
            user_data.update_user_data(user_id, "selected_factory", factory_info)
            
            # Verify storage worked
            stored_factory = user_data.get_user_data(user_id).get("selected_factory")
            if stored_factory:
                logger.info(f"✅ Factory stored successfully for user {user_id}: {stored_factory}")
            else:
                logger.error(f"❌ Factory storage failed for user {user_id}!")
                return None
            
            bot.answer_callback_query(call.id, f"Выбрана фабрика: {factory_info['name']}")
            
            logger.info(f"User {user_id} selected factory: {factory_info['name']} (tab: {tab_name})")
            
            # Clear pending action since we're continuing with the flow
            user_data.update_user_data(user_id, "current_action", None)
            
            return factory_info
            
    except Exception as e:
        logger.error(f"Error in factory selection for user {user_id}: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка")
        return None


def prompt_factory_selection(bot: TeleBot, message, action_type: str) -> bool:
    """Prompt user to select a factory - FIXED VERSION"""
    try:
        # Handle both message and callback contexts properly
        user_id = message.from_user.id if hasattr(message, 'from_user') else message.chat.id
        logger.info(f"Prompting factory selection for user {user_id}, action: {action_type}")
        
        # CRITICAL: Initialize user data for the correct user first
        user_data.initialize_user(user_id)
        
        # Clear cache and get fresh factory data
        factory_manager.clear_cache()
        factories = factory_manager.get_user_factories(user_id)
        
        logger.info(f"User {user_id} has {len(factories)} factories: {[f['name'] for f in factories]}")
        
        if not factories:
            bot.send_message(
                message.chat.id,
                "❌ У вас нет назначенных фабрик. Обратитесь к администратору для настройки доступа.\n\n"
                f"Ваш ID: `{user_id}`",
                parse_mode='Markdown'
            )
            return True
        
        if len(factories) == 1:
            # Only one factory, select it automatically
            factory_info = factories[0]
            
            # CRITICAL: Store the factory for this specific user
            user_data.update_user_data(user_id, "selected_factory", factory_info)
            logger.info(f"Auto-selected single factory for user {user_id}: {factory_info['name']}")
            
            # Verify storage worked
            stored_factory = user_data.get_user_data(user_id).get("selected_factory")
            if stored_factory:
                logger.info(f"✅ Auto-selected factory stored successfully: {stored_factory}")
            else:
                logger.error(f"❌ Auto-selected factory storage failed!")
                return True
            
            return False  # Continue with the action
        
        # Multiple factories, show selection
        keyboard = create_factory_keyboard(user_id)
        if not keyboard:
            bot.send_message(message.chat.id, "❌ Ошибка создания меню выбора фабрик.")
            return True
            
        action_names = {
            "save": "сохранения",
            "status": "просмотра статуса", 
            "edit": "редактирования"
        }
        action_name = action_names.get(action_type, "операции")
        
        # CRITICAL: Set pending action for this specific user
        user_data.update_user_data(user_id, "current_action", action_type)
        
        bot.send_message(
            message.chat.id,
            f"Выберите фабрику для {action_name}:",
            reply_markup=keyboard
        )
        return True
        
    except Exception as e:
        logger.error(f"Error in prompt_factory_selection for user {user_id}: {e}")
        bot.send_message(message.chat.id, "❌ Произошла ошибка при выборе фабрики.")
        return True




# Fixed models/factory_data.py - Updated factory manager with better debugging
# -*- coding: utf-8 -*-

import logging
import json
import os
from typing import Dict, List, Optional
from utils.google_sheets import GoogleSheetsManager

logger = logging.getLogger(__name__)

class FactoryManager:
    """Manages factory assignments and operations"""
    
    def __init__(self):
        self._factories_cache = None
        self._user_factories_cache = {}
        
    def get_factories_config(self) -> Dict:
        """Get factories configuration from Google Sheets or config file"""
        if self._factories_cache is not None:
            return self._factories_cache
            
        try:
            # Try to get from Google Sheets first
            sheets_manager = GoogleSheetsManager.get_instance()
            try:
                factories_ws = sheets_manager._spreadsheet.worksheet("Factories")
                factories_data = factories_ws.get_all_values()
                
                logger.info(f"Factories worksheet data: {factories_data}")
                
                if len(factories_data) > 1:  # Has data beyond headers
                    factories_config = {"users": {}}
                    for row_idx, row in enumerate(factories_data[1:], start=2):  # Skip header
                        if len(row) >= 3:
                            try:
                                user_id = int(row[0])
                                factory_name = row[1].strip()
                                factory_tab = row[2].strip()
                                
                                if user_id not in factories_config["users"]:
                                    factories_config["users"][user_id] = []
                                
                                factories_config["users"][user_id].append({
                                    "name": factory_name,
                                    "tab_name": factory_tab
                                })
                                
                                logger.info(f"Added factory: user_id={user_id}, name={factory_name}, tab={factory_tab}")
                                
                            except ValueError as e:
                                logger.error(f"Error parsing user_id in row {row_idx}: {row[0]} - {e}")
                                continue
                        else:
                            logger.warning(f"Incomplete row {row_idx}: {row}")
                    
                    self._factories_cache = factories_config
                    logger.info(f"Loaded factories config: {factories_config}")
                    return factories_config
                else:
                    logger.warning("Factories worksheet exists but has no data")
                    
            except Exception as e:
                logger.info(f"Factories worksheet not found or error accessing it: {e}")
                # Create default factories worksheet
                try:
                    factories_ws = sheets_manager._spreadsheet.add_worksheet("Factories", 100, 3)
                    factories_ws.update('A1', [['user_id', 'factory_name', 'tab_name']])
                    logger.info("Created new Factories worksheet")
                except Exception as create_error:
                    logger.error(f"Error creating Factories worksheet: {create_error}")
                
        except Exception as e:
            logger.error(f"Error accessing Google Sheets for factories: {e}")
            
        # Fallback to environment variable or default config
        try:
            factories_json = os.getenv('FACTORIES_CONFIG')
            if factories_json:
                factories_config = json.loads(factories_json)
                self._factories_cache = factories_config
                logger.info(f"Loaded factories from environment: {factories_config}")
                return factories_config
        except Exception as e:
            logger.error(f"Error parsing FACTORIES_CONFIG: {e}")
            
        # Default configuration (empty)
        default_config = {"users": {}}
        self._factories_cache = default_config
        logger.info("Using default empty factories config")
        return default_config
    
    def get_user_factories(self, user_id: int) -> List[Dict]:
        """Get list of factories for a specific user"""
        if user_id in self._user_factories_cache:
            cached_factories = self._user_factories_cache[user_id]
            logger.info(f"Using cached factories for user {user_id}: {cached_factories}")
            return cached_factories
            
        factories_config = self.get_factories_config()
        user_factories = factories_config.get("users", {}).get(user_id, [])
        
        logger.info(f"Loaded factories for user {user_id}: {user_factories}")
        
        # Cache for performance
        self._user_factories_cache[user_id] = user_factories
        return user_factories
    
    def has_factories(self, user_id: int) -> bool:
        """Check if user has any assigned factories"""
        return len(self.get_user_factories(user_id)) > 0
    
    def get_factory_by_name(self, user_id: int, factory_name: str) -> Optional[Dict]:
        """Get factory info by name for a specific user"""
        factories = self.get_user_factories(user_id)
        for factory in factories:
            if factory["name"] == factory_name:
                return factory
        return None
    
    def get_factory_by_tab_name(self, user_id: int, tab_name: str) -> Optional[Dict]:
        """Get factory info by tab name for a specific user"""
        factories = self.get_user_factories(user_id)
        for factory in factories:
            if factory["tab_name"] == tab_name:
                return factory
        return None
    
    def add_factory(self, user_id: int, factory_name: str, tab_name: str) -> bool:
        """Add a new factory for a user (admin function)"""
        try:
            sheets_manager = GoogleSheetsManager.get_instance()
            factories_ws = sheets_manager._spreadsheet.worksheet("Factories")
            
            # Add to Google Sheets
            factories_ws.append_row([user_id, factory_name, tab_name])
            
            # Clear cache to force refresh
            self._factories_cache = None
            if user_id in self._user_factories_cache:
                del self._user_factories_cache[user_id]
                
            # Create the worksheet if it doesn't exist
            self.ensure_factory_worksheet(tab_name)
            
            logger.info(f"Added factory {factory_name} (tab: {tab_name}) for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding factory: {e}")
            return False
    
    def ensure_factory_worksheet(self, tab_name: str):
        """Ensure the factory worksheet exists with proper headers"""
        try:
            sheets_manager = GoogleSheetsManager.get_instance()
            
            try:
                # Try to get existing worksheet
                worksheet = sheets_manager._spreadsheet.worksheet(tab_name)
                
                # Check if headers are correct
                headers = worksheet.row_values(1)
                from utils.google_sheets import EXPECTED_HEADERS
                if headers != EXPECTED_HEADERS:
                    worksheet.clear()
                    worksheet.update('A1', [EXPECTED_HEADERS])
                    logger.info(f"Updated headers for worksheet {tab_name}")
                    
            except Exception:
                # Create new worksheet
                from utils.google_sheets import EXPECTED_HEADERS
                worksheet = sheets_manager._spreadsheet.add_worksheet(tab_name, 1000, len(EXPECTED_HEADERS))
                worksheet.update('A1', [EXPECTED_HEADERS])
                logger.info(f"Created new worksheet {tab_name}")
                
        except Exception as e:
            logger.error(f"Error ensuring factory worksheet {tab_name}: {e}")
            raise
    
    def get_factory_worksheet(self, tab_name: str):
        """Get the worksheet for a specific factory"""
        try:
            sheets_manager = GoogleSheetsManager.get_instance()
            return sheets_manager._spreadsheet.worksheet(tab_name)
        except Exception as e:
            logger.error(f"Error accessing factory worksheet {tab_name}: {e}")
            raise
    
    def clear_cache(self):
        """Clear all cached data"""
        self._factories_cache = None
        self._user_factories_cache = {}
        logger.info("Cleared factory cache")

# Global factory manager instance
factory_manager = FactoryManager()


# Updated setup_save_handler function - Fixed callback handling
def setup_save_handler(bot: TeleBot):
    """Set up save handler with factory support"""

    @bot.message_handler(commands=['save'])
    def start_flow(message):
        """Start save flow with factory selection"""
        uid = message.from_user.id
        
        # Set pending action for factory selection
        user_data.initialize_user(uid)
        user_data.update_user_data(uid, "pending_action", "save")
        
        # First, prompt for factory selection
        if prompt_factory_selection(bot, message, "save"):
            return  # Factory selection was prompted or user has no factories
        
        # If we reach here, user has only one factory and it was auto-selected
        start_save_flow_with_factory(bot, message)

    # FIXED: Factory selection callback handler - more specific matching
    @bot.callback_query_handler(func=lambda c: c.data.startswith("select_factory:"))
    def on_factory_selection_save(call):
        """Handle factory selection callbacks"""
        try:
            user_id = call.from_user.id
            user_session = user_data.get_user_data(user_id)
            
            if not user_session:
                bot.answer_callback_query(call.id, "Сессия не найдена")
                return
            
            pending_action = user_session.get("pending_action")
            logger.info(f"Factory selection callback for user {user_id}, pending action: {pending_action}")
            
            # Handle the factory selection
            factory_info = handle_factory_selection(bot, call, pending_action or "unknown")
            
            if factory_info and pending_action == "save":
                # Start save flow after successful factory selection
                try:
                    bot.edit_message_text(
                        f"✅ Выбрана фабрика: {factory_info['name']}\n\nНачинаем процесс сохранения...",
                        call.message.chat.id,
                        call.message.message_id
                    )
                except Exception:
                    bot.send_message(call.message.chat.id, 
                                   f"✅ Выбрана фабрика: {factory_info['name']}\n\nНачинаем процесс сохранения...")
                
                start_save_flow_with_factory(bot, call.message)
                
        except Exception as e:
            logger.error(f"Error in factory selection callback: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка")

    # Rest of the save handler code remains the same...
    # (All the other handlers from the complete save handler)