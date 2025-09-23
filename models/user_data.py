from dataclasses import dataclass, field
from typing import Dict, List, Any


class UserData:
    def __init__(self):
        self.data = {}
    SIZE_COLS = ["XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL", "5XL", "6XL", "7XL", "8XL"]

    def initialize_user(self, user_id):
        """Create a user record only if it doesn't exist (do not overwrite!)."""
        if user_id not in self.data:
            self.data[user_id] = {
                "current_step": 0,
                "current_action": None,
                "data": {}
            }

    def initialize_form_data(self, user_id):
        """Prepare form payload but only replace if empty/missing."""
        self.initialize_user(user_id)
        cur = self.data[user_id].get("data")
        if not isinstance(cur, dict) or not cur:
            payload = {
                "shipment_id": None,
                "bag_id": None,
                "warehouse": None,
                "product_name": None,
                "color": None,
                "shipment_date": None,
                "estimated_arrival": None,
                "actual_arrival": "",
                "total_amount": 0,
                "status": "в обработке",
            }
            for k in self.SIZE_COLS:
                payload[k] = 0
            self.data[user_id]["data"] = payload

    # ... keep the rest as-is ...

    def get_state(self, user_id):
        """Return the whole per-user dict; always initialized."""
        self.initialize_user(user_id)
        return self.data[user_id]


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

@dataclass
class Bag:
    bag_id: str = ""
    sizes: Dict[str, int] = field(default_factory=dict)  # e.g. {"XS": 5, "S": 8, ...}

@dataclass
class SessionState:
    step: str = "start"

    # existing fields you already use (examples, keep your actual ones)
    warehouse: str | None = None
    model: str | None = None
    color: str | None = None

    # NEW: shipment/bag context
    shipment_id: str | None = None
    bags: List[Bag] = field(default_factory=list)         # committed bags of this shipment
    current_bag: Bag = field(default_factory=Bag)         # in-progress bag (sizes typed so far)

    # (optional) any other fields you had
    extra: Dict[str, Any] = field(default_factory=dict)


def reset_shipment_state(s: SessionState) -> None:
    s.shipment_id = None
    s.bags = []
    s.current_bag = Bag()


# Create a singleton instance
user_data = UserData()