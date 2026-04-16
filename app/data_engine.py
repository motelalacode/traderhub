from kiteconnect import KiteTicker, KiteConnect
from config import API_KEY, ACCESS_TOKEN
from signal_engine import usdinr_data, crude_data, process
from db import insert_price

USDINR = 123456
CRUDE = 654321

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

kws = KiteTicker(API_KEY, ACCESS_TOKEN)

def on_ticks(ws, ticks):
    for t in ticks:
        price = t["last_price"]

        if t["instrument_token"] == USDINR:
            usdinr_data.append(price)
            insert_price("USDINR", price)

        elif t["instrument_token"] == CRUDE:
            crude_data.append(price)
            insert_price("CRUDE", price)

    process()

def on_connect(ws, response):
    ws.subscribe([USDINR, CRUDE])
    ws.set_mode(ws.MODE_LTP, [USDINR, CRUDE])

kws.on_ticks = on_ticks
kws.on_connect = on_connect

def start():
    kws.connect()