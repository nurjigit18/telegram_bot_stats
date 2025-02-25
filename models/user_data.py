# models/user_data.py
class UserData:
    def __init__(self):
        self.data = {}  # Internal dictionary to store user data

    def initialize_user(self, user_id):
        """Initialize user data for a new session."""
        self.data[user_id] = {
            "current_step": 0,
            "current_action": None,
            "data": {}
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

# Create a singleton instance
user_data = UserData()