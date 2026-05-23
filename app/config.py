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

UPSTOX_CLIENT_ID = os.getenv("UPSTOX_CLIENT_ID")
UPSTOX_CLIENT_SECRET = os.getenv("UPSTOX_CLIENT_SECRET")
UPSTOX_REDIRECT_URI = os.getenv("UPSTOX_REDIRECT_URI")
UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN")
UPSTOX_API_BASE_URL = os.getenv("UPSTOX_API_BASE_URL") or "https://api.upstox.com/v2"

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
        "UPSTOX_CLIENT_ID": values.get("UPSTOX_CLIENT_ID") or UPSTOX_CLIENT_ID,
        "UPSTOX_CLIENT_SECRET": values.get("UPSTOX_CLIENT_SECRET") or UPSTOX_CLIENT_SECRET,
        "UPSTOX_REDIRECT_URI": values.get("UPSTOX_REDIRECT_URI") or UPSTOX_REDIRECT_URI,
        "UPSTOX_ACCESS_TOKEN": values.get("UPSTOX_ACCESS_TOKEN") or UPSTOX_ACCESS_TOKEN,
        "UPSTOX_API_BASE_URL": values.get("UPSTOX_API_BASE_URL") or UPSTOX_API_BASE_URL,
        "TELEGRAM_TOKEN": values.get("TELEGRAM_TOKEN") or TELEGRAM_TOKEN,
        "TELEGRAM_CHAT_ID": values.get("TELEGRAM_CHAT_ID") or CHAT_ID,
    }
