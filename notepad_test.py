
from kiteconnect import KiteConnect

kite = KiteConnect(api_key="2vbfmuw58qhevltntn")

print("Open this URL in browser:\n")
print(kite.login_url())