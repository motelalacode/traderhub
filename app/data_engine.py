from kiteconnect import KiteConnect, KiteTicker

from app.config import ACCESS_TOKEN, API_KEY
from app.db import insert_price
from app.signal_engine import crude, process, usdinr

USDINR = 262915
CRUDE = 125002247


def validate_runtime_config():
    issues = []

    if not API_KEY:
        issues.append("KITE_API_KEY is missing in .env")

    if not ACCESS_TOKEN:
        issues.append("KITE_ACCESS_TOKEN is missing in .env")

    if USDINR == 123456 or CRUDE == 654321:
        issues.append("Instrument tokens are still placeholders in app/data_engine.py")

    if issues:
        print("Startup check failed:")
        for issue in issues:
            print(f"- {issue}")
        return False

    return True


kite = KiteConnect(api_key=API_KEY)
if ACCESS_TOKEN:
    kite.set_access_token(ACCESS_TOKEN)

kws = KiteTicker(API_KEY, ACCESS_TOKEN)


def on_ticks(ws, ticks):
    for tick in ticks:
        price = tick["last_price"]

        if tick["instrument_token"] == USDINR:
            usdinr.append(price)
            insert_price("USDINR", price)
        elif tick["instrument_token"] == CRUDE:
            crude.append(price)
            insert_price("CRUDE", price)

    process()


def on_connect(ws, response):
    print("WebSocket connected to Zerodha.")
    print(f"Subscribing to tokens: USDINR={USDINR}, CRUDE={CRUDE}")
    ws.subscribe([USDINR, CRUDE])
    ws.set_mode(ws.MODE_LTP, [USDINR, CRUDE])


def on_close(ws, code, reason):
    print(f"Connection closed: {code} - {reason}")


def on_error(ws, code, reason):
    print(f"Connection error: {code} - {reason}")
    if code == 1006 and "403" in str(reason):
        print("Zerodha rejected the WebSocket login.")
        print("Check that KITE_ACCESS_TOKEN is fresh and matches KITE_API_KEY.")


def on_reconnect(ws, attempts_count):
    print(f"Reconnecting to Zerodha... attempt {attempts_count}")


def on_noreconnect(ws):
    print("Zerodha WebSocket stopped reconnecting.")


kws.on_ticks = on_ticks
kws.on_connect = on_connect
kws.on_close = on_close
kws.on_error = on_error
kws.on_reconnect = on_reconnect
kws.on_noreconnect = on_noreconnect


def start():
    if not validate_runtime_config():
        return

    print("Starting live data engine...")
    kws.connect()


if __name__ == "__main__":
    start()
