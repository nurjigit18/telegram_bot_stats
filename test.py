from dotenv import load_dotenv
import os

load_dotenv()
print(os.getenv('GOOGLE_CREDS_JSON'))
print(os.getenv('SHEET_ID'))