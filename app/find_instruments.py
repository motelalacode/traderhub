import sys

from kiteconnect import KiteConnect

from app.config import KITE_ACCESS_TOKEN, KITE_API_KEY


def fetch_instruments():
    if not KITE_API_KEY:
        raise ValueError("KITE_API_KEY is missing in .env")
    if not KITE_ACCESS_TOKEN:
        raise ValueError("KITE_ACCESS_TOKEN is missing in .env")

    kite = KiteConnect(api_key=KITE_API_KEY)
    kite.set_access_token(KITE_ACCESS_TOKEN)
    return kite.instruments()


def normalize(value):
    return str(value or "").strip().lower()


def search_instruments(rows, query):
    q = normalize(query)
    matches = []

    for row in rows:
        tradingsymbol = normalize(row.get("tradingsymbol"))
        name = normalize(row.get("name"))
        exchange = normalize(row.get("exchange"))
        segment = normalize(row.get("segment"))

        haystack = " ".join([tradingsymbol, name, exchange, segment])
        if q in haystack:
            matches.append(row)

    return matches


def print_rows(rows, limit=20):
    if not rows:
        print("No matching instruments found.")
        return

    print(
        "instrument_token | exchange | segment | tradingsymbol | name | expiry | lot_size"
    )
    print("-" * 100)

    for row in rows[:limit]:
        print(
            f"{row.get('instrument_token')} | "
            f"{row.get('exchange')} | "
            f"{row.get('segment')} | "
            f"{row.get('tradingsymbol')} | "
            f"{row.get('name')} | "
            f"{row.get('expiry')} | "
            f"{row.get('lot_size')}"
        )

    if len(rows) > limit:
        print(f"\nShowing first {limit} of {len(rows)} matches.")


def main():
    queries = sys.argv[1:] or ["USDINR", "CRUDE"]

    try:
        rows = fetch_instruments()
    except Exception as exc:
        print(f"Could not fetch instruments: {exc}")
        return

    for query in queries:
        print(f"\nSearch: {query}")
        matches = search_instruments(rows, query)
        print_rows(matches)


if __name__ == "__main__":
    main()
