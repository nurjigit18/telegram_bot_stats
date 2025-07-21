#!/usr/bin/env python3
"""
Test script for OpenAI integration in save.py
"""

import os
import sys
from utils.openai_parser import openai_parser
from config import OPENAI_ENABLED

def test_openai_parser():
    """Test the OpenAI parser with sample inputs"""
    
    print("🧪 Testing OpenAI Integration")
    print("=" * 50)
    
    if not OPENAI_ENABLED:
        print("❌ OpenAI is not enabled. Please set OPENAI_API_KEY environment variable.")
        return
    
    print("✅ OpenAI is enabled")
    print(f"📋 Testing natural language parsing...")
    
    # Test cases
    test_cases = [
        {
            "name": "Complete Russian natural language",
            "input": "Привет! Мне нужно сохранить данные о красных рубашках. У нас есть 100 штук, которые будут распределены по складу в Казани: 50 размера S, 25 размера M и 25 размера L. Отправляем 12 декабря 2021 года, а прибыть должны примерно 15 декабря."
        },
        {
            "name": "Incomplete data - missing dates",
            "input": "Синие джинсы, 80 штук, склад Москва: M-40 L-40"
        },
        {
            "name": "Incomplete data - missing sizes",
            "input": "Белые футболки, 50 штук, отправка 20/01/2024, прибытие 25/01/2024"
        },
        {
            "name": "Partial data - only product info",
            "input": "Черные куртки"
        },
        {
            "name": "Complete English natural language",
            "input": "I need to save data about blue t-shirts. We have 200 pieces distributed across warehouses: Moscow warehouse has 80 size L and 70 size XL, Kazan warehouse has 50 size M. Shipping on 25/01/2024, estimated arrival 30/01/2024."
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n🔍 Test {i}: {test_case['name']}")
        print(f"Input: {test_case['input'][:100]}...")
        
        try:
            success, parsed_data, error_msg = openai_parser.parse_product_data(test_case['input'])
            
            if success:
                print("✅ Parsing successful!")
                print("📦 Extracted data:")
                for key, value in parsed_data.items():
                    print(f"  {key}: {value}")
            else:
                print(f"❌ Parsing failed: {error_msg}")
                
                # Test friendly missing data request generation
                if parsed_data and any(parsed_data.values()):
                    print("🤖 Testing friendly missing data request...")
                    try:
                        friendly_msg = openai_parser.generate_missing_data_request(test_case['input'], parsed_data)
                        print(f"💬 Generated message: {friendly_msg}")
                    except Exception as friendly_error:
                        print(f"❌ Failed to generate friendly message: {str(friendly_error)}")
                
        except Exception as e:
            print(f"💥 Exception occurred: {str(e)}")
    
    print("\n" + "=" * 50)
    print("🏁 Test completed!")

def test_missing_data_generation():
    """Test the missing data request generation"""
    
    print("\n🧪 Testing Missing Data Request Generation")
    print("=" * 50)
    
    if not OPENAI_ENABLED:
        print("❌ OpenAI is not enabled.")
        return
    
    test_cases = [
        {
            "name": "Only product name",
            "input": "Красные рубашки",
            "partial_data": {"product_name": "рубашки", "product_color": "красные"}
        },
        {
            "name": "Product with quantity but no sizes",
            "input": "Синие джинсы 100 штук",
            "partial_data": {"product_name": "джинсы", "product_color": "синие", "total_amount": 100}
        },
        {
            "name": "Complete except dates",
            "input": "Белые футболки 50 штук Москва S-25 M-25",
            "partial_data": {
                "product_name": "футболки", 
                "product_color": "белые", 
                "total_amount": 50,
                "warehouse_sizes": "Москва: S-25 M-25"
            }
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n🔍 Test {i}: {test_case['name']}")
        print(f"Input: {test_case['input']}")
        print(f"Partial data: {test_case['partial_data']}")
        
        try:
            friendly_msg = openai_parser.generate_missing_data_request(
                test_case['input'], 
                test_case['partial_data']
            )
            print(f"💬 Generated message: {friendly_msg}")
        except Exception as e:
            print(f"❌ Failed to generate message: {str(e)}")
    
    print("\n" + "=" * 50)
    print("🏁 Missing data test completed!")

if __name__ == "__main__":
    test_openai_parser()
    test_missing_data_generation()
