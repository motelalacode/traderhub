import csv
import difflib
import re
from functools import lru_cache
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent.parent / "list of shares with symbols.csv"

# Manual convenience aliases for common name-style inputs and misspellings.
SYMBOL_ALIASES = {
    "tata motors": "TATAMOTORS",
    "tata moters": "TATAMOTORS",
    "tata motor": "TATAMOTORS",
    "state bank": "SBIN",
    "state bank of india": "SBIN",
    "sbi bank": "SBIN",
    "reliance industries": "RELIANCE",
    "itc ltd": "ITC",
}


def normalize_lookup_value(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=1)
def load_symbol_master():
    by_symbol = {}
    by_normalized_symbol = {}
    by_security_name = {}
    fuzzy_keys = set()

    if not CSV_PATH.exists():
        return {
            "by_symbol": by_symbol,
            "by_normalized_symbol": by_normalized_symbol,
            "by_security_name": by_security_name,
            "fuzzy_keys": [],
        }

    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            series = str(row.get("SERIES") or "").strip().upper()
            symbol = str(row.get("SYMBOL") or "").strip().upper()
            security = str(row.get("SECURITY") or "").strip()

            # This master list is treated as cash-equity coverage for NSE/BSE style EQ-series shares.
            if series != "EQ" or not symbol:
                continue

            master_row = {
                "series": series,
                "symbol": symbol,
                "security": security,
            }
            by_symbol[symbol] = master_row
            by_normalized_symbol[normalize_lookup_value(symbol)] = symbol

            if security:
                normalized_security = normalize_lookup_value(security)
                by_security_name[normalized_security] = symbol
                fuzzy_keys.add(normalized_security)

            fuzzy_keys.add(normalize_lookup_value(symbol))

    return {
        "by_symbol": by_symbol,
        "by_normalized_symbol": by_normalized_symbol,
        "by_security_name": by_security_name,
        "fuzzy_keys": sorted(fuzzy_keys),
    }


def resolve_symbol(value):
    raw = str(value or "").strip()
    if not raw:
        return None

    master = load_symbol_master()
    exact_symbol = raw.upper()
    if exact_symbol in master["by_symbol"]:
        return exact_symbol

    normalized_value = normalize_lookup_value(raw)
    if not normalized_value:
        return None

    alias_symbol = SYMBOL_ALIASES.get(normalized_value)
    if alias_symbol:
        return alias_symbol

    normalized_symbol = master["by_normalized_symbol"].get(normalized_value)
    if normalized_symbol:
        return normalized_symbol

    security_symbol = master["by_security_name"].get(normalized_value)
    if security_symbol:
        return security_symbol

    close_matches = difflib.get_close_matches(normalized_value, master["fuzzy_keys"], n=1, cutoff=0.86)
    if not close_matches:
        return exact_symbol

    best_match = close_matches[0]
    return (
        master["by_security_name"].get(best_match)
        or master["by_normalized_symbol"].get(best_match)
        or SYMBOL_ALIASES.get(best_match)
        or exact_symbol
    )


def resolve_symbol_list(raw_values):
    resolved_symbols = []
    seen = set()

    if isinstance(raw_values, str):
        values = raw_values.split(",")
    else:
        values = list(raw_values)

    for value in values:
        symbol = resolve_symbol(value)
        if symbol and symbol not in seen:
            resolved_symbols.append(symbol)
            seen.add(symbol)

    return resolved_symbols
