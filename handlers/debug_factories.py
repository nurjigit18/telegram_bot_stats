# handlers/debug_factories.py - Debug commands for factory management
# -*- coding: utf-8 -*-

from telebot import TeleBot
from models.factory_data import factory_manager
from models.user_data import user_data
from utils.google_sheets import GoogleSheetsManager
import logging

logger = logging.getLogger(__name__)

def setup_debug_factory_handlers(bot: TeleBot):
    """Set up debug handlers for factory management"""
    
    @bot.message_handler(commands=['debug_factories'])
    def debug_factories_command(message):
        """Debug command to check factory assignments"""
        try:
            user_id = message.from_user.id
            
            # Clear cache first
            factory_manager.clear_cache()
            
            # Get raw factories config
            factories_config = factory_manager.get_factories_config()
            
            # Get user-specific factories
            user_factories = factory_manager.get_user_factories(user_id)
            
            debug_info = []
            debug_info.append(f"🔍 Debug Info for User {user_id}")
            debug_info.append(f"Username: @{message.from_user.username or 'N/A'}")
            debug_info.append("")
            
            debug_info.append("📊 Raw Factories Config:")
            debug_info.append(f"Total users with factories: {len(factories_config.get('users', {}))}")
            
            for uid, factories in factories_config.get('users', {}).items():
                debug_info.append(f"  User {uid}: {len(factories)} factories")
                for factory in factories:
                    debug_info.append(f"    - {factory['name']} ({factory['tab_name']})")
            
            debug_info.append("")
            debug_info.append(f"🏭 Your Factories ({len(user_factories)}):")
            if user_factories:
                for i, factory in enumerate(user_factories, 1):
                    debug_info.append(f"{i}. {factory['name']} → {factory['tab_name']}")
            else:
                debug_info.append("❌ No factories assigned")
            
            debug_info.append("")
            debug_info.append("📋 Google Sheets Data:")
            try:
                sheets_manager = GoogleSheetsManager.get_instance()
                factories_ws = sheets_manager._spreadsheet.worksheet("цехи")
                all_data = factories_ws.get_all_values()
                
                debug_info.append(f"Total rows in Factories sheet: {len(all_data)}")
                if len(all_data) > 0:
                    debug_info.append(f"Headers: {all_data[0]}")
                
                for row_idx, row in enumerate(all_data[1:], start=2):
                    if len(row) >= 3:
                        debug_info.append(f"Row {row_idx}: {row[0]} | {row[1]} | {row[2]}")
                        
            except Exception as e:
                debug_info.append(f"❌ Error reading Factories sheet: {e}")
            
            # Send debug info (split if too long)
            debug_text = "\n".join(debug_info)
            if len(debug_text) > 4000:
                parts = [debug_text[i:i+4000] for i in range(0, len(debug_text), 4000)]
                for part in parts:
                    bot.send_message(message.chat.id, f"```\n{part}\n```", parse_mode='Markdown')
            else:
                bot.send_message(message.chat.id, f"```\n{debug_text}\n```", parse_mode='Markdown')
                
        except Exception as e:
            logger.error(f"Error in debug_factories_command: {e}")
            bot.reply_to(message, f"❌ Error: {e}")
    
    @bot.message_handler(commands=['test_factory_selection'])
    def test_factory_selection_command(message):
        """Test factory selection flow"""
        try:
            user_id = message.from_user.id
            
            # Clear any existing state
            user_data.initialize_user(user_id)
            user_data.update_user_data(user_id, "pending_action", "test")
            
            # Import the factory selection function
            from handlers.factory_selection import prompt_factory_selection
            
            result = prompt_factory_selection(bot, message, "test")
            
            bot.send_message(
                message.chat.id,
                f"🧪 Factory selection test result: {result}\n"
                f"- True = Selection menu shown or no factories\n"
                f"- False = Single factory auto-selected"
            )
            
        except Exception as e:
            logger.error(f"Error in test_factory_selection: {e}")
            bot.reply_to(message, f"❌ Test failed: {e}")
    
    @bot.message_handler(commands=['clear_factory_cache'])
    def clear_factory_cache_command(message):
        """Clear factory cache and reload"""
        try:
            factory_manager.clear_cache()
            
            user_id = message.from_user.id
            user_factories = factory_manager.get_user_factories(user_id)
            
            bot.reply_to(
                message,
                f"✅ Factory cache cleared!\n"
                f"Reloaded: {len(user_factories)} factories for you"
            )
            
        except Exception as e:
            logger.error(f"Error clearing factory cache: {e}")
            bot.reply_to(message, f"❌ Error: {e}")

    @bot.message_handler(commands=['add_test_factory'])
    def add_test_factory_command(message):
        """Add a test factory for current user"""
        try:
            user_id = message.from_user.id
            
            # Check if user already has the test factory
            existing_factories = factory_manager.get_user_factories(user_id)
            for factory in existing_factories:
                if factory['tab_name'] == 'test_factory':
                    bot.reply_to(message, "❌ Test factory already exists for you")
                    return
            
            success = factory_manager.add_factory(user_id, "Test Factory", "test_factory")
            
            if success:
                bot.reply_to(
                    message, 
                    f"✅ Test factory added!\n"
                    f"User ID: {user_id}\n"
                    f"Factory: Test Factory\n"
                    f"Tab: test_factory\n\n"
                    f"Now try /save to test the selection flow."
                )
            else:
                bot.reply_to(message, "❌ Failed to add test factory")
                
        except Exception as e:
            logger.error(f"Error adding test factory: {e}")
            bot.reply_to(message, f"❌ Error: {e}")


