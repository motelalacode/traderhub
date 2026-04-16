# app/indicators.py
import pandas as pd

def apply_indicators(df):
    df["ema9"] = df["price"].ewm(span=9).mean()
    df["ema21"] = df["price"].ewm(span=21).mean()

    df["vwap"] = (df["price"] * 1).cumsum() / (1).cumsum()
    return df