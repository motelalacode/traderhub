# app/signal_engine.py
import numpy as np
import pandas as pd

from app.ai_engine import get_ai_insight
from app.alert_engine import send_alert
from app.db import insert_signal
from app.indicators import apply_indicators

usdinr = []
crude = []

WINDOW = 20


def process():
    if len(usdinr) < WINDOW or len(crude) < WINDOW:
        return

    df_u = apply_indicators(pd.DataFrame(usdinr, columns=["price"]))
    df_c = apply_indicators(pd.DataFrame(crude, columns=["price"]))

    u_change = (df_u.iloc[-1].price - df_u.iloc[-WINDOW].price) / df_u.iloc[-WINDOW].price * 100
    c_change = (df_c.iloc[-1].price - df_c.iloc[-WINDOW].price) / df_c.iloc[-WINDOW].price * 100

    corr = df_u["price"].corr(df_c["price"])

    trend_ok = (
        df_u.iloc[-1].ema9 > df_u.iloc[-1].ema21
        and df_c.iloc[-1].ema9 > df_c.iloc[-1].ema21
        and df_u.iloc[-1].price > df_u.iloc[-1].vwap
        and df_c.iloc[-1].price > df_c.iloc[-1].vwap
    )

    if abs(u_change) > 0.5 and abs(c_change) > 0.5:
        insight = get_ai_insight(u_change, c_change, corr)

        if np.sign(u_change) == np.sign(c_change) and corr > 0.6 and trend_ok:
            msg = (
                "SYNC ALERT\n"
                f"USDINR: {u_change:.2f}%\n"
                f"CRUDE: {c_change:.2f}%\n"
                f"Corr: {corr:.2f}\n\n"
                f"{insight}"
            )
            send_alert(msg)
            insert_signal("SYNC", u_change, c_change, corr, insight)
        elif np.sign(u_change) != np.sign(c_change):
            msg = (
                "DIVERGENCE\n"
                f"USDINR: {u_change:.2f}%\n"
                f"CRUDE: {c_change:.2f}%\n\n"
                f"{insight}"
            )
            send_alert(msg)
            insert_signal("DIV", u_change, c_change, corr, insight)