# Quick fix for the main issue - Updated factory selection callback handler
def setup_fixed_callback_handler(bot: TeleBot):
    """Set up the fixed callback handler for factory selection"""
    
    @bot.callback_query_handler(func=lambda c: c.data.startswith("select_factory:"))
    def on_factory_selection_global(call):
        """Global handler for factory selection - handles all actions"""
        try:
            user_id = call.from_user.id
            user_session = user_data.get_user_data(user_id)
            
            logger.info(f"Factory selection callback: user_id={user_id}, data={call.data}")
            
            if not user_session:
                bot.answer_callback_query(call.id, "Сессия не найдена")
                logger.warning(f"No user session found for user {user_id}")
                return
            
            pending_action = user_session.get("pending_action")
            logger.info(f"Pending action for user {user_id}: {pending_action}")
            
            # Import here to avoid circular imports
            from handlers.factory_selection import handle_factory_selection
            
            # Handle the factory selection
            factory_info = handle_factory_selection(bot, call, pending_action or "unknown")
            
            if factory_info:
                logger.info(f"Factory selected: {factory_info}")
                
                if pending_action == "save":
                    # Import and start save flow
                    try:
                        bot.edit_message_text(
                            f"✅ Выбрана фабрика: {factory_info['name']}\n\nНачинаем процесс сохранения...",
                            call.message.chat.id,
                            call.message.message_id
                        )
                    except Exception:
                        bot.send_message(
                            call.message.chat.id, 
                            f"✅ Выбрана фабрика: {factory_info['name']}\n\nНачинаем процесс сохранения..."
                        )
                    
                    # Import the save flow function and start it
                    # This will be called from the main save handler
                    
                elif pending_action == "status":
                    # Handle status flow
                    try:
                        bot.edit_message_text(
                            f"✅ Выбрана фабрика: {factory_info['name']}\n\nПоказываем статус...",
                            call.message.chat.id,
                            call.message.message_id
                        )
                    except Exception:
                        bot.send_message(
                            call.message.chat.id, 
                            f"✅ Выбрана фабрика: {factory_info['name']}\n\nПоказываем статус..."
                        )
                
                elif pending_action == "edit":
                    # Handle edit flow
                    try:
                        bot.edit_message_text(
                            f"✅ Выбрана фабрика: {factory_info['name']}\n\nЗапускаем редактирование...",
                            call.message.chat.id,
                            call.message.message_id
                        )
                    except Exception:
                        bot.send_message(
                            call.message.chat.id, 
                            f"✅ Выбрана фабрика: {factory_info['name']}\n\nЗапускаем редактирование..."
                        )
            else:
                logger.error(f"Factory selection failed for user {user_id}")
                
        except Exception as e:
            logger.error(f"Error in factory selection callback: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка")

    @bot.callback_query_handler(func=lambda c: c.data == "factory_cancel")
    def on_factory_cancel(call):
        """Handle factory selection cancellation"""
        try:
            user_id = call.from_user.id
            bot.answer_callback_query(call.id, "Операция отменена")
            
            # Clear pending action
            user_data.update_user_data(user_id, "pending_action", None)
            
            try:
                bot.edit_message_text(
                    "❌ Операция отменена.",
                    call.message.chat.id,
                    call.message.message_id
                )
            except Exception:
                bot.send_message(call.message.chat.id, "❌ Операция отменена.")
                
        except Exception as e:
            logger.error(f"Error in factory cancel callback: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка")