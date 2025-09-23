# models/factory_data.py - Factory management system
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
                factories_ws = sheets_manager._spreadsheet.worksheet("цехи")
                factories_data = factories_ws.get_all_values()
                
                if len(factories_data) > 1:  # Has data beyond headers
                    factories_config = {"users": {}}
                    for row in factories_data[1:]:  # Skip header
                        if len(row) >= 3:
                            user_id = int(row[0])
                            factory_name = row[1]
                            factory_tab = row[2]
                            
                            if user_id not in factories_config["users"]:
                                factories_config["users"][user_id] = []
                            
                            factories_config["users"][user_id].append({
                                "name": factory_name,
                                "tab_name": factory_tab
                            })
                    
                    self._factories_cache = factories_config
                    return factories_config
                    
            except Exception as e:
                logger.info(f"Factories worksheet not found or empty, creating default: {e}")
                # Create default factories worksheet
                factories_ws = sheets_manager._spreadsheet.add_worksheet("цехи", 100, 3)
                factories_ws.update('A1', [['user_id', 'factory_name', 'tab_name']])
                
        except Exception as e:
            logger.error(f"Error accessing Google Sheets for factories: {e}")
            
        # Fallback to environment variable or default config
        try:
            factories_json = os.getenv('FACTORIES_CONFIG')
            if factories_json:
                factories_config = json.loads(factories_json)
                self._factories_cache = factories_config
                return factories_config
        except Exception as e:
            logger.error(f"Error parsing FACTORIES_CONFIG: {e}")
            
        # Default configuration (empty)
        default_config = {"users": {}}
        self._factories_cache = default_config
        return default_config
    
    def get_user_factories(self, user_id: int) -> List[Dict]:
        """Get list of factories for a specific user"""
        if user_id in self._user_factories_cache:
            return self._user_factories_cache[user_id]
            
        factories_config = self.get_factories_config()
        user_factories = factories_config.get("users", {}).get(user_id, [])
        
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
    
    def add_factory(self, user_id: int, factory_name: str, tab_name: str) -> bool:
        """Add a new factory for a user (admin function)"""
        try:
            sheets_manager = GoogleSheetsManager.get_instance()
            factories_ws = sheets_manager._spreadsheet.worksheet("цехи")
            
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
        """Ensure the factory worksheet exists with proper headers - FIXED VERSION"""
        try:
            sheets_manager = GoogleSheetsManager.get_instance()
            
            try:
                # Try to get existing worksheet first
                worksheet = sheets_manager._spreadsheet.worksheet(tab_name)
                logger.info(f"Found existing worksheet: {tab_name}")
                
                # Check if headers are correct
                headers = worksheet.row_values(1)
                from utils.google_sheets import EXPECTED_HEADERS
                
                if not headers or headers != EXPECTED_HEADERS:
                    # Headers are missing or incorrect, update them
                    worksheet.update('A1', [EXPECTED_HEADERS])
                    logger.info(f"Updated headers for existing worksheet {tab_name}")
                else:
                    logger.info(f"Worksheet {tab_name} already has correct headers")
                    
            except Exception as worksheet_error:
                # Worksheet doesn't exist, create it
                logger.info(f"Worksheet {tab_name} not found, creating new one: {worksheet_error}")
                
                try:
                    from utils.google_sheets import EXPECTED_HEADERS
                    worksheet = sheets_manager._spreadsheet.add_worksheet(
                        title=tab_name, 
                        rows=1000, 
                        cols=len(EXPECTED_HEADERS)
                    )
                    worksheet.update('A1', [EXPECTED_HEADERS])
                    logger.info(f"Created new worksheet {tab_name} with headers")
                    
                except Exception as create_error:
                    # Check if the error is about duplicate name
                    if "already exists" in str(create_error).lower():
                        # Worksheet was created by another process, try to get it again
                        logger.info(f"Worksheet {tab_name} was created by another process, retrieving it")
                        worksheet = sheets_manager._spreadsheet.worksheet(tab_name)
                        
                        # Still check headers
                        headers = worksheet.row_values(1)
                        from utils.google_sheets import EXPECTED_HEADERS
                        if not headers or headers != EXPECTED_HEADERS:
                            worksheet.update('A1', [EXPECTED_HEADERS])
                            logger.info(f"Updated headers for concurrently created worksheet {tab_name}")
                    else:
                        # Different error, re-raise
                        raise create_error
                    
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
        
    def get_factory_warehouses(self, factory_tab_name: str) -> List[str]:
        """Get list of warehouses for a specific factory"""
        try:
            sheets_manager = GoogleSheetsManager.get_instance()
            
            try:
                # Get the Factory_Warehouses worksheet
                warehouses_ws = sheets_manager._spreadsheet.worksheet("склады")
                warehouses_data = warehouses_ws.get_all_values()
                
                if len(warehouses_data) <= 1:  # Only headers or empty
                    logger.warning("Factory_Warehouses worksheet is empty")
                    return self._get_default_warehouses()
                
                # Find warehouses for this factory
                factory_warehouses = []
                for row in warehouses_data[1:]:  # Skip header
                    if len(row) >= 2:
                        row_factory = row[0].strip()
                        warehouse_name = row[1].strip()
                        
                        if row_factory == factory_tab_name and warehouse_name:
                            factory_warehouses.append(warehouse_name)
                
                if not factory_warehouses:
                    logger.info(f"No warehouses found for factory {factory_tab_name}, using defaults")
                    return self._get_default_warehouses()
                
                logger.info(f"Found {len(factory_warehouses)} warehouses for factory {factory_tab_name}: {factory_warehouses}")
                return factory_warehouses
                
            except Exception as e:
                logger.info(f"Factory_Warehouses worksheet not found, creating default: {e}")
                # Create the worksheet with default structure
                self._create_factory_warehouses_worksheet()
                return self._get_default_warehouses()
                
        except Exception as e:
            logger.error(f"Error getting warehouses for factory {factory_tab_name}: {e}")
            return self._get_default_warehouses()

    def _get_default_warehouses(self) -> List[str]:
        """Return default warehouses if factory-specific ones aren't found"""
        return [
            "Казань", "Краснодар", "Электросталь", "Коледино",
            "Тула", "Невинномысск", "Рязань", "Новосибирск", 
            "Алматы", "Котовск"
        ]

    def _create_factory_warehouses_worksheet(self):
        """Create Factory_Warehouses worksheet with sample data"""
        try:
            sheets_manager = GoogleSheetsManager.get_instance()
            
            # Create worksheet
            warehouses_ws = sheets_manager._spreadsheet.add_worksheet("склады", 100, 2)
            
            # Add headers and sample data
            sample_data = [
                ['factory_tab_name', 'warehouse_name'],
                ['нарселя', 'Казань'],
                ['нарселя', 'Краснодар'], 
                ['нарселя', 'Электросталь'],
                ['gulzina', 'Алматы'],
                ['gulzina', 'Новосибирск'],
                ['gulzina', 'Тула']
            ]
            
            warehouses_ws.update('A1', sample_data)
            logger.info("Created Factory_Warehouses worksheet with sample data")
            
        except Exception as e:
            logger.error(f"Error creating Factory_Warehouses worksheet: {e}")


# Global factory manager instance
factory_manager = FactoryManager()