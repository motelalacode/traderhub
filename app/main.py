from flask import Flask, redirect, request
from kiteconnect import KiteConnect
from app.config import KITE_API_KEY, KITE_API_SECRET, KITE_ACCESS_TOKEN

app = Flask(__name__)

kite = KiteConnect(api_key=KITE_API_KEY)


@app.route("/")
def home():
    return '<h2>TraderHub</h2><a href="/login">Login with Zerodha</a>'


@app.route("/login")
def login():
    return redirect(kite.login_url())


@app.route("/callback")
def callback():
    request_token = request.args.get("request_token")

    data = kite.generate_session(
        request_token,
        api_secret=KITE_API_SECRET
    )

    access_token = data["access_token"]

    # 🔥 Print new token (manually update .env)
    print("NEW ACCESS TOKEN:", access_token)

    return f"""
    <h2>Login Successful ✅</h2>
    <p>Copy token from terminal & update .env</p>
    """


@app.route("/ltp")
def ltp():
    # 🔥 Token from .env
    kite.set_access_token(KITE_ACCESS_TOKEN)

    data = kite.ltp("NSE:INFY")
    return data


if __name__ == "__main__":
    app.run(port=8000, debug=True)