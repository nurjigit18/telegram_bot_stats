# Add this to your utils/validators.py file

import re
from datetime import datetime

def validate_warehouse_sizes(warehouse_sizes_str):
    """
    Validate warehouse and sizes format
    
    Valid formats:
    - Single warehouse: "Казань: S-50 M-25 L-25"
    - Multiple warehouses: "Казань: S-30 M-40, Москва: L-50 XL-80"
    - Extended sizes: "Казань: 4XL-30 5XL-40 6XL-20"
    """
    try:
        if not warehouse_sizes_str or not warehouse_sizes_str.strip():
            return False
        
        # Split by comma for multiple warehouses
        warehouse_parts = [part.strip() for part in warehouse_sizes_str.split(',')]
        
        for warehouse_part in warehouse_parts:
            if ':' not in warehouse_part:
                return False
            
            warehouse_name, sizes_str = warehouse_part.split(':', 1)
            warehouse_name = warehouse_name.strip()
            sizes_str = sizes_str.strip()
            
            if not warehouse_name or not sizes_str:
                return False
            
            # Validate sizes format (S-50 M-25 L-25)
            size_parts = sizes_str.split()
            if not size_parts:
                return False
            
            for size_part in size_parts:
                if '-' not in size_part:
                    return False
                
                size, quantity_str = size_part.split('-', 1)
                size = size.strip()
                quantity_str = quantity_str.strip()
                
                # Validate size format - Updated to allow numeric prefixes
                # Valid sizes: S, M, L, XL, XXL, XXXL, 2XL, 3XL, 4XL, 5XL, 6XL, 7XL, etc.
                if not size or not re.match(r'^\d*[XSML]+$', size.upper()):
                    return False
                
                # Validate quantity (should be positive integer)
                try:
                    quantity = int(quantity_str)
                    if quantity <= 0:
                        return False
                except ValueError:
                    return False
        
        return True
        
    except Exception:
        return False

def parse_warehouse_sizes(warehouse_sizes_str):
    """
    Parse warehouse and sizes string into structured data
    
    Returns: List of tuples [(warehouse_name, {size: quantity})]
    """
    try:
        warehouse_data = []
        
        # Split by comma for multiple warehouses
        warehouse_parts = [part.strip() for part in warehouse_sizes_str.split(',')]
        
        for warehouse_part in warehouse_parts:
            warehouse_name, sizes_str = warehouse_part.split(':', 1)
            warehouse_name = warehouse_name.strip()
            sizes_str = sizes_str.strip()
            
            # Parse sizes (format: S-50 M-25 L-25)
            sizes = {}
            size_parts = sizes_str.split()
            
            for size_part in size_parts:
                size, quantity_str = size_part.split('-', 1)
                size = size.strip().upper()
                quantity = int(quantity_str.strip())
                sizes[size] = quantity
            
            warehouse_data.append((warehouse_name, sizes))
        
        return warehouse_data
        
    except Exception:
        return None

# Your existing validators remain the same
def validate_date(date_str):
    """Validate date format (dd/mm/yyyy or dd.mm.yyyy)"""
    if not date_str:
        return False
    
    # Try both formats
    formats = ['%d/%m/%Y', '%d.%m.%Y']
    
    for fmt in formats:
        try:
            datetime.strptime(date_str, fmt)
            return True
        except ValueError:
            continue
    
    return False

def validate_amount(amount_str):
    """Validate amount is a positive integer"""
    try:
        amount = int(amount_str)
        return amount > 0
    except ValueError:
        return False

def validate_size_amounts(size_amounts_str):
    """Validate size amounts format (S: 50 M: 25 L: 50)"""
    if not size_amounts_str:
        return False
    
    # Pattern to match size amounts like "S: 50 M: 25 L: 50"
    pattern = r'^[A-Za-z]+\s*:\s*\d+(\s+[A-Za-z]+\s*:\s*\d+)*$'
    return bool(re.match(pattern, size_amounts_str.strip()))

def parse_size_amounts(size_amounts_str):
    """Parse size amounts string into dictionary"""
    sizes = {}
    
    # Split by spaces and process pairs
    parts = size_amounts_str.split()
    
    i = 0
    while i < len(parts):
        if i + 2 < len(parts) and parts[i + 1] == ':':
            size = parts[i].upper()
            quantity = int(parts[i + 2])
            sizes[size] = quantity
            i += 3
        else:
            i += 1
    
    return sizes

def standardize_date(date_str):
    """Convert date to standard format (dd/mm/yyyy)"""
    formats = ['%d/%m/%Y', '%d.%m.%Y']
    
    for fmt in formats:
        try:
            date_obj = datetime.strptime(date_str, fmt)
            return date_obj.strftime('%d/%m/%Y')
        except ValueError:
            continue
    
    return date_str  # Return original if can't parse

# Test function to verify the fix
def test_size_validation():
    """Test the size validation with various formats"""
    test_cases = [
        # Valid cases
        ("Казань: S-50 M-25 L-25", True),
        ("Казань: S-30 M-40 , Москва: L-50 XL-80", True),
        ("Казань: 4XL-30 5XL-40 6XL-20", True),
        ("Казань: S-30 M-40 6XL-20 , Москва: L-50 XL-80 7XL-50", True),
        ("Москва: XL-100 2XL-50 3XL-25", True),
        ("Тест: XXL-25 XXXL-15", True),
        
        # Invalid cases
        ("", False),
        ("Казань S-50", False),
        ("Казань: ", False),
        ("Казань: S50", False),
        ("Казань: S-", False),
        ("Казань: -50", False),
        ("Казань: ABC-50", False),
    ]
    
    print("Testing warehouse sizes validation:")
    for test_input, expected in test_cases:
        result = validate_warehouse_sizes(test_input)
        status = "✓" if result == expected else "✗"
        print(f"{status} '{test_input}' -> {result} (expected {expected})")

if __name__ == "__main__":
    test_size_validation()