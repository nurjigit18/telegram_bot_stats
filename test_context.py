#!/usr/bin/env python3
"""
Test script for the context window system
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models.user_data import user_data
from utils.openai_parser import openai_parser

def test_context_window():
    """Test the context window functionality"""
    print("🧪 Testing Context Window System")
    print("=" * 50)
    
    # Test user ID
    test_user_id = 12345
    
    # Test 1: Initialize user and add messages
    print("\n1. Testing message addition to context...")
    user_data.initialize_user(test_user_id)
    
    # Simulate a conversation
    user_data.add_message_to_context(test_user_id, "user", "/save")
    user_data.add_message_to_context(test_user_id, "assistant", "Please provide product details...")
    user_data.add_message_to_context(test_user_id, "user", "Red shirts, 100 pieces")
    user_data.add_message_to_context(test_user_id, "assistant", "I need more information about sizes and warehouse")
    user_data.add_message_to_context(test_user_id, "user", "Kazan warehouse: S-50 M-30 L-20")
    
    # Test 2: Get context messages
    print("\n2. Testing context retrieval...")
    context_messages = user_data.get_context_messages(test_user_id)
    print(f"Retrieved {len(context_messages)} messages from context:")
    for i, msg in enumerate(context_messages, 1):
        role_emoji = "👤" if msg["role"] == "user" else "🤖"
        print(f"  {i}. {role_emoji} {msg['content'][:50]}...")
    
    # Test 3: Context summary
    print("\n3. Testing context summary...")
    summary = user_data.get_context_summary(test_user_id)
    print("Context Summary:")
    print(summary)
    
    # Test 4: Test OpenAI parser with context (if enabled)
    print("\n4. Testing OpenAI parser with context...")
    try:
        success, parsed_data, error_msg = openai_parser.parse_product_data(
            "Add dates: shipped 15/01/2025, arriving 20/01/2025", 
            user_id=test_user_id
        )
        if success:
            print("✅ OpenAI successfully used context!")
            print(f"Parsed data: {parsed_data}")
        else:
            print(f"❌ OpenAI parsing failed: {error_msg}")
    except Exception as e:
        print(f"⚠️ OpenAI test skipped: {e}")
    
    # Test 5: Context window size limit
    print("\n5. Testing context window size limit...")
    initial_count = len(user_data.get_context_messages(test_user_id))
    
    # Add more messages than the window size
    for i in range(15):  # More than the default window size of 10
        user_data.add_message_to_context(test_user_id, "user", f"Test message {i}")
    
    final_count = len(user_data.get_context_messages(test_user_id))
    print(f"Initial messages: {initial_count}")
    print(f"Final messages after adding 15 more: {final_count}")
    print(f"Window size limit working: {final_count <= user_data.context_window_size}")
    
    # Test 6: Context cleanup
    print("\n6. Testing context cleanup...")
    user_data.clear_context(test_user_id)
    cleared_count = len(user_data.get_context_messages(test_user_id))
    print(f"Messages after clearing context: {cleared_count}")
    print(f"Context cleared successfully: {cleared_count == 0}")
    
    # Test 7: Cleanup user data
    print("\n7. Testing user data cleanup...")
    user_data.clear_user_data(test_user_id)
    has_user_after_clear = user_data.has_user(test_user_id)
    print(f"User exists after cleanup: {has_user_after_clear}")
    print(f"User data cleared successfully: {not has_user_after_clear}")
    
    print("\n" + "=" * 50)
    print("✅ Context Window System Test Complete!")

if __name__ == "__main__":
    test_context_window()
