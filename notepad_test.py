from kiteconnect import KiteConnect
from app.config import KITE_API_KEY

kite = KiteConnect(api_key=KITE_API_KEY)
print("Open this URL in browser:\n")
print(kite.login_url())
