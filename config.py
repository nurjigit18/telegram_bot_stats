import os
from dotenv import load_dotenv

# Auto-detect if we're running locally
if os.path.exists('.env'):
    load_dotenv()
    print("Loading environment from .env file (local development)")
else:
    print("Using system environment variables (production)")

# Get environment variables
BOT_TOKEN = os.getenv('TELEGRAM_TOKEN')
GOOGLE_CREDS_FILE = os.getenv('GOOGLE_CREDS_JSON')  # Note: using GOOGLE_CREDS_JSON from .env
SHEET_ID = os.getenv('SHEET_ID')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Debug: Print what we actually found (remove in production)
print(f"BOT_TOKEN: {'✓' if BOT_TOKEN else '✗'}")
print(f"GOOGLE_CREDS_FILE: {'✓' if GOOGLE_CREDS_FILE else '✗'}")
print(f"SHEET_ID: {'✓' if SHEET_ID else '✗'}")
print(f"OPENAI_API_KEY: {'✓' if OPENAI_API_KEY else '✗'}")

# Validate environment variables (fix the error message)
if not all([BOT_TOKEN, GOOGLE_CREDS_FILE, SHEET_ID]):
    missing_vars = []
    if not BOT_TOKEN:
        missing_vars.append('TELEGRAM_TOKEN')
    if not GOOGLE_CREDS_FILE:
        missing_vars.append('GOOGLE_CREDS_JSON')
    if not SHEET_ID:
        missing_vars.append('SHEET_ID')
    
    raise ValueError(f"Please set {', '.join(missing_vars)} in your .env file")

# OpenAI configuration (optional - will fall back to manual parsing if not set)
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-3.5-turbo')
OPENAI_ENABLED = bool(OPENAI_API_KEY)

# ADMIN_USER_USERNAMES = ["nKurm", "AlinaK2205", "shamieva17", "agrmmsv"]  # Replace with actual admin user IDs
ADMIN_USER_USERNAMES = ["nKurm"]  # Replace with actual admin user IDs

SIZE_PATTERN = r'([a-zA-Z]+)\s*:\s*(\d+)'