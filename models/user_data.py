# models/user_data.py
from datetime import datetime, timedelta
import pytz

class UserData:
    def __init__(self):
        self.data = {}  # Internal dictionary to store user data
        self.context_window_size = 10  # Number of messages to keep in context
        self.context_expiry_hours = 24  # Context expires after 24 hours

    def initialize_user(self, user_id):
        """Initialize user data for a new session."""
        self.data[user_id] = {
            "current_step": 0,
            "current_action": None,
            "data": {},
            "conversation_history": [],
            "last_activity": datetime.now(pytz.timezone('Asia/Bishkek'))
        }

    def initialize_form_data(self, user_id):
        """Initialize form data structure for a user."""
        if user_id in self.data:
            self.data[user_id]["data"] = {
                "product_name": None,
                "shipment_date": None,
                "estimated_arrival": None,
                "product_color": None,
                "total_amount": None,
                "warehouse": None,
                "s_amount": None,
                "m_amount": None,
                "l_amount": None
            }

    def update_form_data(self, user_id, field, value):
        """Update a specific field in the user's form data."""
        if user_id in self.data:
            self.data[user_id]["data"][field] = value

    def get_form_data(self, user_id):
        """Get all form data for a user."""
        if user_id in self.data:
            return self.data[user_id]["data"]
        return None

    def get_user_data(self, user_id):
        """Get user data by user ID."""
        return self.data.get(user_id)

    def update_user_data(self, user_id, key, value):
        """Update a specific field in the user's data."""
        if user_id in self.data:
            self.data[user_id][key] = value

    def clear_user_data(self, user_id):
        """Clear user data after the session is complete."""
        if user_id in self.data:
            del self.data[user_id]

    def get_current_step(self, user_id):
        """Get the current step for a user."""
        if user_id in self.data:
            return self.data[user_id].get("current_step")
        return None

    def set_current_step(self, user_id, step):
        """Set the current step for a user."""
        if user_id in self.data:
            self.data[user_id]["current_step"] = step

    def get_current_action(self, user_id):
        """Get the current action for a user."""
        if user_id in self.data:
            return self.data[user_id].get("current_action")
        return None

    def set_current_action(self, user_id, action):
        """Set the current action for a user."""
        if user_id in self.data:
            self.data[user_id]["current_action"] = action

    def has_user(self, user_id):
        """Check if a user ID exists in the data."""
        return user_id in self.data
    
    def set_row_index(self, user_id, row_index):
        """Set the row index for a user."""
        if user_id in self.data:
            self.data[user_id]["row_index"] = row_index
        else:
            self.data[user_id] = {"row_index": row_index}

    def get_row_index(self, user_id):
        """Get the row index for a user."""
        if user_id in self.data:
            return self.data[user_id].get("row_index")
        return None

    def add_message_to_context(self, user_id, role, content):
        """Add a message to the user's conversation context."""
        if user_id not in self.data:
            self.initialize_user(user_id)
        
        # Update last activity
        self.data[user_id]["last_activity"] = datetime.now(pytz.timezone('Asia/Bishkek'))
        
        # Add message to conversation history
        message = {
            "role": role,  # "user" or "assistant"
            "content": content,
            "timestamp": datetime.now(pytz.timezone('Asia/Bishkek'))
        }
        
        self.data[user_id]["conversation_history"].append(message)
        
        # Keep only the last N messages within the context window
        if len(self.data[user_id]["conversation_history"]) > self.context_window_size:
            self.data[user_id]["conversation_history"] = self.data[user_id]["conversation_history"][-self.context_window_size:]

    def get_context_messages(self, user_id):
        """Get conversation context formatted for OpenAI API."""
        if user_id not in self.data:
            return []
        
        # Clean up expired context first
        self._cleanup_expired_context(user_id)
        
        # Return messages in OpenAI format (without timestamp)
        messages = []
        for msg in self.data[user_id].get("conversation_history", []):
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        
        return messages

    def clear_context(self, user_id):
        """Clear conversation context for a user."""
        if user_id in self.data:
            self.data[user_id]["conversation_history"] = []

    def _cleanup_expired_context(self, user_id):
        """Remove expired messages from context."""
        if user_id not in self.data:
            return
        
        current_time = datetime.now(pytz.timezone('Asia/Bishkek'))
        expiry_time = current_time - timedelta(hours=self.context_expiry_hours)
        
        # Filter out expired messages
        valid_messages = []
        for msg in self.data[user_id].get("conversation_history", []):
            if msg["timestamp"] > expiry_time:
                valid_messages.append(msg)
        
        self.data[user_id]["conversation_history"] = valid_messages

    def cleanup_all_expired_contexts(self):
        """Clean up expired contexts for all users."""
        for user_id in list(self.data.keys()):
            self._cleanup_expired_context(user_id)
            
            # Remove users with no recent activity
            if user_id in self.data:
                last_activity = self.data[user_id].get("last_activity")
                if last_activity:
                    current_time = datetime.now(pytz.timezone('Asia/Bishkek'))
                    if current_time - last_activity > timedelta(hours=self.context_expiry_hours):
                        # Only clear if no active session
                        if not self.data[user_id].get("current_action"):
                            del self.data[user_id]

    def get_context_summary(self, user_id):
        """Get a summary of the current context for debugging."""
        if user_id not in self.data:
            return "No context available"
        
        history = self.data[user_id].get("conversation_history", [])
        if not history:
            return "Empty conversation history"
        
        summary = f"Context: {len(history)} messages\n"
        for i, msg in enumerate(history[-3:], 1):  # Show last 3 messages
            role_emoji = "👤" if msg["role"] == "user" else "🤖"
            content_preview = msg["content"][:50] + "..." if len(msg["content"]) > 50 else msg["content"]
            summary += f"{role_emoji} {content_preview}\n"
        
        return summary

# Create a singleton instance
user_data = UserData()
