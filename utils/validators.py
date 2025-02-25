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
    """Validate size amounts format"""
    match = re.match(SIZE_PATTERN, size_str.strip())
    if match:
        return True
    return False

def parse_size_amounts(size_str):
    """Parse size amounts into individual values"""
    match = re.match(SIZE_PATTERN, size_str.strip())
    if match:
        return {
            "s_amount": int(match.group(1)),
            "m_amount": int(match.group(2)),
            "l_amount": int(match.group(3))
        }
    return None

def standardize_date(date_str):
    """Convert date to standard format"""
    # Handle both . and / as separators
    date_str = date_str.replace('.', '/')
    day, month, year = date_str.split('/')
    return f"{day.zfill(2)}/{month.zfill(2)}/{year}"
