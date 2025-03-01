import re
from constants import DATE_PATTERN, SIZE_PATTERN

def validate_date(date_str):
    """Validate date format"""
    return re.match(DATE_PATTERN, date_str)

def validate_amount(amount_str):
    """Validate that the amount is a positive integer"""
    try:
        amount = int(amount_str)
        return amount > 0
    except ValueError:
        return False

def validate_size_amounts(size_str):
    """Validate size amounts format - accepts any letter-based sizes"""
    # Check if there's at least one valid size:amount pair
    matches = re.findall(SIZE_PATTERN, size_str)
    return len(matches) > 0

def parse_size_amounts(size_str):
    """Parse size amounts into a single string value"""
    matches = re.findall(SIZE_PATTERN, size_str)
    
    if not matches:
        return {}
    
    # Format all sizes as a single string
    formatted_sizes = ", ".join([f"{size.upper()}: {amount}" for size, amount in matches])
    return {"sizes_data": formatted_sizes}

def standardize_date(date_str):
    """Convert date to standard format"""
    # Handle both . and / as separators
    date_str = date_str.replace('.', '/')
    day, month, year = date_str.split('/')
    return f"{day.zfill(2)}/{month.zfill(2)}/{year}"
