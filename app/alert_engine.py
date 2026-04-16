# app/alert_engine.py
import requests
from config import TELEGRAM_TOKEN, CHAT_ID

def send_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})