import os
# from dotenv import load_dotenv

# # Load environment variables
# load_dotenv()

# Get environment variables
BOT_TOKEN = os.getenv('TELEGRAM_TOKEN')
GOOGLE_CREDS_FILE = os.getenv('GOOGLE_CREDS_JSON')
SHEET_ID = os.getenv('SHEET_ID')

# Validate environment variables
if not all([BOT_TOKEN, GOOGLE_CREDS_FILE, SHEET_ID]):
    raise ValueError("Please set TELEGRAM_TOKEN, GOOGLE_CREDS_FILE, and SHEET_ID in your .env file")

# ADMIN_USER_USERNAMES = ["nKurm", "AlinaK2205", "shamieva17", "agrmmsv"]  # Replace with actual admin user IDs
ADMIN_USER_USERNAMES = ["nKurm"]  # Replace with actual admin user IDs


SIZE_PATTERN = r'([a-zA-Z]+)\s*:\s*(\d+)'

