# app/alert_engine.py
import requests

from app.config import CHAT_ID, TELEGRAM_TOKEN

def send_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
