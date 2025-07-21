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
            "name": "Russian natural language",
            "input": "Привет! Мне нужно сохранить данные о красных рубашках. У нас есть 100 штук, которые будут распределены по складу в Казани: 50 размера S, 25 размера M и 25 размера L. Отправляем 12 декабря 2021 года, а прибыть должны примерно 15 декабря."
        },
        {
            "name": "English natural language",
            "input": "I need to save data about blue t-shirts. We have 200 pieces distributed across warehouses: Moscow warehouse has 80 size L and 70 size XL, Kazan warehouse has 50 size M. Shipping on 25/01/2024, estimated arrival 30/01/2024."
        },
        {
            "name": "Mixed format",
            "input": "Джинсы черные, всего 150 штук. Склад Москва: M-60 L-40, склад СПб: S-30 XL-20. Дата отправки: 15.03.2024, прибытие: 20.03.2024"
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
                
        except Exception as e:
            print(f"💥 Exception occurred: {str(e)}")
    
    print("\n" + "=" * 50)
    print("🏁 Test completed!")

if __name__ == "__main__":
    test_openai_parser()
