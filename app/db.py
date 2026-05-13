# app/db.py
from datetime import datetime

import psycopg2

from app.config import DB_CONFIG


def get_connection():
    return psycopg2.connect(
        host=DB_CONFIG["host"],
        database=DB_CONFIG["dbname"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        port=DB_CONFIG["port"] or 5432,
    )


def insert_price(symbol, price):
    try:
        conn = get_connection()
        cur = conn.cursor()

        query = """
        INSERT INTO price_data (symbol, timestamp, price)
        VALUES (%s, %s, %s);
        """

        cur.execute(query, (symbol, datetime.now(), price))

        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        print("DB Price Insert Error:", e)


def save_signal(signal):
    try:
        conn = get_connection()
        cur = conn.cursor()

        query = """
        INSERT INTO signals (
            signal_type, instrument, confidence_score,
            usdinr_price, crude_price,
            trend_usdinr, trend_crude,
            correlation_value, divergence_flag,
            ai_reason, timestamp
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id;
        """

        cur.execute(
            query,
            (
                signal["type"],
                signal["instrument"],
                signal["confidence"],
                signal["usdinr_price"],
                signal["crude_price"],
                signal["trend_usdinr"],
                signal["trend_crude"],
                signal["correlation"],
                signal["divergence"],
                signal["reason"],
                datetime.now(),
            ),
        )

        signal_id = cur.fetchone()[0]

        conn.commit()
        cur.close()
        conn.close()

        return signal_id

    except Exception as e:
        print("DB Signal Insert Error:", e)
        return None


def insert_signal(signal_type, usdinr_change, crude_change, corr, insight):
    signal = {
        "type": signal_type,
        "instrument": "CRUDE",
        "confidence": round(abs(corr), 2),
        "usdinr_price": usdinr_change,
        "crude_price": crude_change,
        "trend_usdinr": "UP" if usdinr_change >= 0 else "DOWN",
        "trend_crude": "UP" if crude_change >= 0 else "DOWN",
        "correlation": corr,
        "divergence": signal_type == "DIV",
        "reason": insight,
    }
    return save_signal(signal)
