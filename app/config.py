# app/config.py
import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)

KITE_API_KEY = os.getenv("KITE_API_KEY")
KITE_API_SECRET = os.getenv("KITE_API_SECRET")
KITE_ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")

# Backward-compatible aliases for modules that use the shorter names.
API_KEY = KITE_API_KEY
ACCESS_TOKEN = KITE_ACCESS_TOKEN

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
}


def get_runtime_config():
    values = dotenv_values(ENV_PATH)
    return {
        "KITE_API_KEY": values.get("KITE_API_KEY") or KITE_API_KEY,
        "KITE_API_SECRET": values.get("KITE_API_SECRET") or KITE_API_SECRET,
        "KITE_ACCESS_TOKEN": values.get("KITE_ACCESS_TOKEN") or KITE_ACCESS_TOKEN,
    }
