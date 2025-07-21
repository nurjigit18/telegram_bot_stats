import json
import logging
from typing import Dict, Optional, Tuple
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_ENABLED

logger = logging.getLogger(__name__)

class OpenAIParser:
    """OpenAI-powered parser for extracting product data from natural language input"""
    
    def __init__(self):
        if OPENAI_ENABLED:
            self.client = OpenAI(api_key=OPENAI_API_KEY)
            self.model = OPENAI_MODEL
        else:
            self.client = None
            logger.warning("OpenAI API key not configured. OpenAI parsing will be disabled.")
    
    def parse_product_data(self, user_input: str) -> Tuple[bool, Optional[Dict], Optional[str]]:
        """
        Parse natural language input to extract product data
        
        Args:
            user_input: Natural language text from user
            
        Returns:
            Tuple of (success, parsed_data_dict, error_message)
        """
        if not OPENAI_ENABLED:
            return False, None, "OpenAI API not configured"
        
        try:
            prompt = self._create_parsing_prompt(user_input)
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,  # Low temperature for consistent parsing
                max_tokens=1000,
                timeout=30
            )
            
            content = response.choices[0].message.content.strip()
            
            # Try to parse JSON response
            try:
                parsed_data = json.loads(content)
                
                # Validate required fields
                required_fields = ['product_name', 'product_color', 'total_amount', 
                                 'warehouse_sizes', 'shipment_date', 'estimated_arrival']
                
                if not all(field in parsed_data for field in required_fields):
                    missing_fields = [f for f in required_fields if f not in parsed_data]
                    return False, None, f"Missing required fields: {', '.join(missing_fields)}"
                
                # Additional validation
                if not isinstance(parsed_data['total_amount'], int) or parsed_data['total_amount'] <= 0:
                    return False, None, "Total amount must be a positive integer"
                
                return True, parsed_data, None
                
            except json.JSONDecodeError:
                logger.error(f"Failed to parse OpenAI response as JSON: {content}")
                return False, None, "Failed to parse OpenAI response"
                
        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}")
            return False, None, f"OpenAI API error: {str(e)}"
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for OpenAI"""
        return """You are a data extraction assistant for a warehouse management system. Your task is to extract structured product information from natural language input in Russian or English.

You must extract exactly these 6 fields:
1. product_name - name of the product
2. product_color - color of the product  
3. total_amount - total quantity as integer
4. warehouse_sizes - warehouse and size distribution
5. shipment_date - shipping date
6. estimated_arrival - estimated arrival date

For warehouse_sizes, use this exact format: "WarehouseName: SIZE-QUANTITY SIZE-QUANTITY"
- Multiple warehouses separated by " , " (comma with spaces)
- Sizes: XS, S, M, L, XL, 2XL, 3XL, 4XL, 5XL, 6XL, 7XL
- Example: "Казань: S-50 M-25 L-25" or "Казань: S-30 M-40 , Москва: L-50 XL-80"

For dates, use DD/MM/YYYY or DD.MM.YYYY format.

Always respond with valid JSON only, no additional text."""

    def _create_parsing_prompt(self, user_input: str) -> str:
        """Create the parsing prompt for the user input"""
        return f"""Extract product information from this text and return as JSON:

Text: "{user_input}"

Required JSON format:
{{
    "product_name": "extracted product name",
    "product_color": "extracted color", 
    "total_amount": extracted_total_quantity_as_integer,
    "warehouse_sizes": "WarehouseName: SIZE-QUANTITY SIZE-QUANTITY",
    "shipment_date": "DD/MM/YYYY",
    "estimated_arrival": "DD/MM/YYYY"
}}

Examples of warehouse_sizes format:
- Single warehouse: "Казань: S-50 M-25 L-25"
- Multiple warehouses: "Казань: S-30 M-40 , Москва: L-50 XL-80"

Extract the information and respond with JSON only."""

# Global instance
openai_parser = OpenAIParser()
