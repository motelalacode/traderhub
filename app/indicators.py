# app/indicators.py
import pandas as pd

def apply_indicators(df):
    df["ema9"] = df["price"].ewm(span=9).mean()
    df["ema21"] = df["price"].ewm(span=21).mean()

    # Use a cumulative average until per-tick volume is available.
    df["vwap"] = df["price"].expanding().mean()
    return df
