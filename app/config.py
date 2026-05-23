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
GOOGLE_SITE_VERIFICATION = os.getenv("GOOGLE_SITE_VERIFICATION") or os.getenv("GOOGLE_SEARCH_CONSOLE_VERIFICATION")
BING_SITE_VERIFICATION = os.getenv("BING_SITE_VERIFICATION") or os.getenv("BING_WEBMASTER_VERIFICATION")
SEARCH_CONSOLE_PROPERTY = os.getenv("SEARCH_CONSOLE_PROPERTY")
BING_WEBMASTER_PROPERTY = os.getenv("BING_WEBMASTER_PROPERTY")
GA4_MEASUREMENT_ID = os.getenv("GA4_MEASUREMENT_ID") or os.getenv("GOOGLE_ANALYTICS_ID") or os.getenv("GA_MEASUREMENT_ID")
ADSENSE_CLIENT = os.getenv("ADSENSE_CLIENT") or os.getenv("ADSENSE_PUBLISHER_ID")
INDEXNOW_KEY = os.getenv("INDEXNOW_KEY")

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
        "GOOGLE_SITE_VERIFICATION": values.get("GOOGLE_SITE_VERIFICATION") or values.get("GOOGLE_SEARCH_CONSOLE_VERIFICATION") or GOOGLE_SITE_VERIFICATION,
        "BING_SITE_VERIFICATION": values.get("BING_SITE_VERIFICATION") or values.get("BING_WEBMASTER_VERIFICATION") or BING_SITE_VERIFICATION,
        "SEARCH_CONSOLE_PROPERTY": values.get("SEARCH_CONSOLE_PROPERTY") or SEARCH_CONSOLE_PROPERTY,
        "BING_WEBMASTER_PROPERTY": values.get("BING_WEBMASTER_PROPERTY") or BING_WEBMASTER_PROPERTY,
        "GA4_MEASUREMENT_ID": values.get("GA4_MEASUREMENT_ID") or values.get("GOOGLE_ANALYTICS_ID") or values.get("GA_MEASUREMENT_ID") or GA4_MEASUREMENT_ID,
        "ADSENSE_CLIENT": values.get("ADSENSE_CLIENT") or values.get("ADSENSE_PUBLISHER_ID") or ADSENSE_CLIENT,
        "INDEXNOW_KEY": values.get("INDEXNOW_KEY") or INDEXNOW_KEY,
    }
