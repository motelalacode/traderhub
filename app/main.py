import datetime
import json
import math
import csv
import io
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, Response, jsonify, redirect, render_template_string, request
from kiteconnect import KiteConnect

from app.ai_engine import get_trade_setup_insight
from app.config import ENV_PATH, KITE_API_KEY, KITE_API_SECRET, get_runtime_config
from app.symbol_resolver import load_symbol_master, normalize_lookup_value, resolve_symbol_list

APP_TZ = ZoneInfo("Asia/Kolkata")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ARBITRAGE_HISTORY_PATH = DATA_DIR / "arbitrage_history.json"
ARBITRAGE_VIRTUAL_STATE_PATH = DATA_DIR / "arbitrage_virtual_state.json"
ARBITRAGE_LIVE_STATE_PATH = DATA_DIR / "arbitrage_live_state.json"
MANUAL_WATCHLISTS_PATH = DATA_DIR / "manual_watchlists.json"
ARBITRAGE_HISTORY_RETENTION_DAYS = 3
MANUAL_WATCHLIST_LIMIT = 5
MANUAL_WATCHLIST_STOCK_LIMIT = 25
MANUAL_WATCHLIST_DEFAULT_NAMES = ["Intraday", "Swing", "Portfolio", "Breakout", "Radar"]
ARBITRAGE_RULES = {
    "capital_amount": 20000.0,
    "min_spread": 0.20,
    "min_net_profit": 5.0,
    "min_depth_quantity": 5,
    "persistence_seconds": 3,
    "cooldown_seconds": 5,
    "max_ready_setups": 3,
    "max_trades_per_day": 10,
    "stop_hour": 15,
    "stop_minute": 0,
}
DEFAULT_SYMBOLS = ["IOC", "PNB"]
SCANNER_DEFAULT_SYMBOLS = ["IOC", "PNB", "SBIN", "RELIANCE", "ITC", "TATAMOTORS"]
WATCHLISTS = {
    "psu_bank": ["PNB", "SBIN", "BANKBARODA", "CANBK", "UNIONBANK"],
    "oil_gas": ["IOC", "BPCL", "HPCL", "ONGC", "RELIANCE"],
    "nifty_leaders": ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS"],
    "auto": ["TATAMOTORS", "MARUTI", "M&M", "BAJAJ-AUTO", "HEROMOTOCO"],
    "my_intraday": ["IOC", "PNB", "SBIN", "RELIANCE", "ITC", "TATAMOTORS"],
}
NIFTY_50_SYMBOLS = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJFINANCE",
    "BAJAJFINSV", "BEL", "BHARTIARTL", "BPCL", "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO",
    "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY", "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK",
    "LT", "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE",
    "SHRIRAMFIN", "SBIN", "SUNPHARMA", "TCS", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TECHM",
    "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]
NIFTY_NEXT_50_SYMBOLS = [
    "ABB", "ADANIENSOL", "ADANIGREEN", "ADANIPOWER", "AMBUJACEM", "BAJAJHLDNG", "BANKBARODA",
    "BOSCHLTD", "CANBK", "CGPOWER", "CHOLAFIN", "DABUR", "DIVISLAB", "DLF", "DMART", "GAIL",
    "GODREJCP", "HAVELLS", "HAL", "HDFCAMC", "ICICIGI", "ICICIPRULI", "INDIGO", "INDUSTOWER",
    "IOC", "IRFC", "JINDALSTEL", "JSWENERGY", "LICI", "LODHA", "MOTHERSON", "NAUKRI", "NHPC",
    "PIDILITIND", "PFC", "PNB", "RECLTD", "SHREECEM", "SIEMENS", "SRF", "TORNTPHARM", "TVSMOTOR",
    "UNITDSPR", "VBL", "VEDL", "ZYDUSLIFE", "HINDPETRO", "BERGEPAINT", "COLPAL", "MARICO",
]
SECTOR_GROUPS = {
    "psu_banks": ["PNB", "SBIN", "BANKBARODA", "CANBK", "UNIONBANK"],
    "oil_gas": ["IOC", "BPCL", "HPCL", "ONGC", "RELIANCE"],
    "it": ["INFY", "TCS", "WIPRO", "HCLTECH", "TECHM"],
    "auto": ["TATAMOTORS", "MARUTI", "M&M", "BAJAJ-AUTO", "HEROMOTOCO"],
    "metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "NMDC"],
    "private_banks": ["HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK", "INDUSINDBK"],
    "fmcg": ["ITC", "HINDUNILVR", "NESTLEIND", "BRITANNIA", "DABUR"],
}
SECTOR_HEATMAP_GROUPS = {
    "financials": {
        "label": "Financials",
        "subsectors": {
            "psu_banks": ["PNB", "SBIN", "BANKBARODA", "CANBK", "UNIONBANK", "INDIANB"],
            "private_banks": ["HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK", "INDUSINDBK"],
            "nbfcs": ["BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "SHRIRAMFIN", "MUTHOOTFIN"],
            "insurance": ["SBILIFE", "HDFCLIFE", "ICICIPRULI", "ICICIGI"],
        },
    },
    "energy": {
        "label": "Energy",
        "subsectors": {
            "omcs": ["IOC", "BPCL", "HPCL", "MRPL"],
            "upstream_oil_gas": ["ONGC", "OIL"],
            "gas_utilities": ["GAIL", "IGL", "MGL", "PETRONET"],
            "integrated_energy": ["RELIANCE"],
        },
    },
    "technology": {
        "label": "Technology",
        "subsectors": {
            "it_services": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM"],
            "digital_telecom": ["BHARTIARTL", "IDEA", "TATACOMM"],
        },
    },
    "auto_mobility": {
        "label": "Auto & Mobility",
        "subsectors": {
            "passenger_vehicles": ["MARUTI", "M&M", "TATAMOTORS"],
            "two_wheelers": ["HEROMOTOCO", "BAJAJ-AUTO", "TVSMOTOR", "EICHERMOT"],
            "auto_ancillaries": ["BOSCHLTD", "MOTHERSON", "BHARATFORG", "EXIDEIND"],
        },
    },
    "metals_materials": {
        "label": "Metals & Materials",
        "subsectors": {
            "steel": ["TATASTEEL", "JSWSTEEL", "JINDALSTEL", "SAIL"],
            "non_ferrous": ["HINDALCO", "VEDL", "NALCO", "HINDCOPPER"],
            "mining": ["NMDC", "COALINDIA"],
            "cement": ["ULTRACEMCO", "ACC", "AMBUJACEM", "DALBHARAT"],
        },
    },
    "industrials": {
        "label": "Industrials",
        "subsectors": {
            "capital_goods": ["LT", "SIEMENS", "ABB", "CUMMINSIND"],
            "railways": ["IRFC", "RVNL", "IRCON", "RAILTEL"],
            "defence": ["HAL", "BEL", "BDL", "MAZDOCK"],
            "infrastructure": ["LT", "KEC", "NBCC"],
        },
    },
    "consumer": {
        "label": "Consumer",
        "subsectors": {
            "fmcg": ["ITC", "HINDUNILVR", "NESTLEIND", "BRITANNIA", "DABUR"],
            "consumer_durables": ["VOLTAS", "HAVELLS", "DIXON"],
            "retail": ["TRENT", "DMART", "VMART", "SHOPERSTOP"],
        },
    },
    "healthcare": {
        "label": "Healthcare",
        "subsectors": {
            "pharma": ["SUNPHARMA", "DRREDDY", "CIPLA", "LUPIN", "AUROPHARMA"],
            "hospitals": ["APOLLOHOSP", "MAXHEALTH", "FORTIS"],
        },
    },
    "utilities_real_assets": {
        "label": "Utilities & Real Assets",
        "subsectors": {
            "power_utilities": ["NTPC", "POWERGRID", "TATAPOWER", "NHPC"],
            "realty": ["DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE"],
            "chemicals": ["PIDILITIND", "DEEPAKNTR", "AARTIIND", "TATACHEM"],
        },
    },
}
DEFAULT_START = "09:15"
DEFAULT_END = "09:30"
CURRENT_ACCESS_TOKEN = None

PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Equity OHLC</title>
  <style>
    :root {
      --bg: #f6f3ea;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --accent-soft: #dbece7;
      --warn: #8a3b12;
      --warn-soft: #f7e3d9;
      --up: #116149;
      --up-soft: #d7efe7;
      --down: #8a2e2e;
      --down-soft: #f7dddd;
      --neutral: #7a5a18;
      --neutral-soft: #f5ebcc;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(31,111,95,0.12), transparent 28%),
        linear-gradient(180deg, #faf6ee 0%, #f0eadf 100%);
    }
    .page {
      max-width: 1180px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }
    .hero {
      background: linear-gradient(135deg, rgba(31,111,95,0.95), rgba(20,44,62,0.96));
      color: #f8f5ef;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 24px 60px rgba(24,32,39,0.14);
    }
    .eyebrow {
      margin: 0 0 10px;
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 12px;
      opacity: 0.85;
    }
    h1 {
      margin: 0;
      font-size: 42px;
      line-height: 1;
      font-weight: 700;
    }
    .sub {
      margin: 14px 0 0;
      max-width: 720px;
      font-size: 18px;
      line-height: 1.5;
      color: rgba(248,245,239,0.88);
    }
    .meta {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 22px;
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      font-size: 14px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 18px;
      margin-top: 24px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: 0 18px 44px rgba(24,32,39,0.07);
    }
    .card h2, .card h3 {
      margin: 0 0 12px;
      font-size: 26px;
    }
    .legend {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin-top: 20px;
    }
    .legend-item {
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
    }
    .legend-item strong {
      display: block;
      margin-bottom: 6px;
      font-size: 14px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .muted {
      color: var(--muted);
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      align-items: end;
    }
    .quick-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }
    .quick-link {
      display: inline-flex;
      align-items: center;
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      text-decoration: none;
      font-size: 14px;
      font-weight: 700;
    }
    .quick-link.active {
      background: var(--accent-soft);
      color: var(--accent);
      border-color: rgba(31,111,95,0.24);
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    button {
      cursor: pointer;
      border: 0;
      border-radius: 14px;
      padding: 13px 18px;
      font: inherit;
      font-weight: 700;
      color: #fff;
      background: var(--accent);
    }
    .error {
      margin-top: 18px;
      border-radius: 18px;
      padding: 16px 18px;
      background: var(--warn-soft);
      color: var(--warn);
      border: 1px solid rgba(138,59,18,0.2);
    }
    .summary {
      width: 100%;
      border-collapse: collapse;
    }
    .summary th, .summary td {
      text-align: left;
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      font-size: 15px;
    }
    .summary th {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .status-strip {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 16px 0 14px;
    }
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.04em;
    }
    .status-up {
      color: var(--up);
      background: var(--up-soft);
    }
    .status-down {
      color: var(--down);
      background: var(--down-soft);
    }
    .status-neutral {
      color: var(--neutral);
      background: var(--neutral-soft);
    }
    .value-up { color: #116149; font-weight: 700; }
    .value-down { color: #8a2e2e; font-weight: 700; }
    .candles {
      margin-top: 14px;
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 18px;
    }
    .candles table {
      width: 100%;
      border-collapse: collapse;
      min-width: 620px;
    }
    .candles th, .candles td {
      padding: 10px 12px;
      text-align: left;
      border-bottom: 1px solid var(--line);
      font-size: 14px;
    }
    .candles th {
      background: var(--accent-soft);
      color: var(--ink);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .footnote {
      margin-top: 22px;
      font-size: 13px;
      color: var(--muted);
    }
    @media (max-width: 700px) {
      h1 { font-size: 32px; }
      .sub { font-size: 16px; }
      .page { padding: 18px 14px 34px; }
      .hero, .card { border-radius: 18px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <p class="eyebrow">bot.traderhub.in</p>
      <h1>NSE Equity Opening Range OHLC</h1>
      <p class="sub">
        Today window view for NSE equities between {{ start_time }} and {{ end_time }} on {{ selected_date }}.
        This page shows both the aggregated session OHLC and the minute-by-minute candles returned by Zerodha.
      </p>
      <div class="meta">
        <div class="pill">Symbols: {{ symbols|join(", ") }}</div>
        <div class="pill">Date: {{ selected_date }}</div>
        <div class="pill">Time Zone: Asia/Kolkata</div>
      </div>
    </section>

    <section class="card" style="margin-top: 22px;">
      <h2>Filter</h2>
      <form method="get" class="form-grid">
        <div>
          <label for="symbols">Symbols</label>
          <input id="symbols" name="symbols" value="{{ request_symbols }}" placeholder="IOC,PNB,RELIANCE">
        </div>
        <div>
          <label for="date">Date</label>
          <input id="date" name="date" value="{{ selected_date }}" placeholder="YYYY-MM-DD">
        </div>
        <div>
          <label for="start">Start</label>
          <input id="start" name="start" value="{{ start_time }}" placeholder="09:15">
        </div>
        <div>
          <label for="end">End</label>
          <input id="end" name="end" value="{{ end_time }}" placeholder="09:30">
        </div>
        <div>
          <button type="submit">Refresh Data</button>
        </div>
      </form>
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
      <div class="quick-links">
        <a class="quick-link {{ 'active' if selected_date == today_date else '' }}"
           href="/equity-ohlc?symbols={{ request_symbols|urlencode }}&date={{ today_date }}&start={{ start_time }}&end={{ end_time }}">
          Today
        </a>
        <a class="quick-link {{ 'active' if selected_date == yesterday_date else '' }}"
           href="/equity-ohlc?symbols={{ request_symbols|urlencode }}&date={{ yesterday_date }}&start={{ start_time }}&end={{ end_time }}">
          Yesterday
        </a>
      </div>
    </section>

    <section class="card" style="margin-top: 18px;">
      <h2>How To Read It</h2>
      <div class="legend">
        <div class="legend-item">
          <strong>Above OR High</strong>
          Green means bullish breakout. Price moved above the opening range high after the selected time window.
        </div>
        <div class="legend-item">
          <strong>Below OR Low</strong>
          Red means bearish breakdown. Price moved below the opening range low after the selected time window.
        </div>
        <div class="legend-item">
          <strong>Inside Range</strong>
          Yellow means price is still inside the opening range, so no breakout is confirmed yet.
        </div>
      </div>
    </section>

    {% if results %}
    <section class="grid">
      {% for result in results %}
      <article class="card">
        <h3>{{ result.symbol }}</h3>
        <p class="muted">Instrument token: {{ result.instrument_token }}</p>
        <div class="status-strip">
          <div class="status-badge {{ result.breakout.badge_class }}">
            {{ result.breakout.label }}
          </div>
          <div class="status-badge status-neutral">
            Last: {{ result.breakout.last_price }}
            {% if result.breakout.last_time %}
            at {{ result.breakout.last_time }}
            {% endif %}
          </div>
        </div>
        <table class="summary">
          <thead>
            <tr>
              <th>Open</th>
              <th>High</th>
              <th>Low</th>
              <th>Close</th>
              <th>Candles</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{{ result.summary.open }}</td>
              <td>{{ result.summary.high }}</td>
              <td>{{ result.summary.low }}</td>
              <td class="{{ 'value-up' if result.summary.close >= result.summary.open else 'value-down' }}">
                {{ result.summary.close }}
              </td>
              <td>{{ result.summary.candle_count }}</td>
            </tr>
          </tbody>
        </table>
        <table class="summary" style="margin-top: 14px;">
          <thead>
            <tr>
              <th>OR High</th>
              <th>OR Low</th>
              <th>Range Size</th>
              <th>Breakout Gap</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{{ result.breakout.or_high }}</td>
              <td>{{ result.breakout.or_low }}</td>
              <td>{{ result.breakout.range_size }}</td>
              <td>{{ result.breakout.breakout_gap }}</td>
            </tr>
          </tbody>
        </table>
        <div class="candles">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Open</th>
                <th>High</th>
                <th>Low</th>
                <th>Close</th>
                <th>Volume</th>
              </tr>
            </thead>
            <tbody>
              {% for candle in result.candles %}
              <tr>
                <td>{{ candle.time }}</td>
                <td>{{ candle.open }}</td>
                <td>{{ candle.high }}</td>
                <td>{{ candle.low }}</td>
                <td>{{ candle.close }}</td>
                <td>{{ candle.volume }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </article>
      {% endfor %}
    </section>
    {% endif %}

    <p class="footnote">
      Fresh page path: <strong>/equity-ohlc</strong>. Example:
      /equity-ohlc?symbols=IOC,PNB&date={{ selected_date }}&start=09:15&end=09:30
    </p>
  </div>
</body>
</html>
"""

SCANNER_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Intraday Scanner</title>
  <style>
    :root {
      --bg: #f3efe5;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --accent-soft: #dbece7;
      --up: #116149;
      --up-soft: #d7efe7;
      --down: #8a2e2e;
      --down-soft: #f7dddd;
      --neutral: #7a5a18;
      --neutral-soft: #f5ebcc;
      --info: #1f3f73;
      --info-soft: #dde8f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(31,111,95,0.1), transparent 30%),
        linear-gradient(180deg, #faf6ee 0%, #efe7da 100%);
    }
    .page {
      max-width: 1320px;
      margin: 0 auto;
      padding: 28px 18px 52px;
    }
    .hero {
      background: linear-gradient(135deg, rgba(20,44,62,0.98), rgba(31,111,95,0.92));
      color: #f8f5ef;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 22px 60px rgba(24,32,39,0.14);
    }
    h1 {
      margin: 0;
      font-size: 40px;
      line-height: 1;
    }
    .sub {
      margin: 12px 0 0;
      max-width: 840px;
      font-size: 17px;
      line-height: 1.5;
      color: rgba(248,245,239,0.88);
    }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      font-size: 14px;
    }
    .card {
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: 0 18px 44px rgba(24,32,39,0.07);
    }
    .card h2 {
      margin: 0 0 12px;
      font-size: 24px;
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      align-items: end;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    button, .quick-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      border: 0;
      border-radius: 14px;
      padding: 13px 18px;
      font: inherit;
      font-weight: 700;
      text-decoration: none;
    }
    button {
      color: #fff;
      background: var(--accent);
    }
    .quick-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .quick-link {
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
    }
    .quick-link.active {
      background: var(--accent-soft);
      color: var(--accent);
      border-color: rgba(31,111,95,0.24);
    }
    .scanner-wrap {
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 18px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 1180px;
    }
    th, td {
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }
    tbody tr {
      cursor: pointer;
    }
    tbody tr:hover {
      background: rgba(31,111,95,0.06);
    }
    th {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      background: #faf7f1;
      cursor: pointer;
      user-select: none;
    }
    th.sortable:hover {
      color: var(--ink);
    }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up {
      background: var(--up-soft);
      color: var(--up);
    }
    .badge-down {
      background: var(--down-soft);
      color: var(--down);
    }
    .badge-neutral {
      background: var(--neutral-soft);
      color: var(--neutral);
    }
    .badge-info {
      background: var(--info-soft);
      color: var(--info);
    }
    .muted {
      color: var(--muted);
    }
    .error {
      margin-top: 14px;
      border-radius: 16px;
      padding: 14px 16px;
      background: #f7e3d9;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.18);
    }
    .ai-text {
      max-width: 320px;
      line-height: 1.45;
    }
    .symbol-link {
      color: var(--accent);
      font-weight: 700;
      text-decoration: none;
    }
    .symbol-link:hover {
      text-decoration: underline;
    }
    .legend {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }
    .legend-item {
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
    }
    .legend-item strong {
      display: block;
      margin-bottom: 6px;
      font-size: 14px;
      text-transform: uppercase;
    }
    @media (max-width: 720px) {
      h1 { font-size: 32px; }
      .page { padding: 18px 12px 40px; }
      .hero, .card { border-radius: 18px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Equity Intraday Scanner</h1>
      <p class="sub">
        A separate multi-stock scanner for ORB status, latest price, breakout gap, VWAP status, volume status,
        and AI suggestion when available. Click any column header to sort the table.
      </p>
      <div class="meta">
        <div class="pill">Symbols: {{ symbols|join(", ") }}</div>
        <div class="pill">Date: {{ selected_date }}</div>
        <div class="pill">Range: {{ start_time }} to {{ end_time }}</div>
      </div>
    </section>

    <section class="card">
      <h2>Scanner Filter</h2>
      <form method="get" class="form-grid">
        <div>
          <label for="symbols">Symbols</label>
          <input id="symbols" name="symbols" value="{{ request_symbols }}" placeholder="IOC,PNB,SBIN,RELIANCE">
        </div>
        <div>
          <label for="date">Date</label>
          <input id="date" name="date" value="{{ selected_date }}" placeholder="YYYY-MM-DD">
        </div>
        <div>
          <label for="start">Start</label>
          <input id="start" name="start" value="{{ start_time }}" placeholder="09:15">
        </div>
        <div>
          <label for="end">End</label>
          <input id="end" name="end" value="{{ end_time }}" placeholder="09:30">
        </div>
        <div>
          <button type="submit">Run Scanner</button>
        </div>
      </form>
      <div class="quick-links">
        <a class="quick-link {{ 'active' if selected_date == today_date else '' }}"
           href="/equity-scanner?symbols={{ request_symbols|urlencode }}&date={{ today_date }}&start={{ start_time }}&end={{ end_time }}">
          Today
        </a>
        <a class="quick-link {{ 'active' if selected_date == yesterday_date else '' }}"
           href="/equity-scanner?symbols={{ request_symbols|urlencode }}&date={{ yesterday_date }}&start={{ start_time }}&end={{ end_time }}">
          Yesterday
        </a>
      </div>
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
    </section>

    <section class="card">
      <h2>How To Read It</h2>
      <div class="legend">
        <div class="legend-item">
          <strong>ORB Status</strong>
          Green means bullish breakout, red means bearish breakdown, and yellow means price is still inside the opening range.
        </div>
        <div class="legend-item">
          <strong>VWAP Status</strong>
          Above VWAP supports intraday strength. Below VWAP suggests weakness or fading momentum.
        </div>
        <div class="legend-item">
          <strong>Volume Status</strong>
          High volume means the latest candle is trading above its recent average, which can confirm a move.
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Scanner Table</h2>
      <div class="scanner-wrap">
        <table id="scanner-table">
          <thead>
            <tr>
              <th class="sortable" data-key="symbol">Symbol</th>
              <th class="sortable" data-key="orb_sort">ORB Status</th>
              <th class="sortable" data-key="last_price">Latest Price</th>
              <th class="sortable" data-key="breakout_gap">Breakout Gap</th>
              <th class="sortable" data-key="vwap_sort">VWAP Status</th>
              <th class="sortable" data-key="volume_ratio">Volume Status</th>
              <th class="sortable" data-key="or_high">OR High</th>
              <th class="sortable" data-key="or_low">OR Low</th>
              <th class="sortable" data-key="range_size">Range Size</th>
              <th>AI Suggestion</th>
            </tr>
          </thead>
          <tbody>
            {% for row in scanner_rows %}
            <tr onclick="window.location='/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}'">
              <td data-sort="{{ row.symbol }}">
                <a class="symbol-link" href="/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}" onclick="event.stopPropagation()">{{ row.symbol }}</a>
              </td>
              <td data-sort="{{ row.orb_sort }}">
                <span class="badge {{ row.orb_badge }}">{{ row.orb_status }}</span>
              </td>
              <td data-sort="{{ row.last_price_numeric }}">{{ row.last_price }}</td>
              <td data-sort="{{ row.breakout_gap_numeric }}">
                <span class="badge {{ row.breakout_gap_badge }}">{{ row.breakout_gap }}</span>
              </td>
              <td data-sort="{{ row.vwap_sort }}">
                <span class="badge {{ row.vwap_badge }}">{{ row.vwap_status }}</span>
              </td>
              <td data-sort="{{ row.volume_ratio_numeric }}">
                <span class="badge {{ row.volume_badge }}">{{ row.volume_status }}</span>
              </td>
              <td data-sort="{{ row.or_high_numeric }}">{{ row.or_high }}</td>
              <td data-sort="{{ row.or_low_numeric }}">{{ row.or_low }}</td>
              <td data-sort="{{ row.range_size_numeric }}">{{ row.range_size }}</td>
              <td class="ai-text">{{ row.ai_suggestion }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </section>
  </div>
  <script>
    (function () {
      const table = document.getElementById("scanner-table");
      if (!table) return;
      const tbody = table.querySelector("tbody");
      const headers = table.querySelectorAll("th.sortable");
      let currentKey = null;
      let ascending = false;

      function getCellValue(row, index) {
        const cell = row.children[index];
        return cell ? cell.dataset.sort || cell.textContent.trim() : "";
      }

      headers.forEach((header, index) => {
        header.addEventListener("click", () => {
          const key = header.dataset.key;
          ascending = currentKey === key ? !ascending : false;
          currentKey = key;
          const rows = Array.from(tbody.querySelectorAll("tr"));
          rows.sort((a, b) => {
            const aValue = getCellValue(a, index);
            const bValue = getCellValue(b, index);
            const aNumber = Number(aValue);
            const bNumber = Number(bValue);
            let result = 0;

            if (!Number.isNaN(aNumber) && !Number.isNaN(bNumber)) {
              result = aNumber - bNumber;
            } else {
              result = aValue.localeCompare(bValue);
            }

            return ascending ? result : -result;
          });
          rows.forEach((row) => tbody.appendChild(row));
        });
      });
    })();
  </script>
</body>
</html>
"""

WATCHLIST_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Watchlists</title>
  <style>
    :root {
      --bg: #f2ede2;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --accent-soft: #dbece7;
      --up: #116149;
      --up-soft: #d7efe7;
      --down: #8a2e2e;
      --down-soft: #f7dddd;
      --neutral: #7a5a18;
      --neutral-soft: #f5ebcc;
      --info: #1f3f73;
      --info-soft: #dde8f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at right top, rgba(31,111,95,0.1), transparent 28%),
        linear-gradient(180deg, #fbf7ef 0%, #eee5d8 100%);
    }
    .page {
      max-width: 1360px;
      margin: 0 auto;
      padding: 28px 18px 56px;
    }
    .hero {
      background: linear-gradient(135deg, rgba(20,44,62,0.98), rgba(31,111,95,0.92));
      color: #f8f5ef;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 22px 60px rgba(24,32,39,0.14);
    }
    h1 {
      margin: 0;
      font-size: 40px;
      line-height: 1;
    }
    .sub {
      margin: 12px 0 0;
      max-width: 900px;
      font-size: 17px;
      line-height: 1.5;
      color: rgba(248,245,239,0.88);
    }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      font-size: 14px;
    }
    .card {
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: 0 18px 44px rgba(24,32,39,0.07);
    }
    .card h2 {
      margin: 0 0 12px;
      font-size: 24px;
    }
    .toolbar-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      align-items: end;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input, select {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    button, .watch-link, .quick-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      border: 0;
      border-radius: 14px;
      padding: 12px 16px;
      font: inherit;
      font-weight: 700;
      text-decoration: none;
    }
    button {
      color: #fff;
      background: var(--accent);
    }
    .watch-links, .quick-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .watch-link, .quick-link {
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
    }
    .watch-link.active, .quick-link.active {
      background: var(--accent-soft);
      color: var(--accent);
      border-color: rgba(31,111,95,0.24);
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }
    .summary-box {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
    }
    .summary-box strong {
      display: block;
      margin-bottom: 8px;
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .summary-value {
      font-size: 28px;
      font-weight: 700;
    }
    .scanner-wrap {
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 18px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 1180px;
    }
    th, td {
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }
    tbody tr {
      cursor: pointer;
    }
    tbody tr:hover {
      background: rgba(31,111,95,0.06);
    }
    th {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      background: #faf7f1;
      cursor: pointer;
      user-select: none;
    }
    th.sortable:hover {
      color: var(--ink);
    }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up {
      background: var(--up-soft);
      color: var(--up);
    }
    .badge-down {
      background: var(--down-soft);
      color: var(--down);
    }
    .badge-neutral {
      background: var(--neutral-soft);
      color: var(--neutral);
    }
    .badge-info {
      background: var(--info-soft);
      color: var(--info);
    }
    .symbol-link {
      color: var(--accent);
      font-weight: 700;
      text-decoration: none;
    }
    .symbol-link:hover {
      text-decoration: underline;
    }
    .muted {
      color: var(--muted);
    }
    .error {
      margin-top: 14px;
      border-radius: 16px;
      padding: 14px 16px;
      background: #f7e3d9;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.18);
    }
    .ai-text {
      max-width: 320px;
      line-height: 1.45;
    }
    .legend {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }
    .legend-item {
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
    }
    .legend-item strong {
      display: block;
      margin-bottom: 6px;
      font-size: 14px;
      text-transform: uppercase;
    }
    @media (max-width: 720px) {
      h1 { font-size: 32px; }
      .page { padding: 18px 12px 40px; }
      .hero, .card { border-radius: 18px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Equity Watchlists</h1>
      <p class="sub">
        A daily-driver page with saved watchlists, ORB scanner signals, and timed auto-refresh. Use the watchlist buttons
        for one-click baskets, or type your own symbols and let the table refresh itself during market hours.
      </p>
      <div class="meta">
        <div class="pill">Watchlist: {{ active_watchlist_label }}</div>
        <div class="pill">Date: {{ selected_date }}</div>
        <div class="pill">Range: {{ start_time }} to {{ end_time }}</div>
        <div class="pill">Auto Refresh: {{ refresh_label }}</div>
      </div>
    </section>

    <section class="card">
      <h2>Saved Watchlists</h2>
      <div class="watch-links">
        {% for watch in watchlists %}
        <a class="watch-link {{ 'active' if watch.key == active_watchlist else '' }}"
           href="/equity-watchlists?watchlist={{ watch.key }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}&refresh={{ refresh_seconds }}">
          {{ watch.label }}
        </a>
        {% endfor %}
      </div>
    </section>

    <section class="card">
      <h2>Watchlist Controls</h2>
      <form method="get" class="toolbar-grid">
        <div>
          <label for="watchlist">Watchlist</label>
          <select id="watchlist" name="watchlist">
            {% for watch in watchlists %}
            <option value="{{ watch.key }}" {{ 'selected' if watch.key == active_watchlist else '' }}>{{ watch.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="symbols">Custom Symbols</label>
          <input id="symbols" name="symbols" value="{{ request_symbols }}" placeholder="IOC,PNB,SBIN,RELIANCE">
        </div>
        <div>
          <label for="date">Date</label>
          <input id="date" name="date" value="{{ selected_date }}" placeholder="YYYY-MM-DD">
        </div>
        <div>
          <label for="start">Start</label>
          <input id="start" name="start" value="{{ start_time }}" placeholder="09:15">
        </div>
        <div>
          <label for="end">End</label>
          <input id="end" name="end" value="{{ end_time }}" placeholder="09:30">
        </div>
        <div>
          <label for="refresh">Auto Refresh</label>
          <select id="refresh" name="refresh">
            {% for option in refresh_options %}
            <option value="{{ option.value }}" {{ 'selected' if option.value == refresh_seconds else '' }}>{{ option.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <button type="submit">Open Watchlist</button>
        </div>
      </form>
      <div class="quick-links">
        <a class="quick-link {{ 'active' if selected_date == today_date else '' }}"
           href="/equity-watchlists?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ today_date }}&start={{ start_time }}&end={{ end_time }}&refresh={{ refresh_seconds }}">
          Today
        </a>
        <a class="quick-link {{ 'active' if selected_date == yesterday_date else '' }}"
           href="/equity-watchlists?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ yesterday_date }}&start={{ start_time }}&end={{ end_time }}&refresh={{ refresh_seconds }}">
          Yesterday
        </a>
      </div>
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Watchlist Summary</h2>
      <div class="summary-grid">
        <div class="summary-box">
          <strong>Bullish Breakouts</strong>
          <div class="summary-value">{{ summary.above_count }}</div>
          <div class="muted">Above OR high</div>
        </div>
        <div class="summary-box">
          <strong>Bearish Breakdowns</strong>
          <div class="summary-value">{{ summary.below_count }}</div>
          <div class="muted">Below OR low</div>
        </div>
        <div class="summary-box">
          <strong>Inside Range</strong>
          <div class="summary-value">{{ summary.inside_count }}</div>
          <div class="muted">Still inside opening range</div>
        </div>
        <div class="summary-box">
          <strong>Volume Confirmed</strong>
          <div class="summary-value">{{ summary.high_volume_count }}</div>
          <div class="muted">High-volume names</div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>How To Use The Page</h2>
      <div class="legend">
        <div class="legend-item">
          <strong>Watchlist Buttons</strong>
          Use one-click baskets like PSU banks, oil & gas, or your own intraday set to avoid typing symbols every session.
        </div>
        <div class="legend-item">
          <strong>Auto Refresh</strong>
          Pick 15s, 30s, or 60s to keep the page updating during market hours. Use Off when you want a static review snapshot.
        </div>
        <div class="legend-item">
          <strong>Click Through</strong>
          Click any row or symbol to jump into the detailed OHLC page for that stock with the same date and range.
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Watchlist Table</h2>
      <div class="scanner-wrap">
        <table id="watchlist-table">
          <thead>
            <tr>
              <th class="sortable" data-key="symbol">Symbol</th>
              <th class="sortable" data-key="orb_sort">ORB Status</th>
              <th class="sortable" data-key="last_price">Latest Price</th>
              <th class="sortable" data-key="breakout_gap">Breakout Gap</th>
              <th class="sortable" data-key="vwap_sort">VWAP Status</th>
              <th class="sortable" data-key="volume_ratio">Volume Status</th>
              <th class="sortable" data-key="or_high">OR High</th>
              <th class="sortable" data-key="or_low">OR Low</th>
              <th class="sortable" data-key="range_size">Range Size</th>
              <th>AI Suggestion</th>
            </tr>
          </thead>
          <tbody>
            {% for row in scanner_rows %}
            <tr onclick="window.location='/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}'">
              <td data-sort="{{ row.symbol }}">
                <a class="symbol-link" href="/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}" onclick="event.stopPropagation()">{{ row.symbol }}</a>
              </td>
              <td data-sort="{{ row.orb_sort }}">
                <span class="badge {{ row.orb_badge }}">{{ row.orb_status }}</span>
              </td>
              <td data-sort="{{ row.last_price_numeric }}">{{ row.last_price }}</td>
              <td data-sort="{{ row.breakout_gap_numeric }}">
                <span class="badge {{ row.breakout_gap_badge }}">{{ row.breakout_gap }}</span>
              </td>
              <td data-sort="{{ row.vwap_sort }}">
                <span class="badge {{ row.vwap_badge }}">{{ row.vwap_status }}</span>
              </td>
              <td data-sort="{{ row.volume_ratio_numeric }}">
                <span class="badge {{ row.volume_badge }}">{{ row.volume_status }}</span>
              </td>
              <td data-sort="{{ row.or_high_numeric }}">{{ row.or_high }}</td>
              <td data-sort="{{ row.or_low_numeric }}">{{ row.or_low }}</td>
              <td data-sort="{{ row.range_size_numeric }}">{{ row.range_size }}</td>
              <td class="ai-text">{{ row.ai_suggestion }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </section>
  </div>
  {% if refresh_seconds > 0 %}
  <script>
    window.setTimeout(function () {
      window.location.reload();
    }, {{ refresh_seconds * 1000 }});
  </script>
  {% endif %}
  <script>
    (function () {
      const table = document.getElementById("watchlist-table");
      if (!table) return;
      const tbody = table.querySelector("tbody");
      const headers = table.querySelectorAll("th.sortable");
      let currentKey = null;
      let ascending = false;

      function getCellValue(row, index) {
        const cell = row.children[index];
        return cell ? cell.dataset.sort || cell.textContent.trim() : "";
      }

      headers.forEach((header, index) => {
        header.addEventListener("click", () => {
          const key = header.dataset.key;
          ascending = currentKey === key ? !ascending : false;
          currentKey = key;
          const rows = Array.from(tbody.querySelectorAll("tr"));
          rows.sort((a, b) => {
            const aValue = getCellValue(a, index);
            const bValue = getCellValue(b, index);
            const aNumber = Number(aValue);
            const bNumber = Number(bValue);
            let result = 0;

            if (!Number.isNaN(aNumber) && !Number.isNaN(bNumber)) {
              result = aNumber - bNumber;
            } else {
              result = aValue.localeCompare(bValue);
            }

            return ascending ? result : -result;
          });
          rows.forEach((row) => tbody.appendChild(row));
        });
      });
    })();
  </script>
</body>
</html>
"""

MARKET_WATCH_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Market Watch</title>
  <style>
    :root {
      --bg: #eef1f4;
      --panel: #f9fbfd;
      --panel-strong: #ffffff;
      --ink: #17212b;
      --muted: #5a6775;
      --line: #c9d3dd;
      --accent: #176f62;
      --up: #0f6a4b;
      --up-soft: #d6f0e4;
      --down: #8c2f34;
      --down-soft: #f8dee1;
      --neutral: #8a6a19;
      --neutral-soft: #f4ebc8;
      --info: #1e4f88;
      --info-soft: #dbe8f7;
      --sheet-head: #dde5ec;
      --sheet-row: #fdfefe;
      --sheet-alt: #f6f8fa;
      --selected: #e4f0ec;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Tahoma, sans-serif;
      background:
        radial-gradient(circle at top right, rgba(23,111,98,0.08), transparent 24%),
        linear-gradient(180deg, #f7f7f4 0%, #eef1f4 100%);
      color: var(--ink);
    }
    .page { max-width: 1460px; margin: 0 auto; padding: 14px 12px 28px; }
    .surface {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 12px 32px rgba(23,33,43,0.08);
    }
    .top-strip {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 8px;
      padding: 10px;
    }
    .strip-box {
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      min-height: 72px;
    }
    .strip-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 6px;
      font-weight: 700;
    }
    .strip-value {
      font-size: 22px;
      font-weight: 700;
      line-height: 1;
    }
    .strip-note { margin-top: 6px; font-size: 12px; color: var(--muted); }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 5px 9px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up { background: var(--up-soft); color: var(--up); }
    .badge-down { background: var(--down-soft); color: var(--down); }
    .badge-neutral { background: var(--neutral-soft); color: var(--neutral); }
    .badge-info { background: var(--info-soft); color: var(--info); }
    .title-row {
      margin-top: 12px;
      padding: 14px 16px;
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: center;
    }
    h1 {
      margin: 0;
      font-size: 28px;
      line-height: 1;
      font-family: Georgia, "Times New Roman", serif;
    }
    .subtitle {
      margin-top: 6px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
    }
    .toolbar {
      margin-top: 12px;
      padding: 12px 16px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto auto;
      gap: 10px;
      align-items: center;
    }
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .tab-link {
      text-decoration: none;
      color: var(--ink);
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 9px 12px;
      font-size: 13px;
      font-weight: 700;
    }
    .tab-link.active {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    .toolbar select, .toolbar a {
      border-radius: 12px;
      border: 1px solid var(--line);
      background: var(--panel-strong);
      color: var(--ink);
      font: inherit;
      padding: 10px 12px;
      text-decoration: none;
      font-weight: 700;
    }
    .error {
      margin: 12px 16px 0;
      padding: 12px 14px;
      border-radius: 14px;
      background: #f8e2df;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.16);
    }
    .workspace {
      margin-top: 12px;
      display: grid;
      grid-template-columns: minmax(0, 1.85fr) minmax(280px, 0.62fr);
      gap: 12px;
      align-items: start;
      padding: 0 12px 12px;
    }
    .sheet-wrap {
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 16px;
      overflow: hidden;
    }
    .sheet-header {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, #f7fafc, #eef3f7);
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
    }
    .sheet-title {
      font-size: 16px;
      font-weight: 700;
      font-family: Georgia, "Times New Roman", serif;
    }
    .sheet-note { color: var(--muted); font-size: 12px; }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 13px;
    }
    thead th {
      position: sticky;
      top: 0;
      z-index: 2;
      background: var(--sheet-head);
      color: #344252;
      border-bottom: 1px solid var(--line);
      border-right: 1px solid var(--line);
      padding: 7px 7px;
      text-align: left;
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: 0.05em;
    }
    tbody td {
      background: var(--sheet-row);
      border-bottom: 1px solid var(--line);
      border-right: 1px solid var(--line);
      padding: 6px 7px;
      vertical-align: middle;
      font-variant-numeric: tabular-nums;
    }
    tbody tr:nth-child(even) td { background: var(--sheet-alt); }
    tbody tr:hover td { background: #edf3f8; }
    tbody tr.active td { background: var(--selected); }
    .sheet-symbol { width: 126px; }
    .sheet-status { width: 122px; }
    .sheet-num { text-align: right; }
    .sheet-center { text-align: center; }
    .symbol-main {
      font-weight: 700;
      color: #0c5678;
      font-size: 13px;
      line-height: 1.1;
    }
    .symbol-sub {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.2;
      margin-top: 3px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .cell-up, .cell-down, .cell-neutral {
      display: inline-block;
      min-width: 62px;
      padding: 3px 5px;
      border-radius: 7px;
      font-weight: 700;
      text-align: right;
    }
    .sheet-change {
      white-space: nowrap;
      font-size: 12px;
      font-weight: 700;
    }
    .cell-up { background: var(--up-soft); color: var(--up); }
    .cell-down { background: var(--down-soft); color: var(--down); }
    .cell-neutral { background: #edf1f4; color: #4f5c69; }
    .detail-panel {
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 16px;
      overflow: hidden;
      position: sticky;
      top: 12px;
    }
    .detail-head {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(135deg, #163346, #176f62);
      color: #fff;
    }
    .detail-symbol {
      font-size: 28px;
      font-weight: 700;
      line-height: 1;
      font-family: Georgia, "Times New Roman", serif;
    }
    .detail-name {
      margin-top: 8px;
      font-size: 13px;
      color: rgba(255,255,255,0.82);
      line-height: 1.35;
    }
    .detail-body { padding: 12px 14px 14px; }
    .detail-price {
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 12px;
      margin-bottom: 14px;
    }
    .detail-ltp {
      font-size: 34px;
      font-weight: 700;
      line-height: 1;
      font-variant-numeric: tabular-nums;
    }
    .detail-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    .detail-box {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 11px;
      background: #fafcfe;
    }
    .detail-label {
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 4px;
      font-weight: 700;
    }
    .detail-value {
      font-size: 18px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }
    .detail-actions {
      margin-top: 14px;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .detail-actions a {
      text-decoration: none;
      text-align: center;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      background: #fff;
      color: var(--ink);
      font-weight: 700;
      font-size: 13px;
    }
    .mobile-list { display: none; }
    .mobile-card {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }
    .mobile-top {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: start;
    }
    .mobile-symbol { font-weight: 700; font-size: 18px; color: #0c5678; }
    .mobile-name { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .mobile-grid {
      margin-top: 10px;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .mobile-metric {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px;
      background: #fafcfe;
    }
    .mobile-label {
      font-size: 9px;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: var(--muted);
      margin-bottom: 3px;
      font-weight: 700;
    }
    .mobile-value {
      font-size: 14px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }
    @media (max-width: 1180px) {
      .workspace { grid-template-columns: 1fr; }
      .detail-panel { position: static; }
    }
    @media (max-width: 900px) {
      .top-strip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .toolbar { grid-template-columns: 1fr; }
      .detail-actions { grid-template-columns: 1fr; }
    }
    @media (max-width: 760px) {
      .page { padding: 12px 10px 24px; }
      .top-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .workspace { display: block; }
      .desktop-sheet { display: none; }
      .mobile-list { display: block; }
      .detail-panel { margin-top: 12px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <div class="surface">
      <div id="market-watch-strip">{{ top_strip_html|safe }}</div>
      <div class="title-row">
        <div>
          <h1>Market Watch</h1>
          <div class="subtitle">Terminal-style live pricing for your saved scripts. Values refresh in place through background requests, so the screen stays stable while you read.</div>
        </div>
      </div>
      <div class="toolbar">
        <div class="tabs">
          {% for watch in watchlist_options %}
          <a class="tab-link {{ 'active' if watch.key == active_watchlist.key else '' }}" href="/market-watch?watchlist={{ watch.key }}&selected={{ selected_symbol }}&refresh={{ refresh_seconds }}">{{ watch.name }} ({{ watch.stock_count }})</a>
          {% endfor %}
        </div>
        <select id="market-watch-refresh" onchange="setRefresh(this.value)">
          {% for option in refresh_options %}
          <option value="{{ option.value }}" {{ 'selected' if option.value == refresh_seconds else '' }}>{{ option.label }}</option>
          {% endfor %}
        </select>
        <a href="/scripts-watchlists">Manage Watchlists</a>
      </div>
      <div id="market-watch-error">{% if error %}<div class="error">{{ error }}</div>{% endif %}</div>
      <div class="workspace">
        <div id="market-watch-grid">{{ grid_html|safe }}</div>
        <div id="market-watch-detail">{{ detail_html|safe }}</div>
      </div>
    </div>
  </div>
  <script>
    let currentWatchlist = "{{ active_watchlist.key }}";
    let currentSelectedSymbol = "{{ selected_symbol }}";
    let currentRefresh = {{ refresh_seconds }};

    function setRefresh(value) {
      const params = new URLSearchParams(window.location.search);
      params.set("watchlist", currentWatchlist);
      params.set("selected", currentSelectedSymbol);
      params.set("refresh", value);
      window.location.href = "/market-watch?" + params.toString();
    }

    async function loadMarketWatchPartial(options) {
      if (options?.watchlist) currentWatchlist = options.watchlist;
      if (options?.selectedSymbol !== undefined) currentSelectedSymbol = options.selectedSymbol;
      const params = new URLSearchParams({
        watchlist: currentWatchlist,
        selected: currentSelectedSymbol,
        refresh: currentRefresh
      });
      const response = await fetch("/market-watch/partial?" + params.toString(), {
        headers: { "X-Requested-With": "XMLHttpRequest" }
      });
      if (!response.ok) return;
      const payload = await response.json();
      currentSelectedSymbol = payload.selected_symbol || currentSelectedSymbol;
      document.getElementById("market-watch-strip").innerHTML = payload.top_strip_html || "";
      document.getElementById("market-watch-error").innerHTML = payload.error_html || "";
      document.getElementById("market-watch-grid").innerHTML = payload.grid_html || "";
      document.getElementById("market-watch-detail").innerHTML = payload.detail_html || "";
    }

    function selectWatchSymbol(symbol) {
      loadMarketWatchPartial({ selectedSymbol: symbol });
    }

    if (currentRefresh > 0) {
      window.setInterval(() => {
        loadMarketWatchPartial({});
      }, currentRefresh * 1000);
    }
  </script>
</body>
</html>
"""

MANUAL_WATCHLIST_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Watchlists</title>
  <style>
    :root {
      --bg: #f3ecdf;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --up: #116149;
      --up-soft: #d7efe7;
      --down: #8a2e2e;
      --down-soft: #f7dddd;
      --neutral: #7a5a18;
      --neutral-soft: #f5ebcc;
      --info: #1f3f73;
      --info-soft: #dde8f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(31,111,95,0.12), transparent 25%),
        linear-gradient(180deg, #fbf7ef 0%, #ece3d6 100%);
    }
    .page { max-width: 1500px; margin: 0 auto; padding: 28px 18px 56px; }
    .hero {
      background: linear-gradient(135deg, rgba(20,44,62,0.98), rgba(31,111,95,0.92));
      color: #f8f5ef;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 22px 60px rgba(24,32,39,0.14);
    }
    h1 { margin: 0; font-size: 40px; line-height: 1; }
    .sub {
      margin: 12px 0 0;
      max-width: 1000px;
      font-size: 17px;
      line-height: 1.5;
      color: rgba(248,245,239,0.88);
    }
    .meta, .watch-tabs, .inline-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      font-size: 14px;
    }
    .tab-link, button, .action-link {
      border-radius: 14px;
      font: inherit;
      text-decoration: none;
    }
    .tab-link, .action-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
      padding: 12px 16px;
      font-weight: 700;
    }
    .tab-link.active {
      background: #dbece7;
      color: var(--accent);
      border-color: rgba(31,111,95,0.24);
    }
    .card {
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: 0 18px 44px rgba(24,32,39,0.07);
    }
    .card h2, .card h3 { margin: 0 0 12px; }
    .controls-grid, .summary-grid, .detail-grid, .mobile-card-grid {
      display: grid;
      gap: 14px;
    }
    .controls-grid { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
    .summary-grid { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
    .detail-grid { grid-template-columns: minmax(0, 1fr) minmax(380px, 430px); align-items: start; }
    .mobile-card-grid { grid-template-columns: 1fr; }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input, select, textarea {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    textarea { min-height: 110px; resize: vertical; }
    button {
      width: 100%;
      border: 0;
      padding: 12px 16px;
      cursor: pointer;
      font-weight: 700;
      color: #fff;
      background: var(--accent);
    }
    button.secondary {
      background: #f1eee7;
      color: var(--ink);
      border: 1px solid var(--line);
    }
    .summary-box, .detail-box, .notice-box {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.78);
    }
    .summary-box strong {
      display: block;
      font-size: 13px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }
    .summary-value { font-size: 28px; font-weight: 700; margin-top: 8px; }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up { background: var(--up-soft); color: var(--up); }
    .badge-down { background: var(--down-soft); color: var(--down); }
    .badge-neutral { background: var(--neutral-soft); color: var(--neutral); }
    .badge-info { background: var(--info-soft); color: var(--info); }
    .error, .success {
      margin-top: 14px;
      border-radius: 16px;
      padding: 14px 16px;
    }
    .error {
      background: #f7e3d9;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.18);
    }
    .success {
      background: #deefe8;
      color: #155744;
      border: 1px solid rgba(21,87,68,0.16);
    }
    .table-wrap {
      overflow-x: auto;
      border: 1px solid #cfc6b5;
      border-radius: 8px;
      background: #fffdf9;
    }
    .desktop-only { display: block; }
    .mobile-only { display: none; }
    table { width: 100%; border-collapse: collapse; min-width: 1060px; }
    th, td {
      padding: 8px 10px;
      border-bottom: 1px solid #d8cfbf;
      border-right: 1px solid #e3dac9;
      text-align: left;
      vertical-align: middle;
      font-size: 13px;
      line-height: 1.25;
    }
    th:last-child, td:last-child { border-right: 0; }
    tbody tr:hover { background: #f5faf7; }
    th {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #55616c;
      background: #f1ece2;
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
    }
    th.sortable:hover { color: var(--ink); }
    .table-wrap tbody tr.active-row {
      background: #edf5f2;
    }
    .table-wrap .badge {
      padding: 5px 8px;
      border-radius: 8px;
      font-size: 11px;
      letter-spacing: 0.02em;
    }
    .symbol-link {
      color: var(--accent);
      font-weight: 700;
      text-decoration: none;
    }
    .symbol-link:hover { text-decoration: underline; }
    .table-row-link {
      color: inherit;
      text-decoration: none;
    }
    .note-preview {
      max-width: 220px;
      color: var(--muted);
      line-height: 1.45;
      white-space: normal;
    }
    .ohlc-compact {
      line-height: 1.3;
      white-space: nowrap;
      font-size: 12px;
    }
    .sheet-stock {
      min-width: 210px;
    }
    .sheet-company {
      display: block;
      margin-top: 2px;
      font-size: 11px;
      color: #61707d;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }
    .sheet-number {
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }
    .sheet-ohlc-line {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .sheet-ohlc-tag {
      width: 12px;
      color: #6a7680;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .detail-actions {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 14px;
    }
    .detail-actions button {
      padding: 10px 12px;
      font-size: 13px;
    }
    .range-shell {
      width: 132px;
    }
    .range-bar {
      position: relative;
      height: 10px;
      border-radius: 999px;
      background: #ece3d6;
      overflow: hidden;
      border: 1px solid rgba(24,32,39,0.08);
    }
    .range-fill {
      position: absolute;
      left: 0;
      top: 0;
      bottom: 0;
      background: linear-gradient(90deg, rgba(31,111,95,0.28), rgba(31,111,95,0.8));
      border-radius: 999px;
    }
    .range-meta {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 11px;
      color: var(--muted);
      margin-top: 6px;
    }
    .mini-form {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 6px;
    }
    .mini-form button {
      padding: 8px 10px;
      font-size: 12px;
    }
    .detail-column {
      position: sticky;
      top: 18px;
      align-self: start;
    }
    .detail-metrics {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }
    .detail-metric {
      padding: 12px;
      border-radius: 14px;
      background: #faf7f1;
      border: 1px solid var(--line);
    }
    .detail-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 4px;
    }
    .detail-value {
      font-size: 18px;
      font-weight: 700;
    }
    .mobile-card {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.82);
      box-shadow: 0 10px 26px rgba(24,32,39,0.06);
    }
    .mobile-head {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
      margin-bottom: 12px;
    }
    .mobile-title {
      font-size: 22px;
      font-weight: 700;
    }
    .mobile-sub {
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
    }
    .mobile-metrics {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 12px;
    }
    .mobile-metric {
      padding: 10px 12px;
      border-radius: 14px;
      background: #faf7f1;
      border: 1px solid var(--line);
    }
    .mobile-metric-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 4px;
    }
    .mobile-metric-value {
      font-size: 17px;
      font-weight: 700;
    }
    .empty-copy {
      color: var(--muted);
      line-height: 1.55;
    }
    @media (max-width: 1320px) {
      .detail-grid { grid-template-columns: 1fr; }
      .detail-column {
        position: static;
        order: -1;
      }
      .detail-metrics { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    }
    @media (max-width: 980px) {
      .detail-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 760px) {
      .desktop-only { display: none; }
      .mobile-only { display: block; }
      .page { padding: 20px 12px 40px; }
      .hero, .card { border-radius: 18px; }
      h1 { font-size: 32px; }
      .detail-metrics, .controls-grid, .summary-grid { grid-template-columns: 1fr; }
      .mini-form { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .detail-actions { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Watchlists</h1>
      <p class="sub">
        A personal watchlist workspace with five manual tabs, up to 25 stocks per list, live price tracking, previous-day breakout context,
        saved notes, and alert-rule placeholders. Build your own Intraday, Swing, Portfolio, Breakout, or future derivatives-focused lists without depending on preset baskets.
      </p>
      <div class="meta">
        <div class="pill">Watchlists: {{ watchlist_limit }}</div>
        <div class="pill">Stocks / List: {{ stock_limit }}</div>
        <div class="pill">Active Watchlist: {{ active_watchlist.name }}</div>
        <div class="pill">Tracked Stocks: {{ active_watchlist.stock_count }}</div>
        <div class="pill">Auto Refresh: {{ refresh_label }}</div>
      </div>
      <div class="watch-tabs">
        {% for watch in watchlists %}
        <a class="tab-link {{ 'active' if watch.key == active_watchlist.key else '' }}" href="/scripts-watchlists?watchlist={{ watch.key }}&refresh={{ refresh_seconds }}">{{ watch.name }}</a>
        {% endfor %}
      </div>
    </section>

    <section class="card">
      <h2>Watchlist Controls</h2>
      <div class="controls-grid">
        <form method="post">
          <input type="hidden" name="action" value="rename_watchlist">
          <input type="hidden" name="watchlist" value="{{ active_watchlist.key }}">
          <input type="hidden" name="refresh" value="{{ refresh_seconds }}">
          <label for="watchlist_name">Rename Watchlist</label>
          <input id="watchlist_name" name="watchlist_name" value="{{ active_watchlist.name }}" maxlength="24" placeholder="Intraday">
          <div style="margin-top: 10px;"><button type="submit">Save Name</button></div>
        </form>

        <form method="post">
          <input type="hidden" name="action" value="add_stock">
          <input type="hidden" name="watchlist" value="{{ active_watchlist.key }}">
          <input type="hidden" name="refresh" value="{{ refresh_seconds }}">
          <label for="add_symbol">Search Stock and Add</label>
          <input id="add_symbol" name="add_symbol" list="stock-master-options" placeholder="TATAMOTORS or Tata Motors">
          <div style="margin-top: 10px;"><button type="submit">Add Stock</button></div>
        </form>

        <form method="get">
          <input type="hidden" name="watchlist" value="{{ active_watchlist.key }}">
          {% if selected_symbol %}
          <input type="hidden" name="selected" value="{{ selected_symbol }}">
          {% endif %}
          <label for="refresh">Auto Refresh</label>
          <select id="refresh" name="refresh">
            {% for option in refresh_options %}
            <option value="{{ option.value }}" {{ 'selected' if option.value == refresh_seconds else '' }}>{{ option.label }}</option>
            {% endfor %}
          </select>
          <div style="margin-top: 10px;"><button type="submit">Apply Refresh</button></div>
        </form>

        <div class="notice-box">
          <strong>Working Rules</strong>
          <div class="empty-copy" style="margin-top: 8px;">
            Fixed at 5 watchlists and 25 stocks per list. Add by symbol or company name, then save notes and alert rules on the selected stock.
            Use refresh carefully during market hours because each live row needs quote, daily, and intraday context.
          </div>
        </div>
      </div>
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
      {% if success_message %}
      <div class="success">{{ success_message }}</div>
      {% endif %}
      <datalist id="stock-master-options">
        {% for option in stock_search_options %}
        <option value="{{ option.symbol }}">{{ option.label }}</option>
        {% endfor %}
      </datalist>
    </section>

    <section class="card">
      <h2>Watchlist Summary</h2>
      <div class="summary-grid">
        <div class="summary-box"><strong>Stocks</strong><div class="summary-value">{{ summary.total_count }}</div><div>Active names in {{ active_watchlist.name }}</div></div>
        <div class="summary-box"><strong>Gainers</strong><div class="summary-value">{{ summary.up_count }}</div><div>Names trading above previous close</div></div>
        <div class="summary-box"><strong>Losers</strong><div class="summary-value">{{ summary.down_count }}</div><div>Names trading below previous close</div></div>
        <div class="summary-box"><strong>Above PDH</strong><div class="summary-value">{{ summary.above_pdh_count }}</div><div>Breakout names holding above yesterday high</div></div>
        <div class="summary-box"><strong>Below PDL</strong><div class="summary-value">{{ summary.below_pdl_count }}</div><div>Weak names trading below yesterday low</div></div>
        <div class="summary-box"><strong>Gap Up</strong><div class="summary-value">{{ summary.gap_up_count }}</div><div>Opens above previous close</div></div>
        <div class="summary-box"><strong>Gap Down</strong><div class="summary-value">{{ summary.gap_down_count }}</div><div>Opens below previous close</div></div>
        <div class="summary-box"><strong>Above VWAP</strong><div class="summary-value">{{ summary.above_vwap_count }}</div><div>Names holding above intraday VWAP</div></div>
      </div>
    </section>

    <section class="card detail-grid">
      <div>
        <h2>Watchlist Table</h2>
        {% if rows %}
        <div class="table-wrap desktop-only">
          <table id="manual-watchlist-table">
            <thead>
              <tr>
                <th class="sortable" data-key="symbol">Stock</th>
                <th class="sortable" data-key="last_price">LTP</th>
                <th class="sortable" data-key="change_pct">Change %</th>
                <th>OHLC</th>
                <th class="sortable" data-key="volume_numeric">Volume</th>
                <th class="sortable" data-key="pdh">PDH</th>
                <th class="sortable" data-key="pdl">PDL</th>
                <th class="sortable" data-key="prev_close">Prev Close</th>
                <th class="sortable" data-key="vwap">VWAP</th>
                <th class="sortable" data-key="status_sort">Status</th>
                <th>Alert</th>
              </tr>
            </thead>
            <tbody>
              {% for row in rows %}
              <tr class="{{ 'active-row' if row.symbol == selected_symbol else '' }}" onclick="window.location='/scripts-watchlists?watchlist={{ active_watchlist.key }}&selected={{ row.symbol }}&refresh={{ refresh_seconds }}'">
                <td data-sort="{{ row.symbol }}">
                  <div class="sheet-stock">
                    <a class="symbol-link" href="/scripts-watchlists?watchlist={{ active_watchlist.key }}&selected={{ row.symbol }}&refresh={{ refresh_seconds }}" onclick="event.stopPropagation()">{{ row.symbol }}</a>
                    <span class="sheet-company">{{ row.security_name }}</span>
                  </div>
                </td>
                <td data-sort="{{ row.last_price_numeric }}"><span class="badge {{ row.price_badge }} sheet-number">{{ row.last_price }}</span></td>
                <td data-sort="{{ row.change_pct_numeric }}"><span class="badge {{ row.change_badge }} sheet-number">{{ row.change_text }}</span></td>
                <td data-sort="{{ row.close_price_numeric }}">
                  <div class="ohlc-compact">
                    <div class="sheet-ohlc-line"><span class="sheet-ohlc-tag">O</span><span class="sheet-number">{{ row.open_price }}</span></div>
                    <div class="sheet-ohlc-line"><span class="sheet-ohlc-tag">H</span><span class="sheet-number">{{ row.day_high }}</span></div>
                    <div class="sheet-ohlc-line"><span class="sheet-ohlc-tag">L</span><span class="sheet-number">{{ row.day_low }}</span></div>
                    <div class="sheet-ohlc-line"><span class="sheet-ohlc-tag">C</span><span class="sheet-number">{{ row.close_price }}</span></div>
                  </div>
                </td>
                <td data-sort="{{ row.volume_numeric }}" class="sheet-number">{{ row.volume_display }}</td>
                <td data-sort="{{ row.pdh_numeric }}" class="sheet-number">{{ row.pdh }}</td>
                <td data-sort="{{ row.pdl_numeric }}" class="sheet-number">{{ row.pdl }}</td>
                <td data-sort="{{ row.prev_close_numeric }}" class="sheet-number">{{ row.prev_close }}</td>
                <td data-sort="{{ row.vwap_numeric }}"><span class="badge {{ row.vwap_badge }} sheet-number">{{ row.vwap }}</span></td>
                <td data-sort="{{ row.status_sort }}"><span class="badge {{ row.status_badge }}">{{ row.status_label }}</span></td>
                <td><span class="badge {{ row.alert_badge }}">{{ row.alert_label }}</span></td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>

        <div class="mobile-only">
          <div class="mobile-card-grid">
            {% for row in rows %}
            <div class="mobile-card">
              <div class="mobile-head">
                <div>
                  <div class="mobile-title"><a class="symbol-link" href="/scripts-watchlists?watchlist={{ active_watchlist.key }}&selected={{ row.symbol }}&refresh={{ refresh_seconds }}">{{ row.symbol }}</a></div>
                  <div class="mobile-sub">{{ row.security_name }}</div>
                </div>
                <span class="badge {{ row.change_badge }}">{{ row.change_text }}</span>
              </div>
              <div class="mobile-metrics">
                <div class="mobile-metric"><div class="mobile-metric-label">LTP</div><div class="mobile-metric-value">{{ row.last_price }}</div></div>
                <div class="mobile-metric"><div class="mobile-metric-label">Volume</div><div class="mobile-metric-value">{{ row.volume_display }}</div></div>
                <div class="mobile-metric"><div class="mobile-metric-label">PDH</div><div class="mobile-metric-value">{{ row.pdh }}</div></div>
                <div class="mobile-metric"><div class="mobile-metric-label">PDL</div><div class="mobile-metric-value">{{ row.pdl }}</div></div>
                <div class="mobile-metric"><div class="mobile-metric-label">Prev Close</div><div class="mobile-metric-value">{{ row.prev_close }}</div></div>
                <div class="mobile-metric"><div class="mobile-metric-label">VWAP</div><div class="mobile-metric-value">{{ row.vwap }}</div></div>
              </div>
              <div class="inline-actions">
                <span class="badge {{ row.status_badge }}">{{ row.status_label }}</span>
                <span class="badge {{ row.alert_badge }}">{{ row.alert_label }}</span>
              </div>
              <div class="mobile-note" style="margin-top: 10px;">
                <strong>OHLC:</strong> {{ row.open_price }} / {{ row.day_high }} / {{ row.day_low }} / {{ row.close_price }}<br>
                <strong>Gap:</strong> {{ row.gap_text }}
              </div>
              <form method="post" class="mini-form" style="margin-top: 12px;">
                <input type="hidden" name="watchlist" value="{{ active_watchlist.key }}">
                <input type="hidden" name="symbol" value="{{ row.symbol }}">
                <input type="hidden" name="selected_symbol" value="{{ row.symbol }}">
                <input type="hidden" name="refresh" value="{{ refresh_seconds }}">
                <button type="submit" class="secondary" name="action" value="move_up">Up</button>
                <button type="submit" class="secondary" name="action" value="move_down">Down</button>
                <button type="submit" name="action" value="remove_stock">Remove</button>
              </form>
            </div>
            {% endfor %}
          </div>
        </div>
        {% else %}
        <div class="notice-box">
          <div class="empty-copy">This watchlist is empty right now. Add a stock above by symbol or company name and the desk will start tracking it here.</div>
        </div>
        {% endif %}
      </div>

      <div class="detail-column">
        <h2>Selected Stock Detail</h2>
        {% if selected_row %}
        <div class="detail-box">
          <div class="inline-actions" style="margin-top: 0;">
            <span class="badge {{ selected_row.status_badge }}">{{ selected_row.status_label }}</span>
            <span class="badge {{ selected_row.change_badge }}">{{ selected_row.change_text }}</span>
            <span class="badge {{ selected_row.alert_badge }}">{{ selected_row.alert_label }}</span>
          </div>
          <h3 style="margin-top: 12px;">{{ selected_row.symbol }}</h3>
          <div class="empty-copy">{{ selected_row.security_name }}</div>
          <div class="detail-metrics">
            <div class="detail-metric"><div class="detail-label">LTP</div><div class="detail-value">{{ selected_row.last_price }}</div></div>
            <div class="detail-metric"><div class="detail-label">Volume</div><div class="detail-value">{{ selected_row.volume_display }}</div></div>
            <div class="detail-metric"><div class="detail-label">PDH</div><div class="detail-value">{{ selected_row.pdh }}</div></div>
            <div class="detail-metric"><div class="detail-label">PDL</div><div class="detail-value">{{ selected_row.pdl }}</div></div>
            <div class="detail-metric"><div class="detail-label">Prev Close</div><div class="detail-value">{{ selected_row.prev_close }}</div></div>
            <div class="detail-metric"><div class="detail-label">VWAP</div><div class="detail-value">{{ selected_row.vwap }}</div></div>
            <div class="detail-metric"><div class="detail-label">Gap</div><div class="detail-value">{{ selected_row.gap_text }}</div></div>
            <div class="detail-metric"><div class="detail-label">52 Week</div><div class="detail-value">{{ selected_row.week_high }} / {{ selected_row.week_low }}</div></div>
          </div>
          <div style="margin-top: 14px;">
            <div class="detail-label">Day Range Position</div>
            <div class="range-bar" style="height: 14px;"><div class="range-fill" style="width: {{ selected_row.day_range_percent }}%;"></div></div>
            <div class="range-meta"><span>Low {{ selected_row.day_low }}</span><span>{{ selected_row.day_range_percent }}%</span><span>High {{ selected_row.day_high }}</span></div>
          </div>
          <div style="margin-top: 16px;">
            <a class="action-link" href="/equity-ohlc?symbols={{ selected_row.symbol }}&date={{ today_date }}&start=09:15&end=09:30">Open OHLC Page</a>
            <a class="action-link" href="/equity-previous-levels?universe_mode=nifty50&signal_view=all&refresh=0">Open Previous Levels</a>
          </div>
          <form method="post" class="detail-actions">
            <input type="hidden" name="watchlist" value="{{ active_watchlist.key }}">
            <input type="hidden" name="symbol" value="{{ selected_row.symbol }}">
            <input type="hidden" name="selected_symbol" value="{{ selected_row.symbol }}">
            <input type="hidden" name="refresh" value="{{ refresh_seconds }}">
            <button type="submit" class="secondary" name="action" value="move_up">Move Up</button>
            <button type="submit" class="secondary" name="action" value="move_down">Move Down</button>
            <button type="submit" name="action" value="remove_stock">Remove Stock</button>
          </form>
          <form method="post" style="margin-top: 16px;">
            <input type="hidden" name="action" value="save_meta">
            <input type="hidden" name="watchlist" value="{{ active_watchlist.key }}">
            <input type="hidden" name="symbol" value="{{ selected_row.symbol }}">
            <input type="hidden" name="selected_symbol" value="{{ selected_row.symbol }}">
            <input type="hidden" name="refresh" value="{{ refresh_seconds }}">
            <div style="margin-bottom: 12px;">
              <label for="alert_rule">Alert Rule</label>
              <select id="alert_rule" name="alert_rule">
                {% for option in alert_options %}
                <option value="{{ option.value }}" {{ 'selected' if option.value == selected_row.alert_rule else '' }}>{{ option.label }}</option>
                {% endfor %}
              </select>
            </div>
            <div style="margin-top: 12px;"><button type="submit">Save Alert Rule</button></div>
          </form>
        </div>
        {% else %}
        <div class="notice-box">
          <div class="empty-copy">Choose a stock from the table to open its detail panel. Notes and alert rules are saved per stock inside this watchlist.</div>
        </div>
        {% endif %}
      </div>
    </section>
  </div>
  <script>
    (function () {
      const table = document.getElementById("manual-watchlist-table");
      if (!table) return;
      const tbody = table.querySelector("tbody");
      const headers = table.querySelectorAll("th.sortable");
      let currentKey = null;
      let ascending = false;

      function getCellValue(row, index) {
        const cell = row.children[index];
        return cell ? cell.dataset.sort || cell.textContent.trim() : "";
      }

      headers.forEach((header, index) => {
        header.addEventListener("click", () => {
          const key = header.dataset.key;
          ascending = currentKey === key ? !ascending : false;
          currentKey = key;
          const rows = Array.from(tbody.querySelectorAll("tr"));
          rows.sort((a, b) => {
            const aValue = getCellValue(a, index);
            const bValue = getCellValue(b, index);
            const aNumber = Number(aValue);
            const bNumber = Number(bValue);
            let result = 0;

            if (!Number.isNaN(aNumber) && !Number.isNaN(bNumber)) {
              result = aNumber - bNumber;
            } else {
              result = aValue.localeCompare(bValue);
            }

            return ascending ? result : -result;
          });
          rows.forEach((row) => tbody.appendChild(row));
        });
      });
    })();
  </script>
  {% if refresh_seconds > 0 %}
  <script>
    window.setTimeout(function () {
      window.location.reload();
    }, {{ refresh_seconds * 1000 }});
  </script>
  {% endif %}
</body>
</html>
"""

MOVERS_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Movers</title>
  <style>
    :root {
      --bg: #f2ede2;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --accent-soft: #dbece7;
      --up: #116149;
      --up-soft: #d7efe7;
      --down: #8a2e2e;
      --down-soft: #f7dddd;
      --neutral: #7a5a18;
      --neutral-soft: #f5ebcc;
      --info: #1f3f73;
      --info-soft: #dde8f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at left top, rgba(31,111,95,0.1), transparent 28%),
        linear-gradient(180deg, #fbf7ef 0%, #ece3d6 100%);
    }
    .page {
      max-width: 1360px;
      margin: 0 auto;
      padding: 28px 18px 56px;
    }
    .hero {
      background: linear-gradient(135deg, rgba(20,44,62,0.98), rgba(31,111,95,0.92));
      color: #f8f5ef;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 22px 60px rgba(24,32,39,0.14);
    }
    h1 {
      margin: 0;
      font-size: 40px;
      line-height: 1;
    }
    .sub {
      margin: 12px 0 0;
      max-width: 900px;
      font-size: 17px;
      line-height: 1.5;
      color: rgba(248,245,239,0.88);
    }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      font-size: 14px;
    }
    .card {
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: 0 18px 44px rgba(24,32,39,0.07);
    }
    .card h2 {
      margin: 0 0 12px;
      font-size: 24px;
    }
    .toolbar-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      align-items: end;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input, select {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    button, .watch-link, .quick-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      border: 0;
      border-radius: 14px;
      padding: 12px 16px;
      font: inherit;
      font-weight: 700;
      text-decoration: none;
    }
    button {
      color: #fff;
      background: var(--accent);
    }
    .watch-links, .quick-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .watch-link, .quick-link {
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
    }
    .watch-link.active, .quick-link.active {
      background: var(--accent-soft);
      color: var(--accent);
      border-color: rgba(31,111,95,0.24);
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }
    .summary-box {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
    }
    .summary-box strong {
      display: block;
      margin-bottom: 8px;
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .summary-value {
      font-size: 28px;
      font-weight: 700;
    }
    .table-wrap {
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 18px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 1120px;
    }
    th, td {
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }
    tbody tr {
      cursor: pointer;
    }
    tbody tr:hover {
      background: rgba(31,111,95,0.06);
    }
    th {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      background: #faf7f1;
      cursor: pointer;
      user-select: none;
    }
    th.sortable:hover {
      color: var(--ink);
    }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up {
      background: var(--up-soft);
      color: var(--up);
    }
    .badge-down {
      background: var(--down-soft);
      color: var(--down);
    }
    .badge-neutral {
      background: var(--neutral-soft);
      color: var(--neutral);
    }
    .badge-info {
      background: var(--info-soft);
      color: var(--info);
    }
    .symbol-link {
      color: var(--accent);
      font-weight: 700;
      text-decoration: none;
    }
    .symbol-link:hover {
      text-decoration: underline;
    }
    .muted {
      color: var(--muted);
    }
    .error {
      margin-top: 14px;
      border-radius: 16px;
      padding: 14px 16px;
      background: #f7e3d9;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.18);
    }
    .legend {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }
    .legend-item {
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
    }
    .legend-item strong {
      display: block;
      margin-bottom: 6px;
      font-size: 14px;
      text-transform: uppercase;
    }
    @media (max-width: 720px) {
      h1 { font-size: 32px; }
      .page { padding: 18px 12px 40px; }
      .hero, .card { border-radius: 18px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Equity Movers & Gap Scanner</h1>
      <p class="sub">
        A separate page for top gainers, top losers, and gap-up / gap-down tracking inside your chosen basket.
        The table ranks symbols by day change and opening gap, and auto-refresh can keep the board current.
      </p>
      <div class="meta">
        <div class="pill">Watchlist: {{ active_watchlist_label }}</div>
        <div class="pill">Date: {{ selected_date }}</div>
        <div class="pill">Auto Refresh: {{ refresh_label }}</div>
      </div>
    </section>

    <section class="card">
      <h2>Saved Watchlists</h2>
      <div class="watch-links">
        {% for watch in watchlists %}
        <a class="watch-link {{ 'active' if watch.key == active_watchlist else '' }}"
           href="/equity-movers?watchlist={{ watch.key }}&date={{ selected_date }}&refresh={{ refresh_seconds }}">
          {{ watch.label }}
        </a>
        {% endfor %}
      </div>
    </section>

    <section class="card">
      <h2>Movers Controls</h2>
      <form method="get" class="toolbar-grid">
        <div>
          <label for="watchlist">Watchlist</label>
          <select id="watchlist" name="watchlist">
            {% for watch in watchlists %}
            <option value="{{ watch.key }}" {{ 'selected' if watch.key == active_watchlist else '' }}>{{ watch.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="symbols">Custom Symbols</label>
          <input id="symbols" name="symbols" value="{{ request_symbols }}" placeholder="IOC,PNB,SBIN,RELIANCE">
        </div>
        <div>
          <label for="date">Date</label>
          <input id="date" name="date" value="{{ selected_date }}" placeholder="YYYY-MM-DD">
        </div>
        <div>
          <label for="refresh">Auto Refresh</label>
          <select id="refresh" name="refresh">
            {% for option in refresh_options %}
            <option value="{{ option.value }}" {{ 'selected' if option.value == refresh_seconds else '' }}>{{ option.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <button type="submit">Run Movers Page</button>
        </div>
      </form>
      <div class="quick-links">
        <a class="quick-link {{ 'active' if selected_date == today_date else '' }}"
           href="/equity-movers?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ today_date }}&refresh={{ refresh_seconds }}">
          Today
        </a>
        <a class="quick-link {{ 'active' if selected_date == yesterday_date else '' }}"
           href="/equity-movers?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ yesterday_date }}&refresh={{ refresh_seconds }}">
          Yesterday
        </a>
      </div>
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Summary</h2>
      <div class="summary-grid">
        <div class="summary-box">
          <strong>Top Gainers</strong>
          <div class="summary-value">{{ summary.gainers_count }}</div>
          <div class="muted">Positive day-change names</div>
        </div>
        <div class="summary-box">
          <strong>Top Losers</strong>
          <div class="summary-value">{{ summary.losers_count }}</div>
          <div class="muted">Negative day-change names</div>
        </div>
        <div class="summary-box">
          <strong>Gap Up</strong>
          <div class="summary-value">{{ summary.gap_up_count }}</div>
          <div class="muted">Opened above previous close</div>
        </div>
        <div class="summary-box">
          <strong>Gap Down</strong>
          <div class="summary-value">{{ summary.gap_down_count }}</div>
          <div class="muted">Opened below previous close</div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>How To Read It</h2>
      <div class="legend">
        <div class="legend-item">
          <strong>Day Change %</strong>
          Positive names are your gainers, negative names are your losers. Sort this column to instantly rank the basket.
        </div>
        <div class="legend-item">
          <strong>Gap %</strong>
          Gap-up names opened above the previous close, gap-down names opened below it. That helps spot overnight strength or weakness.
        </div>
        <div class="legend-item">
          <strong>Click Through</strong>
          Click any row or symbol to open the detailed OHLC page for deeper intraday review.
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Movers Table</h2>
      <div class="table-wrap">
        <table id="movers-table">
          <thead>
            <tr>
              <th class="sortable" data-key="symbol">Symbol</th>
              <th class="sortable" data-key="last_price">Last Price</th>
              <th class="sortable" data-key="day_change_pct">Day Change %</th>
              <th class="sortable" data-key="gap_pct">Gap %</th>
              <th class="sortable" data-key="open_price">Open</th>
              <th class="sortable" data-key="prev_close">Prev Close</th>
              <th class="sortable" data-key="day_high">Day High</th>
              <th class="sortable" data-key="day_low">Day Low</th>
              <th class="sortable" data-key="gap_sort">Gap Status</th>
            </tr>
          </thead>
          <tbody>
            {% for row in mover_rows %}
            <tr onclick="window.location='/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start=09:15&end=09:30'">
              <td data-sort="{{ row.symbol }}">
                <a class="symbol-link" href="/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start=09:15&end=09:30" onclick="event.stopPropagation()">{{ row.symbol }}</a>
              </td>
              <td data-sort="{{ row.last_price_numeric }}">{{ row.last_price }}</td>
              <td data-sort="{{ row.day_change_pct_numeric }}">
                <span class="badge {{ row.day_change_badge }}">{{ row.day_change_pct }}</span>
              </td>
              <td data-sort="{{ row.gap_pct_numeric }}">
                <span class="badge {{ row.gap_badge }}">{{ row.gap_pct }}</span>
              </td>
              <td data-sort="{{ row.open_price_numeric }}">{{ row.open_price }}</td>
              <td data-sort="{{ row.prev_close_numeric }}">{{ row.prev_close }}</td>
              <td data-sort="{{ row.day_high_numeric }}">{{ row.day_high }}</td>
              <td data-sort="{{ row.day_low_numeric }}">{{ row.day_low }}</td>
              <td data-sort="{{ row.gap_sort }}">
                <span class="badge {{ row.gap_badge }}">{{ row.gap_status }}</span>
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </section>
  </div>
  {% if refresh_seconds > 0 %}
  <script>
    window.setTimeout(function () {
      window.location.reload();
    }, {{ refresh_seconds * 1000 }});
  </script>
  {% endif %}
  <script>
    (function () {
      const table = document.getElementById("movers-table");
      if (!table) return;
      const tbody = table.querySelector("tbody");
      const headers = table.querySelectorAll("th.sortable");
      let currentKey = null;
      let ascending = false;

      function getCellValue(row, index) {
        const cell = row.children[index];
        return cell ? cell.dataset.sort || cell.textContent.trim() : "";
      }

      headers.forEach((header, index) => {
        header.addEventListener("click", () => {
          const key = header.dataset.key;
          ascending = currentKey === key ? !ascending : false;
          currentKey = key;
          const rows = Array.from(tbody.querySelectorAll("tr"));
          rows.sort((a, b) => {
            const aValue = getCellValue(a, index);
            const bValue = getCellValue(b, index);
            const aNumber = Number(aValue);
            const bNumber = Number(bValue);
            let result = 0;

            if (!Number.isNaN(aNumber) && !Number.isNaN(bNumber)) {
              result = aNumber - bNumber;
            } else {
              result = aValue.localeCompare(bValue);
            }

            return ascending ? result : -result;
          });
          rows.forEach((row) => tbody.appendChild(row));
        });
      });
    })();
  </script>
</body>
</html>
"""

CONFIRMATION_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub ORB Confirmation</title>
  <style>
    :root {
      --bg: #f2ede2;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --accent-soft: #dbece7;
      --up: #116149;
      --up-soft: #d7efe7;
      --down: #8a2e2e;
      --down-soft: #f7dddd;
      --neutral: #7a5a18;
      --neutral-soft: #f5ebcc;
      --info: #1f3f73;
      --info-soft: #dde8f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at right top, rgba(31,111,95,0.1), transparent 28%),
        linear-gradient(180deg, #fbf7ef 0%, #ece3d6 100%);
    }
    .page {
      max-width: 1360px;
      margin: 0 auto;
      padding: 28px 18px 56px;
    }
    .hero {
      background: linear-gradient(135deg, rgba(20,44,62,0.98), rgba(31,111,95,0.92));
      color: #f8f5ef;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 22px 60px rgba(24,32,39,0.14);
    }
    h1 { margin: 0; font-size: 40px; line-height: 1; }
    .sub {
      margin: 12px 0 0;
      max-width: 920px;
      font-size: 17px;
      line-height: 1.5;
      color: rgba(248,245,239,0.88);
    }
    .meta, .watch-links, .quick-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      font-size: 14px;
    }
    .card {
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: 0 18px 44px rgba(24,32,39,0.07);
    }
    .card h2 { margin: 0 0 12px; font-size: 24px; }
    .toolbar-grid, .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input, select {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    button, .watch-link, .quick-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      border: 0;
      border-radius: 14px;
      padding: 12px 16px;
      font: inherit;
      font-weight: 700;
      text-decoration: none;
    }
    button { color: #fff; background: var(--accent); }
    .watch-link, .quick-link {
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
    }
    .watch-link.active, .quick-link.active {
      background: var(--accent-soft);
      color: var(--accent);
      border-color: rgba(31,111,95,0.24);
    }
    .summary-box, .legend-item {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
    }
    .summary-box strong, .legend-item strong {
      display: block;
      margin-bottom: 8px;
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .summary-value {
      font-size: 28px;
      font-weight: 700;
    }
    .table-wrap {
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 18px;
    }
    table { width: 100%; border-collapse: collapse; min-width: 1240px; }
    th, td {
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }
    tbody tr { cursor: pointer; }
    tbody tr:hover { background: rgba(31,111,95,0.06); }
    th {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      background: #faf7f1;
      cursor: pointer;
      user-select: none;
    }
    th.sortable:hover { color: var(--ink); }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up { background: var(--up-soft); color: var(--up); }
    .badge-down { background: var(--down-soft); color: var(--down); }
    .badge-neutral { background: var(--neutral-soft); color: var(--neutral); }
    .badge-info { background: var(--info-soft); color: var(--info); }
    .symbol-link {
      color: var(--accent);
      font-weight: 700;
      text-decoration: none;
    }
    .symbol-link:hover { text-decoration: underline; }
    .error {
      margin-top: 14px;
      border-radius: 16px;
      padding: 14px 16px;
      background: #f7e3d9;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.18);
    }
    .ai-text { max-width: 320px; line-height: 1.45; }
    .legend {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }
    @media (max-width: 720px) {
      h1 { font-size: 32px; }
      .page { padding: 18px 12px 40px; }
      .hero, .card { border-radius: 18px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>ORB Confirmation Dashboard</h1>
      <p class="sub">
        A separate page for the cleaner intraday setups where ORB direction, VWAP position, and volume confirmation are aligned.
        This helps you focus only on bullish or bearish names with stronger participation.
      </p>
      <div class="meta">
        <div class="pill">Watchlist: {{ active_watchlist_label }}</div>
        <div class="pill">Date: {{ selected_date }}</div>
        <div class="pill">Range: {{ start_time }} to {{ end_time }}</div>
        <div class="pill">Auto Refresh: {{ refresh_label }}</div>
      </div>
    </section>

    <section class="card">
      <h2>Saved Watchlists</h2>
      <div class="watch-links">
        {% for watch in watchlists %}
        <a class="watch-link {{ 'active' if watch.key == active_watchlist else '' }}"
           href="/equity-confirmation?watchlist={{ watch.key }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}&refresh={{ refresh_seconds }}">
          {{ watch.label }}
        </a>
        {% endfor %}
      </div>
    </section>

    <section class="card">
      <h2>Confirmation Controls</h2>
      <form method="get" class="toolbar-grid">
        <div>
          <label for="watchlist">Watchlist</label>
          <select id="watchlist" name="watchlist">
            {% for watch in watchlists %}
            <option value="{{ watch.key }}" {{ 'selected' if watch.key == active_watchlist else '' }}>{{ watch.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="symbols">Custom Symbols</label>
          <input id="symbols" name="symbols" value="{{ request_symbols }}" placeholder="IOC,PNB,SBIN,RELIANCE">
        </div>
        <div>
          <label for="date">Date</label>
          <input id="date" name="date" value="{{ selected_date }}" placeholder="YYYY-MM-DD">
        </div>
        <div>
          <label for="start">Start</label>
          <input id="start" name="start" value="{{ start_time }}" placeholder="09:15">
        </div>
        <div>
          <label for="end">End</label>
          <input id="end" name="end" value="{{ end_time }}" placeholder="09:30">
        </div>
        <div>
          <label for="refresh">Auto Refresh</label>
          <select id="refresh" name="refresh">
            {% for option in refresh_options %}
            <option value="{{ option.value }}" {{ 'selected' if option.value == refresh_seconds else '' }}>{{ option.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <button type="submit">Open Confirmation Page</button>
        </div>
      </form>
      <div class="quick-links">
        <a class="quick-link {{ 'active' if selected_date == today_date else '' }}"
           href="/equity-confirmation?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ today_date }}&start={{ start_time }}&end={{ end_time }}&refresh={{ refresh_seconds }}">
          Today
        </a>
        <a class="quick-link {{ 'active' if selected_date == yesterday_date else '' }}"
           href="/equity-confirmation?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ yesterday_date }}&start={{ start_time }}&end={{ end_time }}&refresh={{ refresh_seconds }}">
          Yesterday
        </a>
      </div>
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Summary</h2>
      <div class="summary-grid">
        <div class="summary-box">
          <strong>Confirmed Longs</strong>
          <div class="summary-value">{{ summary.long_count }}</div>
          <div>Above OR high + above VWAP + high volume</div>
        </div>
        <div class="summary-box">
          <strong>Confirmed Shorts</strong>
          <div class="summary-value">{{ summary.short_count }}</div>
          <div>Below OR low + below VWAP + high volume</div>
        </div>
        <div class="summary-box">
          <strong>Total Confirmations</strong>
          <div class="summary-value">{{ summary.total_count }}</div>
          <div>Strongest names in the current basket</div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>How To Read It</h2>
      <div class="legend">
        <div class="legend-item">
          <strong>Confirmed Long</strong>
          Price is above OR high, above VWAP, and the latest volume is high versus recent average.
        </div>
        <div class="legend-item">
          <strong>Confirmed Short</strong>
          Price is below OR low, below VWAP, and the latest volume is high versus recent average.
        </div>
        <div class="legend-item">
          <strong>Click Through</strong>
          Click any row or symbol to open the detailed OHLC page for deeper confirmation and minute-level context.
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Confirmation Table</h2>
      <div class="table-wrap">
        <table id="confirmation-table">
          <thead>
            <tr>
              <th class="sortable" data-key="symbol">Symbol</th>
              <th class="sortable" data-key="confirmation_sort">Confirmation</th>
              <th class="sortable" data-key="last_price">Latest Price</th>
              <th class="sortable" data-key="breakout_gap">Breakout Gap</th>
              <th class="sortable" data-key="vwap_sort">VWAP Status</th>
              <th class="sortable" data-key="volume_ratio">Volume Status</th>
              <th class="sortable" data-key="or_high">OR High</th>
              <th class="sortable" data-key="or_low">OR Low</th>
              <th class="sortable" data-key="range_size">Range Size</th>
              <th>AI Suggestion</th>
            </tr>
          </thead>
          <tbody>
            {% for row in confirmation_rows %}
            <tr onclick="window.location='/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}'">
              <td data-sort="{{ row.symbol }}">
                <a class="symbol-link" href="/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}" onclick="event.stopPropagation()">{{ row.symbol }}</a>
              </td>
              <td data-sort="{{ row.confirmation_sort }}">
                <span class="badge {{ row.confirmation_badge }}">{{ row.confirmation_status }}</span>
              </td>
              <td data-sort="{{ row.last_price_numeric }}">{{ row.last_price }}</td>
              <td data-sort="{{ row.breakout_gap_numeric }}">
                <span class="badge {{ row.breakout_gap_badge }}">{{ row.breakout_gap }}</span>
              </td>
              <td data-sort="{{ row.vwap_sort }}">
                <span class="badge {{ row.vwap_badge }}">{{ row.vwap_status }}</span>
              </td>
              <td data-sort="{{ row.volume_ratio_numeric }}">
                <span class="badge {{ row.volume_badge }}">{{ row.volume_status }}</span>
              </td>
              <td data-sort="{{ row.or_high_numeric }}">{{ row.or_high }}</td>
              <td data-sort="{{ row.or_low_numeric }}">{{ row.or_low }}</td>
              <td data-sort="{{ row.range_size_numeric }}">{{ row.range_size }}</td>
              <td class="ai-text">{{ row.ai_suggestion }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </section>
  </div>
  {% if refresh_seconds > 0 %}
  <script>
    window.setTimeout(function () {
      window.location.reload();
    }, {{ refresh_seconds * 1000 }});
  </script>
  {% endif %}
  <script>
    (function () {
      const table = document.getElementById("confirmation-table");
      if (!table) return;
      const tbody = table.querySelector("tbody");
      const headers = table.querySelectorAll("th.sortable");
      let currentKey = null;
      let ascending = false;

      function getCellValue(row, index) {
        const cell = row.children[index];
        return cell ? cell.dataset.sort || cell.textContent.trim() : "";
      }

      headers.forEach((header, index) => {
        header.addEventListener("click", () => {
          const key = header.dataset.key;
          ascending = currentKey === key ? !ascending : false;
          currentKey = key;
          const rows = Array.from(tbody.querySelectorAll("tr"));
          rows.sort((a, b) => {
            const aValue = getCellValue(a, index);
            const bValue = getCellValue(b, index);
            const aNumber = Number(aValue);
            const bNumber = Number(bValue);
            let result = 0;

            if (!Number.isNaN(aNumber) && !Number.isNaN(bNumber)) {
              result = aNumber - bNumber;
            } else {
              result = aValue.localeCompare(bValue);
            }

            return ascending ? result : -result;
          });
          rows.forEach((row) => tbody.appendChild(row));
        });
      });
    })();
  </script>
</body>
</html>
"""

SECTOR_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Sector Strength</title>
  <style>
    :root {
      --bg: #f2ede2;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --accent-soft: #dbece7;
      --up: #116149;
      --up-soft: #d7efe7;
      --down: #8a2e2e;
      --down-soft: #f7dddd;
      --neutral: #7a5a18;
      --neutral-soft: #f5ebcc;
      --info: #1f3f73;
      --info-soft: #dde8f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at left top, rgba(31,111,95,0.1), transparent 28%),
        linear-gradient(180deg, #fbf7ef 0%, #ece3d6 100%);
    }
    .page {
      max-width: 1380px;
      margin: 0 auto;
      padding: 28px 18px 56px;
    }
    .hero {
      background: linear-gradient(135deg, rgba(20,44,62,0.98), rgba(31,111,95,0.92));
      color: #f8f5ef;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 22px 60px rgba(24,32,39,0.14);
    }
    h1 { margin: 0; font-size: 40px; line-height: 1; }
    .sub {
      margin: 12px 0 0;
      max-width: 940px;
      font-size: 17px;
      line-height: 1.5;
      color: rgba(248,245,239,0.88);
    }
    .meta, .sector-links, .quick-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      font-size: 14px;
    }
    .card {
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: 0 18px 44px rgba(24,32,39,0.07);
    }
    .card h2 { margin: 0 0 12px; font-size: 24px; }
    .toolbar-grid, .sector-card-grid, .legend {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input, select {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    button, .sector-link, .quick-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      border: 0;
      border-radius: 14px;
      padding: 12px 16px;
      font: inherit;
      font-weight: 700;
      text-decoration: none;
    }
    button { color: #fff; background: var(--accent); }
    .sector-link, .quick-link {
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
    }
    .sector-link.active, .quick-link.active {
      background: var(--accent-soft);
      color: var(--accent);
      border-color: rgba(31,111,95,0.24);
    }
    .sector-card, .legend-item {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
    }
    .sector-card h3 {
      margin: 0 0 8px;
      font-size: 20px;
    }
    .stat-row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-top: 8px;
      font-size: 14px;
    }
    .summary-value {
      font-size: 30px;
      font-weight: 700;
    }
    .table-wrap {
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 18px;
    }
    table { width: 100%; border-collapse: collapse; min-width: 1220px; }
    th, td {
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }
    tbody tr { cursor: pointer; }
    tbody tr:hover { background: rgba(31,111,95,0.06); }
    th {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      background: #faf7f1;
      cursor: pointer;
      user-select: none;
    }
    th.sortable:hover { color: var(--ink); }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up { background: var(--up-soft); color: var(--up); }
    .badge-down { background: var(--down-soft); color: var(--down); }
    .badge-neutral { background: var(--neutral-soft); color: var(--neutral); }
    .badge-info { background: var(--info-soft); color: var(--info); }
    .symbol-link {
      color: var(--accent);
      font-weight: 700;
      text-decoration: none;
    }
    .symbol-link:hover { text-decoration: underline; }
    .error {
      margin-top: 14px;
      border-radius: 16px;
      padding: 14px 16px;
      background: #f7e3d9;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.18);
    }
    .muted { color: var(--muted); }
    .note-text { max-width: 340px; line-height: 1.45; }
    @media (max-width: 720px) {
      h1 { font-size: 32px; }
      .page { padding: 18px 12px 40px; }
      .hero, .card { border-radius: 18px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Sector Strength Dashboard</h1>
      <p class="sub">
        A sector-level dashboard that ranks baskets by average day change, opening gap, confirmation counts, VWAP breadth,
        and high-volume participation. Use it to see where broad strength or weakness is building before drilling into stocks.
      </p>
      <div class="meta">
        <div class="pill">Date: {{ selected_date }}</div>
        <div class="pill">Range: {{ start_time }} to {{ end_time }}</div>
        <div class="pill">Selected Sector: {{ selected_sector_label }}</div>
        <div class="pill">Auto Refresh: {{ refresh_label }}</div>
      </div>
    </section>

    <section class="card">
      <h2>Controls</h2>
      <form method="get" class="toolbar-grid">
        <div>
          <label for="date">Date</label>
          <input id="date" name="date" value="{{ selected_date }}" placeholder="YYYY-MM-DD">
        </div>
        <div>
          <label for="start">Start</label>
          <input id="start" name="start" value="{{ start_time }}" placeholder="09:15">
        </div>
        <div>
          <label for="end">End</label>
          <input id="end" name="end" value="{{ end_time }}" placeholder="09:30">
        </div>
        <div>
          <label for="sector">Sector</label>
          <select id="sector" name="sector">
            {% for sector in sector_options %}
            <option value="{{ sector.key }}" {{ 'selected' if sector.key == selected_sector else '' }}>{{ sector.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="refresh">Auto Refresh</label>
          <select id="refresh" name="refresh">
            {% for option in refresh_options %}
            <option value="{{ option.value }}" {{ 'selected' if option.value == refresh_seconds else '' }}>{{ option.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <button type="submit">Open Dashboard</button>
        </div>
      </form>
      <div class="quick-links">
        <a class="quick-link {{ 'active' if selected_date == today_date else '' }}"
           href="/equity-sector-strength?date={{ today_date }}&start={{ start_time }}&end={{ end_time }}&sector={{ selected_sector }}&refresh={{ refresh_seconds }}">
          Today
        </a>
        <a class="quick-link {{ 'active' if selected_date == yesterday_date else '' }}"
           href="/equity-sector-strength?date={{ yesterday_date }}&start={{ start_time }}&end={{ end_time }}&sector={{ selected_sector }}&refresh={{ refresh_seconds }}">
          Yesterday
        </a>
      </div>
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Sector Cards</h2>
      <div class="sector-card-grid">
        {% for row in sector_rows[:4] %}
        <div class="sector-card">
          <h3>{{ row.sector_label }}</h3>
          <div class="summary-value">{{ row.sector_score_display }}</div>
          <div class="muted">Sector score</div>
          <div class="stat-row"><span>Avg Change</span><strong>{{ row.avg_change_pct }}</strong></div>
          <div class="stat-row"><span>Avg Gap</span><strong>{{ row.avg_gap_pct }}</strong></div>
          <div class="stat-row"><span>Confirmed Longs</span><strong>{{ row.bullish_confirmations }}</strong></div>
          <div class="stat-row"><span>Confirmed Shorts</span><strong>{{ row.bearish_confirmations }}</strong></div>
          <div class="stat-row"><span>Top Gainer</span><strong>{{ row.top_gainer }}</strong></div>
          <div class="stat-row"><span>Top Loser</span><strong>{{ row.top_loser }}</strong></div>
        </div>
        {% endfor %}
      </div>
    </section>

    <section class="card">
      <h2>How To Read It</h2>
      <div class="legend">
        <div class="legend-item">
          <strong>Sector Score</strong>
          A practical weighted score built from average day change plus bullish confirmations minus bearish confirmations.
        </div>
        <div class="legend-item">
          <strong>Breadth</strong>
          Above VWAP counts, below VWAP counts, and high-volume counts show whether the move is broad-based or just one stock.
        </div>
        <div class="legend-item">
          <strong>Selected Sector</strong>
          Choose a sector from the table or dropdown to inspect all stocks in that basket below.
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Sector Ranking Table</h2>
      <div class="table-wrap">
        <table id="sector-table">
          <thead>
            <tr>
              <th class="sortable" data-key="sector">Sector</th>
              <th class="sortable" data-key="sector_score">Sector Score</th>
              <th class="sortable" data-key="avg_change_pct">Avg Change %</th>
              <th class="sortable" data-key="avg_gap_pct">Avg Gap %</th>
              <th class="sortable" data-key="bullish_confirmations">Bullish Conf.</th>
              <th class="sortable" data-key="bearish_confirmations">Bearish Conf.</th>
              <th class="sortable" data-key="above_vwap_count">Above VWAP</th>
              <th class="sortable" data-key="below_vwap_count">Below VWAP</th>
              <th class="sortable" data-key="high_volume_count">High Volume</th>
              <th>Top Gainer</th>
              <th>Top Loser</th>
              <th>AI Note</th>
            </tr>
          </thead>
          <tbody>
            {% for row in sector_rows %}
            <tr onclick="window.location='/equity-sector-strength?date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}&sector={{ row.sector_key }}&refresh={{ refresh_seconds }}'">
              <td data-sort="{{ row.sector_label }}">{{ row.sector_label }}</td>
              <td data-sort="{{ row.sector_score_numeric }}"><span class="badge {{ row.score_badge }}">{{ row.sector_score_display }}</span></td>
              <td data-sort="{{ row.avg_change_pct_numeric }}"><span class="badge {{ row.avg_change_badge }}">{{ row.avg_change_pct }}</span></td>
              <td data-sort="{{ row.avg_gap_pct_numeric }}"><span class="badge {{ row.avg_gap_badge }}">{{ row.avg_gap_pct }}</span></td>
              <td data-sort="{{ row.bullish_confirmations }}">{{ row.bullish_confirmations }}</td>
              <td data-sort="{{ row.bearish_confirmations }}">{{ row.bearish_confirmations }}</td>
              <td data-sort="{{ row.above_vwap_count }}">{{ row.above_vwap_count }}</td>
              <td data-sort="{{ row.below_vwap_count }}">{{ row.below_vwap_count }}</td>
              <td data-sort="{{ row.high_volume_count }}">{{ row.high_volume_count }}</td>
              <td>{{ row.top_gainer }}</td>
              <td>{{ row.top_loser }}</td>
              <td class="note-text">{{ row.ai_note }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </section>

    <section class="card">
      <h2>{{ selected_sector_label }} Stocks</h2>
      <div class="table-wrap">
        <table id="sector-detail-table">
          <thead>
            <tr>
              <th class="sortable" data-key="symbol">Symbol</th>
              <th class="sortable" data-key="orb_sort">ORB Status</th>
              <th class="sortable" data-key="last_price">Latest Price</th>
              <th class="sortable" data-key="day_change_pct">Day Change %</th>
              <th class="sortable" data-key="gap_pct">Gap %</th>
              <th class="sortable" data-key="vwap_sort">VWAP Status</th>
              <th class="sortable" data-key="volume_ratio">Volume Status</th>
              <th>AI Suggestion</th>
            </tr>
          </thead>
          <tbody>
            {% for row in selected_sector_rows %}
            <tr onclick="window.location='/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}'">
              <td data-sort="{{ row.symbol }}">
                <a class="symbol-link" href="/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}" onclick="event.stopPropagation()">{{ row.symbol }}</a>
              </td>
              <td data-sort="{{ row.orb_sort }}"><span class="badge {{ row.orb_badge }}">{{ row.orb_status }}</span></td>
              <td data-sort="{{ row.last_price_numeric }}">{{ row.last_price }}</td>
              <td data-sort="{{ row.day_change_pct_numeric }}"><span class="badge {{ row.day_change_badge }}">{{ row.day_change_pct }}</span></td>
              <td data-sort="{{ row.gap_pct_numeric }}"><span class="badge {{ row.gap_badge }}">{{ row.gap_pct }}</span></td>
              <td data-sort="{{ row.vwap_sort }}"><span class="badge {{ row.vwap_badge }}">{{ row.vwap_status }}</span></td>
              <td data-sort="{{ row.volume_ratio_numeric }}"><span class="badge {{ row.volume_badge }}">{{ row.volume_status }}</span></td>
              <td class="note-text">{{ row.ai_suggestion }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </section>
  </div>
  {% if refresh_seconds > 0 %}
  <script>
    window.setTimeout(function () {
      window.location.reload();
    }, {{ refresh_seconds * 1000 }});
  </script>
  {% endif %}
  <script>
    (function () {
      ["sector-table", "sector-detail-table"].forEach((tableId) => {
        const table = document.getElementById(tableId);
        if (!table) return;
        const tbody = table.querySelector("tbody");
        const headers = table.querySelectorAll("th.sortable");
        let currentKey = null;
        let ascending = false;

        function getCellValue(row, index) {
          const cell = row.children[index];
          return cell ? cell.dataset.sort || cell.textContent.trim() : "";
        }

        headers.forEach((header, index) => {
          header.addEventListener("click", () => {
            const key = header.dataset.key;
            ascending = currentKey === key ? !ascending : false;
            currentKey = key;
            const rows = Array.from(tbody.querySelectorAll("tr"));
            rows.sort((a, b) => {
              const aValue = getCellValue(a, index);
              const bValue = getCellValue(b, index);
              const aNumber = Number(aValue);
              const bNumber = Number(bValue);
              let result = 0;

              if (!Number.isNaN(aNumber) && !Number.isNaN(bNumber)) {
                result = aNumber - bNumber;
              } else {
                result = aValue.localeCompare(bValue);
              }

              return ascending ? result : -result;
            });
            rows.forEach((row) => tbody.appendChild(row));
          });
        });
      });
    })();
  </script>
</body>
</html>
"""

SECTOR_HEATMAP_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Sector Rotation Heatmap</title>
  <style>
    :root {
      --bg: #f3ecdf;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --up-strong: #0f5a43;
      --up-soft: #d9f0e8;
      --up-light: #ecf8f3;
      --down-strong: #842b2b;
      --down-soft: #f7dddd;
      --down-light: #fbeeee;
      --neutral-strong: #7a5a18;
      --neutral-soft: #f5ebcc;
      --neutral-light: #faf5e4;
      --info: #1f3f73;
      --info-soft: #dde8f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(31,111,95,0.11), transparent 25%),
        linear-gradient(180deg, #fbf7ef 0%, #ece3d6 100%);
    }
    .page {
      max-width: 1460px;
      margin: 0 auto;
      padding: 28px 18px 56px;
    }
    .hero {
      background: linear-gradient(135deg, rgba(20,44,62,0.98), rgba(31,111,95,0.92));
      color: #f8f5ef;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 22px 60px rgba(24,32,39,0.14);
    }
    h1 { margin: 0; font-size: 40px; line-height: 1; }
    .sub {
      margin: 12px 0 0;
      max-width: 980px;
      font-size: 17px;
      line-height: 1.5;
      color: rgba(248,245,239,0.88);
    }
    .meta, .quick-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      font-size: 14px;
    }
    .card {
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: 0 18px 44px rgba(24,32,39,0.07);
    }
    .card h2 { margin: 0 0 12px; font-size: 24px; }
    .toolbar-grid, .summary-grid, .legend, .heatmap-grid {
      display: grid;
      gap: 14px;
    }
    .toolbar-grid {
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    }
    .summary-grid {
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    }
    .heatmap-grid {
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
    }
    .split-grid {
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 18px;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input, select {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    button, .quick-link, .heat-tile {
      border-radius: 14px;
      font: inherit;
      text-decoration: none;
    }
    button {
      width: 100%;
      border: 0;
      padding: 12px 16px;
      cursor: pointer;
      font-weight: 700;
      color: #fff;
      background: var(--accent);
    }
    .quick-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
      padding: 12px 16px;
      font-weight: 700;
    }
    .quick-link.active {
      background: #dbece7;
      color: var(--accent);
      border-color: rgba(31,111,95,0.24);
    }
    .summary-box, .legend-item {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
    }
    .summary-value {
      font-size: 28px;
      font-weight: 700;
      margin-top: 8px;
    }
    .heat-tile {
      display: block;
      padding: 18px;
      border: 1px solid var(--line);
      background: #fff;
      color: inherit;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.25);
    }
    .heat-tile:hover {
      transform: translateY(-1px);
      transition: transform 0.15s ease;
    }
    .heat-tile.active {
      outline: 2px solid rgba(20,44,62,0.35);
    }
    .heat-up-strong { background: linear-gradient(180deg, rgba(15,90,67,0.95), rgba(38,127,97,0.92)); color: #f8f5ef; }
    .heat-up-soft { background: linear-gradient(180deg, #d9f0e8, #ecf8f3); }
    .heat-neutral { background: linear-gradient(180deg, #faf5e4, #f5ebcc); }
    .heat-down-soft { background: linear-gradient(180deg, #fbeeee, #f7dddd); }
    .heat-down-strong { background: linear-gradient(180deg, rgba(132,43,43,0.93), rgba(167,66,66,0.88)); color: #f8f5ef; }
    .tile-title {
      font-size: 20px;
      font-weight: 700;
      margin-bottom: 8px;
    }
    .tile-score {
      font-size: 30px;
      font-weight: 700;
      line-height: 1;
    }
    .tile-label {
      margin-top: 8px;
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      opacity: 0.88;
    }
    .tile-stats {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px 14px;
      margin-top: 14px;
      font-size: 14px;
    }
    .tile-note {
      margin-top: 12px;
      font-size: 14px;
      line-height: 1.45;
    }
    .table-wrap {
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 18px;
    }
    table { width: 100%; border-collapse: collapse; min-width: 1240px; }
    th, td {
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }
    tbody tr { cursor: pointer; }
    tbody tr:hover { background: rgba(31,111,95,0.06); }
    th {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      background: #faf7f1;
      cursor: pointer;
      user-select: none;
    }
    th.sortable:hover { color: var(--ink); }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up { background: var(--up-soft); color: var(--up-strong); }
    .badge-down { background: var(--down-soft); color: var(--down-strong); }
    .badge-neutral { background: var(--neutral-soft); color: var(--neutral-strong); }
    .badge-info { background: var(--info-soft); color: var(--info); }
    .symbol-link {
      color: var(--accent);
      font-weight: 700;
      text-decoration: none;
    }
    .symbol-link:hover { text-decoration: underline; }
    .error {
      margin-top: 14px;
      border-radius: 16px;
      padding: 14px 16px;
      background: #f7e3d9;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.18);
    }
    .muted { color: var(--muted); }
    .note-text { max-width: 360px; line-height: 1.45; }
    @media (max-width: 980px) {
      .split-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 720px) {
      h1 { font-size: 32px; }
      .page { padding: 18px 12px 40px; }
      .hero, .card { border-radius: 18px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Sector Rotation Heatmap</h1>
      <p class="sub">
        A rotation-first dashboard that maps broad sectors and sub-sectors by strength, breadth, VWAP participation,
        opening-range confirmation, and gap behavior. Use it to spot where money is flowing before committing to a single stock.
      </p>
      <div class="meta">
        <div class="pill">Date: {{ selected_date }}</div>
        <div class="pill">Range: {{ start_time }} to {{ end_time }}</div>
        <div class="pill">Sector: {{ selected_sector_label }}</div>
        <div class="pill">Sub-Sector: {{ selected_sub_sector_label }}</div>
        <div class="pill">Auto Refresh: {{ refresh_label }}</div>
      </div>
    </section>

    <section class="card">
      <h2>Controls</h2>
      <form method="get" class="toolbar-grid">
        <div>
          <label for="date">Date</label>
          <input id="date" name="date" value="{{ selected_date }}" placeholder="YYYY-MM-DD">
        </div>
        <div>
          <label for="start">Start</label>
          <input id="start" name="start" value="{{ start_time }}" placeholder="09:15">
        </div>
        <div>
          <label for="end">End</label>
          <input id="end" name="end" value="{{ end_time }}" placeholder="09:30">
        </div>
        <div>
          <label for="sector">Sector</label>
          <select id="sector" name="sector">
            {% for sector in sector_options %}
            <option value="{{ sector.key }}" {{ 'selected' if sector.key == selected_sector else '' }}>{{ sector.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="subsector">Sub-Sector</label>
          <select id="subsector" name="subsector">
            {% for sub_sector in sub_sector_options %}
            <option value="{{ sub_sector.key }}" {{ 'selected' if sub_sector.key == selected_sub_sector else '' }}>{{ sub_sector.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="refresh">Auto Refresh</label>
          <select id="refresh" name="refresh">
            {% for option in refresh_options %}
            <option value="{{ option.value }}" {{ 'selected' if option.value == refresh_seconds else '' }}>{{ option.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <button type="submit">Open Heatmap</button>
        </div>
      </form>
      <div class="quick-links">
        <a class="quick-link {{ 'active' if selected_date == today_date else '' }}"
           href="/equity-sector-heatmap?date={{ today_date }}&start={{ start_time }}&end={{ end_time }}&sector={{ selected_sector }}&subsector={{ selected_sub_sector }}&refresh={{ refresh_seconds }}">
          Today
        </a>
        <a class="quick-link {{ 'active' if selected_date == yesterday_date else '' }}"
           href="/equity-sector-heatmap?date={{ yesterday_date }}&start={{ start_time }}&end={{ end_time }}&sector={{ selected_sector }}&subsector={{ selected_sub_sector }}&refresh={{ refresh_seconds }}">
          Yesterday
        </a>
      </div>
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Market Pulse</h2>
      <div class="summary-grid">
        <div class="summary-box">
          <strong>Strongest Sector</strong>
          <div class="summary-value">{{ summary.strongest_sector }}</div>
          <div>{{ summary.strongest_sector_note }}</div>
        </div>
        <div class="summary-box">
          <strong>Weakest Sector</strong>
          <div class="summary-value">{{ summary.weakest_sector }}</div>
          <div>{{ summary.weakest_sector_note }}</div>
        </div>
        <div class="summary-box">
          <strong>Strongest Sub-Sector</strong>
          <div class="summary-value">{{ summary.strongest_sub_sector }}</div>
          <div>{{ summary.strongest_sub_sector_note }}</div>
        </div>
        <div class="summary-box">
          <strong>Rotation Breadth</strong>
          <div class="summary-value">{{ summary.rotation_bias }}</div>
          <div>{{ summary.rotation_note }}</div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Main Sector Heatmap</h2>
      <div class="heatmap-grid">
        {% for row in sector_rows %}
        <a class="heat-tile {{ row.heat_class }} {{ 'active' if row.sector_key == selected_sector else '' }}"
           href="/equity-sector-heatmap?date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}&sector={{ row.sector_key }}&subsector={{ row.default_sub_sector }}&refresh={{ refresh_seconds }}">
          <div class="tile-title">{{ row.sector_label }}</div>
          <div class="tile-score">{{ row.sector_score_display }}</div>
          <div class="tile-label">{{ row.rotation_label }}</div>
          <div class="tile-stats">
            <span>Avg Chg</span><strong>{{ row.avg_change_pct }}</strong>
            <span>Avg Gap</span><strong>{{ row.avg_gap_pct }}</strong>
            <span>Bullish</span><strong>{{ row.bullish_confirmations }}</strong>
            <span>Bearish</span><strong>{{ row.bearish_confirmations }}</strong>
          </div>
          <div class="tile-note">{{ row.ai_note }}</div>
        </a>
        {% endfor %}
      </div>
    </section>

    <section class="card">
      <h2>{{ selected_sector_label }} Sub-Sectors</h2>
      <div class="heatmap-grid">
        {% for row in sub_sector_rows %}
        <a class="heat-tile {{ row.heat_class }} {{ 'active' if row.sector_key == selected_sub_sector else '' }}"
           href="/equity-sector-heatmap?date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}&sector={{ selected_sector }}&subsector={{ row.sector_key }}&refresh={{ refresh_seconds }}">
          <div class="tile-title">{{ row.sector_label }}</div>
          <div class="tile-score">{{ row.sector_score_display }}</div>
          <div class="tile-label">{{ row.rotation_label }}</div>
          <div class="tile-stats">
            <span>Avg Chg</span><strong>{{ row.avg_change_pct }}</strong>
            <span>Above VWAP</span><strong>{{ row.above_vwap_count }}</strong>
            <span>High Vol</span><strong>{{ row.high_volume_count }}</strong>
            <span>Top Gainer</span><strong>{{ row.top_gainer }}</strong>
          </div>
          <div class="tile-note">{{ row.ai_note }}</div>
        </a>
        {% endfor %}
      </div>
    </section>

    <section class="card">
      <h2>How To Read It</h2>
      <div class="summary-grid">
        <div class="legend-item">
          <strong>Color Depth</strong>
          Deep green means strong bullish rotation. Deep red means strong bearish rotation. Yellow means mixed breadth.
        </div>
        <div class="legend-item">
          <strong>Broad vs Narrow</strong>
          Compare confirmations, VWAP breadth, and high-volume counts. A green tile with weak breadth is less trustworthy.
        </div>
        <div class="legend-item">
          <strong>Drilldown Flow</strong>
          Pick a sector, then a sub-sector, then use the detail table to jump into symbol-level ORB context.
        </div>
        <div class="legend-item">
          <strong>Rotation Use</strong>
          This page is best used to answer where capital is rotating, not just which stock is printing the biggest candle.
        </div>
      </div>
    </section>

    <section class="card split-grid">
      <div>
        <h2>Sector Ranking Table</h2>
        <div class="table-wrap">
          <table id="heatmap-sector-table">
            <thead>
              <tr>
                <th class="sortable" data-key="sector">Sector</th>
                <th class="sortable" data-key="sector_score">Score</th>
                <th class="sortable" data-key="avg_change_pct">Avg Change %</th>
                <th class="sortable" data-key="avg_gap_pct">Avg Gap %</th>
                <th class="sortable" data-key="bullish_confirmations">Bullish</th>
                <th class="sortable" data-key="bearish_confirmations">Bearish</th>
                <th class="sortable" data-key="above_vwap_count">Above VWAP</th>
                <th class="sortable" data-key="high_volume_count">High Vol</th>
                <th>Top Gainer</th>
              </tr>
            </thead>
            <tbody>
              {% for row in sector_rows %}
              <tr onclick="window.location='/equity-sector-heatmap?date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}&sector={{ row.sector_key }}&subsector={{ row.default_sub_sector }}&refresh={{ refresh_seconds }}'">
                <td data-sort="{{ row.sector_label }}">{{ row.sector_label }}</td>
                <td data-sort="{{ row.sector_score_numeric }}"><span class="badge {{ row.score_badge }}">{{ row.sector_score_display }}</span></td>
                <td data-sort="{{ row.avg_change_pct_numeric }}"><span class="badge {{ row.avg_change_badge }}">{{ row.avg_change_pct }}</span></td>
                <td data-sort="{{ row.avg_gap_pct_numeric }}"><span class="badge {{ row.avg_gap_badge }}">{{ row.avg_gap_pct }}</span></td>
                <td data-sort="{{ row.bullish_confirmations }}">{{ row.bullish_confirmations }}</td>
                <td data-sort="{{ row.bearish_confirmations }}">{{ row.bearish_confirmations }}</td>
                <td data-sort="{{ row.above_vwap_count }}">{{ row.above_vwap_count }}</td>
                <td data-sort="{{ row.high_volume_count }}">{{ row.high_volume_count }}</td>
                <td>{{ row.top_gainer }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </div>
      <div>
        <h2>{{ selected_sub_sector_label }} Note</h2>
        <div class="legend-item">
          <div class="badge {{ selected_sub_sector_row.score_badge }}">{{ selected_sub_sector_row.rotation_label }}</div>
          <p class="tile-note">{{ selected_sub_sector_row.ai_note }}</p>
          <div class="tile-stats">
            <span>Top Gainer</span><strong>{{ selected_sub_sector_row.top_gainer }}</strong>
            <span>Top Loser</span><strong>{{ selected_sub_sector_row.top_loser }}</strong>
            <span>Above VWAP</span><strong>{{ selected_sub_sector_row.above_vwap_count }}</strong>
            <span>Below VWAP</span><strong>{{ selected_sub_sector_row.below_vwap_count }}</strong>
            <span>High Volume</span><strong>{{ selected_sub_sector_row.high_volume_count }}</strong>
            <span>Breadth</span><strong>{{ selected_sub_sector_row.breadth_label }}</strong>
          </div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>{{ selected_sub_sector_label }} Stocks</h2>
      <div class="table-wrap">
        <table id="heatmap-detail-table">
          <thead>
            <tr>
              <th class="sortable" data-key="symbol">Symbol</th>
              <th class="sortable" data-key="orb_sort">ORB Status</th>
              <th class="sortable" data-key="last_price">Latest Price</th>
              <th class="sortable" data-key="day_change_pct">Day Change %</th>
              <th class="sortable" data-key="gap_pct">Gap %</th>
              <th class="sortable" data-key="vwap_sort">VWAP Status</th>
              <th class="sortable" data-key="volume_ratio">Volume Status</th>
              <th>AI Suggestion</th>
            </tr>
          </thead>
          <tbody>
            {% for row in selected_sub_sector_rows %}
            <tr onclick="window.location='/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}'">
              <td data-sort="{{ row.symbol }}">
                <a class="symbol-link" href="/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}" onclick="event.stopPropagation()">{{ row.symbol }}</a>
              </td>
              <td data-sort="{{ row.orb_sort }}"><span class="badge {{ row.orb_badge }}">{{ row.orb_status }}</span></td>
              <td data-sort="{{ row.last_price_numeric }}">{{ row.last_price }}</td>
              <td data-sort="{{ row.day_change_pct_numeric }}"><span class="badge {{ row.day_change_badge }}">{{ row.day_change_pct }}</span></td>
              <td data-sort="{{ row.gap_pct_numeric }}"><span class="badge {{ row.gap_badge }}">{{ row.gap_pct }}</span></td>
              <td data-sort="{{ row.vwap_sort }}"><span class="badge {{ row.vwap_badge }}">{{ row.vwap_status }}</span></td>
              <td data-sort="{{ row.volume_ratio_numeric }}"><span class="badge {{ row.volume_badge }}">{{ row.volume_status }}</span></td>
              <td class="note-text">{{ row.ai_suggestion }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </section>
  </div>
  {% if refresh_seconds > 0 %}
  <script>
    window.setTimeout(function () {
      window.location.reload();
    }, {{ refresh_seconds * 1000 }});
  </script>
  {% endif %}
  <script>
    (function () {
      ["heatmap-sector-table", "heatmap-detail-table"].forEach((tableId) => {
        const table = document.getElementById(tableId);
        if (!table) return;
        const tbody = table.querySelector("tbody");
        const headers = table.querySelectorAll("th.sortable");
        let currentKey = null;
        let ascending = false;

        function getCellValue(row, index) {
          const cell = row.children[index];
          return cell ? cell.dataset.sort || cell.textContent.trim() : "";
        }

        headers.forEach((header, index) => {
          header.addEventListener("click", () => {
            const key = header.dataset.key;
            ascending = currentKey === key ? !ascending : false;
            currentKey = key;
            const rows = Array.from(tbody.querySelectorAll("tr"));
            rows.sort((a, b) => {
              const aValue = getCellValue(a, index);
              const bValue = getCellValue(b, index);
              const aNumber = Number(aValue);
              const bNumber = Number(bValue);
              let result = 0;

              if (!Number.isNaN(aNumber) && !Number.isNaN(bNumber)) {
                result = aNumber - bNumber;
              } else {
                result = aValue.localeCompare(bValue);
              }

              return ascending ? result : -result;
            });
            rows.forEach((row) => tbody.appendChild(row));
          });
        });
      });
    })();
  </script>
</body>
</html>
"""

ROTATION_HOME_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Rotation Home</title>
  <style>
    :root {
      --bg: #f3ecdf;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --up: #116149;
      --up-soft: #d7efe7;
      --down: #8a2e2e;
      --down-soft: #f7dddd;
      --neutral: #7a5a18;
      --neutral-soft: #f5ebcc;
      --info: #1f3f73;
      --info-soft: #dde8f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(31,111,95,0.12), transparent 25%),
        linear-gradient(180deg, #fbf7ef 0%, #ece3d6 100%);
    }
    .page { max-width: 1460px; margin: 0 auto; padding: 28px 18px 56px; }
    .hero {
      background: linear-gradient(135deg, rgba(20,44,62,0.98), rgba(31,111,95,0.92));
      color: #f8f5ef;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 22px 60px rgba(24,32,39,0.14);
    }
    .hero-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(300px, 0.95fr);
      gap: 22px;
      align-items: stretch;
    }
    .hero-copy {
      display: flex;
      flex-direction: column;
      justify-content: center;
    }
    h1 { margin: 0; font-size: 40px; line-height: 1; }
    .sub {
      margin: 12px 0 0;
      max-width: 980px;
      font-size: 17px;
      line-height: 1.5;
      color: rgba(248,245,239,0.88);
    }
    .meta, .quick-links, .nav-grid, .setup-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      font-size: 14px;
    }
    .hero-stage {
      position: relative;
      overflow: hidden;
      border-radius: 22px;
      border: 1px solid rgba(255,255,255,0.18);
      background:
        radial-gradient(circle at top right, rgba(255,255,255,0.18), transparent 32%),
        linear-gradient(180deg, rgba(10,21,33,0.58), rgba(10,21,33,0.12));
      min-height: 280px;
      padding: 20px;
    }
    .hero-stage::after {
      content: "";
      position: absolute;
      left: 18px;
      right: 18px;
      bottom: 18px;
      height: 72px;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(232,214,174,0.18), rgba(232,214,174,0.3));
      border: 1px solid rgba(255,255,255,0.08);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.08);
    }
    .stage-label {
      position: relative;
      z-index: 2;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.12);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: rgba(248,245,239,0.9);
    }
    .desk-crew {
      position: relative;
      z-index: 2;
      display: flex;
      justify-content: center;
      align-items: flex-end;
      gap: 14px;
      margin-top: 16px;
      min-height: 188px;
    }
    .crew-card {
      width: 31%;
      min-width: 84px;
      text-align: center;
      color: #f8f5ef;
    }
    .avatar {
      position: relative;
      width: 88px;
      height: 112px;
      margin: 0 auto 10px;
    }
    .avatar-head {
      position: absolute;
      left: 50%;
      top: 0;
      width: 56px;
      height: 56px;
      transform: translateX(-50%);
      border-radius: 50%;
      background: #f2d0b4;
      border: 2px solid rgba(24,32,39,0.18);
      box-shadow: inset 0 -6px 0 rgba(0,0,0,0.05);
    }
    .avatar-head::before,
    .avatar-head::after {
      content: "";
      position: absolute;
      top: 22px;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #182027;
    }
    .avatar-head::before { left: 15px; }
    .avatar-head::after { right: 15px; }
    .avatar-face {
      position: absolute;
      left: 50%;
      top: 29px;
      width: 20px;
      height: 10px;
      transform: translateX(-50%);
      border-bottom: 2px solid #182027;
      border-radius: 0 0 16px 16px;
    }
    .avatar-body {
      position: absolute;
      left: 50%;
      top: 46px;
      width: 64px;
      height: 62px;
      transform: translateX(-50%);
      border-radius: 18px 18px 14px 14px;
      border: 2px solid rgba(255,255,255,0.24);
      background: linear-gradient(180deg, rgba(255,255,255,0.18), rgba(255,255,255,0.08));
    }
    .avatar-body::before {
      content: "";
      position: absolute;
      left: 50%;
      top: 10px;
      width: 16px;
      height: 36px;
      transform: translateX(-50%);
      clip-path: polygon(50% 0, 100% 38%, 68% 100%, 32% 100%, 0 38%);
      background: rgba(20,44,62,0.78);
    }
    .avatar-screen {
      position: absolute;
      left: 50%;
      bottom: -2px;
      width: 80px;
      height: 26px;
      transform: translateX(-50%);
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,0.2);
      background: rgba(11,23,35,0.68);
      box-shadow: 0 8px 16px rgba(7,13,20,0.2);
      overflow: hidden;
    }
    .avatar-screen::before {
      content: "";
      position: absolute;
      inset: 4px 6px;
      border-radius: 6px;
      background: linear-gradient(90deg, rgba(17,97,73,0.75), rgba(255,255,255,0.12), rgba(138,46,46,0.75));
    }
    .crew-card.bull .avatar-body { background: linear-gradient(180deg, rgba(17,97,73,0.44), rgba(17,97,73,0.18)); }
    .crew-card.bear .avatar-body { background: linear-gradient(180deg, rgba(138,46,46,0.4), rgba(138,46,46,0.14)); }
    .crew-card.scout .avatar-body { background: linear-gradient(180deg, rgba(31,63,115,0.42), rgba(31,63,115,0.14)); }
    .crew-name {
      font-size: 14px;
      font-weight: 700;
      letter-spacing: 0.03em;
    }
    .crew-role {
      margin-top: 4px;
      font-size: 12px;
      color: rgba(248,245,239,0.78);
      line-height: 1.35;
    }
    .card {
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: 0 18px 44px rgba(24,32,39,0.07);
    }
    .card h2 { margin: 0 0 12px; font-size: 24px; }
    .toolbar-grid, .summary-grid, .heatmap-grid, .setup-grid, .nav-grid {
      display: grid;
      gap: 14px;
    }
    .toolbar-grid { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
    .summary-grid, .setup-grid, .nav-grid { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
    .heatmap-grid { grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); }
    .split-grid { display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 18px; }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input, select {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    button, .quick-link, .nav-link, .heat-tile {
      border-radius: 14px;
      font: inherit;
      text-decoration: none;
    }
    button {
      width: 100%;
      border: 0;
      padding: 12px 16px;
      cursor: pointer;
      font-weight: 700;
      color: #fff;
      background: var(--accent);
    }
    .quick-link, .nav-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
      padding: 12px 16px;
      font-weight: 700;
    }
    .quick-link.active { background: #dbece7; color: var(--accent); border-color: rgba(31,111,95,0.24); }
    .summary-box, .setup-box, .nav-link {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.78);
    }
    .summary-value { font-size: 28px; font-weight: 700; margin-top: 8px; }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up { background: var(--up-soft); color: var(--up); }
    .badge-down { background: var(--down-soft); color: var(--down); }
    .badge-neutral { background: var(--neutral-soft); color: var(--neutral); }
    .badge-info { background: var(--info-soft); color: var(--info); }
    .heat-tile {
      display: block;
      padding: 16px;
      border: 1px solid var(--line);
      color: inherit;
      background: #fff;
    }
    .heat-up-strong { background: linear-gradient(180deg, rgba(15,90,67,0.95), rgba(38,127,97,0.92)); color: #f8f5ef; }
    .heat-up-soft { background: linear-gradient(180deg, #d9f0e8, #ecf8f3); }
    .heat-neutral { background: linear-gradient(180deg, #faf5e4, #f5ebcc); }
    .heat-down-soft { background: linear-gradient(180deg, #fbeeee, #f7dddd); }
    .heat-down-strong { background: linear-gradient(180deg, rgba(132,43,43,0.93), rgba(167,66,66,0.88)); color: #f8f5ef; }
    .tile-title { font-size: 20px; font-weight: 700; margin-bottom: 6px; }
    .tile-score { font-size: 28px; font-weight: 700; line-height: 1; }
    .tile-note { margin-top: 10px; font-size: 14px; line-height: 1.45; }
    .tile-stats { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 14px; margin-top: 12px; font-size: 14px; }
    .table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 18px; }
    table { width: 100%; border-collapse: collapse; min-width: 1100px; }
    th, td {
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }
    tbody tr { cursor: pointer; }
    tbody tr:hover { background: rgba(31,111,95,0.06); }
    th {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      background: #faf7f1;
      cursor: pointer;
      user-select: none;
    }
    .symbol-link { color: var(--accent); font-weight: 700; text-decoration: none; }
    .symbol-link:hover { text-decoration: underline; }
    .error {
      margin-top: 14px;
      border-radius: 16px;
      padding: 14px 16px;
      background: #f7e3d9;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.18);
    }
    .muted { color: var(--muted); }
    .note-text { line-height: 1.45; }
    @media (max-width: 980px) { .split-grid { grid-template-columns: 1fr; } }
    @media (max-width: 720px) {
      h1 { font-size: 32px; }
      .page { padding: 18px 12px 40px; }
      .hero, .card { border-radius: 18px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Rotation Summary Home</h1>
      <p class="sub">
        A command-center landing page that summarizes sector rotation, breadth, confirmed setups, previous-day level breaks,
        and the best places to drill deeper across the rest of TraderHub.
      </p>
      <div class="meta">
        <div class="pill">Date: {{ selected_date }}</div>
        <div class="pill">Range: {{ start_time }} to {{ end_time }}</div>
        <div class="pill">Rotation Bias: {{ home_summary.rotation_bias }}</div>
        <div class="pill">Confidence: {{ home_summary.confidence_label }}</div>
        <div class="pill">Watchlist: {{ active_watchlist_label }}</div>
        <div class="pill">Auto Refresh: {{ refresh_label }}</div>
      </div>
    </section>

    <section class="card">
      <h2>Controls</h2>
      <form method="get" class="toolbar-grid">
        <div>
          <label for="watchlist">Watchlist</label>
          <select id="watchlist" name="watchlist">
            {% for watch in watchlists %}
            <option value="{{ watch.key }}" {{ 'selected' if watch.key == active_watchlist else '' }}>{{ watch.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="symbols">Custom Symbols</label>
          <input id="symbols" name="symbols" value="{{ request_symbols }}" placeholder="IOC,PNB,SBIN">
        </div>
        <div>
          <label for="date">Date</label>
          <input id="date" name="date" value="{{ selected_date }}" placeholder="YYYY-MM-DD">
        </div>
        <div>
          <label for="start">Start</label>
          <input id="start" name="start" value="{{ start_time }}" placeholder="09:15">
        </div>
        <div>
          <label for="end">End</label>
          <input id="end" name="end" value="{{ end_time }}" placeholder="09:30">
        </div>
        <div>
          <label for="refresh">Auto Refresh</label>
          <select id="refresh" name="refresh">
            {% for option in refresh_options %}
            <option value="{{ option.value }}" {{ 'selected' if option.value == refresh_seconds else '' }}>{{ option.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <button type="submit">Open Home</button>
        </div>
      </form>
      <div class="quick-links">
        <a class="quick-link {{ 'active' if selected_date == today_date else '' }}"
           href="/equity-rotation-home?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ today_date }}&start={{ start_time }}&end={{ end_time }}&refresh={{ refresh_seconds }}">
          Today
        </a>
        <a class="quick-link {{ 'active' if selected_date == yesterday_date else '' }}"
           href="/equity-rotation-home?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ yesterday_date }}&start={{ start_time }}&end={{ end_time }}&refresh={{ refresh_seconds }}">
          Yesterday
        </a>
      </div>
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Market Briefing</h2>
      <div class="summary-grid">
        <div class="summary-box">
          <strong>Strongest Sector</strong>
          <div class="summary-value">{{ heatmap_summary.strongest_sector }}</div>
          <div>{{ heatmap_summary.strongest_sector_note }}</div>
        </div>
        <div class="summary-box">
          <strong>Weakest Sector</strong>
          <div class="summary-value">{{ heatmap_summary.weakest_sector }}</div>
          <div>{{ heatmap_summary.weakest_sector_note }}</div>
        </div>
        <div class="summary-box">
          <strong>Strongest Sub-Sector</strong>
          <div class="summary-value">{{ heatmap_summary.strongest_sub_sector }}</div>
          <div>{{ heatmap_summary.strongest_sub_sector_note }}</div>
        </div>
        <div class="summary-box">
          <strong>Rotation Note</strong>
          <div class="summary-value">{{ home_summary.rotation_bias }}</div>
          <div>{{ home_summary.market_note }}</div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Summary Cards</h2>
      <div class="summary-grid">
        <div class="summary-box"><strong>Bullish Sectors</strong><div class="summary-value">{{ home_summary.bullish_sector_count }}</div><div>Sectors with positive rotation scores</div></div>
        <div class="summary-box"><strong>Bearish Sectors</strong><div class="summary-value">{{ home_summary.bearish_sector_count }}</div><div>Sectors with negative rotation scores</div></div>
        <div class="summary-box"><strong>Confirmed Longs</strong><div class="summary-value">{{ home_summary.confirmed_long_count }}</div><div>From the selected watchlist</div></div>
        <div class="summary-box"><strong>Confirmed Shorts</strong><div class="summary-value">{{ home_summary.confirmed_short_count }}</div><div>From the selected watchlist</div></div>
        <div class="summary-box"><strong>Above PDH</strong><div class="summary-value">{{ home_summary.above_pdh_count }}</div><div>Names above previous-day high</div></div>
        <div class="summary-box"><strong>Below PDL</strong><div class="summary-value">{{ home_summary.below_pdl_count }}</div><div>Names below previous-day low</div></div>
        <div class="summary-box"><strong>High-Volume Leaders</strong><div class="summary-value">{{ home_summary.high_volume_leaders }}</div><div>Across the selected watchlist</div></div>
        <div class="summary-box"><strong>VWAP Breadth Leaders</strong><div class="summary-value">{{ home_summary.broad_above_vwap }}</div><div>Top sectors by above-VWAP breadth</div></div>
      </div>
    </section>

    <section class="card split-grid">
      <div>
        <h2>Top Rotation Table</h2>
        <div class="table-wrap">
          <table id="rotation-home-table">
            <thead>
              <tr>
                <th>Sector</th>
                <th>Score</th>
                <th>Avg Change %</th>
                <th>Avg Gap %</th>
                <th>Bullish</th>
                <th>Bearish</th>
                <th>Above VWAP</th>
                <th>Below VWAP</th>
                <th>High Vol</th>
                <th>Top Gainer</th>
                <th>Top Loser</th>
              </tr>
            </thead>
            <tbody>
              {% for row in sector_rows[:8] %}
              <tr onclick="window.location='/equity-sector-strength?date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}&sector={{ row.sector_key }}&refresh={{ refresh_seconds }}'">
                <td>{{ row.sector_label }}</td>
                <td><span class="badge {{ row.score_badge }}">{{ row.sector_score_display }}</span></td>
                <td><span class="badge {{ row.avg_change_badge }}">{{ row.avg_change_pct }}</span></td>
                <td><span class="badge {{ row.avg_gap_badge }}">{{ row.avg_gap_pct }}</span></td>
                <td>{{ row.bullish_confirmations }}</td>
                <td>{{ row.bearish_confirmations }}</td>
                <td>{{ row.above_vwap_count }}</td>
                <td>{{ row.below_vwap_count }}</td>
                <td>{{ row.high_volume_count }}</td>
                <td>{{ row.top_gainer }}</td>
                <td>{{ row.top_loser }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </div>
      <div>
        <h2>Trade Focus</h2>
        <div class="setup-box">
          <div class="badge {{ home_summary.focus_badge }}">{{ home_summary.focus_label }}</div>
          <p class="note-text">{{ home_summary.focus_note }}</p>
          <div class="setup-links">
            <a class="nav-link" href="/equity-confirmation?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}&refresh={{ refresh_seconds }}">Open Confirmation</a>
            <a class="nav-link" href="/equity-sector-heatmap?date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}&sector=financials&refresh={{ refresh_seconds }}">Open Heatmap</a>
            <a class="nav-link" href="/equity-previous-levels?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ selected_date }}&refresh={{ refresh_seconds }}">Open Previous Levels</a>
          </div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Heatmap Snapshot</h2>
      <div class="heatmap-grid">
        {% for row in heatmap_sector_rows[:8] %}
        <a class="heat-tile {{ row.heat_class }}"
           href="/equity-sector-heatmap?date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}&sector={{ row.sector_key }}&subsector={{ row.default_sub_sector }}&refresh={{ refresh_seconds }}">
          <div class="tile-title">{{ row.sector_label }}</div>
          <div class="tile-score">{{ row.sector_score_display }}</div>
          <div class="badge {{ row.score_badge }}">{{ row.rotation_label }}</div>
          <div class="tile-note">{{ row.ai_note }}</div>
        </a>
        {% endfor %}
      </div>
    </section>

    <section class="card">
      <h2>Best Setups</h2>
      <div class="setup-grid">
        <div class="setup-box">
          <strong>Top Confirmed Longs</strong>
          {% for row in top_longs %}
          <p><a class="symbol-link" href="/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}">{{ row.symbol }}</a> {{ row.last_price }} | {{ row.orb_status }} | {{ row.volume_status }}</p>
          {% else %}
          <p class="muted">No confirmed long setups right now.</p>
          {% endfor %}
        </div>
        <div class="setup-box">
          <strong>Top Confirmed Shorts</strong>
          {% for row in top_shorts %}
          <p><a class="symbol-link" href="/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}">{{ row.symbol }}</a> {{ row.last_price }} | {{ row.orb_status }} | {{ row.volume_status }}</p>
          {% else %}
          <p class="muted">No confirmed short setups right now.</p>
          {% endfor %}
        </div>
        <div class="setup-box">
          <strong>Near PDH Breakouts</strong>
          {% for row in near_pdh_rows %}
          <p><a class="symbol-link" href="/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}">{{ row.symbol }}</a> {{ row.last_price }} | {{ row.distance_pdh }}</p>
          {% else %}
          <p class="muted">No close PDH tests in the selected list.</p>
          {% endfor %}
        </div>
        <div class="setup-box">
          <strong>Near PDL Breakdowns</strong>
          {% for row in near_pdl_rows %}
          <p><a class="symbol-link" href="/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}">{{ row.symbol }}</a> {{ row.last_price }} | {{ row.distance_pdl }}</p>
          {% else %}
          <p class="muted">No close PDL tests in the selected list.</p>
          {% endfor %}
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Quick Navigation</h2>
      <div class="nav-grid">
        <a class="nav-link" href="/equity-scanner?symbols={{ request_symbols|urlencode }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}">Open Scanner</a>
        <a class="nav-link" href="/equity-watchlists?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}&refresh={{ refresh_seconds }}">Open Watchlists</a>
        <a class="nav-link" href="/equity-movers?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ selected_date }}&refresh={{ refresh_seconds }}">Open Movers</a>
        <a class="nav-link" href="/equity-confirmation?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}&refresh={{ refresh_seconds }}">Open Confirmation</a>
        <a class="nav-link" href="/equity-sector-strength?date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}&refresh={{ refresh_seconds }}">Open Sector Strength</a>
        <a class="nav-link" href="/equity-sector-heatmap?date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}&sector=financials&refresh={{ refresh_seconds }}">Open Sector Heatmap</a>
        <a class="nav-link" href="/equity-previous-levels?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ selected_date }}&refresh={{ refresh_seconds }}">Open Previous Levels</a>
        <a class="nav-link" href="/equity-ohlc?symbols={{ request_symbols|urlencode }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}">Open OHLC</a>
      </div>
    </section>
  </div>
  {% if refresh_seconds > 0 %}
  <script>
    window.setTimeout(function () {
      window.location.reload();
    }, {{ refresh_seconds * 1000 }});
  </script>
  {% endif %}
</body>
</html>
"""

MARKET_BREADTH_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Market Breadth</title>
  <style>
    :root {
      --bg: #f3ecdf;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --up: #116149;
      --up-soft: #d7efe7;
      --down: #8a2e2e;
      --down-soft: #f7dddd;
      --neutral: #7a5a18;
      --neutral-soft: #f5ebcc;
      --info: #1f3f73;
      --info-soft: #dde8f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(31,111,95,0.12), transparent 25%),
        linear-gradient(180deg, #fbf7ef 0%, #ece3d6 100%);
    }
    .page { max-width: 1460px; margin: 0 auto; padding: 28px 18px 56px; }
    .hero {
      background: linear-gradient(135deg, rgba(20,44,62,0.98), rgba(31,111,95,0.92));
      color: #f8f5ef;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 22px 60px rgba(24,32,39,0.14);
    }
    h1 { margin: 0; font-size: 40px; line-height: 1; }
    .sub {
      margin: 12px 0 0;
      max-width: 980px;
      font-size: 17px;
      line-height: 1.5;
      color: rgba(248,245,239,0.88);
    }
    .meta, .quick-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      font-size: 14px;
    }
    .card {
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: 0 18px 44px rgba(24,32,39,0.07);
    }
    .card h2 { margin: 0 0 12px; font-size: 24px; }
    .toolbar-grid, .summary-grid, .signal-grid {
      display: grid;
      gap: 14px;
    }
    .toolbar-grid { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
    .summary-grid, .signal-grid { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
    .split-grid { display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 18px; }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input, select {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    button, .quick-link {
      border-radius: 14px;
      font: inherit;
      text-decoration: none;
    }
    button {
      width: 100%;
      border: 0;
      padding: 12px 16px;
      cursor: pointer;
      font-weight: 700;
      color: #fff;
      background: var(--accent);
    }
    .quick-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
      padding: 12px 16px;
      font-weight: 700;
    }
    .quick-link.active { background: #dbece7; color: var(--accent); border-color: rgba(31,111,95,0.24); }
    .summary-box, .signal-box {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.78);
    }
    .summary-value { font-size: 28px; font-weight: 700; margin-top: 8px; }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up { background: var(--up-soft); color: var(--up); }
    .badge-down { background: var(--down-soft); color: var(--down); }
    .badge-neutral { background: var(--neutral-soft); color: var(--neutral); }
    .badge-info { background: var(--info-soft); color: var(--info); }
    .table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 18px; }
    table { width: 100%; border-collapse: collapse; min-width: 1080px; }
    th, td {
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }
    tbody tr { cursor: pointer; }
    tbody tr:hover { background: rgba(31,111,95,0.06); }
    th {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      background: #faf7f1;
      cursor: pointer;
      user-select: none;
    }
    .symbol-link { color: var(--accent); font-weight: 700; text-decoration: none; }
    .symbol-link:hover { text-decoration: underline; }
    .error {
      margin-top: 14px;
      border-radius: 16px;
      padding: 14px 16px;
      background: #f7e3d9;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.18);
    }
    .muted { color: var(--muted); }
    .note-text { line-height: 1.45; }
    @media (max-width: 980px) { .split-grid { grid-template-columns: 1fr; } }
    @media (max-width: 720px) {
      h1 { font-size: 32px; }
      .page { padding: 18px 12px 40px; }
      .hero, .card { border-radius: 18px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Market Breadth Dashboard</h1>
      <p class="sub">
        A breadth-first view of the market that combines sector participation, ORB/VWAP alignment, gap behavior,
        and previous-day level pressure so you can judge whether momentum is broad, narrow, or fading.
      </p>
      <div class="meta">
        <div class="pill">Watchlist: {{ active_watchlist_label }}</div>
        <div class="pill">Date: {{ selected_date }}</div>
        <div class="pill">Range: {{ start_time }} to {{ end_time }}</div>
        <div class="pill">Breadth Bias: {{ summary.breadth_bias }}</div>
        <div class="pill">Auto Refresh: {{ refresh_label }}</div>
      </div>
    </section>

    <section class="card">
      <h2>Controls</h2>
      <form method="get" class="toolbar-grid">
        <div>
          <label for="watchlist">Watchlist</label>
          <select id="watchlist" name="watchlist">
            {% for watch in watchlists %}
            <option value="{{ watch.key }}" {{ 'selected' if watch.key == active_watchlist else '' }}>{{ watch.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="symbols">Custom Symbols</label>
          <input id="symbols" name="symbols" value="{{ request_symbols }}" placeholder="IOC,PNB,SBIN">
        </div>
        <div>
          <label for="date">Date</label>
          <input id="date" name="date" value="{{ selected_date }}" placeholder="YYYY-MM-DD">
        </div>
        <div>
          <label for="start">Start</label>
          <input id="start" name="start" value="{{ start_time }}" placeholder="09:15">
        </div>
        <div>
          <label for="end">End</label>
          <input id="end" name="end" value="{{ end_time }}" placeholder="09:30">
        </div>
        <div>
          <label for="refresh">Auto Refresh</label>
          <select id="refresh" name="refresh">
            {% for option in refresh_options %}
            <option value="{{ option.value }}" {{ 'selected' if option.value == refresh_seconds else '' }}>{{ option.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <button type="submit">Open Breadth Page</button>
        </div>
      </form>
      <div class="quick-links">
        <a class="quick-link {{ 'active' if selected_date == today_date else '' }}"
           href="/equity-market-breadth?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ today_date }}&start={{ start_time }}&end={{ end_time }}&refresh={{ refresh_seconds }}">
          Today
        </a>
        <a class="quick-link {{ 'active' if selected_date == yesterday_date else '' }}"
           href="/equity-market-breadth?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ yesterday_date }}&start={{ start_time }}&end={{ end_time }}&refresh={{ refresh_seconds }}">
          Yesterday
        </a>
      </div>
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Breadth Snapshot</h2>
      <div class="summary-grid">
        <div class="summary-box"><strong>Above VWAP</strong><div class="summary-value">{{ summary.above_vwap_count }}</div><div>Names holding above intraday VWAP</div></div>
        <div class="summary-box"><strong>Below VWAP</strong><div class="summary-value">{{ summary.below_vwap_count }}</div><div>Names trading below intraday VWAP</div></div>
        <div class="summary-box"><strong>Above OR High</strong><div class="summary-value">{{ summary.above_or_count }}</div><div>Opening-range bullish breaks</div></div>
        <div class="summary-box"><strong>Below OR Low</strong><div class="summary-value">{{ summary.below_or_count }}</div><div>Opening-range bearish breaks</div></div>
        <div class="summary-box"><strong>Above PDH</strong><div class="summary-value">{{ summary.above_pdh_count }}</div><div>Names clearing previous-day highs</div></div>
        <div class="summary-box"><strong>Below PDL</strong><div class="summary-value">{{ summary.below_pdl_count }}</div><div>Names breaking previous-day lows</div></div>
        <div class="summary-box"><strong>Gap Up</strong><div class="summary-value">{{ summary.gap_up_count }}</div><div>Positive opening gap breadth</div></div>
        <div class="summary-box"><strong>Gap Down</strong><div class="summary-value">{{ summary.gap_down_count }}</div><div>Negative opening gap breadth</div></div>
      </div>
    </section>

    <section class="card split-grid">
      <div>
        <h2>Sector Breadth Leaders</h2>
        <div class="table-wrap">
          <table id="breadth-sector-table">
            <thead>
              <tr>
                <th>Sector</th>
                <th>Score</th>
                <th>Rotation</th>
                <th>Above VWAP</th>
                <th>Below VWAP</th>
                <th>High Vol</th>
                <th>Bullish</th>
                <th>Bearish</th>
              </tr>
            </thead>
            <tbody>
              {% for row in sector_rows[:10] %}
              <tr onclick="window.location='/equity-sector-heatmap?date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}&sector={{ row.sector_key }}&subsector={{ row.default_sub_sector }}&refresh={{ refresh_seconds }}'">
                <td>{{ row.sector_label }}</td>
                <td><span class="badge {{ row.score_badge }}">{{ row.sector_score_display }}</span></td>
                <td>{{ row.rotation_label }}</td>
                <td>{{ row.above_vwap_count }}</td>
                <td>{{ row.below_vwap_count }}</td>
                <td>{{ row.high_volume_count }}</td>
                <td>{{ row.bullish_confirmations }}</td>
                <td>{{ row.bearish_confirmations }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </div>
      <div>
        <h2>Signal Notes</h2>
        <div class="signal-grid">
          <div class="signal-box">
            <div class="badge {{ summary.bias_badge }}">{{ summary.breadth_bias }}</div>
            <p class="note-text">{{ summary.bias_note }}</p>
          </div>
          <div class="signal-box">
            <strong>Best Breadth Sector</strong>
            <p>{{ summary.best_sector }}</p>
            <p class="muted">{{ summary.best_sector_note }}</p>
          </div>
          <div class="signal-box">
            <strong>Weakest Breadth Sector</strong>
            <p>{{ summary.weakest_sector }}</p>
            <p class="muted">{{ summary.weakest_sector_note }}</p>
          </div>
          <div class="signal-box">
            <strong>Watchlist Focus</strong>
            <p class="note-text">{{ summary.watchlist_focus_note }}</p>
          </div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Watchlist Breadth Table</h2>
      <div class="table-wrap">
        <table id="breadth-stock-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>ORB</th>
              <th>VWAP</th>
              <th>Volume</th>
              <th>Day Change %</th>
              <th>Gap %</th>
              <th>Prev-Day Status</th>
              <th>Dist to PDH</th>
              <th>Dist to PDL</th>
            </tr>
          </thead>
          <tbody>
            {% for row in breadth_rows %}
            <tr onclick="window.location='/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}'">
              <td><a class="symbol-link" href="/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}" onclick="event.stopPropagation()">{{ row.symbol }}</a></td>
              <td><span class="badge {{ row.orb_badge }}">{{ row.orb_status }}</span></td>
              <td><span class="badge {{ row.vwap_badge }}">{{ row.vwap_status }}</span></td>
              <td><span class="badge {{ row.volume_badge }}">{{ row.volume_status }}</span></td>
              <td><span class="badge {{ row.day_change_badge }}">{{ row.day_change_pct }}</span></td>
              <td><span class="badge {{ row.gap_badge }}">{{ row.gap_pct }}</span></td>
              <td><span class="badge {{ row.status_badge }}">{{ row.status_label }}</span></td>
              <td><span class="badge {{ row.distance_pdh_badge }}">{{ row.distance_pdh }}</span></td>
              <td><span class="badge {{ row.distance_pdl_badge }}">{{ row.distance_pdl }}</span></td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </section>
  </div>
  {% if refresh_seconds > 0 %}
  <script>
    window.setTimeout(function () {
      window.location.reload();
    }, {{ refresh_seconds * 1000 }});
  </script>
  {% endif %}
</body>
</html>
"""

BACKTEST_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Strategy Backtest</title>
  <style>
    :root {
      --bg: #f3ecdf;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --up: #116149;
      --up-soft: #d7efe7;
      --down: #8a2e2e;
      --down-soft: #f7dddd;
      --neutral: #7a5a18;
      --neutral-soft: #f5ebcc;
      --info: #1f3f73;
      --info-soft: #dde8f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(31,111,95,0.12), transparent 25%),
        linear-gradient(180deg, #fbf7ef 0%, #ece3d6 100%);
    }
    .page { max-width: 1480px; margin: 0 auto; padding: 28px 18px 56px; }
    .hero {
      background: linear-gradient(135deg, rgba(20,44,62,0.98), rgba(31,111,95,0.92));
      color: #f8f5ef;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 22px 60px rgba(24,32,39,0.14);
    }
    h1 { margin: 0; font-size: 40px; line-height: 1; }
    .sub {
      margin: 12px 0 0;
      max-width: 980px;
      font-size: 17px;
      line-height: 1.5;
      color: rgba(248,245,239,0.88);
    }
    .meta, .preset-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      font-size: 14px;
    }
    .card {
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: 0 18px 44px rgba(24,32,39,0.07);
    }
    .card h2 { margin: 0 0 12px; font-size: 24px; }
    .toolbar-grid, .summary-grid, .legend, .mobile-card-grid {
      display: grid;
      gap: 14px;
    }
    .toolbar-grid { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
    .summary-grid { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
    .mobile-card-grid { grid-template-columns: 1fr; }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input, select {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    button, .preset-link {
      border-radius: 14px;
      font: inherit;
      text-decoration: none;
    }
    button {
      width: 100%;
      border: 0;
      padding: 12px 16px;
      cursor: pointer;
      font-weight: 700;
      color: #fff;
      background: var(--accent);
    }
    .preset-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
      padding: 12px 16px;
      font-weight: 700;
    }
    .summary-box, .legend-item {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.78);
    }
    .summary-box strong {
      display: block;
      font-size: 13px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }
    .summary-value { font-size: 28px; font-weight: 700; margin-top: 8px; }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up { background: var(--up-soft); color: var(--up); }
    .badge-down { background: var(--down-soft); color: var(--down); }
    .badge-neutral { background: var(--neutral-soft); color: var(--neutral); }
    .badge-info { background: var(--info-soft); color: var(--info); }
    .table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 18px; }
    table { width: 100%; border-collapse: collapse; min-width: 1320px; }
    th, td {
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }
    tbody tr:hover { background: rgba(31,111,95,0.05); }
    th {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      background: #faf7f1;
    }
    .error {
      margin-top: 14px;
      border-radius: 16px;
      padding: 14px 16px;
      background: #f7e3d9;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.18);
    }
    .muted { color: var(--muted); }
    @media (max-width: 720px) {
      h1 { font-size: 32px; }
      .page { padding: 18px 12px 40px; }
      .hero, .card { border-radius: 18px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Strategy Backtest</h1>
      <p class="sub">
        A separate ORB backtest page for replaying breakout trades across a date range with configurable direction,
        stop multiple, target multiple, and simple rule-based exits.
      </p>
      <div class="meta">
        <div class="pill">Watchlist: {{ active_watchlist_label }}</div>
        <div class="pill">From: {{ from_date }}</div>
        <div class="pill">To: {{ to_date }}</div>
        <div class="pill">Direction: {{ direction_label }}</div>
        <div class="pill">Stop: {{ stop_multiple }}R</div>
        <div class="pill">Target: {{ target_multiple }}R</div>
      </div>
    </section>

    <section class="card">
      <h2>Backtest Controls</h2>
      <form method="get" class="toolbar-grid">
        <div>
          <label for="watchlist">Watchlist</label>
          <select id="watchlist" name="watchlist">
            {% for watch in watchlists %}
            <option value="{{ watch.key }}" {{ 'selected' if watch.key == active_watchlist else '' }}>{{ watch.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="symbols">Custom Symbols</label>
          <input id="symbols" name="symbols" value="{{ request_symbols }}" placeholder="IOC,PNB,SBIN">
        </div>
        <div>
          <label for="from_date">From Date</label>
          <input id="from_date" name="from_date" value="{{ from_date }}" placeholder="YYYY-MM-DD">
        </div>
        <div>
          <label for="to_date">To Date</label>
          <input id="to_date" name="to_date" value="{{ to_date }}" placeholder="YYYY-MM-DD">
        </div>
        <div>
          <label for="start">ORB Start</label>
          <input id="start" name="start" value="{{ start_time }}" placeholder="09:15">
        </div>
        <div>
          <label for="end">ORB End</label>
          <input id="end" name="end" value="{{ end_time }}" placeholder="09:30">
        </div>
        <div>
          <label for="direction">Direction</label>
          <select id="direction" name="direction">
            {% for option in direction_options %}
            <option value="{{ option.value }}" {{ 'selected' if option.value == direction else '' }}>{{ option.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="stop_multiple">Stop Multiple</label>
          <input id="stop_multiple" name="stop_multiple" value="{{ stop_multiple }}" placeholder="1.0">
        </div>
        <div>
          <label for="target_multiple">Target Multiple</label>
          <input id="target_multiple" name="target_multiple" value="{{ target_multiple }}" placeholder="1.5">
        </div>
        <div>
          <button type="submit">Run Backtest</button>
        </div>
      </form>
      <div class="preset-links">
        {% for preset in presets %}
        <a class="preset-link" href="{{ preset.href }}">{{ preset.label }}</a>
        {% endfor %}
      </div>
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Summary</h2>
      <div class="summary-grid">
        <div class="summary-box"><strong>Total Trades</strong><div class="summary-value">{{ summary.total_trades }}</div><div>Triggered breakout entries</div></div>
        <div class="summary-box"><strong>Wins</strong><div class="summary-value">{{ summary.win_count }}</div><div>Target hits or profitable EOD exits</div></div>
        <div class="summary-box"><strong>Losses</strong><div class="summary-value">{{ summary.loss_count }}</div><div>Stop hits or losing EOD exits</div></div>
        <div class="summary-box"><strong>Win Rate</strong><div class="summary-value">{{ summary.win_rate }}</div><div>Percentage of winning trades</div></div>
        <div class="summary-box"><strong>Total P&L</strong><div class="summary-value">{{ summary.total_pnl_points }}</div><div>Raw points across all trades</div></div>
        <div class="summary-box"><strong>Average P&L</strong><div class="summary-value">{{ summary.avg_pnl_points }}</div><div>Average points per trade</div></div>
        <div class="summary-box"><strong>Best Trade</strong><div class="summary-value">{{ summary.best_trade }}</div><div>Strongest single-trade result</div></div>
        <div class="summary-box"><strong>Worst Trade</strong><div class="summary-value">{{ summary.worst_trade }}</div><div>Weakest single-trade result</div></div>
      </div>
    </section>

    <section class="card">
      <h2>How To Read It</h2>
      <div class="legend">
        <div class="legend-item">
          <strong>Entry Rule</strong>
          A trade is opened on the first valid ORB break after the opening range window. Longs use OR high and shorts use OR low.
        </div>
        <div class="legend-item">
          <strong>Risk Model</strong>
          Stop and target are based on the opening-range size multiplied by your chosen stop and target settings.
        </div>
        <div class="legend-item">
          <strong>Same-Candle Ambiguity</strong>
          If stop and target are both touched in the same minute candle, the backtest assumes the stop was hit first.
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Trade Log</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Date</th>
              <th>Side</th>
              <th>Entry Time</th>
              <th>Entry</th>
              <th>Stop</th>
              <th>Target</th>
              <th>Exit Time</th>
              <th>Exit</th>
              <th>Outcome</th>
              <th>P&L</th>
              <th>Range</th>
              <th>Exit Reason</th>
            </tr>
          </thead>
          <tbody>
            {% for row in trade_rows %}
            <tr>
              <td>{{ row.symbol }}</td>
              <td>{{ row.trade_date }}</td>
              <td><span class="badge {{ row.side_badge }}">{{ row.side }}</span></td>
              <td>{{ row.entry_time }}</td>
              <td>{{ row.entry_price }}</td>
              <td>{{ row.stop_price }}</td>
              <td>{{ row.target_price }}</td>
              <td>{{ row.exit_time }}</td>
              <td>{{ row.exit_price }}</td>
              <td><span class="badge {{ row.outcome_badge }}">{{ row.outcome }}</span></td>
              <td><span class="badge {{ row.pnl_badge }}">{{ row.pnl_points }}</span></td>
              <td>{{ row.range_size }}</td>
              <td>{{ row.exit_reason }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </section>
  </div>
</body>
</html>
"""

TRADE_PLAN_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Trade Plan</title>
  <style>
    :root {
      --bg: #f3ecdf;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --up: #116149;
      --up-soft: #d7efe7;
      --down: #8a2e2e;
      --down-soft: #f7dddd;
      --neutral: #7a5a18;
      --neutral-soft: #f5ebcc;
      --info: #1f3f73;
      --info-soft: #dde8f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(31,111,95,0.12), transparent 25%),
        linear-gradient(180deg, #fbf7ef 0%, #ece3d6 100%);
    }
    .page { max-width: 960px; margin: 0 auto; padding: 20px 14px 40px; }
    .hero {
      background: linear-gradient(135deg, rgba(20,44,62,0.98), rgba(31,111,95,0.92));
      color: #f8f5ef;
      border-radius: 22px;
      padding: 22px 18px;
      box-shadow: 0 20px 50px rgba(24,32,39,0.14);
    }
    h1 { margin: 0; font-size: 32px; line-height: 1.05; }
    .sub {
      margin: 10px 0 0;
      font-size: 16px;
      line-height: 1.45;
      color: rgba(248,245,239,0.88);
    }
    .meta, .quick-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .pill {
      padding: 9px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      font-size: 13px;
    }
    .card {
      margin-top: 16px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 16px;
      box-shadow: 0 16px 36px rgba(24,32,39,0.07);
    }
    .card h2 { margin: 0 0 12px; font-size: 22px; }
    .toolbar-grid, .summary-grid, .plan-grid {
      display: grid;
      gap: 12px;
    }
    .toolbar-grid { grid-template-columns: 1fr 1fr; }
    .summary-grid { grid-template-columns: 1fr 1fr; }
    .plan-grid { grid-template-columns: 1fr; }
    label {
      display: block;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input, select {
      width: 100%;
      padding: 11px 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    button, .quick-link, .symbol-link {
      font: inherit;
      text-decoration: none;
    }
    button {
      width: 100%;
      border: 0;
      padding: 12px 14px;
      border-radius: 14px;
      cursor: pointer;
      font-weight: 700;
      color: #fff;
      background: var(--accent);
    }
    .quick-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 10px 14px;
      font-weight: 700;
    }
    .quick-link.active { background: #dbece7; color: var(--accent); border-color: rgba(31,111,95,0.24); }
    .summary-box, .plan-card {
      padding: 14px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.78);
    }
    .summary-value { font-size: 26px; font-weight: 700; margin-top: 6px; }
    .plan-head {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
      margin-bottom: 12px;
    }
    .plan-title { font-size: 22px; font-weight: 700; }
    .plan-sub { color: var(--muted); font-size: 13px; margin-top: 4px; }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up { background: var(--up-soft); color: var(--up); }
    .badge-down { background: var(--down-soft); color: var(--down); }
    .badge-neutral { background: var(--neutral-soft); color: var(--neutral); }
    .badge-info { background: var(--info-soft); color: var(--info); }
    .metrics {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 12px;
    }
    .metric {
      padding: 10px 12px;
      border-radius: 14px;
      background: #faf7f1;
      border: 1px solid var(--line);
    }
    .metric-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 4px;
    }
    .metric-value { font-size: 18px; font-weight: 700; }
    .plan-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 12px;
    }
    .symbol-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: var(--accent);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      background: #fff;
      font-weight: 700;
    }
    .error {
      margin-top: 14px;
      border-radius: 16px;
      padding: 14px 16px;
      background: #f7e3d9;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.18);
    }
    .note-text { line-height: 1.45; margin: 0; }
    @media (min-width: 760px) {
      .toolbar-grid { grid-template-columns: repeat(5, 1fr); }
      .summary-grid { grid-template-columns: repeat(4, 1fr); }
      .plan-grid { grid-template-columns: repeat(2, 1fr); }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Trade Plan Dashboard</h1>
      <p class="sub">
        A mobile-optimized execution page that turns intraday signals into clean trade plans with entry, stop, target levels,
        and fast drilldowns to the detailed OHLC view.
      </p>
      <div class="meta">
        <div class="pill">Watchlist: {{ active_watchlist_label }}</div>
        <div class="pill">Date: {{ selected_date }}</div>
        <div class="pill">Range: {{ start_time }} to {{ end_time }}</div>
        <div class="pill">Risk Stop: {{ risk_multiple }}R</div>
        <div class="pill">Target 1: {{ target_one_multiple }}R</div>
        <div class="pill">Target 2: {{ target_two_multiple }}R</div>
      </div>
    </section>

    <section class="card">
      <h2>Controls</h2>
      <form method="get" class="toolbar-grid">
        <div>
          <label for="watchlist">Watchlist</label>
          <select id="watchlist" name="watchlist">
            {% for watch in watchlists %}
            <option value="{{ watch.key }}" {{ 'selected' if watch.key == active_watchlist else '' }}>{{ watch.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="symbols">Custom Symbols</label>
          <input id="symbols" name="symbols" value="{{ request_symbols }}" placeholder="IOC,PNB,SBIN">
        </div>
        <div>
          <label for="date">Date</label>
          <input id="date" name="date" value="{{ selected_date }}" placeholder="YYYY-MM-DD">
        </div>
        <div>
          <label for="start">ORB Start</label>
          <input id="start" name="start" value="{{ start_time }}" placeholder="09:15">
        </div>
        <div>
          <label for="end">ORB End</label>
          <input id="end" name="end" value="{{ end_time }}" placeholder="09:30">
        </div>
        <div>
          <label for="risk_multiple">Stop Multiple</label>
          <input id="risk_multiple" name="risk_multiple" value="{{ risk_multiple }}" placeholder="1.0">
        </div>
        <div>
          <label for="target_one_multiple">Target 1</label>
          <input id="target_one_multiple" name="target_one_multiple" value="{{ target_one_multiple }}" placeholder="1.0">
        </div>
        <div>
          <label for="target_two_multiple">Target 2</label>
          <input id="target_two_multiple" name="target_two_multiple" value="{{ target_two_multiple }}" placeholder="2.0">
        </div>
        <div style="align-self:end">
          <button type="submit">Open Trade Plans</button>
        </div>
      </form>
      <div class="quick-links">
        <a class="quick-link {{ 'active' if selected_date == today_date else '' }}"
           href="/equity-trade-plan?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ today_date }}&start={{ start_time }}&end={{ end_time }}&risk_multiple={{ risk_multiple }}&target_one_multiple={{ target_one_multiple }}&target_two_multiple={{ target_two_multiple }}">
          Today
        </a>
        <a class="quick-link {{ 'active' if selected_date == yesterday_date else '' }}"
           href="/equity-trade-plan?watchlist={{ active_watchlist }}&symbols={{ request_symbols|urlencode }}&date={{ yesterday_date }}&start={{ start_time }}&end={{ end_time }}&risk_multiple={{ risk_multiple }}&target_one_multiple={{ target_one_multiple }}&target_two_multiple={{ target_two_multiple }}">
          Yesterday
        </a>
      </div>
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Summary</h2>
      <div class="summary-grid">
        <div class="summary-box"><strong>Long Plans</strong><div class="summary-value">{{ summary.long_count }}</div><div>Constructive execution candidates</div></div>
        <div class="summary-box"><strong>Short Plans</strong><div class="summary-value">{{ summary.short_count }}</div><div>Weak execution candidates</div></div>
        <div class="summary-box"><strong>Wait / Mixed</strong><div class="summary-value">{{ summary.wait_count }}</div><div>Names without clean alignment</div></div>
        <div class="summary-box"><strong>High Conviction</strong><div class="summary-value">{{ summary.high_conviction_count }}</div><div>ORB, VWAP, and level alignment</div></div>
      </div>
    </section>

    <section class="card">
      <h2>Trade Cards</h2>
      <div class="plan-grid">
        {% for row in trade_plan_rows %}
        <div class="plan-card">
          <div class="plan-head">
            <div>
              <div class="plan-title">{{ row.symbol }}</div>
              <div class="plan-sub">{{ row.plan_label }} | {{ row.orb_status }} | {{ row.vwap_status }}</div>
            </div>
            <span class="badge {{ row.plan_badge }}">{{ row.plan_label }}</span>
          </div>
          <div class="metrics">
            <div class="metric"><div class="metric-label">Entry</div><div class="metric-value">{{ row.entry_price }}</div></div>
            <div class="metric"><div class="metric-label">Stop Loss</div><div class="metric-value">{{ row.stop_price }}</div></div>
            <div class="metric"><div class="metric-label">Target 1</div><div class="metric-value">{{ row.target_one_price }}</div></div>
            <div class="metric"><div class="metric-label">Target 2</div><div class="metric-value">{{ row.target_two_price }}</div></div>
            <div class="metric"><div class="metric-label">Range Size</div><div class="metric-value">{{ row.range_size }}</div></div>
            <div class="metric"><div class="metric-label">Gap / PD Levels</div><div class="metric-value">{{ row.gap_pct }} | {{ row.status_label }}</div></div>
          </div>
          <p class="note-text">{{ row.plan_note }}</p>
          <div class="plan-links">
            <a class="symbol-link" href="/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}">Open OHLC</a>
            <a class="symbol-link" href="/equity-previous-levels?symbols={{ row.symbol }}&date={{ selected_date }}">Prev Levels</a>
            <a class="symbol-link" href="/equity-confirmation?symbols={{ row.symbol }}&date={{ selected_date }}&start={{ start_time }}&end={{ end_time }}">Confirmation</a>
          </div>
        </div>
        {% endfor %}
      </div>
    </section>
  </div>
</body>
</html>
"""

ARBITRAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Cash Arbitrage</title>
  <style>
    :root {
      --bg: #f3ecdf;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --up: #116149;
      --up-soft: #d7efe7;
      --down: #8a2e2e;
      --down-soft: #f7dddd;
      --neutral: #7a5a18;
      --neutral-soft: #f5ebcc;
      --info: #1f3f73;
      --info-soft: #dde8f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(31,111,95,0.12), transparent 25%),
        linear-gradient(180deg, #fbf7ef 0%, #ece3d6 100%);
    }
    .page { max-width: 1460px; margin: 0 auto; padding: 28px 18px 56px; }
    .hero {
      background: linear-gradient(135deg, rgba(20,44,62,0.98), rgba(31,111,95,0.92));
      color: #f8f5ef;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 22px 60px rgba(24,32,39,0.14);
    }
    h1 { margin: 0; font-size: 40px; line-height: 1; }
    .sub {
      margin: 12px 0 0;
      max-width: 1020px;
      font-size: 17px;
      line-height: 1.5;
      color: rgba(248,245,239,0.88);
    }
    .meta, .quick-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      font-size: 14px;
    }
    .card {
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: 0 18px 44px rgba(24,32,39,0.07);
    }
    .card h2 { margin: 0 0 12px; font-size: 24px; }
    .toolbar-grid, .summary-grid, .legend, .mobile-card-grid {
      display: grid;
      gap: 14px;
    }
    .toolbar-grid { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
    .summary-grid { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
    .mobile-card-grid { grid-template-columns: 1fr; }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input, select {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    button, .quick-link {
      border-radius: 14px;
      font: inherit;
      text-decoration: none;
    }
    button {
      width: 100%;
      border: 0;
      padding: 12px 16px;
      cursor: pointer;
      font-weight: 700;
      color: #fff;
      background: var(--accent);
    }
    .quick-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
      padding: 12px 16px;
      font-weight: 700;
    }
    .summary-box, .legend-item {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.78);
    }
    .summary-value { font-size: 28px; font-weight: 700; margin-top: 8px; }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up { background: var(--up-soft); color: var(--up); }
    .badge-down { background: var(--down-soft); color: var(--down); }
    .badge-neutral { background: var(--neutral-soft); color: var(--neutral); }
    .badge-info { background: var(--info-soft); color: var(--info); }
    .table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 18px; }
    .desktop-only { display: block; }
    .mobile-only { display: none; }
    table { width: 100%; border-collapse: collapse; min-width: 1440px; }
    th, td {
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }
    tbody tr:hover { background: rgba(31,111,95,0.05); }
    th {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      background: #faf7f1;
    }
    .error {
      margin-top: 14px;
      border-radius: 16px;
      padding: 14px 16px;
      background: #f7e3d9;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.18);
    }
    .hero-callout {
      margin-top: 16px;
      padding: 16px 18px;
      border-radius: 18px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
    }
    .spotlight-callout {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(31,111,95,0.1);
      color: var(--accent);
      border: 1px solid rgba(31,111,95,0.18);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 700;
    }
    .spotlight-callout-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 0 4px rgba(31,111,95,0.12);
    }
    .spotlight-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 12px;
      margin-top: 14px;
    }
    .spotlight-metric {
      padding: 14px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.78);
    }
    .spotlight-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 4px;
    }
    .spotlight-value {
      font-size: 21px;
      font-weight: 700;
    }
    .mobile-card {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.82);
      box-shadow: 0 10px 26px rgba(24,32,39,0.06);
    }
    .mobile-head {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
      margin-bottom: 12px;
    }
    .mobile-title {
      font-size: 22px;
      font-weight: 700;
    }
    .mobile-sub {
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
    }
    .mobile-metrics {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 12px;
    }
    .mobile-metric {
      padding: 10px 12px;
      border-radius: 14px;
      background: #faf7f1;
      border: 1px solid var(--line);
    }
    .mobile-metric-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 4px;
    }
    .mobile-metric-value {
      font-size: 17px;
      font-weight: 700;
    }
    .mobile-note {
      margin-top: 8px;
      font-size: 14px;
      line-height: 1.45;
    }
    .notice-shell {
      display: grid;
      grid-template-columns: 88px 1fr;
      gap: 16px;
      align-items: center;
      padding: 18px;
      border-radius: 20px;
      border: 1px dashed var(--line);
      background: linear-gradient(180deg, rgba(255,255,255,0.85), rgba(247,243,234,0.9));
    }
    .notice-figure {
      position: relative;
      width: 78px;
      height: 96px;
      margin: 0 auto;
    }
    .notice-figure .avatar-head {
      width: 48px;
      height: 48px;
      border-width: 1px;
    }
    .notice-figure .avatar-head::before,
    .notice-figure .avatar-head::after {
      top: 18px;
      width: 6px;
      height: 6px;
    }
    .notice-figure .avatar-body {
      width: 56px;
      height: 48px;
      top: 38px;
      border-width: 1px;
    }
    .notice-figure .avatar-screen {
      width: 72px;
      height: 20px;
    }
    .notice-title {
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 6px;
    }
    .notice-copy {
      color: var(--muted);
      line-height: 1.55;
      font-size: 14px;
    }
    @media (max-width: 760px) {
      .desktop-only { display: none; }
      .mobile-only { display: block; }
      .page { padding: 20px 12px 40px; }
      .hero, .card { border-radius: 18px; }
      h1 { font-size: 32px; }
      .hero-grid, .notice-shell { grid-template-columns: 1fr; }
      .hero-stage { min-height: 230px; }
      .crew-card { width: 32%; }
      .avatar { width: 76px; height: 100px; }
      .avatar-head { width: 48px; height: 48px; }
      .avatar-body { width: 56px; height: 54px; }
      .avatar-screen { width: 72px; }
      .notice-figure { height: 86px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="hero-grid">
        <div class="hero-copy">
          <h1>Cash Arbitrage Monitor</h1>
          <p class="sub">
            A tradable NSE-vs-BSE cash-equity arbitrage page that compares the best ask on the cheaper exchange against the best bid
            on the richer exchange, then estimates net opportunity after brokerage and transaction taxes. It scans the full common NSE/BSE
            EQ cash universe automatically for today's market and keeps a short post-analysis archive for the last 3 days.
          </p>
          <div class="meta">
            <div class="pill">Universe: {{ common_symbol_count }} common NSE/BSE EQ shares</div>
            <div class="pill">Capital: {{ capital_display }}</div>
            <div class="pill">Min Spread: {{ min_spread_display }}</div>
            <div class="pill">Net Positive Only: {{ net_positive_label }}</div>
            <div class="pill">Auto Refresh: {{ refresh_label }}</div>
            <div class="pill">Archive Window: Last {{ archive_days }} days</div>
            <div class="pill">Virtual Trade Limit: {{ virtual_trade_book.prepared_count }}/{{ rules.max_trades_per_day }}</div>
          </div>
          <div class="hero-callout">
            <span class="badge {{ market_state.badge_class }}">{{ market_state.label }}</span>
            <div style="margin-top: 10px; line-height: 1.5;">{{ market_state.detail }}</div>
            {% if virtual_pause_reason %}
            <div style="margin-top: 10px; line-height: 1.5;"><strong>Prep Status:</strong> {{ virtual_pause_reason }}</div>
            {% endif %}
          </div>
        </div>
        <div class="hero-stage">
          <div class="stage-label">Live Scanner Crew</div>
          <div class="desk-crew">
            <div class="crew-card bull">
              <div class="avatar">
                <div class="avatar-head"></div>
                <div class="avatar-face"></div>
                <div class="avatar-body"></div>
                <div class="avatar-screen"></div>
              </div>
              <div class="crew-name">Spread Runner</div>
              <div class="crew-role">Hunts the best live spread between exchanges.</div>
            </div>
            <div class="crew-card scout">
              <div class="avatar">
                <div class="avatar-head"></div>
                <div class="avatar-face"></div>
                <div class="avatar-body"></div>
                <div class="avatar-screen"></div>
              </div>
              <div class="crew-name">Depth Scout</div>
              <div class="crew-role">Checks whether the spread is actually tradable.</div>
            </div>
            <div class="crew-card bear">
              <div class="avatar">
                <div class="avatar-head"></div>
                <div class="avatar-face"></div>
                <div class="avatar-body"></div>
                <div class="avatar-screen"></div>
              </div>
              <div class="crew-name">Risk Officer</div>
              <div class="crew-role">Cuts off weak setups before they waste attention.</div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Controls</h2>
      <form method="get" class="toolbar-grid">
        <div>
          <label for="capital">Capital (INR)</label>
          <input id="capital" name="capital" value="{{ capital_display }}" placeholder="20000">
        </div>
        <div>
          <label for="min_spread">Min Spread / Share</label>
          <input id="min_spread" name="min_spread" value="{{ min_spread_display }}" placeholder="0.50">
        </div>
        <div>
          <label for="refresh">Auto Refresh</label>
          <select id="refresh" name="refresh">
            {% for option in refresh_options %}
            <option value="{{ option.value }}" {{ 'selected' if option.value == refresh_seconds else '' }}>{{ option.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="net_positive_only">Net Positive Only</label>
          <select id="net_positive_only" name="net_positive_only">
            <option value="1" {{ 'selected' if net_positive_only else '' }}>Yes</option>
            <option value="0" {{ 'selected' if not net_positive_only else '' }}>No</option>
          </select>
        </div>
        <div>
          <button type="submit">Scan Arbitrage</button>
        </div>
      </form>
      <div class="legend" style="margin-top: 14px;">
        <div class="legend-item">
          <strong>Automatic Universe</strong>
          No watchlist is required here. The scanner now checks every share that appears in both NSE and BSE cash markets with EQ series handling.
        </div>
      </div>
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Summary</h2>
      <div class="summary-grid">
        <div class="summary-box"><strong>Opportunities</strong><div class="summary-value">{{ summary.opportunity_count }}</div><div>Tradable spreads after filters</div></div>
        <div class="summary-box"><strong>Best Net Opportunity</strong><div class="summary-value">{{ summary.best_net_profit }}</div><div>Highest estimated net profit</div></div>
        <div class="summary-box"><strong>Total Net Potential</strong><div class="summary-value">{{ summary.total_net_profit }}</div><div>Across shown rows</div></div>
        <div class="summary-box"><strong>Liquidity Flags</strong><div class="summary-value">{{ summary.depth_limited_count }}</div><div>Rows limited by best-depth quantity</div></div>
        <div class="summary-box"><strong>Scan Mode</strong><div class="summary-value">{{ scan_mode_label }}</div><div>Tradable best ask / best bid comparison</div></div>
        <div class="summary-box"><strong>Ready Setups</strong><div class="summary-value">{{ ready_setup_count }}</div><div>Top rule-matched setups ready for virtual prep</div></div>
        <div class="summary-box"><strong>Virtual Net</strong><div class="summary-value">{{ virtual_trade_book.total_virtual_net }}</div><div>Estimated total across virtual trades today</div></div>
      </div>
    </section>

    <section class="card">
      <h2>Best Opportunity Alert</h2>
      {% if spotlight %}
      <div class="summary-box">
        <div class="spotlight-callout"><span class="spotlight-callout-dot"></span>Lead Opportunity On Screen</div>
        <strong>{{ spotlight.symbol }}</strong>
        <div style="margin-top: 8px;"><span class="badge {{ spotlight.badge_class }}">{{ spotlight.net_profit }}</span></div>
        <div style="margin-top: 10px; color: var(--muted);">{{ spotlight.route }} at {{ spotlight.timestamp }}</div>
        <div class="spotlight-grid">
          <div class="spotlight-metric">
            <div class="spotlight-label">Gross Spread</div>
            <div class="spotlight-value">{{ spotlight.gross_spread }}</div>
          </div>
          <div class="spotlight-metric">
            <div class="spotlight-label">Tradable Qty</div>
            <div class="spotlight-value">{{ spotlight.quantity }}</div>
          </div>
          <div class="spotlight-metric">
            <div class="spotlight-label">Liquidity</div>
            <div class="spotlight-value" style="font-size: 18px;">{{ spotlight.liquidity_warning }}</div>
          </div>
        </div>
        <div class="mobile-note">{{ spotlight.note }}</div>
      </div>
      {% else %}
      <div class="notice-shell">
        <div class="notice-figure scout">
          <div class="avatar-head"></div>
          <div class="avatar-face"></div>
          <div class="avatar-body"></div>
          <div class="avatar-screen"></div>
        </div>
        <div>
          <div class="notice-title">No Best Opportunity Yet</div>
          <div class="notice-copy">The scanner is alive, but no spread has cleared costs strongly enough to become the lead trade alert. That usually means the spread is thin, the edge is too brief, or size is not there yet.</div>
        </div>
      </div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Virtual Trade Prep Panel</h2>
      <div class="legend" style="margin-bottom: 14px;">
        <div class="legend-item">
          <strong>Rule Engine</strong>
          Capital {{ capital_display }}, minimum spread {{ rules.min_spread }}, minimum net {{ rules.min_net_profit }}, depth {{ rules.min_depth_quantity }} shares, persistence {{ rules.persistence_seconds }} seconds, cooldown {{ rules.cooldown_seconds }} seconds.
        </div>
      </div>
      {% if ready_setups %}
      <div class="mobile-card-grid">
        {% for setup in ready_setups %}
        <div class="mobile-card">
          <div class="mobile-head">
            <div>
              <div class="mobile-title">{{ setup.symbol }}</div>
              <div class="mobile-sub">{{ setup.route }}</div>
            </div>
            <span class="badge {{ setup.ready_badge }}">{{ setup.net_profit }}</span>
          </div>
          <div class="mobile-metrics">
            <div class="mobile-metric">
              <div class="mobile-metric-label">Buy Price</div>
              <div class="mobile-metric-value">{{ setup.buy_price }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Sell Price</div>
              <div class="mobile-metric-value">{{ setup.sell_price }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Quantity</div>
              <div class="mobile-metric-value">{{ setup.quantity }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Persisted</div>
              <div class="mobile-metric-value">{{ setup.persisted_seconds }}s</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Gross</div>
              <div class="mobile-metric-value">{{ setup.gross_profit }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Charges</div>
              <div class="mobile-metric-value">{{ setup.total_charges }}</div>
            </div>
          </div>
          <div class="mobile-note">
            <strong>Liquidity:</strong> {{ setup.liquidity_warning }}<br>
            <strong>Time:</strong> {{ setup.timestamp }}
          </div>
          <form method="post" style="margin-top: 12px;">
            <input type="hidden" name="capital" value="{{ capital_display }}">
            <input type="hidden" name="min_spread" value="{{ min_spread_display }}">
            <input type="hidden" name="refresh" value="{{ refresh_seconds }}">
            <input type="hidden" name="net_positive_only" value="{{ 1 if net_positive_only else 0 }}">
            <input type="hidden" name="setup_key" value="{{ setup.setup_key }}">
            <div class="toolbar-grid">
              <div>
                <button type="submit" name="action" value="prepare_virtual">Create Virtual Trade</button>
              </div>
              <div>
                <button type="submit" name="action" value="dismiss_setup">Snooze 5s</button>
              </div>
            </div>
          </form>
        </div>
        {% endfor %}
      </div>
      {% else %}
      <div class="notice-shell">
        <div class="notice-figure bear">
          <div class="avatar-head"></div>
          <div class="avatar-face"></div>
          <div class="avatar-body"></div>
          <div class="avatar-screen"></div>
        </div>
        <div>
          <div class="notice-title">No Setup Fully Ready</div>
          <div class="notice-copy">The rule engine is filtering the tape and waiting for at least {{ rules.persistence_seconds }} seconds of persistence, enough depth, and a net profit of at least {{ rules.min_net_profit }} before it promotes anything into the prep queue.</div>
        </div>
      </div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Virtual Trade Book</h2>
      <div class="summary-grid">
        <div class="summary-box"><strong>Prepared Today</strong><div class="summary-value">{{ virtual_trade_book.prepared_count }}</div><div>Virtual trades created so far</div></div>
        <div class="summary-box"><strong>Remaining Slots</strong><div class="summary-value">{{ virtual_trade_book.remaining_trades }}</div><div>Prep slots left before the 10-trade stop</div></div>
        <div class="summary-box"><strong>Total Virtual Trades</strong><div class="summary-value">{{ virtual_trade_book.total_virtual_count }}</div><div>Open and archived together</div></div>
      </div>
      {% if virtual_trade_book.open_trades %}
      <h3 style="margin-top: 18px;">Open Virtual Trades</h3>
      <div class="mobile-card-grid">
        {% for trade in virtual_trade_book.open_trades %}
        <div class="mobile-card">
          <div class="mobile-head">
            <div>
              <div class="mobile-title">{{ trade.symbol }}</div>
              <div class="mobile-sub">{{ trade.route }}</div>
            </div>
            <span class="badge {{ trade.status_badge }}">{{ trade.status }}</span>
          </div>
          <div class="mobile-metrics">
            <div class="mobile-metric">
              <div class="mobile-metric-label">Net Profit</div>
              <div class="mobile-metric-value">{{ trade.net_profit }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Prepared At</div>
              <div class="mobile-metric-value">{{ trade.prepared_at }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Buy Price</div>
              <div class="mobile-metric-value">{{ trade.buy_price }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Sell Price</div>
              <div class="mobile-metric-value">{{ trade.sell_price }}</div>
            </div>
          </div>
          <div class="mobile-note"><strong>Liquidity:</strong> {{ trade.liquidity_warning }}</div>
          <form method="post" style="margin-top: 12px;">
            <input type="hidden" name="capital" value="{{ capital_display }}">
            <input type="hidden" name="min_spread" value="{{ min_spread_display }}">
            <input type="hidden" name="refresh" value="{{ refresh_seconds }}">
            <input type="hidden" name="net_positive_only" value="{{ 1 if net_positive_only else 0 }}">
            <input type="hidden" name="trade_id" value="{{ trade.trade_id }}">
            <button type="submit" name="action" value="archive_virtual">Archive Virtual Trade</button>
          </form>
        </div>
        {% endfor %}
      </div>
      {% endif %}
      {% if virtual_trade_book.closed_trades %}
      <h3 style="margin-top: 18px;">Archived Virtual Trades</h3>
      <div class="mobile-card-grid">
        {% for trade in virtual_trade_book.closed_trades %}
        <div class="mobile-card">
          <div class="mobile-head">
            <div>
              <div class="mobile-title">{{ trade.symbol }}</div>
              <div class="mobile-sub">{{ trade.route }}</div>
            </div>
            <span class="badge {{ trade.status_badge }}">{{ trade.status }}</span>
          </div>
          <div class="mobile-note">
            <strong>Prepared:</strong> {{ trade.prepared_at }}<br>
            <strong>Closed:</strong> {{ trade.closed_at or '-' }}<br>
            <strong>Net:</strong> {{ trade.net_profit }}
          </div>
        </div>
        {% endfor %}
      </div>
      {% endif %}
    </section>

    <section class="card">
      <h2>How To Read It</h2>
      <div class="legend">
        <div class="legend-item">
          <strong>Tradable Mode</strong>
          Buy price uses the best ask on the lower exchange and sell price uses the best bid on the higher exchange, not last traded price.
        </div>
        <div class="legend-item">
          <strong>Common NSE/BSE EQ Stocks</strong>
          This page is designed for shares that are available in both NSE and BSE cash markets with EQ series treatment in your stock master.
        </div>
        <div class="legend-item">
          <strong>Depth Warning</strong>
          Quantity is capped by capital and best-depth availability. Thin depth can make a theoretical spread unusable in practice.
        </div>
      </div>
    </section>

    <section class="card desktop-only">
      <h2>Arbitrage Table</h2>
      {% if not arbitrage_rows %}
      <div class="notice-shell">
        <div class="notice-figure scout">
          <div class="avatar-head"></div>
          <div class="avatar-face"></div>
          <div class="avatar-body"></div>
          <div class="avatar-screen"></div>
        </div>
        <div>
          <div class="notice-title">No Table Rows Yet</div>
          <div class="notice-copy">No net-positive tradable arbitrage met the current filter right now. The scanner is still checking the full NSE/BSE EQ common universe in the background while the market is open.</div>
        </div>
      </div>
      {% else %}
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>NSE Ask</th>
              <th>NSE Bid</th>
              <th>BSE Ask</th>
              <th>BSE Bid</th>
              <th>Buy On</th>
              <th>Sell On</th>
              <th>Gross Spread</th>
              <th>Spread %</th>
              <th>Qty</th>
              <th>Gross Profit</th>
              <th>Charges</th>
              <th>Net Profit</th>
              <th>Liquidity Warning</th>
              <th>Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {% for row in arbitrage_rows %}
            <tr>
              <td>{{ row.symbol }}</td>
              <td>{{ row.nse_ask }}</td>
              <td>{{ row.nse_bid }}</td>
              <td>{{ row.bse_ask }}</td>
              <td>{{ row.bse_bid }}</td>
              <td><span class="badge {{ row.buy_badge }}">{{ row.buy_exchange }}</span></td>
              <td><span class="badge {{ row.sell_badge }}">{{ row.sell_exchange }}</span></td>
              <td><span class="badge {{ row.gross_badge }}">{{ row.gross_spread }}</span></td>
              <td><span class="badge {{ row.spread_pct_badge }}">{{ row.spread_pct }}</span></td>
              <td>{{ row.quantity }}</td>
              <td><span class="badge {{ row.gross_total_badge }}">{{ row.gross_profit }}</span></td>
              <td>{{ row.total_charges }}</td>
              <td><span class="badge {{ row.net_badge }}">{{ row.net_profit }}</span></td>
              <td>{{ row.liquidity_warning }}</td>
              <td>{{ row.timestamp }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      {% endif %}
    </section>

    <section class="card mobile-only">
      <h2>Arbitrage Cards</h2>
      {% if not arbitrage_rows %}
      <div class="notice-shell">
        <div class="notice-figure scout">
          <div class="avatar-head"></div>
          <div class="avatar-face"></div>
          <div class="avatar-body"></div>
          <div class="avatar-screen"></div>
        </div>
        <div>
          <div class="notice-title">No Mobile Cards Yet</div>
          <div class="notice-copy">No live tradable arbitrage met the active filter right now. The mobile scanner is still watching the common NSE/BSE EQ universe automatically and will surface the next valid spread here.</div>
        </div>
      </div>
      {% else %}
      <div class="mobile-card-grid">
        {% for row in arbitrage_rows %}
        <div class="mobile-card">
          <div class="mobile-head">
            <div>
              <div class="mobile-title">{{ row.symbol }}</div>
              <div class="mobile-sub">{{ row.buy_exchange }} buy -> {{ row.sell_exchange }} sell</div>
            </div>
            <span class="badge {{ row.net_badge }}">{{ row.net_profit }}</span>
          </div>
          <div class="mobile-metrics">
            <div class="mobile-metric">
              <div class="mobile-metric-label">Buy Price</div>
              <div class="mobile-metric-value">{{ row.buy_exchange }} {{ row.nse_ask if row.buy_exchange == 'NSE' else row.bse_ask }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Sell Price</div>
              <div class="mobile-metric-value">{{ row.sell_exchange }} {{ row.bse_bid if row.sell_exchange == 'BSE' else row.nse_bid }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Gross Spread</div>
              <div class="mobile-metric-value">{{ row.gross_spread }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Spread %</div>
              <div class="mobile-metric-value">{{ row.spread_pct }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Quantity</div>
              <div class="mobile-metric-value">{{ row.quantity }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Charges</div>
              <div class="mobile-metric-value">{{ row.total_charges }}</div>
            </div>
          </div>
          <div class="mobile-note">
            <strong>Gross:</strong> {{ row.gross_profit }}<br>
            <strong>Liquidity:</strong> {{ row.liquidity_warning }}<br>
            <strong>Time:</strong> {{ row.timestamp }}
          </div>
        </div>
        {% endfor %}
      </div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Post Analysis: Last {{ archive_days }} Days</h2>
      <div class="meta" style="margin-bottom: 14px;">
        <a class="quick-link" href="/equity-arbitrage-export.csv">Download 3-Day CSV</a>
      </div>
      {% if recurring_archive %}
      <div class="summary-grid" style="margin-bottom: 14px;">
        {% for item in recurring_archive %}
        <div class="summary-box">
          <strong>{{ item.symbol }}</strong>
          <div style="margin-top: 8px;"><span class="badge {{ item.badge_class }}">{{ item.best_net_profit }}</span></div>
          <div style="margin-top: 10px;">Seen on {{ item.appearances }} day{{ '' if item.appearances == 1 else 's' }}</div>
          <div style="margin-top: 6px; color: var(--muted);">{{ item.latest_route }}</div>
          <div style="margin-top: 6px; color: var(--muted);">{{ item.latest_liquidity_warning }}</div>
        </div>
        {% endfor %}
      </div>
      {% endif %}
      {% if post_analysis_groups %}
        {% for group in post_analysis_groups %}
        <div class="summary-box" style="margin-bottom: 14px;">
          <strong>{{ group.day_label }}</strong>
          <div style="margin-top: 8px; color: var(--muted);">{{ group.summary_note }}</div>
          <div class="mobile-card-grid" style="margin-top: 14px;">
            {% for story in group.stories %}
            <div class="mobile-card">
              <div class="mobile-head">
                <div>
                  <div class="mobile-title">{{ story.symbol }}</div>
                  <div class="mobile-sub">{{ story.route }}</div>
                </div>
                <span class="badge {{ story.story_badge }}">{{ story.max_net_profit }}</span>
              </div>
              <div class="mobile-metrics">
                <div class="mobile-metric">
                  <div class="mobile-metric-label">Best Gross Spread</div>
                  <div class="mobile-metric-value">{{ story.max_gross_spread }}</div>
                </div>
                <div class="mobile-metric">
                  <div class="mobile-metric-label">Best Net Profit</div>
                  <div class="mobile-metric-value">{{ story.max_net_profit }}</div>
                </div>
                <div class="mobile-metric">
                  <div class="mobile-metric-label">First Seen</div>
                  <div class="mobile-metric-value">{{ story.first_seen }}</div>
                </div>
                <div class="mobile-metric">
                  <div class="mobile-metric-label">Last Seen</div>
                  <div class="mobile-metric-value">{{ story.last_seen }}</div>
                </div>
                <div class="mobile-metric">
                  <div class="mobile-metric-label">Detections</div>
                  <div class="mobile-metric-value">{{ story.detection_count }}</div>
                </div>
                <div class="mobile-metric">
                  <div class="mobile-metric-label">Liquidity</div>
                  <div class="mobile-metric-value">{{ story.liquidity_warning }}</div>
                </div>
              </div>
              <div class="mobile-note">{{ story.story_note }}</div>
            </div>
            {% endfor %}
          </div>
        </div>
        {% endfor %}
      {% else %}
      <div class="notice-shell">
        <div class="notice-figure bull">
          <div class="avatar-head"></div>
          <div class="avatar-face"></div>
          <div class="avatar-body"></div>
          <div class="avatar-screen"></div>
        </div>
        <div>
          <div class="notice-title">Archive Waiting For Its First Story</div>
          <div class="notice-copy">No arbitrage opportunities have been archived yet. As soon as a live spread survives costs, this section will keep the story for the next {{ archive_days }} days so you can review repeated names and timing patterns.</div>
        </div>
      </div>
      {% endif %}
    </section>
  </div>
  {% if refresh_seconds > 0 %}
  <script>
    window.setTimeout(function () {
      window.location.reload();
    }, {{ refresh_seconds * 1000 }});
  </script>
  {% endif %}
</body>
</html>
"""

ARBITRAGE_VIRTUAL_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Virtual Arbitrage Desk</title>
  <style>
    :root {
      --bg: #f3ecdf;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --up: #116149;
      --up-soft: #d7efe7;
      --down: #8a2e2e;
      --down-soft: #f7dddd;
      --neutral: #7a5a18;
      --neutral-soft: #f5ebcc;
      --info: #1f3f73;
      --info-soft: #dde8f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(31,111,95,0.12), transparent 25%),
        linear-gradient(180deg, #fbf7ef 0%, #ece3d6 100%);
    }
    .page { max-width: 1280px; margin: 0 auto; padding: 28px 18px 56px; }
    .hero {
      background: linear-gradient(135deg, rgba(20,44,62,0.98), rgba(31,111,95,0.92));
      color: #f8f5ef;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 22px 60px rgba(24,32,39,0.14);
    }
    .hero-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.9fr);
      gap: 22px;
      align-items: stretch;
    }
    .hero-copy {
      display: flex;
      flex-direction: column;
      justify-content: center;
    }
    h1 { margin: 0; font-size: 40px; line-height: 1; }
    .sub {
      margin: 12px 0 0;
      max-width: 980px;
      font-size: 17px;
      line-height: 1.5;
      color: rgba(248,245,239,0.88);
    }
    .meta, .nav-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      font-size: 14px;
    }
    .hero-stage {
      position: relative;
      overflow: hidden;
      border-radius: 22px;
      border: 1px solid rgba(255,255,255,0.18);
      background:
        radial-gradient(circle at top right, rgba(255,255,255,0.18), transparent 32%),
        linear-gradient(180deg, rgba(10,21,33,0.58), rgba(10,21,33,0.12));
      min-height: 260px;
      padding: 20px;
    }
    .hero-stage::after {
      content: "";
      position: absolute;
      left: 18px;
      right: 18px;
      bottom: 18px;
      height: 64px;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(232,214,174,0.18), rgba(232,214,174,0.3));
      border: 1px solid rgba(255,255,255,0.08);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.08);
    }
    .stage-label {
      position: relative;
      z-index: 2;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.12);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: rgba(248,245,239,0.9);
    }
    .desk-crew {
      position: relative;
      z-index: 2;
      display: flex;
      justify-content: center;
      align-items: flex-end;
      gap: 14px;
      margin-top: 16px;
      min-height: 170px;
    }
    .crew-card {
      width: 31%;
      min-width: 84px;
      text-align: center;
      color: #f8f5ef;
    }
    .avatar {
      position: relative;
      width: 88px;
      height: 112px;
      margin: 0 auto 10px;
    }
    .avatar-head {
      position: absolute;
      left: 50%;
      top: 0;
      width: 56px;
      height: 56px;
      transform: translateX(-50%);
      border-radius: 50%;
      background: #f2d0b4;
      border: 2px solid rgba(24,32,39,0.18);
      box-shadow: inset 0 -6px 0 rgba(0,0,0,0.05);
    }
    .avatar-head::before,
    .avatar-head::after {
      content: "";
      position: absolute;
      top: 22px;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #182027;
    }
    .avatar-head::before { left: 15px; }
    .avatar-head::after { right: 15px; }
    .avatar-face {
      position: absolute;
      left: 50%;
      top: 29px;
      width: 20px;
      height: 10px;
      transform: translateX(-50%);
      border-bottom: 2px solid #182027;
      border-radius: 0 0 16px 16px;
    }
    .avatar-body {
      position: absolute;
      left: 50%;
      top: 46px;
      width: 64px;
      height: 62px;
      transform: translateX(-50%);
      border-radius: 18px 18px 14px 14px;
      border: 2px solid rgba(255,255,255,0.24);
      background: linear-gradient(180deg, rgba(255,255,255,0.18), rgba(255,255,255,0.08));
    }
    .avatar-body::before {
      content: "";
      position: absolute;
      left: 50%;
      top: 10px;
      width: 16px;
      height: 36px;
      transform: translateX(-50%);
      clip-path: polygon(50% 0, 100% 38%, 68% 100%, 32% 100%, 0 38%);
      background: rgba(20,44,62,0.78);
    }
    .avatar-screen {
      position: absolute;
      left: 50%;
      bottom: -2px;
      width: 80px;
      height: 26px;
      transform: translateX(-50%);
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,0.2);
      background: rgba(11,23,35,0.68);
      box-shadow: 0 8px 16px rgba(7,13,20,0.2);
      overflow: hidden;
    }
    .avatar-screen::before {
      content: "";
      position: absolute;
      inset: 4px 6px;
      border-radius: 6px;
      background: linear-gradient(90deg, rgba(17,97,73,0.75), rgba(255,255,255,0.12), rgba(138,46,46,0.75));
    }
    .crew-card.bull .avatar-body { background: linear-gradient(180deg, rgba(17,97,73,0.44), rgba(17,97,73,0.18)); }
    .crew-card.bear .avatar-body { background: linear-gradient(180deg, rgba(138,46,46,0.4), rgba(138,46,46,0.14)); }
    .crew-card.scout .avatar-body { background: linear-gradient(180deg, rgba(31,63,115,0.42), rgba(31,63,115,0.14)); }
    .crew-name {
      font-size: 14px;
      font-weight: 700;
      letter-spacing: 0.03em;
    }
    .crew-role {
      margin-top: 4px;
      font-size: 12px;
      color: rgba(248,245,239,0.78);
      line-height: 1.35;
    }
    .card {
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: 0 18px 44px rgba(24,32,39,0.07);
    }
    .card h2 { margin: 0 0 12px; font-size: 24px; }
    .toolbar-grid, .summary-grid, .mobile-card-grid, .spotlight-grid {
      display: grid;
      gap: 14px;
    }
    .toolbar-grid { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
    .summary-grid { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
    .mobile-card-grid { grid-template-columns: 1fr; }
    .spotlight-grid { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input, select {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    button, .quick-link {
      border-radius: 14px;
      font: inherit;
      text-decoration: none;
    }
    button {
      width: 100%;
      border: 0;
      padding: 12px 16px;
      cursor: pointer;
      font-weight: 700;
      color: #fff;
      background: var(--accent);
    }
    .quick-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
      padding: 12px 16px;
      font-weight: 700;
    }
    .summary-box, .legend-item, .spotlight-metric {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.78);
    }
    .summary-box strong {
      display: block;
      font-size: 13px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }
    .summary-value, .spotlight-value { font-size: 28px; font-weight: 700; margin-top: 8px; }
    .spotlight-label, .mobile-metric-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 4px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up { background: var(--up-soft); color: var(--up); }
    .badge-down { background: var(--down-soft); color: var(--down); }
    .badge-neutral { background: var(--neutral-soft); color: var(--neutral); }
    .badge-info { background: var(--info-soft); color: var(--info); }
    .error {
      margin-top: 14px;
      border-radius: 16px;
      padding: 14px 16px;
      background: #f7e3d9;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.18);
    }
    .notice-shell {
      display: grid;
      grid-template-columns: 88px 1fr;
      gap: 16px;
      align-items: center;
      padding: 18px;
      border-radius: 20px;
      border: 1px dashed var(--line);
      background: linear-gradient(180deg, rgba(255,255,255,0.85), rgba(247,243,234,0.9));
    }
    .notice-figure {
      position: relative;
      width: 78px;
      height: 96px;
      margin: 0 auto;
    }
    .notice-figure .avatar-head {
      width: 48px;
      height: 48px;
      border-width: 1px;
    }
    .notice-figure .avatar-head::before,
    .notice-figure .avatar-head::after {
      top: 18px;
      width: 6px;
      height: 6px;
    }
    .notice-figure .avatar-body {
      width: 56px;
      height: 48px;
      top: 38px;
      border-width: 1px;
    }
    .notice-figure .avatar-screen {
      width: 72px;
      height: 20px;
    }
    .notice-title {
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 6px;
    }
    .notice-copy {
      color: var(--muted);
      line-height: 1.55;
      font-size: 14px;
    }
    .spotlight-callout {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(31,111,95,0.1);
      color: var(--accent);
      border: 1px solid rgba(31,111,95,0.18);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 700;
    }
    .spotlight-callout-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 0 4px rgba(31,111,95,0.12);
    }
    .mobile-card {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.82);
      box-shadow: 0 10px 26px rgba(24,32,39,0.06);
    }
    .mobile-head {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
      margin-bottom: 12px;
    }
    .mobile-title {
      font-size: 22px;
      font-weight: 700;
    }
    .mobile-sub {
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
    }
    .mobile-metrics {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 12px;
    }
    .mobile-metric {
      padding: 10px 12px;
      border-radius: 14px;
      background: #faf7f1;
      border: 1px solid var(--line);
    }
    .mobile-metric-value {
      font-size: 17px;
      font-weight: 700;
    }
    .mobile-note {
      margin-top: 8px;
      font-size: 14px;
      line-height: 1.45;
    }
    @media (max-width: 760px) {
      .page { padding: 20px 12px 40px; }
      .hero, .card { border-radius: 18px; }
      h1 { font-size: 32px; }
      .hero-grid, .notice-shell { grid-template-columns: 1fr; }
      .hero-stage { min-height: 220px; }
      .crew-card { width: 32%; }
      .avatar { width: 76px; height: 100px; }
      .avatar-head { width: 48px; height: 48px; }
      .avatar-body { width: 56px; height: 54px; }
      .avatar-screen { width: 72px; }
      .notice-figure { height: 86px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="hero-grid">
        <div class="hero-copy">
          <h1>Virtual Arbitrage Desk</h1>
          <p class="sub">
            A dedicated paper-trading workspace for your NSE-vs-BSE arbitrage rules. It watches the common EQ universe, promotes only persistent rule-matched setups, and lets you create virtual trades without placing any real orders.
          </p>
          <div class="meta">
            <div class="pill">Capital: {{ capital_display }}</div>
            <div class="pill">Min Spread: {{ min_spread_display }}</div>
            <div class="pill">Ready Setups: {{ ready_setup_count }}/{{ rules.max_ready_setups }}</div>
            <div class="pill">Prepared Today: {{ virtual_trade_book.prepared_count }}/{{ rules.max_trades_per_day }}</div>
          </div>
          <div class="nav-links">
            <a class="quick-link" href="/equity-arbitrage">Open Scanner Page</a>
            <a class="quick-link" href="/equity-arbitrage-export.csv">Download 3-Day CSV</a>
          </div>
        </div>
        <div class="hero-stage">
          <div class="stage-label">Desk Crew On Duty</div>
          <div class="desk-crew">
            <div class="crew-card bull">
              <div class="avatar">
                <div class="avatar-head"></div>
                <div class="avatar-face"></div>
                <div class="avatar-body"></div>
                <div class="avatar-screen"></div>
              </div>
              <div class="crew-name">Spread Runner</div>
              <div class="crew-role">Chases fast buy-low sell-high windows.</div>
            </div>
            <div class="crew-card scout">
              <div class="avatar">
                <div class="avatar-head"></div>
                <div class="avatar-face"></div>
                <div class="avatar-body"></div>
                <div class="avatar-screen"></div>
              </div>
              <div class="crew-name">Depth Scout</div>
              <div class="crew-role">Checks if enough size exists to matter.</div>
            </div>
            <div class="crew-card bear">
              <div class="avatar">
                <div class="avatar-head"></div>
                <div class="avatar-face"></div>
                <div class="avatar-body"></div>
                <div class="avatar-screen"></div>
              </div>
              <div class="crew-name">Risk Officer</div>
              <div class="crew-role">Blocks noisy setups before they waste a slot.</div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>System Status</h2>
      <div class="summary-grid">
        <div class="summary-box"><strong>Market State</strong><div class="summary-value" style="font-size:22px;">{{ market_state.label }}</div><div>{{ market_state.detail }}</div></div>
        <div class="summary-box"><strong>Prep Status</strong><div class="summary-value" style="font-size:22px;">{{ virtual_pause_title }}</div><div>{{ virtual_pause_reason or 'Ready to prepare new virtual trades.' }}</div></div>
        <div class="summary-box"><strong>Best Live Net</strong><div class="summary-value">{{ summary.best_net_profit }}</div><div>Top net setup in the current scan</div></div>
        <div class="summary-box"><strong>Total Virtual Net</strong><div class="summary-value">{{ virtual_trade_book.total_virtual_net }}</div><div>Estimated cumulative virtual net today</div></div>
      </div>
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Rule Controls</h2>
      <form method="get" class="toolbar-grid">
        <div>
          <label for="capital">Capital (INR)</label>
          <input id="capital" name="capital" value="{{ capital_display }}" placeholder="20000">
        </div>
        <div>
          <label for="min_spread">Min Spread / Share</label>
          <input id="min_spread" name="min_spread" value="{{ min_spread_display }}" placeholder="0.20">
        </div>
        <div>
          <label for="refresh">Auto Refresh</label>
          <select id="refresh" name="refresh">
            {% for option in refresh_options %}
            <option value="{{ option.value }}" {{ 'selected' if option.value == refresh_seconds else '' }}>{{ option.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="net_positive_only">Net Positive Only</label>
          <select id="net_positive_only" name="net_positive_only">
            <option value="1" {{ 'selected' if net_positive_only else '' }}>Yes</option>
            <option value="0" {{ 'selected' if not net_positive_only else '' }}>No</option>
          </select>
        </div>
        <div>
          <button type="submit">Refresh Virtual Desk</button>
        </div>
      </form>
      <div class="mobile-note">
        <strong>Locked strategy:</strong> minimum net {{ rules.min_net_profit }}, minimum depth {{ rules.min_depth_quantity }} shares, persistence {{ rules.persistence_seconds }} seconds, cooldown {{ rules.cooldown_seconds }} seconds, stop after 3:00 PM or {{ rules.max_trades_per_day }} prepared trades.
      </div>
    </section>

    <section class="card">
      <h2>Best Opportunity Spotlight</h2>
      {% if spotlight %}
      <div class="summary-box">
        <div class="spotlight-callout"><span class="spotlight-callout-dot"></span>Lead Opportunity On Screen</div>
        <strong>{{ spotlight.symbol }}</strong>
        <div style="margin-top: 8px;"><span class="badge {{ spotlight.badge_class }}">{{ spotlight.net_profit }}</span></div>
        <div style="margin-top: 10px; color: var(--muted);">{{ spotlight.route }} at {{ spotlight.timestamp }}</div>
        <div class="spotlight-grid" style="margin-top: 14px;">
          <div class="spotlight-metric"><div class="spotlight-label">Gross Spread</div><div class="spotlight-value">{{ spotlight.gross_spread }}</div></div>
          <div class="spotlight-metric"><div class="spotlight-label">Tradable Qty</div><div class="spotlight-value">{{ spotlight.quantity }}</div></div>
          <div class="spotlight-metric"><div class="spotlight-label">Liquidity</div><div class="spotlight-value" style="font-size:20px;">{{ spotlight.liquidity_warning }}</div></div>
        </div>
        <div class="mobile-note">{{ spotlight.note }}</div>
      </div>
      {% else %}
      <div class="notice-shell">
        <div class="notice-figure scout">
          <div class="avatar-head"></div>
          <div class="avatar-face"></div>
          <div class="avatar-body"></div>
          <div class="avatar-screen"></div>
        </div>
        <div>
          <div class="notice-title">No Spotlight Yet</div>
          <div class="notice-copy">The desk is scanning, but nothing is strong enough yet to become the lead opportunity. That usually means the spread is thin, depth is weak, or the move has not survived long enough.</div>
        </div>
      </div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Ready Setups</h2>
      {% if ready_setups %}
      <div class="mobile-card-grid">
        {% for setup in ready_setups %}
        <div class="mobile-card">
          <div class="mobile-head">
            <div>
              <div class="mobile-title">{{ setup.symbol }}</div>
              <div class="mobile-sub">{{ setup.route }}</div>
            </div>
            <span class="badge {{ setup.ready_badge }}">{{ setup.net_profit }}</span>
          </div>
          <div class="mobile-metrics">
            <div class="mobile-metric"><div class="mobile-metric-label">Buy Price</div><div class="mobile-metric-value">{{ setup.buy_price }}</div></div>
            <div class="mobile-metric"><div class="mobile-metric-label">Sell Price</div><div class="mobile-metric-value">{{ setup.sell_price }}</div></div>
            <div class="mobile-metric"><div class="mobile-metric-label">Qty</div><div class="mobile-metric-value">{{ setup.quantity }}</div></div>
            <div class="mobile-metric"><div class="mobile-metric-label">Persisted</div><div class="mobile-metric-value">{{ setup.persisted_seconds }}s</div></div>
            <div class="mobile-metric"><div class="mobile-metric-label">Gross</div><div class="mobile-metric-value">{{ setup.gross_profit }}</div></div>
            <div class="mobile-metric"><div class="mobile-metric-label">Charges</div><div class="mobile-metric-value">{{ setup.total_charges }}</div></div>
          </div>
          <div class="mobile-note">
            <strong>Liquidity:</strong> {{ setup.liquidity_warning }}<br>
            <strong>Time:</strong> {{ setup.timestamp }}
          </div>
          <form method="post" style="margin-top: 12px;">
            <input type="hidden" name="capital" value="{{ capital_display }}">
            <input type="hidden" name="min_spread" value="{{ min_spread_display }}">
            <input type="hidden" name="refresh" value="{{ refresh_seconds }}">
            <input type="hidden" name="net_positive_only" value="{{ 1 if net_positive_only else 0 }}">
            <input type="hidden" name="setup_key" value="{{ setup.setup_key }}">
            <div class="toolbar-grid">
              <div><button type="submit" name="action" value="prepare_virtual">Create Virtual Trade</button></div>
              <div><button type="submit" name="action" value="dismiss_setup">Snooze 5s</button></div>
            </div>
          </form>
        </div>
        {% endfor %}
      </div>
      {% else %}
      <div class="notice-shell">
        <div class="notice-figure bear">
          <div class="avatar-head"></div>
          <div class="avatar-face"></div>
          <div class="avatar-body"></div>
          <div class="avatar-screen"></div>
        </div>
        <div>
          <div class="notice-title">No Setup Fully Ready</div>
          <div class="notice-copy">The rule engine is still filtering the tape. It is waiting for persistence, enough depth, and a net profit that clears your threshold before it promotes anything into the trade prep queue.</div>
        </div>
      </div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Virtual Trade Book</h2>
      <div class="summary-grid">
        <div class="summary-box"><strong>Prepared Today</strong><div class="summary-value">{{ virtual_trade_book.prepared_count }}</div><div>Virtual trades created so far</div></div>
        <div class="summary-box"><strong>Remaining Slots</strong><div class="summary-value">{{ virtual_trade_book.remaining_trades }}</div><div>Prep slots left before the daily stop</div></div>
        <div class="summary-box"><strong>Total Virtual Trades</strong><div class="summary-value">{{ virtual_trade_book.total_virtual_count }}</div><div>Open and archived together</div></div>
      </div>
      {% if virtual_trade_book.open_trades %}
      <h3 style="margin-top: 18px;">Open Virtual Trades</h3>
      <div class="mobile-card-grid">
        {% for trade in virtual_trade_book.open_trades %}
        <div class="mobile-card">
          <div class="mobile-head">
            <div>
              <div class="mobile-title">{{ trade.symbol }}</div>
              <div class="mobile-sub">{{ trade.route }}</div>
            </div>
            <span class="badge {{ trade.status_badge }}">{{ trade.status }}</span>
          </div>
          <div class="mobile-metrics">
            <div class="mobile-metric"><div class="mobile-metric-label">Net Profit</div><div class="mobile-metric-value">{{ trade.net_profit }}</div></div>
            <div class="mobile-metric"><div class="mobile-metric-label">Prepared At</div><div class="mobile-metric-value">{{ trade.prepared_at }}</div></div>
            <div class="mobile-metric"><div class="mobile-metric-label">Buy Price</div><div class="mobile-metric-value">{{ trade.buy_price }}</div></div>
            <div class="mobile-metric"><div class="mobile-metric-label">Sell Price</div><div class="mobile-metric-value">{{ trade.sell_price }}</div></div>
          </div>
          <div class="mobile-note"><strong>Liquidity:</strong> {{ trade.liquidity_warning }}</div>
          <form method="post" style="margin-top: 12px;">
            <input type="hidden" name="capital" value="{{ capital_display }}">
            <input type="hidden" name="min_spread" value="{{ min_spread_display }}">
            <input type="hidden" name="refresh" value="{{ refresh_seconds }}">
            <input type="hidden" name="net_positive_only" value="{{ 1 if net_positive_only else 0 }}">
            <input type="hidden" name="trade_id" value="{{ trade.trade_id }}">
            <button type="submit" name="action" value="archive_virtual">Archive Virtual Trade</button>
          </form>
        </div>
        {% endfor %}
      </div>
      {% endif %}
      {% if virtual_trade_book.closed_trades %}
      <h3 style="margin-top: 18px;">Archived Virtual Trades</h3>
      <div class="mobile-card-grid">
        {% for trade in virtual_trade_book.closed_trades %}
        <div class="mobile-card">
          <div class="mobile-head">
            <div>
              <div class="mobile-title">{{ trade.symbol }}</div>
              <div class="mobile-sub">{{ trade.route }}</div>
            </div>
            <span class="badge {{ trade.status_badge }}">{{ trade.status }}</span>
          </div>
          <div class="mobile-note">
            <strong>Prepared:</strong> {{ trade.prepared_at }}<br>
            <strong>Closed:</strong> {{ trade.closed_at or '-' }}<br>
            <strong>Net:</strong> {{ trade.net_profit }}
          </div>
        </div>
        {% endfor %}
      </div>
      {% endif %}
      {% if not virtual_trade_book.open_trades and not virtual_trade_book.closed_trades %}
      <div class="notice-shell" style="margin-top: 18px;">
        <div class="notice-figure bull">
          <div class="avatar-head"></div>
          <div class="avatar-face"></div>
          <div class="avatar-body"></div>
          <div class="avatar-screen"></div>
        </div>
        <div>
          <div class="notice-title">Trade Book Waiting For Its First Session</div>
          <div class="notice-copy">Once you create a virtual trade, this desk will keep the paper position here so you can review timing, route, charges, and repeated opportunities before you decide whether the strategy deserves full automation later.</div>
        </div>
      </div>
      {% endif %}
    </section>
  </div>
  {% if refresh_seconds > 0 %}
  <script>
    window.setTimeout(function () {
      window.location.reload();
    }, {{ refresh_seconds * 1000 }});
  </script>
  {% endif %}
</body>
</html>
"""

PD_LEVELS_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Previous Day Levels</title>
  <style>
    :root {
      --bg: #f2ede2;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --accent-soft: #dbece7;
      --up: #116149;
      --up-soft: #d7efe7;
      --down: #8a2e2e;
      --down-soft: #f7dddd;
      --neutral: #7a5a18;
      --neutral-soft: #f5ebcc;
      --info: #1f3f73;
      --info-soft: #dde8f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at right top, rgba(31,111,95,0.1), transparent 28%),
        linear-gradient(180deg, #fbf7ef 0%, #ece3d6 100%);
    }
    .page {
      max-width: 1380px;
      margin: 0 auto;
      padding: 28px 18px 56px;
    }
    .hero {
      background: linear-gradient(135deg, rgba(20,44,62,0.98), rgba(31,111,95,0.92));
      color: #f8f5ef;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 22px 60px rgba(24,32,39,0.14);
    }
    h1 { margin: 0; font-size: 40px; line-height: 1; }
    .sub {
      margin: 12px 0 0;
      max-width: 920px;
      font-size: 17px;
      line-height: 1.5;
      color: rgba(248,245,239,0.88);
    }
    .meta, .watch-links, .quick-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      font-size: 14px;
    }
    .card {
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: 0 18px 44px rgba(24,32,39,0.07);
    }
    .card h2 { margin: 0 0 12px; font-size: 24px; }
    .toolbar-grid, .summary-grid, .legend {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input, select {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    button, .watch-link, .quick-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      border: 0;
      border-radius: 14px;
      padding: 12px 16px;
      font: inherit;
      font-weight: 700;
      text-decoration: none;
    }
    button { color: #fff; background: var(--accent); }
    .watch-link, .quick-link {
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
    }
    .watch-link.active, .quick-link.active {
      background: var(--accent-soft);
      color: var(--accent);
      border-color: rgba(31,111,95,0.24);
    }
    .summary-box, .legend-item {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
    }
    .summary-box strong, .legend-item strong {
      display: block;
      margin-bottom: 8px;
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .summary-value {
      font-size: 28px;
      font-weight: 700;
    }
    .table-wrap {
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 18px;
    }
    .desktop-only { display: block; }
    .mobile-only { display: none; }
    table { width: 100%; border-collapse: collapse; min-width: 1260px; }
    th, td {
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }
    tbody tr { cursor: pointer; }
    tbody tr:hover { background: rgba(31,111,95,0.06); }
    th {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      background: #faf7f1;
      cursor: pointer;
      user-select: none;
    }
    th.sortable:hover { color: var(--ink); }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up { background: var(--up-soft); color: var(--up); }
    .badge-down { background: var(--down-soft); color: var(--down); }
    .badge-neutral { background: var(--neutral-soft); color: var(--neutral); }
    .badge-info { background: var(--info-soft); color: var(--info); }
    .symbol-link {
      color: var(--accent);
      font-weight: 700;
      text-decoration: none;
    }
    .symbol-link:hover { text-decoration: underline; }
    .error {
      margin-top: 14px;
      border-radius: 16px;
      padding: 14px 16px;
      background: #f7e3d9;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.18);
    }
    .mobile-card-grid {
      display: grid;
      gap: 14px;
      grid-template-columns: 1fr;
    }
    .mobile-card {
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.82);
    }
    .mobile-head {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
      margin-bottom: 12px;
    }
    .mobile-title {
      font-size: 22px;
      font-weight: 700;
    }
    .mobile-sub {
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
    }
    .mobile-metrics {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 12px;
    }
    .mobile-metric {
      padding: 10px 12px;
      border-radius: 14px;
      background: #faf7f1;
      border: 1px solid var(--line);
    }
    .mobile-metric-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 4px;
    }
    .mobile-metric-value {
      font-size: 17px;
      font-weight: 700;
    }
    .mobile-note {
      margin-top: 8px;
      font-size: 14px;
      line-height: 1.45;
    }
    .muted { color: var(--muted); }
    @media (max-width: 720px) {
      .desktop-only { display: none; }
      .mobile-only { display: block; }
      h1 { font-size: 32px; }
      .page { padding: 18px 12px 40px; }
      .hero, .card { border-radius: 18px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Previous Day Breakouts Dashboard</h1>
      <p class="sub">
        An automatic market monitor for previous-day high and low breaks. It scans a broad equity universe, surfaces names
        trading above PDH or below PDL, and highlights the cleaner setups with sector context before you drill into the deeper intraday pages.
      </p>
      <div class="meta">
        <div class="pill">Universe: {{ universe_label }}</div>
        <div class="pill">Signal View: {{ signal_view_label }}</div>
        <div class="pill">Date: {{ selected_date }}</div>
        <div class="pill">Auto Refresh: {{ refresh_label }}</div>
      </div>
    </section>

    <section class="card">
      <h2>Market Controls</h2>
      <form method="get" class="toolbar-grid">
        <div>
          <label for="universe_mode">Universe</label>
          <select id="universe_mode" name="universe_mode">
            {% for option in universe_mode_options %}
            <option value="{{ option.key }}" {{ 'selected' if option.key == universe_mode else '' }}>{{ option.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="signal_view">Signal View</label>
          <select id="signal_view" name="signal_view">
            {% for option in signal_view_options %}
            <option value="{{ option.key }}" {{ 'selected' if option.key == signal_view else '' }}>{{ option.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="date">Date</label>
          <input id="date" name="date" value="{{ selected_date }}" placeholder="YYYY-MM-DD">
        </div>
        <div>
          <label for="refresh">Auto Refresh</label>
          <select id="refresh" name="refresh">
            {% for option in refresh_options %}
            <option value="{{ option.value }}" {{ 'selected' if option.value == refresh_seconds else '' }}>{{ option.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <button type="submit">Open Levels Page</button>
        </div>
      </form>
      <div class="quick-links">
        <a class="quick-link {{ 'active' if selected_date == today_date else '' }}"
           href="/equity-previous-levels?universe_mode={{ universe_mode }}&signal_view={{ signal_view }}&date={{ today_date }}&refresh={{ refresh_seconds }}">
          Today
        </a>
        <a class="quick-link {{ 'active' if selected_date == yesterday_date else '' }}"
           href="/equity-previous-levels?universe_mode={{ universe_mode }}&signal_view={{ signal_view }}&date={{ yesterday_date }}&refresh={{ refresh_seconds }}">
          Yesterday
        </a>
      </div>
      <div class="legend" style="margin-top: 14px;">
        <div class="legend-item">
          <strong>Default Shape</strong>
          The page now starts with Nifty 50 by default to stay lighter on Zerodha requests, while still letting you expand into Nifty Next 50, a liquid trading universe, or the broader common EQ universe.
        </div>
      </div>
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Summary</h2>
      <div class="summary-grid">
        <div class="summary-box">
          <strong>Above PDH</strong>
          <div class="summary-value">{{ summary.above_pdh_count }}</div>
          <div>Names trading above previous-day high</div>
        </div>
        <div class="summary-box">
          <strong>Below PDL</strong>
          <div class="summary-value">{{ summary.below_pdl_count }}</div>
          <div>Names trading below previous-day low</div>
        </div>
        <div class="summary-box">
          <strong>Near Prev Close</strong>
          <div class="summary-value">{{ summary.near_close_count }}</div>
          <div>Names still near previous close</div>
        </div>
        <div class="summary-box">
          <strong>Near PDH</strong>
          <div class="summary-value">{{ summary.near_pdh_count }}</div>
          <div>Names sitting just under PDH</div>
        </div>
        <div class="summary-box">
          <strong>Near PDL</strong>
          <div class="summary-value">{{ summary.near_pdl_count }}</div>
          <div>Names sitting just above PDL</div>
        </div>
        <div class="summary-box">
          <strong>Strong Breaks</strong>
          <div class="summary-value">{{ summary.strong_count }}</div>
          <div>Higher-quality previous-day level breaks</div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>How To Read It</h2>
      <div class="legend">
        <div class="legend-item">
          <strong>PDH / PDL</strong>
          Previous-day high and low are strong reference levels. Above PDH often signals strength; below PDL often signals weakness.
        </div>
        <div class="legend-item">
          <strong>Distance Columns</strong>
          These show how far the current price is from PDH, PDL, and previous close, which helps you spot the cleanest level breaks.
        </div>
        <div class="legend-item">
          <strong>Click Through</strong>
          Click any row or symbol to jump into the detailed OHLC page for minute-level context around the same symbol.
        </div>
        <div class="legend-item">
          <strong>Quality Tags</strong>
          Strong bullish or bearish breaks rank first. Near PDH or near PDL tags help traders watch the names that are closest to triggering next.
        </div>
      </div>
    </section>

    <section class="card desktop-only">
      <h2>Actionable Levels Table</h2>
      {% if not level_rows %}
      <div class="legend-item">
        No names matched the current universe and signal filter right now. Try switching between breakout, breakdown, near-level, or broader universe modes.
      </div>
      {% else %}
      <div class="table-wrap">
        <table id="pd-levels-table">
          <thead>
            <tr>
              <th class="sortable" data-key="symbol">Symbol</th>
              <th class="sortable" data-key="sector">Sector</th>
              <th class="sortable" data-key="breakout_rank">Quality</th>
              <th class="sortable" data-key="status_sort">Status</th>
              <th class="sortable" data-key="last_price">Last Price</th>
              <th class="sortable" data-key="pdh">PDH</th>
              <th class="sortable" data-key="pdl">PDL</th>
              <th class="sortable" data-key="prev_close">Prev Close</th>
              <th class="sortable" data-key="distance_pdh">Dist to PDH</th>
              <th class="sortable" data-key="distance_pdl">Dist to PDL</th>
              <th class="sortable" data-key="distance_close">Dist to Prev Close</th>
              <th class="sortable" data-key="gap_pct">Gap %</th>
              <th>Bias</th>
            </tr>
          </thead>
          <tbody>
            {% for row in level_rows %}
            <tr onclick="window.location='/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start=09:15&end=09:30'">
              <td data-sort="{{ row.symbol }}">
                <a class="symbol-link" href="/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start=09:15&end=09:30" onclick="event.stopPropagation()">{{ row.symbol }}</a>
              </td>
              <td data-sort="{{ row.sector_label }}">{{ row.sector_label }}</td>
              <td data-sort="{{ row.breakout_rank }}"><span class="badge {{ row.quality_badge }}">{{ row.quality_label }}</span></td>
              <td data-sort="{{ row.status_sort }}"><span class="badge {{ row.status_badge }}">{{ row.status_label }}</span></td>
              <td data-sort="{{ row.last_price_numeric }}">{{ row.last_price }}</td>
              <td data-sort="{{ row.pdh_numeric }}">{{ row.pdh }}</td>
              <td data-sort="{{ row.pdl_numeric }}">{{ row.pdl }}</td>
              <td data-sort="{{ row.prev_close_numeric }}">{{ row.prev_close }}</td>
              <td data-sort="{{ row.distance_pdh_numeric }}"><span class="badge {{ row.distance_pdh_badge }}">{{ row.distance_pdh }}</span></td>
              <td data-sort="{{ row.distance_pdl_numeric }}"><span class="badge {{ row.distance_pdl_badge }}">{{ row.distance_pdl }}</span></td>
              <td data-sort="{{ row.distance_close_numeric }}"><span class="badge {{ row.distance_close_badge }}">{{ row.distance_close }}</span></td>
              <td data-sort="{{ row.gap_pct_numeric }}"><span class="badge {{ row.gap_badge }}">{{ row.gap_pct }}</span></td>
              <td>{{ row.bias_note }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      {% endif %}
    </section>

    <section class="card mobile-only">
      <h2>Actionable Breakout Cards</h2>
      {% if not level_rows %}
      <div class="legend-item">
        No names matched the current universe and signal filter right now. Try switching between breakout, breakdown, near-level, or broader universe modes.
      </div>
      {% else %}
      <div class="mobile-card-grid">
        {% for row in level_rows %}
        <div class="mobile-card" onclick="window.location='/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start=09:15&end=09:30'">
          <div class="mobile-head">
            <div>
              <div class="mobile-title">
                <a class="symbol-link" href="/equity-ohlc?symbols={{ row.symbol }}&date={{ selected_date }}&start=09:15&end=09:30" onclick="event.stopPropagation()">{{ row.symbol }}</a>
              </div>
              <div class="mobile-sub">{{ row.sector_label }}</div>
            </div>
            <span class="badge {{ row.quality_badge }}">{{ row.quality_label }}</span>
          </div>
          <div class="mobile-metrics">
            <div class="mobile-metric">
              <div class="mobile-metric-label">Status</div>
              <div class="mobile-metric-value"><span class="badge {{ row.status_badge }}">{{ row.status_label }}</span></div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Last Price</div>
              <div class="mobile-metric-value">{{ row.last_price }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">PDH</div>
              <div class="mobile-metric-value">{{ row.pdh }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">PDL</div>
              <div class="mobile-metric-value">{{ row.pdl }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Gap %</div>
              <div class="mobile-metric-value">{{ row.gap_pct }}</div>
            </div>
            <div class="mobile-metric">
              <div class="mobile-metric-label">Prev Close</div>
              <div class="mobile-metric-value">{{ row.prev_close }}</div>
            </div>
          </div>
          <div class="mobile-note">
            <strong>Distance to PDH:</strong> {{ row.distance_pdh }}<br>
            <strong>Distance to PDL:</strong> {{ row.distance_pdl }}<br>
            <strong>Bias:</strong> {{ row.bias_note }}
          </div>
        </div>
        {% endfor %}
      </div>
      {% endif %}
    </section>
  </div>
  {% if refresh_seconds > 0 %}
  <script>
    window.setTimeout(function () {
      window.location.reload();
    }, {{ refresh_seconds * 1000 }});
  </script>
  {% endif %}
  <script>
    (function () {
      const table = document.getElementById("pd-levels-table");
      if (!table) return;
      const tbody = table.querySelector("tbody");
      const headers = table.querySelectorAll("th.sortable");
      let currentKey = null;
      let ascending = false;

      function getCellValue(row, index) {
        const cell = row.children[index];
        return cell ? cell.dataset.sort || cell.textContent.trim() : "";
      }

      headers.forEach((header, index) => {
        header.addEventListener("click", () => {
          const key = header.dataset.key;
          ascending = currentKey === key ? !ascending : false;
          currentKey = key;
          const rows = Array.from(tbody.querySelectorAll("tr"));
          rows.sort((a, b) => {
            const aValue = getCellValue(a, index);
            const bValue = getCellValue(b, index);
            const aNumber = Number(aValue);
            const bNumber = Number(bValue);
            let result = 0;

            if (!Number.isNaN(aNumber) && !Number.isNaN(bNumber)) {
              result = aNumber - bNumber;
            } else {
              result = aValue.localeCompare(bValue);
            }

            return ascending ? result : -result;
          });
          rows.forEach((row) => tbody.appendChild(row));
        });
      });
    })();
  </script>
</body>
</html>
"""


def is_market_open():
    now = datetime.datetime.now(APP_TZ).time()
    start = datetime.time(9, 0)
    end = datetime.time(15, 30)
    return start <= now <= end


def get_market_state():
    now = datetime.datetime.now(APP_TZ)
    open_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)

    if open_time <= now <= close_time:
        return {
            "label": "Market Live",
            "detail": f"Cash market scan is live as of {now.strftime('%H:%M:%S')}. Refresh keeps watching current two-exchange depth.",
            "badge_class": "badge-up",
        }
    if now < open_time:
        return {
            "label": "Pre-Open / Before Cash Session",
            "detail": f"Archive stays available now. Live monitoring begins at {open_time.strftime('%H:%M')}.",
            "badge_class": "badge-info",
        }
    return {
        "label": "Post-Market Review",
        "detail": "Live cash arbitrage has closed for the day, but the page still shows the last archived opportunities for review.",
        "badge_class": "badge-neutral",
    }


def get_today_ist():
    return datetime.datetime.now(APP_TZ).date()


def get_yesterday_ist():
    return get_today_ist() - datetime.timedelta(days=1)


def parse_symbol_list(raw_symbols):
    return resolve_symbol_list(raw_symbols)


def parse_date(value):
    if not value:
        return get_today_ist()
    return datetime.date.fromisoformat(value)


def parse_time(value, fallback):
    return datetime.time.fromisoformat(value or fallback)


def format_price(value):
    return f"{value:.2f}"


def get_market_close_time():
    return datetime.time(15, 30)


def get_breakout_reference_end(selected_date, end_time):
    today = get_today_ist()
    market_close = get_market_close_time()

    if selected_date < today:
        return market_close

    now = datetime.datetime.now(APP_TZ)
    if selected_date > today:
        return end_time

    current_time = now.time().replace(second=0, microsecond=0)
    if current_time <= end_time:
        return end_time

    return min(current_time, market_close)


def build_breakout_payload(or_high, or_low, last_price, last_time):
    range_size = or_high - or_low

    if last_price is None:
        return {
            "label": "Range Only",
            "badge_class": "status-neutral",
            "last_price": "-",
            "last_time": last_time,
            "or_high": format_price(or_high),
            "or_low": format_price(or_low),
            "range_size": format_price(range_size),
            "breakout_gap": "-",
        }

    if last_price > or_high:
        label = "Above OR High"
        badge_class = "status-up"
        breakout_gap = f"+{format_price(last_price - or_high)}"
    elif last_price < or_low:
        label = "Below OR Low"
        badge_class = "status-down"
        breakout_gap = f"-{format_price(or_low - last_price)}"
    else:
        label = "Inside Range"
        badge_class = "status-neutral"
        breakout_gap = format_price(0)

    return {
        "label": label,
        "badge_class": badge_class,
        "last_price": format_price(last_price),
        "last_time": last_time,
        "or_high": format_price(or_high),
        "or_low": format_price(or_low),
        "range_size": format_price(range_size),
        "breakout_gap": breakout_gap,
    }


def get_vwap_value(candles):
    total_volume = 0
    total_price_volume = 0.0

    for candle in candles:
        volume = candle.get("volume", 0) or 0
        typical_price = (candle["high"] + candle["low"] + candle["close"]) / 3
        total_volume += volume
        total_price_volume += typical_price * volume

    if total_volume <= 0:
        return None

    return total_price_volume / total_volume


def classify_orb_status(last_price, or_high, or_low):
    if last_price > or_high:
        return "Above OR High", "badge-up", 2
    if last_price < or_low:
        return "Below OR Low", "badge-down", 0
    return "Inside Range", "badge-neutral", 1


def classify_vwap_status(last_price, vwap_value):
    if vwap_value is None:
        return "VWAP N/A", "badge-info", -1

    tolerance = max(vwap_value * 0.0015, 0.05)
    if last_price > vwap_value + tolerance:
        return "Above VWAP", "badge-up", 2
    if last_price < vwap_value - tolerance:
        return "Below VWAP", "badge-down", 0
    return "Near VWAP", "badge-neutral", 1


def classify_volume_status(latest_volume, average_volume):
    if average_volume <= 0:
        return "Volume N/A", "badge-info", 0.0

    ratio = latest_volume / average_volume
    if ratio >= 1.5:
        return f"High Volume ({ratio:.2f}x)", "badge-up", ratio
    if ratio >= 0.8:
        return f"Normal Volume ({ratio:.2f}x)", "badge-neutral", ratio
    return f"Light Volume ({ratio:.2f}x)", "badge-down", ratio


def build_breakout_gap(last_price, or_high, or_low):
    if last_price > or_high:
        gap = last_price - or_high
        return f"+{format_price(gap)}", gap, "badge-up"
    if last_price < or_low:
        gap = -(or_low - last_price)
        return format_price(gap), gap, "badge-down"
    return format_price(0), 0.0, "badge-neutral"


def build_empty_scanner_row(symbol, reason):
    return {
        "symbol": symbol,
        "orb_status": reason,
        "orb_badge": "badge-info",
        "orb_sort": -1,
        "last_price": "-",
        "last_price_numeric": -1,
        "breakout_gap": "-",
        "breakout_gap_numeric": 0,
        "breakout_gap_badge": "badge-info",
        "vwap_status": "VWAP N/A",
        "vwap_badge": "badge-info",
        "vwap_sort": -1,
        "volume_status": "Volume N/A",
        "volume_badge": "badge-info",
        "volume_ratio_numeric": 0,
        "or_high": "-",
        "or_high_numeric": -1,
        "or_low": "-",
        "or_low_numeric": -1,
        "range_size": "-",
        "range_size_numeric": -1,
        "ai_suggestion": f"{symbol}: {reason}.",
    }


def get_watchlist_options():
    return [
        {"key": key, "label": key.replace("_", " ").title()}
        for key in WATCHLISTS
    ]


def get_manual_watchlist_alert_options():
    return [
        {"value": "none", "label": "No Alert"},
        {"value": "pdh_break", "label": "Price Crosses PDH"},
        {"value": "pdl_break", "label": "Price Crosses PDL"},
        {"value": "volume_spike", "label": "Volume Spike"},
        {"value": "rsi_above_60", "label": "RSI Above 60"},
        {"value": "rsi_below_40", "label": "RSI Below 40"},
        {"value": "near_vwap", "label": "Near VWAP"},
        {"value": "support_resistance", "label": "Near Support / Resistance"},
    ]


def get_manual_watchlist_alert_label(alert_rule):
    label_map = {option["value"]: option["label"] for option in get_manual_watchlist_alert_options()}
    return label_map.get(alert_rule or "none", "No Alert")


def get_manual_watchlist_alert_badge(alert_rule):
    if alert_rule in {"pdh_break", "volume_spike", "rsi_above_60"}:
        return "badge-up"
    if alert_rule in {"pdl_break", "rsi_below_40"}:
        return "badge-down"
    if alert_rule == "none":
        return "badge-neutral"
    return "badge-info"


def build_default_manual_watchlists_state():
    return {
        "watchlists": [
            {"key": f"watchlist_{index + 1}", "name": MANUAL_WATCHLIST_DEFAULT_NAMES[index], "stocks": []}
            for index in range(MANUAL_WATCHLIST_LIMIT)
        ]
    }


def normalize_manual_watchlists_state(payload):
    payload = payload or {}
    watchlists = payload.get("watchlists") or []
    normalized_watchlists = []
    seen_keys = set()

    for index in range(MANUAL_WATCHLIST_LIMIT):
        source = watchlists[index] if index < len(watchlists) else {}
        key = str(source.get("key") or f"watchlist_{index + 1}").strip().lower()
        if not key or key in seen_keys:
            key = f"watchlist_{index + 1}"
        seen_keys.add(key)

        default_name = MANUAL_WATCHLIST_DEFAULT_NAMES[index]
        raw_name = str(source.get("name") or default_name).strip()
        name = raw_name[:24] or default_name

        stocks = []
        seen_symbols = set()
        for stock in source.get("stocks") or []:
            resolved = resolve_symbol_list([stock.get("symbol")]) if stock.get("symbol") else []
            symbol = resolved[0] if resolved else None
            if not symbol or symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            stocks.append(
                {
                    "symbol": symbol,
                    "note_text": str(stock.get("note_text") or "").strip()[:400],
                    "alert_rule": str(stock.get("alert_rule") or "none").strip() or "none",
                }
            )
            if len(stocks) >= MANUAL_WATCHLIST_STOCK_LIMIT:
                break

        normalized_watchlists.append({"key": key, "name": name, "stocks": stocks})

    return {"watchlists": normalized_watchlists}


def load_manual_watchlists_state():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not MANUAL_WATCHLISTS_PATH.exists():
        state = build_default_manual_watchlists_state()
        MANUAL_WATCHLISTS_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return state

    try:
        payload = json.loads(MANUAL_WATCHLISTS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        payload = build_default_manual_watchlists_state()

    normalized = normalize_manual_watchlists_state(payload)
    MANUAL_WATCHLISTS_PATH.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
    return normalized


def save_manual_watchlists_state(state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    normalized = normalize_manual_watchlists_state(state)
    MANUAL_WATCHLISTS_PATH.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
    return normalized


def get_manual_watchlist_options(state):
    return [
        {
            "key": watch["key"],
            "name": watch["name"],
            "stock_count": len(watch.get("stocks") or []),
        }
        for watch in state.get("watchlists") or []
    ]


def get_manual_watchlist(state, active_watchlist):
    watchlists = state.get("watchlists") or []
    for watch in watchlists:
        if watch["key"] == active_watchlist:
            return watch
    return watchlists[0] if watchlists else {"key": "watchlist_1", "name": "Intraday", "stocks": []}


def get_manual_watchlist_stock_entry(watchlist, symbol):
    for stock in watchlist.get("stocks") or []:
        if stock.get("symbol") == symbol:
            return stock
    return None


def format_volume(value):
    volume = float(value or 0)
    if volume >= 10000000:
        return f"{volume / 10000000:.2f} Cr"
    if volume >= 100000:
        return f"{volume / 100000:.2f} L"
    if volume >= 1000:
        return f"{volume / 1000:.2f} K"
    return f"{int(volume)}"


def build_manual_watchlist_summary(rows):
    return {
        "total_count": len(rows),
        "up_count": sum(1 for row in rows if row["change_pct_numeric"] > 0),
        "down_count": sum(1 for row in rows if row["change_pct_numeric"] < 0),
        "above_pdh_count": sum(1 for row in rows if row["status_label"] == "Above PDH"),
        "below_pdl_count": sum(1 for row in rows if row["status_label"] == "Below PDL"),
        "gap_up_count": sum(1 for row in rows if row["gap_pct_numeric"] > 0),
        "gap_down_count": sum(1 for row in rows if row["gap_pct_numeric"] < 0),
        "above_vwap_count": sum(1 for row in rows if row["vwap_status"] == "Above VWAP"),
    }


def build_manual_watchlist_row(symbol, stock_entry, quote, daily_candles, intraday_candles, security_name):
    ohlc = (quote or {}).get("ohlc") or {}
    last_price = float((quote or {}).get("last_price") or 0)
    bid_price = get_depth_price(quote, "buy", "price")
    ask_price = get_depth_price(quote, "sell", "price")
    open_price = float(ohlc.get("open") or 0)
    day_high = float(ohlc.get("high") or 0)
    day_low = float(ohlc.get("low") or 0)
    prev_close = float(ohlc.get("close") or 0)
    close_price = last_price
    change_abs = last_price - prev_close
    change_pct = ((last_price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
    gap_pct = ((open_price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

    previous_candles = daily_candles[:-1] if len(daily_candles) > 1 else daily_candles
    if previous_candles:
        prev_day = previous_candles[-1]
        pdh = float(prev_day["high"])
        pdl = float(prev_day["low"])
    else:
        pdh = 0.0
        pdl = 0.0

    trailing_year = previous_candles[-260:] if previous_candles else []
    week_high = max((float(candle["high"]) for candle in trailing_year), default=day_high)
    week_low = min((float(candle["low"]) for candle in trailing_year), default=day_low)

    total_volume = sum((candle.get("volume") or 0) for candle in intraday_candles)
    vwap_value = get_vwap_value(intraday_candles)
    vwap_status, vwap_badge, _ = classify_vwap_status(last_price, vwap_value) if vwap_value else ("VWAP N/A", "badge-info", -1)
    tick_time = get_depth_timestamp(quote)
    near_band = max(prev_close * 0.005, 0.20) if prev_close > 0 else 0.20

    if last_price > pdh > 0:
        status_label = "Above PDH"
        status_sort = 4
        status_badge = "badge-up"
    elif last_price < pdl and pdl > 0:
        status_label = "Below PDL"
        status_sort = 0
        status_badge = "badge-down"
    elif abs(day_high - last_price) <= max(last_price * 0.0025, 0.10):
        status_label = "Near Day High"
        status_sort = 3
        status_badge = "badge-neutral"
    elif vwap_status == "Near VWAP":
        status_label = "Near VWAP"
        status_sort = 2
        status_badge = "badge-info"
    else:
        status_label = "Inside Day"
        status_sort = 1
        status_badge = "badge-neutral"

    day_range_percent = 0
    if day_high > day_low:
        day_range_percent = max(0, min(100, round(((last_price - day_low) / (day_high - day_low)) * 100)))

    note_text = str(stock_entry.get("note_text") or "").strip()
    note_preview = note_text[:70] + ("..." if len(note_text) > 70 else "") if note_text else "-"
    alert_rule = str(stock_entry.get("alert_rule") or "none")

    return {
        "symbol": symbol,
        "security_name": security_name,
        "last_price": format_price(last_price),
        "last_price_numeric": round(last_price, 2),
        "price_badge": classify_percent_badge(change_abs),
        "change_text": f"{change_abs:+.2f} / {change_pct:+.2f}%",
        "change_pct_display": f"{change_pct:+.2f}%",
        "change_pct_numeric": round(change_pct, 2),
        "change_badge": classify_percent_badge(change_pct),
        "open_price": format_price(open_price),
        "open_price_numeric": round(open_price, 2),
        "bid_price": format_price(bid_price) if bid_price is not None else "-",
        "bid_price_numeric": round(float(bid_price), 2) if bid_price is not None else -1,
        "ask_price": format_price(ask_price) if ask_price is not None else "-",
        "ask_price_numeric": round(float(ask_price), 2) if ask_price is not None else -1,
        "day_high": format_price(day_high),
        "day_high_numeric": round(day_high, 2),
        "day_low": format_price(day_low),
        "day_low_numeric": round(day_low, 2),
        "close_price": format_price(close_price),
        "close_price_numeric": round(close_price, 2),
        "volume_display": format_volume(total_volume),
        "volume_numeric": round(total_volume, 2),
        "pdh": format_price(pdh),
        "pdh_numeric": round(pdh, 2),
        "pdl": format_price(pdl),
        "pdl_numeric": round(pdl, 2),
        "prev_close": format_price(prev_close),
        "prev_close_numeric": round(prev_close, 2),
        "vwap": format_price(vwap_value) if vwap_value else "-",
        "vwap_numeric": round(vwap_value, 2) if vwap_value else -1,
        "vwap_status": vwap_status,
        "vwap_badge": vwap_badge,
        "tick_time": tick_time,
        "status_label": status_label,
        "status_sort": status_sort,
        "status_badge": status_badge,
        "gap_text": f"{gap_pct:+.2f}%",
        "gap_pct_numeric": round(gap_pct, 2),
        "gap_badge": classify_percent_badge(gap_pct),
        "day_range_percent": day_range_percent,
        "week_high": format_price(week_high),
        "week_low": format_price(week_low),
        "alert_rule": alert_rule,
        "alert_label": get_manual_watchlist_alert_label(alert_rule),
        "alert_badge": get_manual_watchlist_alert_badge(alert_rule),
        "note_text": note_text,
        "note_preview": note_preview,
    }


def get_manual_watchlist_rows(watchlist, selected_date):
    symbols = [stock["symbol"] for stock in (watchlist.get("stocks") or [])]
    if not symbols:
        return [], []

    client = build_kite_client(with_access_token=True)
    instrument_map = get_nse_instrument_map()
    master = load_symbol_master()
    quote_data = fetch_quote_map(client, [f"NSE:{symbol}" for symbol in symbols])
    rows = []
    missing = []

    intraday_end = get_breakout_reference_end(selected_date, datetime.time(15, 30))

    for stock_entry in watchlist.get("stocks") or []:
        symbol = stock_entry["symbol"]
        instrument = instrument_map.get(symbol)
        quote = quote_data.get(f"NSE:{symbol}")
        security_name = (master.get("by_symbol", {}).get(symbol) or {}).get("security") or symbol

        if not instrument or not quote:
            missing.append(symbol)
            continue

        daily_from = datetime.datetime.combine(selected_date - datetime.timedelta(days=380), datetime.time(0, 0), tzinfo=APP_TZ)
        daily_to = datetime.datetime.combine(selected_date, datetime.time(23, 59), tzinfo=APP_TZ)
        intraday_from = datetime.datetime.combine(selected_date, datetime.time(9, 15), tzinfo=APP_TZ)
        intraday_to = datetime.datetime.combine(selected_date, intraday_end, tzinfo=APP_TZ)

        daily_candles = client.historical_data(
            instrument["instrument_token"],
            daily_from,
            daily_to,
            "day",
            continuous=False,
            oi=False,
        )
        intraday_candles = client.historical_data(
            instrument["instrument_token"],
            intraday_from,
            intraday_to,
            "5minute",
            continuous=False,
            oi=False,
        )

        rows.append(build_manual_watchlist_row(symbol, stock_entry, quote, daily_candles, intraday_candles, security_name))

    return rows, missing


def build_market_watch_status(rows, missing):
    now = datetime.datetime.now(APP_TZ)
    up_count = sum(1 for row in rows if row["change_pct_numeric"] > 0)
    down_count = sum(1 for row in rows if row["change_pct_numeric"] < 0)
    flat_count = max(0, len(rows) - up_count - down_count)
    latest_tick = max((row.get("tick_time") for row in rows if row.get("tick_time") and row.get("tick_time") != "-"), default="-")

    feed_health = "Stable"
    feed_badge = "badge-up"
    if missing:
        feed_health = "Partial Feed"
        feed_badge = "badge-neutral"
    if not rows:
        feed_health = "No Feed"
        feed_badge = "badge-down"

    return {
        "market_label": "Market Live" if get_market_state()["label"] == "Market Live" else get_market_state()["label"],
        "market_badge": get_market_state()["badge_class"],
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "latest_tick": latest_tick if latest_tick != "-" else now.strftime("%H:%M:%S"),
        "feed_health": feed_health,
        "feed_badge": feed_badge,
        "missing_count": len(missing),
    }


def get_market_watch_context(active_watchlist_key, selected_symbol, refresh_seconds):
    state = load_manual_watchlists_state()
    watchlist_options = get_manual_watchlist_options(state)
    active_watchlist = get_manual_watchlist(state, active_watchlist_key)
    selected_date = get_today_ist()

    error = None
    rows = []
    missing = []
    try:
        creds = get_active_kite_credentials()
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("Kite API key or access token is missing in .env.")
        rows, missing = get_manual_watchlist_rows(active_watchlist, selected_date)
    except Exception as exc:
        error = str(exc)

    rows.sort(key=lambda row: row["symbol"])
    active_selected_symbol = selected_symbol or (rows[0]["symbol"] if rows else "")
    selected_row = next((row for row in rows if row["symbol"] == active_selected_symbol), rows[0] if rows else None)
    summary = build_manual_watchlist_summary(rows)
    status = build_market_watch_status(rows, missing)

    return {
        "error": error,
        "watchlist_options": watchlist_options,
        "active_watchlist": active_watchlist,
        "rows": rows,
        "summary": summary,
        "status": status,
        "selected_row": selected_row,
        "selected_symbol": active_selected_symbol,
        "refresh_options": get_refresh_options(),
        "refresh_seconds": refresh_seconds,
        "today_date": get_today_ist().isoformat(),
    }


def render_market_watch_partials(context):
    top_strip_html = render_template_string(
        """
        <div class="top-strip">
          <div class="strip-box">
            <div class="strip-label">Session</div>
            <div class="strip-value">{{ status.market_label }}</div>
            <div class="strip-note"><span class="badge {{ status.market_badge }}">{{ status.market_label }}</span></div>
          </div>
          <div class="strip-box">
            <div class="strip-label">Watchlist</div>
            <div class="strip-value">{{ active_watchlist.name }}</div>
            <div class="strip-note">{{ active_watchlist.stocks|length }} stocks tracked</div>
          </div>
          <div class="strip-box">
            <div class="strip-label">Advancing</div>
            <div class="strip-value">{{ summary.up_count }}</div>
            <div class="strip-note">Rows trading above previous close</div>
          </div>
          <div class="strip-box">
            <div class="strip-label">Declining</div>
            <div class="strip-value">{{ summary.down_count }}</div>
            <div class="strip-note">Rows trading below previous close</div>
          </div>
          <div class="strip-box">
            <div class="strip-label">Last Tick</div>
            <div class="strip-value">{{ status.latest_tick }}</div>
            <div class="strip-note">Latest timestamp inside this screen</div>
          </div>
          <div class="strip-box">
            <div class="strip-label">Feed Health</div>
            <div class="strip-value">{{ status.feed_health }}</div>
            <div class="strip-note"><span class="badge {{ status.feed_badge }}">{{ status.missing_count }} missing</span></div>
          </div>
        </div>
        """,
        **context,
    )

    error_html = ""
    if context.get("error"):
        error_html = render_template_string("""<div class="error">{{ error }}</div>""", **context)

    grid_html = render_template_string(
        """
        <div class="sheet-wrap">
          <div class="sheet-header">
            <div>
              <div class="sheet-title">Live Watch Sheet</div>
              <div class="sheet-note">Tap a row to focus the selected-script panel. Prices update in place without reloading the screen.</div>
            </div>
            <div class="sheet-note">Refresh: {{ 'Off' if refresh_seconds == 0 else refresh_seconds ~ 's' }}</div>
          </div>
          <div class="desktop-sheet">
            <table>
              <thead>
                <tr>
                  <th class="sheet-symbol">Symbol</th>
                  <th class="sheet-num">LTP</th>
                  <th class="sheet-num">Chg %</th>
                  <th class="sheet-num">Bid</th>
                  <th class="sheet-num">Ask</th>
                  <th class="sheet-num">Open</th>
                  <th class="sheet-num">High</th>
                  <th class="sheet-num">Low</th>
                  <th class="sheet-num">Prev</th>
                  <th class="sheet-num">Volume</th>
                  <th class="sheet-num">VWAP</th>
                  <th class="sheet-center sheet-status">Status</th>
                </tr>
              </thead>
              <tbody>
                {% for row in rows %}
                <tr class="{{ 'active' if row.symbol == selected_symbol else '' }}" onclick="selectWatchSymbol('{{ row.symbol }}')">
                  <td>
                    <div class="symbol-main">{{ row.symbol }}</div>
                  </td>
                  <td class="sheet-num"><span class="{{ 'cell-up' if row.change_pct_numeric > 0 else 'cell-down' if row.change_pct_numeric < 0 else 'cell-neutral' }}">{{ row.last_price }}</span></td>
                  <td class="sheet-num sheet-change">{{ row.change_pct_display }}</td>
                  <td class="sheet-num">{{ row.bid_price }}</td>
                  <td class="sheet-num">{{ row.ask_price }}</td>
                  <td class="sheet-num">{{ row.open_price }}</td>
                  <td class="sheet-num">{{ row.day_high }}</td>
                  <td class="sheet-num">{{ row.day_low }}</td>
                  <td class="sheet-num">{{ row.prev_close }}</td>
                  <td class="sheet-num">{{ row.volume_display }}</td>
                  <td class="sheet-num">{{ row.vwap }}</td>
                  <td class="sheet-center sheet-status"><span class="badge {{ row.status_badge }}">{{ row.status_label }}</span></td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
          <div class="mobile-list">
            {% for row in rows %}
            <div class="mobile-card" onclick="selectWatchSymbol('{{ row.symbol }}')">
              <div class="mobile-top">
                <div>
                  <div class="mobile-symbol">{{ row.symbol }}</div>
                </div>
                <div class="{{ 'cell-up' if row.change_pct_numeric > 0 else 'cell-down' if row.change_pct_numeric < 0 else 'cell-neutral' }}">{{ row.last_price }}</div>
              </div>
              <div class="mobile-grid">
                <div class="mobile-metric"><div class="mobile-label">Chg</div><div class="mobile-value">{{ row.change_pct_display }}</div></div>
                <div class="mobile-metric"><div class="mobile-label">Bid</div><div class="mobile-value">{{ row.bid_price }}</div></div>
                <div class="mobile-metric"><div class="mobile-label">Ask</div><div class="mobile-value">{{ row.ask_price }}</div></div>
                <div class="mobile-metric"><div class="mobile-label">High</div><div class="mobile-value">{{ row.day_high }}</div></div>
                <div class="mobile-metric"><div class="mobile-label">Low</div><div class="mobile-value">{{ row.day_low }}</div></div>
                <div class="mobile-metric"><div class="mobile-label">VWAP</div><div class="mobile-value">{{ row.vwap }}</div></div>
              </div>
            </div>
            {% endfor %}
          </div>
        </div>
        """,
        **context,
    )

    detail_html = render_template_string(
        """
        <div class="detail-panel">
          {% if selected_row %}
          <div class="detail-head">
            <div class="detail-symbol">{{ selected_row.symbol }}</div>
            <div class="detail-name">{{ selected_row.security_name }}</div>
          </div>
          <div class="detail-body">
            <div class="detail-price">
              <div>
                <div class="detail-ltp">{{ selected_row.last_price }}</div>
                <div style="margin-top:6px;"><span class="{{ 'cell-up' if selected_row.change_pct_numeric > 0 else 'cell-down' if selected_row.change_pct_numeric < 0 else 'cell-neutral' }}">{{ selected_row.change_text }}</span></div>
              </div>
              <div class="badge {{ selected_row.status_badge }}">{{ selected_row.status_label }}</div>
            </div>
            <div class="detail-grid">
              <div class="detail-box"><div class="detail-label">Bid</div><div class="detail-value">{{ selected_row.bid_price }}</div></div>
              <div class="detail-box"><div class="detail-label">Ask</div><div class="detail-value">{{ selected_row.ask_price }}</div></div>
              <div class="detail-box"><div class="detail-label">Open</div><div class="detail-value">{{ selected_row.open_price }}</div></div>
              <div class="detail-box"><div class="detail-label">Prev Close</div><div class="detail-value">{{ selected_row.prev_close }}</div></div>
              <div class="detail-box"><div class="detail-label">High</div><div class="detail-value">{{ selected_row.day_high }}</div></div>
              <div class="detail-box"><div class="detail-label">Low</div><div class="detail-value">{{ selected_row.day_low }}</div></div>
              <div class="detail-box"><div class="detail-label">PDH</div><div class="detail-value">{{ selected_row.pdh }}</div></div>
              <div class="detail-box"><div class="detail-label">PDL</div><div class="detail-value">{{ selected_row.pdl }}</div></div>
              <div class="detail-box"><div class="detail-label">VWAP</div><div class="detail-value">{{ selected_row.vwap }}</div></div>
              <div class="detail-box"><div class="detail-label">Tick Time</div><div class="detail-value">{{ selected_row.tick_time }}</div></div>
              <div class="detail-box"><div class="detail-label">Volume</div><div class="detail-value">{{ selected_row.volume_display }}</div></div>
              <div class="detail-box"><div class="detail-label">Gap</div><div class="detail-value">{{ selected_row.gap_text }}</div></div>
            </div>
            <div class="detail-actions">
              <a href="/equity-ohlc?symbols={{ selected_row.symbol }}">Open OHLC</a>
              <a href="/equity-previous-levels?symbols={{ selected_row.symbol }}">Previous Levels</a>
              <a href="/equity-trade-plan?symbols={{ selected_row.symbol }}&date={{ today_date }}&start=09:15&end=09:30">Trade Plan</a>
              <a href="/scripts-watchlists?watchlist={{ active_watchlist.key }}&selected={{ selected_row.symbol }}">Watchlist Editor</a>
            </div>
          </div>
          {% else %}
          <div class="detail-head">
            <div class="detail-symbol">No Selection</div>
            <div class="detail-name">Add scripts into a watchlist first, then the live panel will show a selected stock here.</div>
          </div>
          {% endif %}
        </div>
        """,
        **context,
    )

    return {
        "top_strip_html": top_strip_html,
        "error_html": error_html,
        "grid_html": grid_html,
        "detail_html": detail_html,
    }


def get_refresh_options():
    return [
        {"value": 0, "label": "Off"},
        {"value": 15, "label": "15 seconds"},
        {"value": 30, "label": "30 seconds"},
        {"value": 60, "label": "60 seconds"},
    ]


def parse_refresh_seconds(value):
    try:
        refresh_seconds = int(value or 0)
    except (TypeError, ValueError):
        return 0

    allowed_values = {0, 15, 30, 60}
    return refresh_seconds if refresh_seconds in allowed_values else 0


def get_symbols_for_watchlist(active_watchlist, raw_symbols):
    custom_symbols = parse_symbol_list(raw_symbols)
    if custom_symbols:
        return custom_symbols
    if active_watchlist in WATCHLISTS:
        return WATCHLISTS[active_watchlist]
    return SCANNER_DEFAULT_SYMBOLS


def build_watchlist_summary(scanner_rows):
    above_count = sum(1 for row in scanner_rows if row["orb_status"] == "Above OR High")
    below_count = sum(1 for row in scanner_rows if row["orb_status"] == "Below OR Low")
    inside_count = sum(1 for row in scanner_rows if row["orb_status"] == "Inside Range")
    high_volume_count = sum(1 for row in scanner_rows if row["volume_status"].startswith("High Volume"))

    return {
        "above_count": above_count,
        "below_count": below_count,
        "inside_count": inside_count,
        "high_volume_count": high_volume_count,
    }


def build_confirmation_summary(confirmation_rows):
    long_count = sum(1 for row in confirmation_rows if row["confirmation_status"] == "Confirmed Long")
    short_count = sum(1 for row in confirmation_rows if row["confirmation_status"] == "Confirmed Short")

    return {
        "long_count": long_count,
        "short_count": short_count,
        "total_count": len(confirmation_rows),
    }


def build_previous_levels_summary(level_rows):
    above_pdh_count = sum(1 for row in level_rows if row["status_label"] == "Above PDH")
    below_pdl_count = sum(1 for row in level_rows if row["status_label"] == "Below PDL")
    near_close_count = sum(1 for row in level_rows if row["status_label"] == "Near Prev Close")
    near_pdh_count = sum(1 for row in level_rows if row["near_pdh"])
    near_pdl_count = sum(1 for row in level_rows if row["near_pdl"])
    strong_count = sum(1 for row in level_rows if row["quality_label"].startswith("Strong"))

    return {
        "above_pdh_count": above_pdh_count,
        "below_pdl_count": below_pdl_count,
        "near_close_count": near_close_count,
        "near_pdh_count": near_pdh_count,
        "near_pdl_count": near_pdl_count,
        "strong_count": strong_count,
    }


def get_previous_levels_universe_mode_options():
    return [
        {"key": "nifty50", "label": "Nifty 50"},
        {"key": "nifty_next_50", "label": "Nifty Next 50"},
        {"key": "liquid_eq", "label": "Liquid Trading Universe"},
        {"key": "common_eq", "label": "Common NSE/BSE EQ Universe"},
    ]


def get_previous_levels_signal_view_options():
    return [
        {"key": "actionable", "label": "Breakouts + Breakdowns"},
        {"key": "breakouts", "label": "Above PDH Only"},
        {"key": "breakdowns", "label": "Below PDL Only"},
        {"key": "near", "label": "Near PDH / PDL"},
        {"key": "all", "label": "All Signals"},
    ]


def get_liquid_equity_symbols():
    liquid_symbols = []
    seen = set()

    def add_symbol(symbol):
        if symbol and symbol not in seen:
            seen.add(symbol)
            liquid_symbols.append(symbol)

    for group_symbols in WATCHLISTS.values():
        for symbol in group_symbols:
            add_symbol(symbol)

    for group_symbols in SECTOR_GROUPS.values():
        for symbol in group_symbols:
            add_symbol(symbol)

    for sector_config in SECTOR_HEATMAP_GROUPS.values():
        for sub_symbols in sector_config.get("subsectors", {}).values():
            for symbol in sub_symbols:
                add_symbol(symbol)

    nse_map = get_nse_instrument_map()
    return [symbol for symbol in liquid_symbols if symbol in nse_map]


def get_auto_previous_levels_universe(universe_mode):
    nse_map = get_nse_instrument_map()
    if universe_mode == "nifty50":
        return [symbol for symbol in NIFTY_50_SYMBOLS if symbol in nse_map]
    if universe_mode == "nifty_next_50":
        return [symbol for symbol in NIFTY_NEXT_50_SYMBOLS if symbol in nse_map]
    if universe_mode == "common_eq":
        return get_common_equity_symbols()
    return get_liquid_equity_symbols()


def get_symbol_sector_lookup():
    lookup = {}
    for sector_key, sector_symbols in SECTOR_GROUPS.items():
        label = sector_key.replace("_", " ").title()
        for symbol in sector_symbols:
            lookup.setdefault(symbol, label)

    for sector_config in SECTOR_HEATMAP_GROUPS.values():
        broad_label = sector_config["label"]
        for sub_key, sub_symbols in sector_config.get("subsectors", {}).items():
            sub_label = sub_key.replace("_", " ").title()
            for symbol in sub_symbols:
                lookup.setdefault(symbol, f"{broad_label} / {sub_label}")

    return lookup


def filter_previous_level_rows(level_rows, signal_view):
    if signal_view == "breakouts":
        return [row for row in level_rows if row["status_label"] == "Above PDH"]
    if signal_view == "breakdowns":
        return [row for row in level_rows if row["status_label"] == "Below PDL"]
    if signal_view == "near":
        return [row for row in level_rows if row["near_pdh"] or row["near_pdl"]]
    if signal_view == "actionable":
        return [row for row in level_rows if row["status_label"] in {"Above PDH", "Below PDL"}]
    return level_rows


def get_sector_options():
    return [
        {"key": key, "label": key.replace("_", " ").title()}
        for key in SECTOR_GROUPS
    ]


def get_heatmap_sector_options():
    return [
        {"key": key, "label": value["label"]}
        for key, value in SECTOR_HEATMAP_GROUPS.items()
    ]


def get_heatmap_sub_sector_options(sector_key):
    sector_config = SECTOR_HEATMAP_GROUPS.get(sector_key, {})
    sub_sectors = sector_config.get("subsectors", {})
    return [
        {"key": key, "label": key.replace("_", " ").title()}
        for key in sub_sectors
    ]


def build_movers_summary(mover_rows):
    gainers_count = sum(1 for row in mover_rows if row["day_change_pct_numeric"] > 0)
    losers_count = sum(1 for row in mover_rows if row["day_change_pct_numeric"] < 0)
    gap_up_count = sum(1 for row in mover_rows if row["gap_pct_numeric"] > 0)
    gap_down_count = sum(1 for row in mover_rows if row["gap_pct_numeric"] < 0)

    return {
        "gainers_count": gainers_count,
        "losers_count": losers_count,
        "gap_up_count": gap_up_count,
        "gap_down_count": gap_down_count,
    }


def classify_percent_badge(value):
    if value > 0:
        return "badge-up"
    if value < 0:
        return "badge-down"
    return "badge-neutral"


def build_sector_note(sector_label, avg_change_pct, bullish_confirmations, bearish_confirmations, high_volume_count):
    if bullish_confirmations > bearish_confirmations and avg_change_pct > 0:
        return (
            f"{sector_label} is showing broad strength with {bullish_confirmations} bullish confirmations "
            f"and {high_volume_count} high-volume names."
        )
    if bearish_confirmations > bullish_confirmations and avg_change_pct < 0:
        return (
            f"{sector_label} is under pressure with {bearish_confirmations} bearish confirmations "
            f"and weak breadth across the basket."
        )
    return f"{sector_label} is mixed right now; sector participation is not yet one-sided."


def build_rotation_label(sector_score, bullish_confirmations, bearish_confirmations, above_vwap_count, below_vwap_count):
    if sector_score >= 4 and bullish_confirmations > bearish_confirmations and above_vwap_count >= below_vwap_count:
        return "Strong Bullish Rotation"
    if sector_score >= 1.5 and bullish_confirmations >= bearish_confirmations:
        return "Bullish Breadth"
    if sector_score <= -4 and bearish_confirmations > bullish_confirmations and below_vwap_count >= above_vwap_count:
        return "Strong Bearish Rotation"
    if sector_score <= -1.5 and bearish_confirmations >= bullish_confirmations:
        return "Bearish Breadth"
    return "Mixed Rotation"


def build_heat_class(sector_score):
    if sector_score >= 4:
        return "heat-up-strong"
    if sector_score >= 1:
        return "heat-up-soft"
    if sector_score <= -4:
        return "heat-down-strong"
    if sector_score <= -1:
        return "heat-down-soft"
    return "heat-neutral"


def build_breadth_label(above_vwap_count, below_vwap_count, high_volume_count):
    if above_vwap_count > below_vwap_count and high_volume_count >= 2:
        return "Positive Breadth"
    if below_vwap_count > above_vwap_count and high_volume_count >= 2:
        return "Negative Breadth"
    return "Balanced Breadth"


def summarize_rotation_bucket(group_key, group_label, detail_rows):
    if not detail_rows:
        return {
            "sector_key": group_key,
            "sector_label": group_label,
            "sector_score_numeric": -999,
            "sector_score_display": "N/A",
            "score_badge": "badge-info",
            "heat_class": "heat-neutral",
            "rotation_label": "Data Unavailable",
            "avg_change_pct": "0.00%",
            "avg_change_pct_numeric": 0.0,
            "avg_change_badge": "badge-neutral",
            "avg_gap_pct": "0.00%",
            "avg_gap_pct_numeric": 0.0,
            "avg_gap_badge": "badge-neutral",
            "bullish_confirmations": 0,
            "bearish_confirmations": 0,
            "above_vwap_count": 0,
            "below_vwap_count": 0,
            "high_volume_count": 0,
            "top_gainer": "-",
            "top_loser": "-",
            "ai_note": f"No usable data returned for {group_label}.",
            "breadth_label": "No Breadth",
        }

    avg_change_pct = sum(row["day_change_pct_numeric"] for row in detail_rows) / len(detail_rows)
    avg_gap_pct = sum(row["gap_pct_numeric"] for row in detail_rows) / len(detail_rows)
    bullish_confirmations = sum(
        1
        for row in detail_rows
        if row["orb_status"] == "Above OR High"
        and row["vwap_status"] == "Above VWAP"
        and row["volume_status"].startswith("High Volume")
    )
    bearish_confirmations = sum(
        1
        for row in detail_rows
        if row["orb_status"] == "Below OR Low"
        and row["vwap_status"] == "Below VWAP"
        and row["volume_status"].startswith("High Volume")
    )
    above_vwap_count = sum(1 for row in detail_rows if row["vwap_status"] == "Above VWAP")
    below_vwap_count = sum(1 for row in detail_rows if row["vwap_status"] == "Below VWAP")
    high_volume_count = sum(1 for row in detail_rows if row["volume_status"].startswith("High Volume"))
    sector_score = (
        avg_change_pct
        + avg_gap_pct * 0.5
        + (bullish_confirmations * 1.5)
        - (bearish_confirmations * 1.5)
        + (above_vwap_count * 0.35)
        - (below_vwap_count * 0.35)
    )
    top_gainer_row = max(detail_rows, key=lambda row: row["day_change_pct_numeric"])
    top_loser_row = min(detail_rows, key=lambda row: row["day_change_pct_numeric"])
    rotation_label = build_rotation_label(
        sector_score,
        bullish_confirmations,
        bearish_confirmations,
        above_vwap_count,
        below_vwap_count,
    )

    return {
        "sector_key": group_key,
        "sector_label": group_label,
        "sector_score_numeric": round(sector_score, 2),
        "sector_score_display": f"{sector_score:+.2f}",
        "score_badge": classify_percent_badge(sector_score),
        "heat_class": build_heat_class(sector_score),
        "rotation_label": rotation_label,
        "avg_change_pct": f"{avg_change_pct:+.2f}%",
        "avg_change_pct_numeric": round(avg_change_pct, 2),
        "avg_change_badge": classify_percent_badge(avg_change_pct),
        "avg_gap_pct": f"{avg_gap_pct:+.2f}%",
        "avg_gap_pct_numeric": round(avg_gap_pct, 2),
        "avg_gap_badge": classify_percent_badge(avg_gap_pct),
        "bullish_confirmations": bullish_confirmations,
        "bearish_confirmations": bearish_confirmations,
        "above_vwap_count": above_vwap_count,
        "below_vwap_count": below_vwap_count,
        "high_volume_count": high_volume_count,
        "top_gainer": f"{top_gainer_row['symbol']} ({top_gainer_row['day_change_pct']})",
        "top_loser": f"{top_loser_row['symbol']} ({top_loser_row['day_change_pct']})",
        "ai_note": build_sector_note(
            group_label,
            avg_change_pct,
            bullish_confirmations,
            bearish_confirmations,
            high_volume_count,
        ),
        "breadth_label": build_breadth_label(above_vwap_count, below_vwap_count, high_volume_count),
    }


def build_empty_mover_row(symbol, reason):
    return {
        "symbol": symbol,
        "last_price": "-",
        "last_price_numeric": -1,
        "day_change_pct": reason,
        "day_change_pct_numeric": 0,
        "day_change_badge": "badge-info",
        "gap_pct": "-",
        "gap_pct_numeric": 0,
        "gap_badge": "badge-info",
        "open_price": "-",
        "open_price_numeric": -1,
        "prev_close": "-",
        "prev_close_numeric": -1,
        "day_high": "-",
        "day_high_numeric": -1,
        "day_low": "-",
        "day_low_numeric": -1,
        "gap_status": reason,
        "gap_sort": -1,
    }


def build_signed_price(value):
    return f"{value:+.2f}"


def build_rule_based_trade_setup_insight(symbol, orb_status, breakout_gap_numeric, vwap_status, volume_status):
    if orb_status == "Above OR High" and vwap_status == "Above VWAP" and volume_status.startswith("High Volume"):
        return f"{symbol} has bullish confirmation across ORB, VWAP, and volume; watch for continuation with tight risk."
    if orb_status == "Below OR Low" and vwap_status == "Below VWAP" and volume_status.startswith("High Volume"):
        return f"{symbol} has bearish confirmation across ORB, VWAP, and volume; watch for follow-through while weakness holds."
    if orb_status == "Above OR High" and vwap_status == "Above VWAP":
        return f"{symbol} is constructive intraday, but volume confirmation is still important before chasing."
    if orb_status == "Below OR Low" and vwap_status == "Below VWAP":
        return f"{symbol} is weak intraday, but wait for cleaner volume participation before pressing shorts."
    if abs(breakout_gap_numeric) <= 0.05:
        return f"{symbol} is still near its opening range; patience is better than forcing a trade here."
    return f"{symbol} is mixed intraday; wait for clearer alignment between price, VWAP, and volume."


def get_active_kite_credentials():
    runtime = get_runtime_config()
    access_token = CURRENT_ACCESS_TOKEN or runtime["KITE_ACCESS_TOKEN"]
    return {
        "api_key": runtime["KITE_API_KEY"] or KITE_API_KEY,
        "api_secret": runtime["KITE_API_SECRET"] or KITE_API_SECRET,
        "access_token": access_token,
    }


def build_kite_client(with_access_token=True):
    creds = get_active_kite_credentials()
    client = KiteConnect(api_key=creds["api_key"])
    if with_access_token and creds["access_token"]:
        client.set_access_token(creds["access_token"])
    return client


@lru_cache(maxsize=1)
def get_nse_instrument_map():
    client = build_kite_client(with_access_token=True)
    rows = client.instruments("NSE")
    instrument_map = {}

    for row in rows:
        symbol = str(row.get("tradingsymbol") or "").upper()
        if symbol:
            instrument_map[symbol] = row

    return instrument_map


def get_equity_ohlc(symbols, selected_date, start_time, end_time):
    client = build_kite_client(with_access_token=True)
    instrument_map = get_nse_instrument_map()
    from_dt = datetime.datetime.combine(selected_date, start_time, tzinfo=APP_TZ)
    to_dt = datetime.datetime.combine(selected_date, end_time, tzinfo=APP_TZ)
    breakout_end_time = get_breakout_reference_end(selected_date, end_time)

    results = []
    missing = []

    for symbol in symbols:
        instrument = instrument_map.get(symbol)
        if not instrument:
            missing.append(symbol)
            continue

        candles = client.historical_data(
            instrument["instrument_token"],
            from_dt,
            to_dt,
            "minute",
            continuous=False,
            oi=False,
        )

        if not candles:
            results.append(
                {
                    "symbol": symbol,
                    "instrument_token": instrument["instrument_token"],
                    "summary": {
                        "open": "-",
                        "high": "-",
                        "low": "-",
                        "close": "-",
                        "candle_count": 0,
                    },
                    "breakout": {
                        "label": "No Data",
                        "badge_class": "status-neutral",
                        "last_price": "-",
                        "last_time": None,
                        "or_high": "-",
                        "or_low": "-",
                        "range_size": "-",
                        "breakout_gap": "-",
                    },
                    "candles": [],
                }
            )
            continue

        minute_rows = []
        highs = []
        lows = []

        for candle in candles:
            ts = candle["date"].astimezone(APP_TZ)
            highs.append(candle["high"])
            lows.append(candle["low"])
            minute_rows.append(
                {
                    "time": ts.strftime("%H:%M"),
                    "open": format_price(candle["open"]),
                    "high": format_price(candle["high"]),
                    "low": format_price(candle["low"]),
                    "close": format_price(candle["close"]),
                    "volume": candle.get("volume", 0),
                }
            )

        or_high = max(highs)
        or_low = min(lows)
        breakout_last_price = candles[-1]["close"]
        breakout_last_time = minute_rows[-1]["time"] if minute_rows else None

        if breakout_end_time > end_time:
            breakout_from_dt = datetime.datetime.combine(selected_date, end_time, tzinfo=APP_TZ)
            breakout_to_dt = datetime.datetime.combine(selected_date, breakout_end_time, tzinfo=APP_TZ)
            post_range_candles = client.historical_data(
                instrument["instrument_token"],
                breakout_from_dt,
                breakout_to_dt,
                "minute",
                continuous=False,
                oi=False,
            )
            if post_range_candles:
                last_candle = post_range_candles[-1]
                breakout_last_price = last_candle["close"]
                breakout_last_time = last_candle["date"].astimezone(APP_TZ).strftime("%H:%M")

        results.append(
            {
                "symbol": symbol,
                "instrument_token": instrument["instrument_token"],
                "summary": {
                    "open": format_price(candles[0]["open"]),
                    "high": format_price(or_high),
                    "low": format_price(or_low),
                    "close": format_price(candles[-1]["close"]),
                    "candle_count": len(candles),
                },
                "breakout": build_breakout_payload(or_high, or_low, breakout_last_price, breakout_last_time),
                "candles": minute_rows,
            }
        )

    return results, missing


def get_intraday_scanner_rows(symbols, selected_date, start_time, end_time, include_ai=True):
    client = build_kite_client(with_access_token=True)
    instrument_map = get_nse_instrument_map()
    from_dt = datetime.datetime.combine(selected_date, start_time, tzinfo=APP_TZ)
    range_to_dt = datetime.datetime.combine(selected_date, end_time, tzinfo=APP_TZ)
    scanner_end_time = get_breakout_reference_end(selected_date, end_time)
    scanner_to_dt = datetime.datetime.combine(selected_date, scanner_end_time, tzinfo=APP_TZ)

    scanner_rows = []
    missing = []

    for symbol in symbols:
        instrument = instrument_map.get(symbol)
        if not instrument:
            missing.append(symbol)
            scanner_rows.append(build_empty_scanner_row(symbol, "Symbol not found on NSE"))
            continue

        candles = client.historical_data(
            instrument["instrument_token"],
            from_dt,
            scanner_to_dt,
            "minute",
            continuous=False,
            oi=False,
        )

        if not candles:
            scanner_rows.append(build_empty_scanner_row(symbol, "No intraday candle data"))
            continue

        range_candles = [
            candle
            for candle in candles
            if candle["date"].astimezone(APP_TZ).time() <= end_time
        ]

        if not range_candles:
            scanner_rows.append(build_empty_scanner_row(symbol, "No opening range data"))
            continue

        or_high = max(candle["high"] for candle in range_candles)
        or_low = min(candle["low"] for candle in range_candles)
        range_size = or_high - or_low
        last_candle = candles[-1]
        last_price = last_candle["close"]
        latest_volume = last_candle.get("volume", 0) or 0

        orb_status, orb_badge, orb_sort = classify_orb_status(last_price, or_high, or_low)
        breakout_gap, breakout_gap_numeric, breakout_gap_badge = build_breakout_gap(last_price, or_high, or_low)
        vwap_value = get_vwap_value(candles)
        vwap_status, vwap_badge, vwap_sort = classify_vwap_status(last_price, vwap_value)

        prior_volumes = [candle.get("volume", 0) or 0 for candle in candles[:-1]]
        average_volume = sum(prior_volumes) / len(prior_volumes) if prior_volumes else latest_volume
        volume_status, volume_badge, volume_ratio = classify_volume_status(latest_volume, average_volume)

        ai_suggestion = build_rule_based_trade_setup_insight(
            symbol,
            orb_status,
            breakout_gap_numeric,
            vwap_status,
            volume_status,
        )
        if include_ai:
            ai_suggestion = get_trade_setup_insight(
                symbol,
                orb_status,
                breakout_gap_numeric,
                vwap_status,
                volume_status,
            )

        scanner_rows.append(
            {
                "symbol": symbol,
                "orb_status": orb_status,
                "orb_badge": orb_badge,
                "orb_sort": orb_sort,
                "last_price": format_price(last_price),
                "last_price_numeric": round(last_price, 2),
                "breakout_gap": breakout_gap,
                "breakout_gap_numeric": round(breakout_gap_numeric, 2),
                "breakout_gap_badge": breakout_gap_badge,
                "vwap_status": vwap_status,
                "vwap_badge": vwap_badge,
                "vwap_sort": vwap_sort,
                "volume_status": volume_status,
                "volume_badge": volume_badge,
                "volume_ratio_numeric": round(volume_ratio, 2),
                "or_high": format_price(or_high),
                "or_high_numeric": round(or_high, 2),
                "or_low": format_price(or_low),
                "or_low_numeric": round(or_low, 2),
                "range_size": format_price(range_size),
                "range_size_numeric": round(range_size, 2),
                "ai_suggestion": ai_suggestion,
            }
        )

    return scanner_rows, missing


def get_confirmation_rows(symbols, selected_date, start_time, end_time, include_ai=True):
    scanner_rows, missing = get_intraday_scanner_rows(
        symbols,
        selected_date,
        start_time,
        end_time,
        include_ai=include_ai,
    )
    confirmation_rows = []

    for row in scanner_rows:
        is_high_volume = row["volume_status"].startswith("High Volume")
        is_confirmed_long = (
            row["orb_status"] == "Above OR High"
            and row["vwap_status"] == "Above VWAP"
            and is_high_volume
        )
        is_confirmed_short = (
            row["orb_status"] == "Below OR Low"
            and row["vwap_status"] == "Below VWAP"
            and is_high_volume
        )

        if not (is_confirmed_long or is_confirmed_short):
            continue

        confirmation_row = dict(row)
        if is_confirmed_long:
            confirmation_row["confirmation_status"] = "Confirmed Long"
            confirmation_row["confirmation_badge"] = "badge-up"
            confirmation_row["confirmation_sort"] = 1
        else:
            confirmation_row["confirmation_status"] = "Confirmed Short"
            confirmation_row["confirmation_badge"] = "badge-down"
            confirmation_row["confirmation_sort"] = 0

        confirmation_rows.append(confirmation_row)

    return confirmation_rows, missing


def get_mover_rows(symbols):
    client = build_kite_client(with_access_token=True)
    quote_symbols = [f"NSE:{symbol}" for symbol in symbols]
    quote_data = client.quote(quote_symbols)

    mover_rows = []
    missing = []

    for symbol in symbols:
        quote_key = f"NSE:{symbol}"
        quote = quote_data.get(quote_key)
        if not quote:
            missing.append(symbol)
            mover_rows.append(build_empty_mover_row(symbol, "Quote unavailable"))
            continue

        last_price = float(quote.get("last_price") or 0)
        ohlc = quote.get("ohlc") or {}
        open_price = float(ohlc.get("open") or 0)
        prev_close = float(ohlc.get("close") or 0)
        day_high = float(ohlc.get("high") or 0)
        day_low = float(ohlc.get("low") or 0)

        day_change_pct = ((last_price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
        gap_pct = ((open_price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

        if gap_pct > 0:
            gap_status = "Gap Up"
            gap_sort = 2
        elif gap_pct < 0:
            gap_status = "Gap Down"
            gap_sort = 0
        else:
            gap_status = "Flat Open"
            gap_sort = 1

        mover_rows.append(
            {
                "symbol": symbol,
                "last_price": format_price(last_price),
                "last_price_numeric": round(last_price, 2),
                "day_change_pct": f"{day_change_pct:+.2f}%",
                "day_change_pct_numeric": round(day_change_pct, 2),
                "day_change_badge": classify_percent_badge(day_change_pct),
                "gap_pct": f"{gap_pct:+.2f}%",
                "gap_pct_numeric": round(gap_pct, 2),
                "gap_badge": classify_percent_badge(gap_pct),
                "open_price": format_price(open_price),
                "open_price_numeric": round(open_price, 2),
                "prev_close": format_price(prev_close),
                "prev_close_numeric": round(prev_close, 2),
                "day_high": format_price(day_high),
                "day_high_numeric": round(day_high, 2),
                "day_low": format_price(day_low),
                "day_low_numeric": round(day_low, 2),
                "gap_status": gap_status,
                "gap_sort": gap_sort,
            }
        )

    return mover_rows, missing


def get_sector_strength_rows(selected_date, start_time, end_time):
    sector_rows = []
    sector_detail_map = {}
    missing = {}

    for sector_key, symbols in SECTOR_GROUPS.items():
        scanner_rows, scanner_missing = get_intraday_scanner_rows(symbols, selected_date, start_time, end_time)
        mover_rows, mover_missing = get_mover_rows(symbols)
        missing[sector_key] = sorted(set(scanner_missing + mover_missing))

        mover_map = {row["symbol"]: row for row in mover_rows}
        detail_rows = []

        for scanner_row in scanner_rows:
            mover_row = mover_map.get(scanner_row["symbol"])
            if not mover_row:
                continue

            detail_row = dict(scanner_row)
            detail_row.update(
                {
                    "day_change_pct": mover_row["day_change_pct"],
                    "day_change_pct_numeric": mover_row["day_change_pct_numeric"],
                    "day_change_badge": mover_row["day_change_badge"],
                    "gap_pct": mover_row["gap_pct"],
                    "gap_pct_numeric": mover_row["gap_pct_numeric"],
                    "gap_badge": mover_row["gap_badge"],
                }
            )
            detail_rows.append(detail_row)

        sector_detail_map[sector_key] = detail_rows

        if not detail_rows:
            sector_rows.append(
                {
                    "sector_key": sector_key,
                    "sector_label": sector_key.replace("_", " ").title(),
                    "sector_score_numeric": -999,
                    "sector_score_display": "N/A",
                    "score_badge": "badge-info",
                    "avg_change_pct": "0.00%",
                    "avg_change_pct_numeric": 0.0,
                    "avg_change_badge": "badge-neutral",
                    "avg_gap_pct": "0.00%",
                    "avg_gap_pct_numeric": 0.0,
                    "avg_gap_badge": "badge-neutral",
                    "bullish_confirmations": 0,
                    "bearish_confirmations": 0,
                    "above_vwap_count": 0,
                    "below_vwap_count": 0,
                    "high_volume_count": 0,
                    "top_gainer": "-",
                    "top_loser": "-",
                    "ai_note": "No usable data returned for this sector.",
                }
            )
            continue

        avg_change_pct = sum(row["day_change_pct_numeric"] for row in detail_rows) / len(detail_rows)
        avg_gap_pct = sum(row["gap_pct_numeric"] for row in detail_rows) / len(detail_rows)
        bullish_confirmations = sum(
            1
            for row in detail_rows
            if row["orb_status"] == "Above OR High"
            and row["vwap_status"] == "Above VWAP"
            and row["volume_status"].startswith("High Volume")
        )
        bearish_confirmations = sum(
            1
            for row in detail_rows
            if row["orb_status"] == "Below OR Low"
            and row["vwap_status"] == "Below VWAP"
            and row["volume_status"].startswith("High Volume")
        )
        above_vwap_count = sum(1 for row in detail_rows if row["vwap_status"] == "Above VWAP")
        below_vwap_count = sum(1 for row in detail_rows if row["vwap_status"] == "Below VWAP")
        high_volume_count = sum(1 for row in detail_rows if row["volume_status"].startswith("High Volume"))

        sector_score = avg_change_pct + (bullish_confirmations * 1.5) - (bearish_confirmations * 1.5)
        top_gainer_row = max(detail_rows, key=lambda row: row["day_change_pct_numeric"])
        top_loser_row = min(detail_rows, key=lambda row: row["day_change_pct_numeric"])
        sector_label = sector_key.replace("_", " ").title()

        sector_rows.append(
            {
                "sector_key": sector_key,
                "sector_label": sector_label,
                "sector_score_numeric": round(sector_score, 2),
                "sector_score_display": f"{sector_score:+.2f}",
                "score_badge": classify_percent_badge(sector_score),
                "avg_change_pct": f"{avg_change_pct:+.2f}%",
                "avg_change_pct_numeric": round(avg_change_pct, 2),
                "avg_change_badge": classify_percent_badge(avg_change_pct),
                "avg_gap_pct": f"{avg_gap_pct:+.2f}%",
                "avg_gap_pct_numeric": round(avg_gap_pct, 2),
                "avg_gap_badge": classify_percent_badge(avg_gap_pct),
                "bullish_confirmations": bullish_confirmations,
                "bearish_confirmations": bearish_confirmations,
                "above_vwap_count": above_vwap_count,
                "below_vwap_count": below_vwap_count,
                "high_volume_count": high_volume_count,
                "top_gainer": f"{top_gainer_row['symbol']} ({top_gainer_row['day_change_pct']})",
                "top_loser": f"{top_loser_row['symbol']} ({top_loser_row['day_change_pct']})",
                "ai_note": build_sector_note(
                    sector_label,
                    avg_change_pct,
                    bullish_confirmations,
                    bearish_confirmations,
                    high_volume_count,
                ),
            }
        )

    sector_rows.sort(key=lambda row: row["sector_score_numeric"], reverse=True)
    return sector_rows, sector_detail_map, missing


def get_sector_heatmap_data(selected_date, start_time, end_time):
    sector_rows = []
    sub_sector_rows_map = {}
    sub_sector_detail_map = {}
    missing = {}

    for sector_key, sector_config in SECTOR_HEATMAP_GROUPS.items():
        sector_label = sector_config["label"]
        sub_sector_rows = []
        combined_detail_rows = []
        sector_missing = []

        for sub_sector_key, symbols in sector_config["subsectors"].items():
            scanner_rows, scanner_missing = get_intraday_scanner_rows(
                symbols,
                selected_date,
                start_time,
                end_time,
                include_ai=False,
            )
            mover_rows, mover_missing = get_mover_rows(symbols)
            mover_map = {row["symbol"]: row for row in mover_rows}

            detail_rows = []
            for scanner_row in scanner_rows:
                mover_row = mover_map.get(scanner_row["symbol"])
                if not mover_row:
                    continue

                detail_row = dict(scanner_row)
                detail_row.update(
                    {
                        "day_change_pct": mover_row["day_change_pct"],
                        "day_change_pct_numeric": mover_row["day_change_pct_numeric"],
                        "day_change_badge": mover_row["day_change_badge"],
                        "gap_pct": mover_row["gap_pct"],
                        "gap_pct_numeric": mover_row["gap_pct_numeric"],
                        "gap_badge": mover_row["gap_badge"],
                    }
                )
                detail_rows.append(detail_row)

            row = summarize_rotation_bucket(
                sub_sector_key,
                sub_sector_key.replace("_", " ").title(),
                detail_rows,
            )
            sub_sector_rows.append(row)
            sub_sector_detail_map[sub_sector_key] = detail_rows
            combined_detail_rows.extend(detail_rows)
            sector_missing.extend(scanner_missing + mover_missing)

        sub_sector_rows.sort(key=lambda row: row["sector_score_numeric"], reverse=True)
        sub_sector_rows_map[sector_key] = sub_sector_rows
        missing[sector_key] = sorted(set(sector_missing))

        sector_row = summarize_rotation_bucket(sector_key, sector_label, combined_detail_rows)
        sector_row["default_sub_sector"] = sub_sector_rows[0]["sector_key"] if sub_sector_rows else ""
        sector_rows.append(sector_row)

    sector_rows.sort(key=lambda row: row["sector_score_numeric"], reverse=True)
    return sector_rows, sub_sector_rows_map, sub_sector_detail_map, missing


def build_sector_heatmap_summary(sector_rows, sub_sector_rows):
    strongest_sector = sector_rows[0] if sector_rows else None
    weakest_sector = sector_rows[-1] if sector_rows else None
    strongest_sub_sector = sub_sector_rows[0] if sub_sector_rows else None

    bullish_total = sum(row["bullish_confirmations"] for row in sector_rows)
    bearish_total = sum(row["bearish_confirmations"] for row in sector_rows)

    if bullish_total > bearish_total:
        rotation_bias = "Bullish"
        rotation_note = (
            f"Market breadth leans positive with {bullish_total} bullish confirmations "
            f"versus {bearish_total} bearish confirmations."
        )
    elif bearish_total > bullish_total:
        rotation_bias = "Bearish"
        rotation_note = (
            f"Market breadth leans defensive with {bearish_total} bearish confirmations "
            f"versus {bullish_total} bullish confirmations."
        )
    else:
        rotation_bias = "Balanced"
        rotation_note = "Bullish and bearish confirmations are evenly matched across sectors."

    return {
        "strongest_sector": strongest_sector["sector_label"] if strongest_sector else "-",
        "strongest_sector_note": strongest_sector["rotation_label"] if strongest_sector else "No data",
        "weakest_sector": weakest_sector["sector_label"] if weakest_sector else "-",
        "weakest_sector_note": weakest_sector["rotation_label"] if weakest_sector else "No data",
        "strongest_sub_sector": strongest_sub_sector["sector_label"] if strongest_sub_sector else "-",
        "strongest_sub_sector_note": strongest_sub_sector["rotation_label"] if strongest_sub_sector else "No data",
        "rotation_bias": rotation_bias,
        "rotation_note": rotation_note,
    }


def build_rotation_home_summary(sector_rows, heatmap_summary, confirmation_rows, level_rows):
    bullish_sector_count = sum(1 for row in sector_rows if row["sector_score_numeric"] > 0)
    bearish_sector_count = sum(1 for row in sector_rows if row["sector_score_numeric"] < 0)
    confirmed_long_count = sum(1 for row in confirmation_rows if row["confirmation_status"] == "Confirmed Long")
    confirmed_short_count = sum(1 for row in confirmation_rows if row["confirmation_status"] == "Confirmed Short")
    high_volume_leaders = sum(1 for row in confirmation_rows if row["volume_status"].startswith("High Volume"))
    above_pdh_count = sum(1 for row in level_rows if row["status_label"] == "Above PDH")
    below_pdl_count = sum(1 for row in level_rows if row["status_label"] == "Below PDL")

    broad_above_vwap_rows = sorted(sector_rows, key=lambda row: row["above_vwap_count"], reverse=True)[:2]
    broad_above_vwap = ", ".join(row["sector_label"] for row in broad_above_vwap_rows if row["above_vwap_count"] > 0) or "None"

    if bullish_sector_count >= bearish_sector_count + 2:
        rotation_bias = "Bullish"
        confidence_label = "High" if confirmed_long_count >= max(1, confirmed_short_count + 1) else "Medium"
        focus_label = "Long Focus"
        focus_badge = "badge-up"
        focus_note = (
            f"Leadership is tilted toward {heatmap_summary['strongest_sector']} and {heatmap_summary['strongest_sub_sector']}. "
            "Favor confirmed long themes and avoid forcing mean-reversion shorts."
        )
    elif bearish_sector_count >= bullish_sector_count + 2:
        rotation_bias = "Bearish"
        confidence_label = "High" if confirmed_short_count >= max(1, confirmed_long_count + 1) else "Medium"
        focus_label = "Short Focus"
        focus_badge = "badge-down"
        focus_note = (
            f"Weakness is concentrated in {heatmap_summary['weakest_sector']}. "
            "Favor breakdowns with clean VWAP and volume confirmation."
        )
    else:
        rotation_bias = "Mixed"
        confidence_label = "Low"
        focus_label = "Selective Focus"
        focus_badge = "badge-neutral"
        focus_note = (
            "Leadership is mixed across sectors. Prioritize only the cleanest confirmed setups and avoid overtrading."
        )

    market_note = (
        f"Rotation bias is {rotation_bias.lower()} with {bullish_sector_count} bullish sectors and "
        f"{bearish_sector_count} bearish sectors. {heatmap_summary['rotation_note']}"
    )

    return {
        "rotation_bias": rotation_bias,
        "confidence_label": confidence_label,
        "bullish_sector_count": bullish_sector_count,
        "bearish_sector_count": bearish_sector_count,
        "confirmed_long_count": confirmed_long_count,
        "confirmed_short_count": confirmed_short_count,
        "above_pdh_count": above_pdh_count,
        "below_pdl_count": below_pdl_count,
        "high_volume_leaders": high_volume_leaders,
        "broad_above_vwap": broad_above_vwap,
        "focus_label": focus_label,
        "focus_badge": focus_badge,
        "focus_note": focus_note,
        "market_note": market_note,
    }


def build_market_breadth_summary(scanner_rows, mover_rows, level_rows, sector_rows):
    above_vwap_count = sum(1 for row in scanner_rows if row["vwap_status"] == "Above VWAP")
    below_vwap_count = sum(1 for row in scanner_rows if row["vwap_status"] == "Below VWAP")
    above_or_count = sum(1 for row in scanner_rows if row["orb_status"] == "Above OR High")
    below_or_count = sum(1 for row in scanner_rows if row["orb_status"] == "Below OR Low")
    above_pdh_count = sum(1 for row in level_rows if row["status_label"] == "Above PDH")
    below_pdl_count = sum(1 for row in level_rows if row["status_label"] == "Below PDL")
    gap_up_count = sum(1 for row in mover_rows if row["gap_pct_numeric"] > 0)
    gap_down_count = sum(1 for row in mover_rows if row["gap_pct_numeric"] < 0)

    if above_vwap_count >= below_vwap_count + 2 and above_or_count >= below_or_count:
        breadth_bias = "Bullish Breadth"
        bias_badge = "badge-up"
    elif below_vwap_count >= above_vwap_count + 2 and below_or_count >= above_or_count:
        breadth_bias = "Bearish Breadth"
        bias_badge = "badge-down"
    else:
        breadth_bias = "Mixed Breadth"
        bias_badge = "badge-neutral"

    best_sector_row = sector_rows[0] if sector_rows else None
    weakest_sector_row = sector_rows[-1] if sector_rows else None

    if breadth_bias == "Bullish Breadth":
        watchlist_focus_note = "Favor long setups where ORB, VWAP, and previous-day levels are aligned."
    elif breadth_bias == "Bearish Breadth":
        watchlist_focus_note = "Favor weak names losing VWAP and previous-day support rather than forcing longs."
    else:
        watchlist_focus_note = "Breadth is mixed, so focus only on the cleanest high-conviction names."

    return {
        "above_vwap_count": above_vwap_count,
        "below_vwap_count": below_vwap_count,
        "above_or_count": above_or_count,
        "below_or_count": below_or_count,
        "above_pdh_count": above_pdh_count,
        "below_pdl_count": below_pdl_count,
        "gap_up_count": gap_up_count,
        "gap_down_count": gap_down_count,
        "breadth_bias": breadth_bias,
        "bias_badge": bias_badge,
        "bias_note": (
            f"VWAP breadth is {above_vwap_count} up vs {below_vwap_count} down, while ORB breadth is "
            f"{above_or_count} bullish vs {below_or_count} bearish."
        ),
        "best_sector": best_sector_row["sector_label"] if best_sector_row else "-",
        "best_sector_note": best_sector_row["ai_note"] if best_sector_row else "No data",
        "weakest_sector": weakest_sector_row["sector_label"] if weakest_sector_row else "-",
        "weakest_sector_note": weakest_sector_row["ai_note"] if weakest_sector_row else "No data",
        "watchlist_focus_note": watchlist_focus_note,
    }


def get_backtest_direction_options():
    return [
        {"value": "both", "label": "Both"},
        {"value": "long", "label": "Long Only"},
        {"value": "short", "label": "Short Only"},
    ]


def parse_positive_float(value, fallback):
    try:
        parsed = float(value or fallback)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def parse_positive_int(value, fallback):
    try:
        parsed = int(value or fallback)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def get_backtest_preset_ranges():
    today = get_today_ist()
    return [
        {"label": "Last 5D", "from_date": (today - datetime.timedelta(days=7)).isoformat(), "to_date": today.isoformat()},
        {"label": "Last 10D", "from_date": (today - datetime.timedelta(days=14)).isoformat(), "to_date": today.isoformat()},
        {"label": "Last 20D", "from_date": (today - datetime.timedelta(days=30)).isoformat(), "to_date": today.isoformat()},
    ]


def build_backtest_presets(active_watchlist, request_symbols, start_time, end_time, direction, stop_multiple, target_multiple):
    presets = []
    for preset in get_backtest_preset_ranges():
        presets.append(
            {
                "label": preset["label"],
                "href": (
                    f"/equity-backtest?watchlist={active_watchlist}"
                    f"&symbols={request_symbols}"
                    f"&from_date={preset['from_date']}"
                    f"&to_date={preset['to_date']}"
                    f"&start={start_time}"
                    f"&end={end_time}"
                    f"&direction={direction}"
                    f"&stop_multiple={stop_multiple}"
                    f"&target_multiple={target_multiple}"
                ),
            }
        )
    return presets


def get_trade_outcome_badge(pnl_points):
    if pnl_points > 0:
        return "badge-up"
    if pnl_points < 0:
        return "badge-down"
    return "badge-neutral"


def build_backtest_summary(trade_rows):
    total_trades = len(trade_rows)
    win_count = sum(1 for row in trade_rows if row["pnl_points_numeric"] > 0)
    loss_count = sum(1 for row in trade_rows if row["pnl_points_numeric"] < 0)
    win_rate = (win_count / total_trades * 100) if total_trades else 0.0
    total_pnl = sum(row["pnl_points_numeric"] for row in trade_rows)
    avg_pnl = (total_pnl / total_trades) if total_trades else 0.0
    best_trade = max((row["pnl_points_numeric"] for row in trade_rows), default=0.0)
    worst_trade = min((row["pnl_points_numeric"] for row in trade_rows), default=0.0)

    return {
        "total_trades": total_trades,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": f"{win_rate:.1f}%",
        "total_pnl_points": f"{total_pnl:+.2f}",
        "avg_pnl_points": f"{avg_pnl:+.2f}",
        "best_trade": f"{best_trade:+.2f}",
        "worst_trade": f"{worst_trade:+.2f}",
    }


def build_trade_plan_summary(trade_plan_rows):
    long_count = sum(1 for row in trade_plan_rows if row["plan_side"] == "Long")
    short_count = sum(1 for row in trade_plan_rows if row["plan_side"] == "Short")
    wait_count = sum(1 for row in trade_plan_rows if row["plan_side"] == "Wait")
    high_conviction_count = sum(1 for row in trade_plan_rows if row["conviction"] == "High")
    return {
        "long_count": long_count,
        "short_count": short_count,
        "wait_count": wait_count,
        "high_conviction_count": high_conviction_count,
    }


def get_refresh_options_with_fast():
    return [
        {"value": 0, "label": "Off"},
        {"value": 15, "label": "15 seconds"},
        {"value": 30, "label": "30 seconds"},
        {"value": 60, "label": "60 seconds"},
    ]


def get_brokerage_charge(turnover):
    return turnover * (600 / 10000000)


def estimate_cash_arbitrage_charges(buy_turnover, sell_turnover):
    total_turnover = buy_turnover + sell_turnover
    brokerage = get_brokerage_charge(total_turnover)
    exchange_txn = total_turnover * 0.0000325
    sebi_charges = total_turnover * 0.000001
    gst = (brokerage + exchange_txn) * 0.18
    stamp_duty = buy_turnover * 0.00015
    stt = sell_turnover * 0.00025
    total_charges = brokerage + exchange_txn + sebi_charges + gst + stamp_duty + stt
    return {
        "brokerage": brokerage,
        "exchange_txn": exchange_txn,
        "sebi_charges": sebi_charges,
        "gst": gst,
        "stamp_duty": stamp_duty,
        "stt": stt,
        "total_charges": total_charges,
    }


@lru_cache(maxsize=1)
def get_bse_instrument_map():
    client = build_kite_client(with_access_token=True)
    rows = client.instruments("BSE")
    instrument_map = {}

    for row in rows:
        symbol = str(row.get("tradingsymbol") or "").upper()
        if symbol:
            instrument_map[symbol] = row

    return instrument_map


@lru_cache(maxsize=1)
def get_common_equity_symbols():
    return get_common_equity_universe_details()["symbols"]


@lru_cache(maxsize=1)
def get_common_equity_universe_details():
    master = load_symbol_master()
    nse_map = get_nse_instrument_map()
    bse_map = get_bse_instrument_map()
    common_symbols = []
    rejected = {
        "missing_on_exchange": 0,
        "series_mismatch": 0,
        "identity_mismatch": 0,
    }

    for symbol, row in master["by_symbol"].items():
        if row.get("series") != "EQ":
            rejected["series_mismatch"] += 1
            continue

        nse_row = nse_map.get(symbol)
        bse_row = bse_map.get(symbol)
        if not nse_row or not bse_row:
            rejected["missing_on_exchange"] += 1
            continue

        if not is_valid_common_cash_equity(symbol, row, nse_row, bse_row):
            master_name = normalize_lookup_value(row.get("security"))
            nse_name = normalize_lookup_value(nse_row.get("name") or nse_row.get("tradingsymbol"))
            bse_name = normalize_lookup_value(bse_row.get("name") or bse_row.get("tradingsymbol"))
            if "sme" in master_name.split() or "sme" in nse_name.split() or "sme" in bse_name.split():
                rejected["series_mismatch"] += 1
            else:
                rejected["identity_mismatch"] += 1
            continue

        common_symbols.append(symbol)

    return {
        "symbols": sorted(common_symbols),
        "rejected": rejected,
    }


def is_valid_common_cash_equity(symbol, master_row, nse_row, bse_row):
    if str(master_row.get("series") or "").upper() != "EQ":
        return False

    if str(nse_row.get("exchange") or "").upper() != "NSE":
        return False
    if str(bse_row.get("exchange") or "").upper() != "BSE":
        return False

    if str(nse_row.get("tradingsymbol") or "").upper() != symbol:
        return False
    if str(bse_row.get("tradingsymbol") or "").upper() != symbol:
        return False

    nse_type = str(nse_row.get("instrument_type") or "").strip().upper()
    bse_type = str(bse_row.get("instrument_type") or "").strip().upper()
    allowed_types = {"", "EQ", "EQUITY"}
    if nse_type not in allowed_types or bse_type not in allowed_types:
        return False

    nse_name = normalize_lookup_value(nse_row.get("name") or "")
    bse_name = normalize_lookup_value(bse_row.get("name") or "")
    master_name = normalize_lookup_value(master_row.get("security") or "")

    if "sme" in master_name.split() or "sme" in nse_name.split() or "sme" in bse_name.split():
        return False

    if nse_name and bse_name and nse_name != bse_name:
        return False

    if master_name:
        if nse_name and master_name != nse_name:
            return False
        if bse_name and master_name != bse_name:
            return False

    return True


def get_depth_price(quote, side, field):
    depth = (quote or {}).get("depth") or {}
    rows = depth.get(side) or []
    if not rows:
        return None
    value = rows[0].get(field)
    return float(value) if value not in (None, "") else None


def get_depth_timestamp(quote):
    timestamp = quote.get("timestamp") or quote.get("last_trade_time")
    if hasattr(timestamp, "astimezone"):
        return timestamp.astimezone(APP_TZ).strftime("%H:%M:%S")
    return str(timestamp or "-")


def get_quote_timestamp_dt(quote):
    timestamp = quote.get("timestamp") or quote.get("last_trade_time")
    if hasattr(timestamp, "astimezone"):
        return timestamp.astimezone(APP_TZ)
    return None


def fetch_quote_map(client, quote_symbols, chunk_size=250):
    quote_data = {}
    for index in range(0, len(quote_symbols), chunk_size):
        batch = quote_symbols[index:index + chunk_size]
        if not batch:
            continue
        quote_data.update(client.quote(batch))
    return quote_data


def build_arbitrage_summary(arbitrage_rows):
    opportunity_count = len(arbitrage_rows)
    total_net_profit_numeric = sum(row["net_profit_numeric"] for row in arbitrage_rows)
    best_net_profit_numeric = max((row["net_profit_numeric"] for row in arbitrage_rows), default=0.0)
    depth_limited_count = sum(1 for row in arbitrage_rows if row["liquidity_warning"] != "Depth supported")
    return {
        "opportunity_count": opportunity_count,
        "best_net_profit": f"{best_net_profit_numeric:+.2f}",
        "total_net_profit": f"{total_net_profit_numeric:+.2f}",
        "depth_limited_count": depth_limited_count,
    }


def load_arbitrage_history():
    if not ARBITRAGE_HISTORY_PATH.exists():
        return {"days": {}}

    try:
        payload = json.loads(ARBITRAGE_HISTORY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"days": {}}

    if not isinstance(payload, dict):
        return {"days": {}}
    if not isinstance(payload.get("days"), dict):
        payload["days"] = {}
    return payload


def prune_arbitrage_history_payload(payload, reference_date):
    cutoff_date = reference_date - datetime.timedelta(days=ARBITRAGE_HISTORY_RETENTION_DAYS - 1)
    pruned_days = {}

    for day_key, day_rows in (payload.get("days") or {}).items():
        try:
            row_date = datetime.date.fromisoformat(day_key)
        except ValueError:
            continue

        if row_date < cutoff_date or row_date > reference_date:
            continue
        if isinstance(day_rows, dict):
            pruned_days[day_key] = day_rows

    payload["days"] = pruned_days
    return payload


def save_arbitrage_history(payload):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARBITRAGE_HISTORY_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_arbitrage_virtual_state():
    if not ARBITRAGE_VIRTUAL_STATE_PATH.exists():
        return {"days": {}}

    try:
        payload = json.loads(ARBITRAGE_VIRTUAL_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"days": {}}

    if not isinstance(payload, dict):
        return {"days": {}}
    if not isinstance(payload.get("days"), dict):
        payload["days"] = {}
    return payload


def save_arbitrage_virtual_state(payload):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARBITRAGE_VIRTUAL_STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def prune_arbitrage_virtual_state(payload, reference_date):
    cutoff_date = reference_date - datetime.timedelta(days=6)
    pruned_days = {}

    for day_key, day_state in (payload.get("days") or {}).items():
        try:
            row_date = datetime.date.fromisoformat(day_key)
        except ValueError:
            continue

        if row_date < cutoff_date or row_date > reference_date:
            continue
        if isinstance(day_state, dict):
            pruned_days[day_key] = day_state

    payload["days"] = pruned_days
    return payload


def ensure_virtual_day_state(payload, reference_date):
    payload = prune_arbitrage_virtual_state(payload, reference_date)
    day_key = reference_date.isoformat()
    day_state = payload["days"].setdefault(
        day_key,
        {
            "tracked": {},
            "virtual_trades": [],
            "prepared_count": 0,
            "paused": False,
            "pause_reason": "",
        },
    )
    day_state.setdefault("tracked", {})
    day_state.setdefault("virtual_trades", [])
    day_state.setdefault("prepared_count", 0)
    day_state.setdefault("paused", False)
    day_state.setdefault("pause_reason", "")
    return payload, day_key, day_state


def build_arbitrage_row_key(row):
    return f"{row['symbol']}:{row['buy_exchange']}:{row['sell_exchange']}"


def evaluate_arbitrage_broker_health(error, missing_count, symbol_count, now_dt):
    stop_time = now_dt.replace(
        hour=ARBITRAGE_RULES["stop_hour"],
        minute=ARBITRAGE_RULES["stop_minute"],
        second=0,
        microsecond=0,
    )
    if now_dt >= stop_time:
        return False, "Trading prep stops after 3:00 PM."
    if error:
        return False, "Broker data is unstable right now because the latest scan raised an error."
    if symbol_count > 0 and missing_count > max(15, int(symbol_count * 0.35)):
        return False, "Broker data is unstable right now because too many quotes were missing in the latest scan."
    return True, "Broker data is stable."


def update_arbitrage_virtual_candidates(day_state, arbitrage_rows, now_dt, broker_stable):
    tracked = day_state.get("tracked", {})
    active_keys = set()

    for row in arbitrage_rows:
        if row["quantity"] < ARBITRAGE_RULES["min_depth_quantity"]:
            continue
        if row["net_profit_numeric"] < ARBITRAGE_RULES["min_net_profit"]:
            continue

        key = build_arbitrage_row_key(row)
        active_keys.add(key)
        existing = tracked.get(key, {})
        first_seen_iso = existing.get("first_seen")
        if first_seen_iso:
            try:
                first_seen_dt = datetime.datetime.fromisoformat(first_seen_iso)
            except ValueError:
                first_seen_dt = now_dt
        else:
            first_seen_dt = now_dt

        cooldown_until_iso = existing.get("cooldown_until")
        cooldown_until_dt = None
        if cooldown_until_iso:
            try:
                cooldown_until_dt = datetime.datetime.fromisoformat(cooldown_until_iso)
            except ValueError:
                cooldown_until_dt = None

        tracked[key] = {
            "symbol": row["symbol"],
            "buy_exchange": row["buy_exchange"],
            "sell_exchange": row["sell_exchange"],
            "first_seen": first_seen_dt.isoformat(),
            "last_seen": now_dt.isoformat(),
            "cooldown_until": cooldown_until_dt.isoformat() if cooldown_until_dt else "",
            "quantity": row["quantity"],
            "gross_spread_numeric": row["gross_spread_numeric"],
            "net_profit_numeric": row["net_profit_numeric"],
            "gross_spread": row["gross_spread"],
            "net_profit": row["net_profit"],
            "gross_profit": row["gross_profit"],
            "total_charges": row["total_charges"],
            "liquidity_warning": row["liquidity_warning"],
            "timestamp": row["timestamp"],
            "buy_price": row["nse_ask"] if row["buy_exchange"] == "NSE" else row["bse_ask"],
            "sell_price": row["bse_bid"] if row["sell_exchange"] == "BSE" else row["nse_bid"],
            "route": f"{row['buy_exchange']} buy -> {row['sell_exchange']} sell",
        }

    for key, existing in tracked.items():
        if key not in active_keys:
            existing["active"] = False
        else:
            existing["active"] = True

    day_state["tracked"] = tracked
    stop_trading = day_state.get("prepared_count", 0) >= ARBITRAGE_RULES["max_trades_per_day"]
    ready_rows = []

    for key, item in tracked.items():
        if not item.get("active"):
            continue
        first_seen_dt = datetime.datetime.fromisoformat(item["first_seen"])
        persisted_seconds = max(0, int((now_dt - first_seen_dt).total_seconds()))
        if persisted_seconds < ARBITRAGE_RULES["persistence_seconds"]:
            continue

        cooldown_until = item.get("cooldown_until")
        if cooldown_until:
            cooldown_until_dt = datetime.datetime.fromisoformat(cooldown_until)
            if now_dt < cooldown_until_dt:
                continue

        if not broker_stable or stop_trading:
            continue

        ready_rows.append(
            {
                "setup_key": key,
                "symbol": item["symbol"],
                "route": item["route"],
                "quantity": item["quantity"],
                "gross_spread": item["gross_spread"],
                "gross_profit": item["gross_profit"],
                "total_charges": item["total_charges"],
                "net_profit": item["net_profit"],
                "net_profit_numeric": item["net_profit_numeric"],
                "liquidity_warning": item["liquidity_warning"],
                "timestamp": item["timestamp"],
                "buy_price": item["buy_price"],
                "sell_price": item["sell_price"],
                "persisted_seconds": persisted_seconds,
                "ready_badge": classify_percent_badge(item["net_profit_numeric"]),
            }
        )

    ready_rows.sort(key=lambda row: row["net_profit_numeric"], reverse=True)
    return ready_rows[:ARBITRAGE_RULES["max_ready_setups"]]


def create_virtual_trade(day_state, setup_key, now_dt):
    tracked = day_state.get("tracked", {})
    item = tracked.get(setup_key)
    if not item:
        return "This setup is no longer available."

    trade_id = f"VT-{now_dt.strftime('%H%M%S')}-{item['symbol']}"
    day_state["virtual_trades"].append(
        {
            "trade_id": trade_id,
            "symbol": item["symbol"],
            "route": item["route"],
            "buy_price": item["buy_price"],
            "sell_price": item["sell_price"],
            "quantity": item["quantity"],
            "gross_spread": item["gross_spread"],
            "gross_profit": item["gross_profit"],
            "total_charges": item["total_charges"],
            "net_profit": item["net_profit"],
            "net_profit_numeric": item["net_profit_numeric"],
            "liquidity_warning": item["liquidity_warning"],
            "prepared_at": now_dt.strftime("%H:%M:%S"),
            "status": "Prepared",
            "status_badge": "badge-up",
        }
    )
    day_state["prepared_count"] = int(day_state.get("prepared_count", 0)) + 1
    cooldown_until = now_dt + datetime.timedelta(seconds=ARBITRAGE_RULES["cooldown_seconds"])
    tracked[setup_key]["cooldown_until"] = cooldown_until.isoformat()
    return f"Virtual trade prepared for {item['symbol']}."


def dismiss_virtual_setup(day_state, setup_key, now_dt):
    tracked = day_state.get("tracked", {})
    item = tracked.get(setup_key)
    if not item:
        return "This setup is no longer available."
    cooldown_until = now_dt + datetime.timedelta(seconds=ARBITRAGE_RULES["cooldown_seconds"])
    tracked[setup_key]["cooldown_until"] = cooldown_until.isoformat()
    return f"{item['symbol']} was snoozed for {ARBITRAGE_RULES['cooldown_seconds']} seconds."


def archive_virtual_trade(day_state, trade_id, now_dt):
    for trade in day_state.get("virtual_trades", []):
        if trade["trade_id"] == trade_id and trade["status"] == "Prepared":
            trade["status"] = "Closed"
            trade["status_badge"] = "badge-neutral"
            trade["closed_at"] = now_dt.strftime("%H:%M:%S")
            return f"Virtual trade {trade_id} archived."
    return "Virtual trade not found."


def build_virtual_trade_book(day_state):
    virtual_trades = day_state.get("virtual_trades", [])
    open_trades = [trade for trade in virtual_trades if trade["status"] == "Prepared"]
    closed_trades = [trade for trade in virtual_trades if trade["status"] != "Prepared"]
    total_net_numeric = sum(trade["net_profit_numeric"] for trade in virtual_trades)
    return {
        "open_trades": list(reversed(open_trades[-10:])),
        "closed_trades": list(reversed(closed_trades[-10:])),
        "prepared_count": int(day_state.get("prepared_count", 0)),
        "remaining_trades": max(0, ARBITRAGE_RULES["max_trades_per_day"] - int(day_state.get("prepared_count", 0))),
        "total_virtual_net": f"{total_net_numeric:+.2f}",
        "total_virtual_count": len(virtual_trades),
    }


def load_arbitrage_live_state():
    if not ARBITRAGE_LIVE_STATE_PATH.exists():
        return {"days": {}}

    try:
        payload = json.loads(ARBITRAGE_LIVE_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"days": {}}

    if not isinstance(payload, dict):
        return {"days": {}}
    if not isinstance(payload.get("days"), dict):
        payload["days"] = {}
    return payload


def save_arbitrage_live_state(payload):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARBITRAGE_LIVE_STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def prune_arbitrage_live_state(payload, reference_date):
    cutoff_date = reference_date - datetime.timedelta(days=6)
    pruned_days = {}

    for day_key, day_state in (payload.get("days") or {}).items():
        try:
            row_date = datetime.date.fromisoformat(day_key)
        except ValueError:
            continue

        if row_date < cutoff_date or row_date > reference_date:
            continue
        if isinstance(day_state, dict):
            pruned_days[day_key] = day_state

    payload["days"] = pruned_days
    return payload


def ensure_live_day_state(payload, reference_date):
    payload = prune_arbitrage_live_state(payload, reference_date)
    day_key = reference_date.isoformat()
    day_state = payload["days"].setdefault(
        day_key,
        {
            "tracked": {},
            "launched_trades": [],
            "launched_count": 0,
            "paused": False,
            "pause_reason": "",
        },
    )
    day_state.setdefault("tracked", {})
    day_state.setdefault("launched_trades", [])
    day_state.setdefault("launched_count", 0)
    day_state.setdefault("paused", False)
    day_state.setdefault("pause_reason", "")
    return payload, day_key, day_state


def build_arbitrage_runtime_rules(max_trades_per_day):
    runtime_rules = dict(ARBITRAGE_RULES)
    runtime_rules["max_trades_per_day"] = max(1, int(max_trades_per_day))
    return runtime_rules


def update_arbitrage_live_candidates(day_state, arbitrage_rows, now_dt, broker_stable, live_rules):
    tracked = day_state.get("tracked", {})
    active_keys = set()

    for row in arbitrage_rows:
        if row["quantity"] < live_rules["min_depth_quantity"]:
            continue
        if row["net_profit_numeric"] < live_rules["min_net_profit"]:
            continue

        key = build_arbitrage_row_key(row)
        active_keys.add(key)
        existing = tracked.get(key, {})
        first_seen_iso = existing.get("first_seen")
        if first_seen_iso:
            try:
                first_seen_dt = datetime.datetime.fromisoformat(first_seen_iso)
            except ValueError:
                first_seen_dt = now_dt
        else:
            first_seen_dt = now_dt

        cooldown_until_iso = existing.get("cooldown_until")
        cooldown_until_dt = None
        if cooldown_until_iso:
            try:
                cooldown_until_dt = datetime.datetime.fromisoformat(cooldown_until_iso)
            except ValueError:
                cooldown_until_dt = None

        tracked[key] = {
            "symbol": row["symbol"],
            "buy_exchange": row["buy_exchange"],
            "sell_exchange": row["sell_exchange"],
            "first_seen": first_seen_dt.isoformat(),
            "last_seen": now_dt.isoformat(),
            "cooldown_until": cooldown_until_dt.isoformat() if cooldown_until_dt else "",
            "quantity": row["quantity"],
            "gross_spread_numeric": row["gross_spread_numeric"],
            "net_profit_numeric": row["net_profit_numeric"],
            "gross_spread": row["gross_spread"],
            "net_profit": row["net_profit"],
            "gross_profit": row["gross_profit"],
            "total_charges": row["total_charges"],
            "liquidity_warning": row["liquidity_warning"],
            "timestamp": row["timestamp"],
            "buy_price": row["nse_ask"] if row["buy_exchange"] == "NSE" else row["bse_ask"],
            "sell_price": row["bse_bid"] if row["sell_exchange"] == "BSE" else row["nse_bid"],
            "route": f"{row['buy_exchange']} buy -> {row['sell_exchange']} sell",
        }

    for key, existing in tracked.items():
        existing["active"] = key in active_keys

    day_state["tracked"] = tracked
    stop_trading = day_state.get("launched_count", 0) >= live_rules["max_trades_per_day"]
    ready_rows = []

    for key, item in tracked.items():
        if not item.get("active"):
            continue

        first_seen_dt = datetime.datetime.fromisoformat(item["first_seen"])
        persisted_seconds = max(0, int((now_dt - first_seen_dt).total_seconds()))
        if persisted_seconds < live_rules["persistence_seconds"]:
            continue

        cooldown_until = item.get("cooldown_until")
        if cooldown_until:
            cooldown_until_dt = datetime.datetime.fromisoformat(cooldown_until)
            if now_dt < cooldown_until_dt:
                continue

        if not broker_stable or stop_trading:
            continue

        ready_rows.append(
            {
                "setup_key": key,
                "symbol": item["symbol"],
                "route": item["route"],
                "quantity": item["quantity"],
                "gross_spread": item["gross_spread"],
                "gross_profit": item["gross_profit"],
                "total_charges": item["total_charges"],
                "net_profit": item["net_profit"],
                "net_profit_numeric": item["net_profit_numeric"],
                "liquidity_warning": item["liquidity_warning"],
                "timestamp": item["timestamp"],
                "buy_price": item["buy_price"],
                "sell_price": item["sell_price"],
                "buy_exchange": item["buy_exchange"],
                "sell_exchange": item["sell_exchange"],
                "persisted_seconds": persisted_seconds,
                "ready_badge": classify_percent_badge(item["net_profit_numeric"]),
            }
        )

    ready_rows.sort(key=lambda row: row["net_profit_numeric"], reverse=True)
    return ready_rows[:live_rules["max_ready_setups"]]


def create_live_trade(day_state, setup_key, now_dt, live_rules):
    tracked = day_state.get("tracked", {})
    item = tracked.get(setup_key)
    if not item:
        return False, "This setup is no longer available."
    if int(day_state.get("launched_count", 0)) >= live_rules["max_trades_per_day"]:
        return False, "The live trading limit for today has already been reached."

    trade_id = f"LT-{now_dt.strftime('%H%M%S')}-{item['symbol']}"
    day_state["launched_trades"].append(
        {
            "trade_id": trade_id,
            "symbol": item["symbol"],
            "route": item["route"],
            "buy_exchange": item["buy_exchange"],
            "sell_exchange": item["sell_exchange"],
            "buy_price": item["buy_price"],
            "sell_price": item["sell_price"],
            "quantity": item["quantity"],
            "gross_spread": item["gross_spread"],
            "gross_profit": item["gross_profit"],
            "total_charges": item["total_charges"],
            "net_profit": item["net_profit"],
            "net_profit_numeric": item["net_profit_numeric"],
            "liquidity_warning": item["liquidity_warning"],
            "launched_at": now_dt.strftime("%H:%M:%S"),
            "status": "Launched",
            "status_badge": "badge-up",
        }
    )
    day_state["launched_count"] = int(day_state.get("launched_count", 0)) + 1
    cooldown_until = now_dt + datetime.timedelta(seconds=live_rules["cooldown_seconds"])
    tracked[setup_key]["cooldown_until"] = cooldown_until.isoformat()
    return True, f"Arbitrage pair opened for {item['symbol']}."


def dismiss_live_setup(day_state, setup_key, now_dt, live_rules):
    tracked = day_state.get("tracked", {})
    item = tracked.get(setup_key)
    if not item:
        return False, "This setup is no longer available."
    cooldown_until = now_dt + datetime.timedelta(seconds=live_rules["cooldown_seconds"])
    tracked[setup_key]["cooldown_until"] = cooldown_until.isoformat()
    return True, f"{item['symbol']} was snoozed for {live_rules['cooldown_seconds']} seconds."


def close_live_trade(day_state, trade_id, now_dt):
    for trade in day_state.get("launched_trades", []):
        if trade["trade_id"] == trade_id and trade["status"] == "Launched":
            trade["status"] = "Closed"
            trade["status_badge"] = "badge-neutral"
            trade["closed_at"] = now_dt.strftime("%H:%M:%S")
            return True, f"Trade {trade_id} marked closed."
    return False, "Live trade not found."


def build_live_trade_book(day_state, live_rules):
    launched_trades = day_state.get("launched_trades", [])
    open_trades = [trade for trade in launched_trades if trade["status"] == "Launched"]
    closed_trades = [trade for trade in launched_trades if trade["status"] != "Launched"]
    total_net_numeric = sum(trade["net_profit_numeric"] for trade in launched_trades)
    return {
        "open_trades": list(reversed(open_trades[-10:])),
        "closed_trades": list(reversed(closed_trades[-10:])),
        "launched_count": int(day_state.get("launched_count", 0)),
        "remaining_trades": max(0, live_rules["max_trades_per_day"] - int(day_state.get("launched_count", 0))),
        "total_live_net": f"{total_net_numeric:+.2f}",
        "total_live_count": len(launched_trades),
    }


def build_kite_basket_payload(setup, product="CNC", order_type="LIMIT"):
    buy_price = float(setup["buy_price"])
    sell_price = float(setup["sell_price"])
    quantity = int(setup["quantity"])
    tag_base = f"ARB{setup['symbol']}"[:20]
    payload = [
        {
            "variety": "regular",
            "tradingsymbol": setup["symbol"],
            "exchange": setup["buy_exchange"],
            "transaction_type": "BUY",
            "order_type": order_type,
            "product": product,
            "price": buy_price,
            "quantity": quantity,
            "validity": "DAY",
            "readonly": True,
            "tag": f"{tag_base}B"[:20],
        },
        {
            "variety": "regular",
            "tradingsymbol": setup["symbol"],
            "exchange": setup["sell_exchange"],
            "transaction_type": "SELL",
            "order_type": order_type,
            "product": product,
            "price": sell_price,
            "quantity": quantity,
            "validity": "DAY",
            "readonly": True,
            "tag": f"{tag_base}S"[:20],
        },
    ]
    return json.dumps(payload, separators=(",", ":"))


def prepare_live_ready_setups(ready_setups, product="CNC", order_type="LIMIT"):
    prepared_rows = []
    for index, setup in enumerate(ready_setups, start=1):
        form_key = "".join(ch.lower() if ch.isalnum() else "-" for ch in setup["setup_key"])
        row = dict(setup)
        row["basket_payload"] = build_kite_basket_payload(setup, product=product, order_type=order_type)
        row["form_id"] = f"arb-live-form-{index}-{form_key}"
        row["rank_label"] = f"Ready {index}"
        prepared_rows.append(row)
    return prepared_rows


def build_arbitrage_rejection_summary(scan_meta):
    universe_meta = get_common_equity_universe_details()
    rejected_universe = universe_meta.get("rejected", {})
    return {
        "accepted": int(scan_meta.get("accepted", 0)),
        "rejected_not_common_eq": int(scan_meta.get("rejected_not_common_eq", 0)),
        "rejected_missing_depth": int(scan_meta.get("rejected_missing_depth", 0)),
        "rejected_stale_quotes": int(scan_meta.get("rejected_stale_quotes", 0)),
        "rejected_spread": int(scan_meta.get("rejected_spread", 0)),
        "rejected_depth": int(scan_meta.get("rejected_depth", 0)),
        "rejected_net_profit": int(scan_meta.get("rejected_net_profit", 0)),
        "universe_missing_on_exchange": int(rejected_universe.get("missing_on_exchange", 0)),
        "universe_series_mismatch": int(rejected_universe.get("series_mismatch", 0)),
        "universe_identity_mismatch": int(rejected_universe.get("identity_mismatch", 0)),
    }


def update_arbitrage_history(arbitrage_rows, reference_date):
    payload = prune_arbitrage_history_payload(load_arbitrage_history(), reference_date)
    day_key = reference_date.isoformat()
    day_rows = payload["days"].setdefault(day_key, {})

    for row in arbitrage_rows:
        record_key = f"{row['symbol']}:{row['buy_exchange']}:{row['sell_exchange']}"
        existing = day_rows.get(record_key)
        if not existing:
            existing = {
                "symbol": row["symbol"],
                "buy_exchange": row["buy_exchange"],
                "sell_exchange": row["sell_exchange"],
                "first_seen": row["timestamp"],
                "last_seen": row["timestamp"],
                "detection_count": 0,
                "max_gross_spread_numeric": row["gross_spread_numeric"],
                "max_net_profit_numeric": row["net_profit_numeric"],
                "latest_liquidity_warning": row["liquidity_warning"],
            }

        existing["detection_count"] = int(existing.get("detection_count", 0)) + 1
        existing["first_seen"] = min(str(existing.get("first_seen") or row["timestamp"]), row["timestamp"])
        existing["last_seen"] = max(str(existing.get("last_seen") or row["timestamp"]), row["timestamp"])
        existing["max_gross_spread_numeric"] = max(float(existing.get("max_gross_spread_numeric", 0.0)), row["gross_spread_numeric"])
        existing["max_net_profit_numeric"] = max(float(existing.get("max_net_profit_numeric", 0.0)), row["net_profit_numeric"])
        existing["latest_liquidity_warning"] = row["liquidity_warning"]
        day_rows[record_key] = existing

    save_arbitrage_history(payload)
    return payload


def build_arbitrage_post_analysis(reference_date):
    payload = prune_arbitrage_history_payload(load_arbitrage_history(), reference_date)
    save_arbitrage_history(payload)
    day_groups = []

    for day_key in sorted(payload["days"].keys(), reverse=True):
        day_rows = list((payload["days"].get(day_key) or {}).values())
        if not day_rows:
            continue

        day_rows.sort(key=lambda row: row.get("max_net_profit_numeric", 0.0), reverse=True)
        top_row = day_rows[0]
        summary_note = (
            f"{len(day_rows)} symbols flashed net-positive spreads. "
            f"Best was {top_row['symbol']} at about {top_row['max_net_profit_numeric']:+.2f} net."
        )

        stories = []
        for row in day_rows:
            if row["latest_liquidity_warning"] == "Depth supported":
                note = "Tradable depth held up cleanly when the spread appeared."
            elif row["latest_liquidity_warning"] == "Depth limited":
                note = "The spread appeared, but executable size was capped by displayed depth."
            else:
                note = "The spread appeared with thin depth, so execution needed extra care."

            stories.append(
                {
                    "symbol": row["symbol"],
                    "route": f"{row['buy_exchange']} buy -> {row['sell_exchange']} sell",
                    "max_gross_spread": f"{row['max_gross_spread_numeric']:+.2f}",
                    "max_net_profit": f"{row['max_net_profit_numeric']:+.2f}",
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                    "detection_count": row["detection_count"],
                    "liquidity_warning": row["latest_liquidity_warning"],
                    "story_note": note,
                    "story_badge": classify_percent_badge(row["max_net_profit_numeric"]),
                }
            )

        day_groups.append(
            {
                "day_label": day_key,
                "summary_note": summary_note,
                "stories": stories,
            }
        )

    return day_groups


def build_arbitrage_recurring_summary(post_analysis_groups):
    recurring = {}
    for group in post_analysis_groups:
        for story in group["stories"]:
            existing = recurring.get(story["symbol"])
            if not existing:
                existing = {
                    "symbol": story["symbol"],
                    "appearances": 0,
                    "best_net_profit_numeric": float(story["max_net_profit"]),
                    "latest_route": story["route"],
                    "latest_liquidity_warning": story["liquidity_warning"],
                }

            existing["appearances"] += 1
            existing["best_net_profit_numeric"] = max(existing["best_net_profit_numeric"], float(story["max_net_profit"]))
            existing["latest_route"] = story["route"]
            existing["latest_liquidity_warning"] = story["liquidity_warning"]
            recurring[story["symbol"]] = existing

    recurring_rows = sorted(
        recurring.values(),
        key=lambda row: (row["appearances"], row["best_net_profit_numeric"]),
        reverse=True,
    )

    return [
        {
            "symbol": row["symbol"],
            "appearances": row["appearances"],
            "best_net_profit": f"{row['best_net_profit_numeric']:+.2f}",
            "latest_route": row["latest_route"],
            "latest_liquidity_warning": row["latest_liquidity_warning"],
            "badge_class": classify_percent_badge(row["best_net_profit_numeric"]),
        }
        for row in recurring_rows[:6]
    ]


def build_best_arbitrage_spotlight(arbitrage_rows):
    if not arbitrage_rows:
        return None

    row = arbitrage_rows[0]
    if row["liquidity_warning"] == "Depth supported":
        note = "This is the cleanest live setup right now because displayed depth is supporting the capital-based size."
    elif row["liquidity_warning"] == "Depth limited":
        note = "This is the best live spread, but the visible size is capped by depth, so execution may need smaller size."
    else:
        note = "This is the best live spread, but thin depth means the opportunity may disappear very quickly."

    return {
        "symbol": row["symbol"],
        "route": f"{row['buy_exchange']} buy -> {row['sell_exchange']} sell",
        "net_profit": row["net_profit"],
        "gross_spread": row["gross_spread"],
        "quantity": row["quantity"],
        "liquidity_warning": row["liquidity_warning"],
        "timestamp": row["timestamp"],
        "badge_class": row["net_badge"],
        "note": note,
    }


def get_cash_arbitrage_rows(symbols, capital_amount, min_spread, net_positive_only):
    common_symbols = set(get_common_equity_symbols())
    eligible_symbols = [symbol for symbol in symbols if symbol in common_symbols]

    client = build_kite_client(with_access_token=True)
    quote_symbols = [*[f"NSE:{symbol}" for symbol in eligible_symbols], *[f"BSE:{symbol}" for symbol in eligible_symbols]]
    quote_data = fetch_quote_map(client, quote_symbols)

    arbitrage_rows = []
    missing = []
    scan_meta = {
        "requested_symbols": len(symbols),
        "eligible_common_eq": len(eligible_symbols),
        "rejected_not_common_eq": max(0, len(symbols) - len(eligible_symbols)),
        "rejected_missing_depth": 0,
        "rejected_stale_quotes": 0,
        "rejected_spread": 0,
        "rejected_depth": 0,
        "rejected_net_profit": 0,
        "accepted": 0,
    }
    stale_cutoff_seconds = 20
    now_dt = datetime.datetime.now(APP_TZ)

    for symbol in eligible_symbols:
        nse_quote = quote_data.get(f"NSE:{symbol}")
        bse_quote = quote_data.get(f"BSE:{symbol}")
        if not nse_quote or not bse_quote:
            missing.append(symbol)
            scan_meta["rejected_missing_depth"] += 1
            continue

        nse_ask = get_depth_price(nse_quote, "sell", "price")
        nse_bid = get_depth_price(nse_quote, "buy", "price")
        bse_ask = get_depth_price(bse_quote, "sell", "price")
        bse_bid = get_depth_price(bse_quote, "buy", "price")
        nse_ask_qty = get_depth_price(nse_quote, "sell", "quantity")
        nse_bid_qty = get_depth_price(nse_quote, "buy", "quantity")
        bse_ask_qty = get_depth_price(bse_quote, "sell", "quantity")
        bse_bid_qty = get_depth_price(bse_quote, "buy", "quantity")

        if None in {nse_ask, nse_bid, bse_ask, bse_bid, nse_ask_qty, nse_bid_qty, bse_ask_qty, bse_bid_qty}:
            missing.append(symbol)
            scan_meta["rejected_missing_depth"] += 1
            continue

        nse_ts_dt = get_quote_timestamp_dt(nse_quote)
        bse_ts_dt = get_quote_timestamp_dt(bse_quote)
        if not nse_ts_dt or not bse_ts_dt:
            scan_meta["rejected_stale_quotes"] += 1
            continue
        if (now_dt - nse_ts_dt).total_seconds() > stale_cutoff_seconds or (now_dt - bse_ts_dt).total_seconds() > stale_cutoff_seconds:
            scan_meta["rejected_stale_quotes"] += 1
            continue

        if nse_ask < bse_bid:
            buy_exchange = "NSE"
            sell_exchange = "BSE"
            buy_price = nse_ask
            sell_price = bse_bid
            buy_qty_depth = int(nse_ask_qty)
            sell_qty_depth = int(bse_bid_qty)
        elif bse_ask < nse_bid:
            buy_exchange = "BSE"
            sell_exchange = "NSE"
            buy_price = bse_ask
            sell_price = nse_bid
            buy_qty_depth = int(bse_ask_qty)
            sell_qty_depth = int(nse_bid_qty)
        else:
            continue

        gross_spread_numeric = sell_price - buy_price
        if gross_spread_numeric < min_spread:
            scan_meta["rejected_spread"] += 1
            continue

        capital_qty = math.floor(capital_amount / buy_price) if buy_price > 0 else 0
        tradable_qty = max(0, min(capital_qty, buy_qty_depth, sell_qty_depth))
        if tradable_qty <= 0:
            scan_meta["rejected_depth"] += 1
            continue

        gross_profit_numeric = gross_spread_numeric * tradable_qty
        charges = estimate_cash_arbitrage_charges(buy_price * tradable_qty, sell_price * tradable_qty)
        net_profit_numeric = gross_profit_numeric - charges["total_charges"]
        if net_positive_only and net_profit_numeric <= 0:
            scan_meta["rejected_net_profit"] += 1
            continue

        if tradable_qty < capital_qty:
            liquidity_warning = "Depth limited"
        elif tradable_qty <= 10:
            liquidity_warning = "Thin depth"
        else:
            liquidity_warning = "Depth supported"

        spread_pct_numeric = (gross_spread_numeric / buy_price * 100) if buy_price > 0 else 0.0
        timestamp = max(get_depth_timestamp(nse_quote), get_depth_timestamp(bse_quote))

        arbitrage_rows.append(
            {
                "symbol": symbol,
                "nse_ask": format_price(nse_ask),
                "nse_bid": format_price(nse_bid),
                "bse_ask": format_price(bse_ask),
                "bse_bid": format_price(bse_bid),
                "buy_exchange": buy_exchange,
                "buy_badge": "badge-info",
                "sell_exchange": sell_exchange,
                "sell_badge": "badge-up",
                "gross_spread": f"{gross_spread_numeric:+.2f}",
                "gross_spread_numeric": round(gross_spread_numeric, 2),
                "gross_badge": classify_percent_badge(gross_spread_numeric),
                "spread_pct": f"{spread_pct_numeric:+.2f}%",
                "spread_pct_numeric": round(spread_pct_numeric, 2),
                "spread_pct_badge": classify_percent_badge(spread_pct_numeric),
                "quantity": tradable_qty,
                "gross_profit": f"{gross_profit_numeric:+.2f}",
                "gross_profit_numeric": round(gross_profit_numeric, 2),
                "gross_total_badge": classify_percent_badge(gross_profit_numeric),
                "total_charges": f"{charges['total_charges']:.2f}",
                "total_charges_numeric": round(charges["total_charges"], 2),
                "net_profit": f"{net_profit_numeric:+.2f}",
                "net_profit_numeric": round(net_profit_numeric, 2),
                "net_badge": classify_percent_badge(net_profit_numeric),
                "liquidity_warning": liquidity_warning,
                "timestamp": timestamp,
            }
        )
        scan_meta["accepted"] += 1

    arbitrage_rows.sort(key=lambda row: row["net_profit_numeric"], reverse=True)
    skipped = [symbol for symbol in symbols if symbol not in common_symbols]
    missing.extend(skipped)
    return arbitrage_rows, sorted(set(missing)), scan_meta


def get_trade_plan_rows(symbols, selected_date, start_time, end_time, risk_multiple, target_one_multiple, target_two_multiple):
    scanner_rows, scanner_missing = get_intraday_scanner_rows(
        symbols,
        selected_date,
        start_time,
        end_time,
        include_ai=False,
    )
    mover_rows, mover_missing = get_mover_rows(symbols)
    level_rows, level_missing = get_previous_day_level_rows(symbols, selected_date)
    mover_map = {row["symbol"]: row for row in mover_rows}
    level_map = {row["symbol"]: row for row in level_rows}

    trade_plan_rows = []
    for scanner_row in scanner_rows:
        mover_row = mover_map.get(scanner_row["symbol"])
        level_row = level_map.get(scanner_row["symbol"])
        if not mover_row or not level_row:
            continue

        range_size_numeric = scanner_row["range_size_numeric"]
        if range_size_numeric <= 0:
            continue

        orb_status = scanner_row["orb_status"]
        vwap_status = scanner_row["vwap_status"]
        status_label = level_row["status_label"]
        volume_status = scanner_row["volume_status"]

        if orb_status == "Above OR High" and vwap_status == "Above VWAP":
            plan_side = "Long"
            plan_label = "Long Plan"
            plan_badge = "badge-up"
            entry_price_numeric = scanner_row["or_high_numeric"]
            stop_price_numeric = entry_price_numeric - (range_size_numeric * risk_multiple)
            target_one_price_numeric = entry_price_numeric + (range_size_numeric * target_one_multiple)
            target_two_price_numeric = entry_price_numeric + (range_size_numeric * target_two_multiple)
            conviction = "High" if volume_status.startswith("High Volume") or status_label == "Above PDH" else "Medium"
            plan_note = (
                f"{scanner_row['symbol']} has bullish ORB and VWAP alignment. Use the OR high as the trigger and manage risk below the range."
            )
        elif orb_status == "Below OR Low" and vwap_status == "Below VWAP":
            plan_side = "Short"
            plan_label = "Short Plan"
            plan_badge = "badge-down"
            entry_price_numeric = scanner_row["or_low_numeric"]
            stop_price_numeric = entry_price_numeric + (range_size_numeric * risk_multiple)
            target_one_price_numeric = entry_price_numeric - (range_size_numeric * target_one_multiple)
            target_two_price_numeric = entry_price_numeric - (range_size_numeric * target_two_multiple)
            conviction = "High" if volume_status.startswith("High Volume") or status_label == "Below PDL" else "Medium"
            plan_note = (
                f"{scanner_row['symbol']} has bearish ORB and VWAP alignment. Use the OR low as the trigger and protect above the range."
            )
        else:
            plan_side = "Wait"
            plan_label = "Wait / Mixed"
            plan_badge = "badge-neutral"
            entry_price_numeric = scanner_row["last_price_numeric"]
            stop_price_numeric = scanner_row["last_price_numeric"] - (range_size_numeric * risk_multiple)
            target_one_price_numeric = scanner_row["last_price_numeric"] + (range_size_numeric * target_one_multiple)
            target_two_price_numeric = scanner_row["last_price_numeric"] + (range_size_numeric * target_two_multiple)
            conviction = "Low"
            plan_note = (
                f"{scanner_row['symbol']} is not fully aligned yet. Wait for cleaner ORB plus VWAP confirmation before planning a full-size trade."
            )

        trade_plan_rows.append(
            {
                "symbol": scanner_row["symbol"],
                "plan_side": plan_side,
                "plan_label": plan_label,
                "plan_badge": plan_badge,
                "conviction": conviction,
                "orb_status": orb_status,
                "orb_badge": scanner_row["orb_badge"],
                "vwap_status": vwap_status,
                "vwap_badge": scanner_row["vwap_badge"],
                "volume_status": volume_status,
                "volume_badge": scanner_row["volume_badge"],
                "status_label": status_label,
                "status_badge": level_row["status_badge"],
                "entry_price": format_price(entry_price_numeric),
                "entry_price_numeric": round(entry_price_numeric, 2),
                "stop_price": format_price(stop_price_numeric),
                "stop_price_numeric": round(stop_price_numeric, 2),
                "target_one_price": format_price(target_one_price_numeric),
                "target_one_price_numeric": round(target_one_price_numeric, 2),
                "target_two_price": format_price(target_two_price_numeric),
                "target_two_price_numeric": round(target_two_price_numeric, 2),
                "range_size": scanner_row["range_size"],
                "range_size_numeric": scanner_row["range_size_numeric"],
                "gap_pct": mover_row["gap_pct"],
                "gap_badge": mover_row["gap_badge"],
                "plan_note": plan_note,
            }
        )

    sort_priority = {"Long": 0, "Short": 1, "Wait": 2}
    trade_plan_rows.sort(key=lambda row: (sort_priority[row["plan_side"]], -row["range_size_numeric"], row["symbol"]))
    missing = sorted(set(scanner_missing + mover_missing + level_missing))
    return trade_plan_rows, missing


def get_previous_day_level_rows(symbols, selected_date):
    client = build_kite_client(with_access_token=True)
    instrument_map = get_nse_instrument_map()
    quote_symbols = [f"NSE:{symbol}" for symbol in symbols]
    quote_data = fetch_quote_map(client, quote_symbols)
    sector_lookup = get_symbol_sector_lookup()

    level_rows = []
    missing = []

    for symbol in symbols:
        instrument = instrument_map.get(symbol)
        quote = quote_data.get(f"NSE:{symbol}")

        if not instrument or not quote:
            missing.append(symbol)
            continue

        from_dt = datetime.datetime.combine(selected_date - datetime.timedelta(days=10), datetime.time(0, 0), tzinfo=APP_TZ)
        to_dt = datetime.datetime.combine(selected_date, datetime.time(0, 0), tzinfo=APP_TZ)
        daily_candles = client.historical_data(
            instrument["instrument_token"],
            from_dt,
            to_dt,
            "day",
            continuous=False,
            oi=False,
        )

        previous_candles = [
            candle
            for candle in daily_candles
            if candle["date"].astimezone(APP_TZ).date() < selected_date
        ]

        if not previous_candles:
            missing.append(symbol)
            continue

        prev_day = previous_candles[-1]
        pdh = float(prev_day["high"])
        pdl = float(prev_day["low"])
        prev_close = float(prev_day["close"])
        last_price = float(quote.get("last_price") or 0)
        open_price = float((quote.get("ohlc") or {}).get("open") or 0)

        distance_pdh = last_price - pdh
        distance_pdl = last_price - pdl
        distance_close = last_price - prev_close
        gap_pct = ((open_price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
        near_band = max(prev_close * 0.005, 0.20)
        near_pdh = abs(distance_pdh) <= near_band
        near_pdl = abs(distance_pdl) <= near_band

        if last_price > pdh:
            status_label = "Above PDH"
            status_sort = 4
            status_badge = "badge-up"
        elif last_price < pdl:
            status_label = "Below PDL"
            status_sort = 0
            status_badge = "badge-down"
        else:
            close_band = max(prev_close * 0.003, 0.10)
            if abs(distance_close) <= close_band:
                status_label = "Near Prev Close"
                status_sort = 1
                status_badge = "badge-info"
            else:
                status_label = "Inside Prev Range"
                status_sort = 2
                status_badge = "badge-neutral"

        if status_label == "Above PDH":
            if gap_pct > 0 and distance_pdh > near_band:
                quality_label = "Strong Bullish Breakout"
                quality_badge = "badge-up"
                breakout_rank = 5
            else:
                quality_label = "Bullish Breakout"
                quality_badge = "badge-info"
                breakout_rank = 4
            bias_note = "Continuation long bias while price holds above PDH."
        elif status_label == "Below PDL":
            if gap_pct < 0 and abs(distance_pdl) > near_band:
                quality_label = "Strong Bearish Breakdown"
                quality_badge = "badge-down"
                breakout_rank = 0
            else:
                quality_label = "Bearish Breakdown"
                quality_badge = "badge-info"
                breakout_rank = 1
            bias_note = "Continuation short bias while price holds below PDL."
        elif near_pdh:
            quality_label = "Near PDH"
            quality_badge = "badge-info"
            breakout_rank = 3
            bias_note = "Watch for a clean breakout through PDH."
        elif near_pdl:
            quality_label = "Near PDL"
            quality_badge = "badge-info"
            breakout_rank = 2
            bias_note = "Watch for a clean breakdown through PDL."
        else:
            quality_label = "Inside Previous Range"
            quality_badge = "badge-neutral"
            breakout_rank = 1
            bias_note = "No decisive previous-day level break yet."

        level_rows.append(
            {
                "symbol": symbol,
                "sector_label": sector_lookup.get(symbol, "General"),
                "status_label": status_label,
                "status_sort": status_sort,
                "status_badge": status_badge,
                "quality_label": quality_label,
                "quality_badge": quality_badge,
                "breakout_rank": breakout_rank,
                "bias_note": bias_note,
                "near_pdh": near_pdh,
                "near_pdl": near_pdl,
                "last_price": format_price(last_price),
                "last_price_numeric": round(last_price, 2),
                "pdh": format_price(pdh),
                "pdh_numeric": round(pdh, 2),
                "pdl": format_price(pdl),
                "pdl_numeric": round(pdl, 2),
                "prev_close": format_price(prev_close),
                "prev_close_numeric": round(prev_close, 2),
                "distance_pdh": build_signed_price(distance_pdh),
                "distance_pdh_numeric": round(distance_pdh, 2),
                "distance_pdh_badge": classify_percent_badge(distance_pdh),
                "distance_pdl": build_signed_price(distance_pdl),
                "distance_pdl_numeric": round(distance_pdl, 2),
                "distance_pdl_badge": classify_percent_badge(distance_pdl),
                "distance_close": build_signed_price(distance_close),
                "distance_close_numeric": round(distance_close, 2),
                "distance_close_badge": classify_percent_badge(distance_close),
                "gap_pct": f"{gap_pct:+.2f}%",
                "gap_pct_numeric": round(gap_pct, 2),
                "gap_badge": classify_percent_badge(gap_pct),
            }
        )

    level_rows.sort(
        key=lambda row: (
            row["breakout_rank"],
            -abs(row["distance_pdh_numeric"]) if row["status_label"] == "Above PDH" else abs(row["distance_pdl_numeric"]),
            row["symbol"],
        ),
        reverse=True,
    )
    return level_rows, missing


def get_orb_backtest_rows(symbols, from_date, to_date, start_time, end_time, direction, stop_multiple, target_multiple):
    client = build_kite_client(with_access_token=True)
    instrument_map = get_nse_instrument_map()
    trade_rows = []
    missing = []

    if (to_date - from_date).days > 45:
        raise ValueError("Please keep the backtest range to 45 days or less for stable performance.")

    day_cursor = from_date
    while day_cursor <= to_date:
        if day_cursor.weekday() >= 5:
            day_cursor += datetime.timedelta(days=1)
            continue

        session_start = datetime.datetime.combine(day_cursor, start_time, tzinfo=APP_TZ)
        session_end = datetime.datetime.combine(day_cursor, datetime.time(15, 30), tzinfo=APP_TZ)

        for symbol in symbols:
            instrument = instrument_map.get(symbol)
            if not instrument:
                if symbol not in missing:
                    missing.append(symbol)
                continue

            candles = client.historical_data(
                instrument["instrument_token"],
                session_start,
                session_end,
                "minute",
                continuous=False,
                oi=False,
            )

            if not candles:
                continue

            range_candles = [
                candle
                for candle in candles
                if candle["date"].astimezone(APP_TZ).time() <= end_time
            ]
            post_candles = [
                candle
                for candle in candles
                if candle["date"].astimezone(APP_TZ).time() > end_time
            ]

            if not range_candles or not post_candles:
                continue

            or_high = max(candle["high"] for candle in range_candles)
            or_low = min(candle["low"] for candle in range_candles)
            range_size = or_high - or_low
            if range_size <= 0:
                continue

            trade = None
            for candle in post_candles:
                breakout_long = direction in {"both", "long"} and candle["high"] >= or_high
                breakout_short = direction in {"both", "short"} and candle["low"] <= or_low

                if breakout_long and breakout_short:
                    continue

                if breakout_long:
                    trade = {
                        "side": "Long",
                        "entry_price_numeric": or_high,
                        "entry_time": candle["date"].astimezone(APP_TZ).strftime("%H:%M"),
                        "stop_price_numeric": or_high - (range_size * stop_multiple),
                        "target_price_numeric": or_high + (range_size * target_multiple),
                        "remaining_candles": post_candles[post_candles.index(candle):],
                    }
                    break

                if breakout_short:
                    trade = {
                        "side": "Short",
                        "entry_price_numeric": or_low,
                        "entry_time": candle["date"].astimezone(APP_TZ).strftime("%H:%M"),
                        "stop_price_numeric": or_low + (range_size * stop_multiple),
                        "target_price_numeric": or_low - (range_size * target_multiple),
                        "remaining_candles": post_candles[post_candles.index(candle):],
                    }
                    break

            if not trade:
                continue

            exit_price = None
            exit_time = None
            exit_reason = "EOD Exit"

            for candle in trade["remaining_candles"]:
                candle_time = candle["date"].astimezone(APP_TZ).strftime("%H:%M")
                if trade["side"] == "Long":
                    hit_stop = candle["low"] <= trade["stop_price_numeric"]
                    hit_target = candle["high"] >= trade["target_price_numeric"]
                    if hit_stop and hit_target:
                        exit_price = trade["stop_price_numeric"]
                        exit_time = candle_time
                        exit_reason = "Stop hit first on overlap candle"
                        break
                    if hit_stop:
                        exit_price = trade["stop_price_numeric"]
                        exit_time = candle_time
                        exit_reason = "Stop Hit"
                        break
                    if hit_target:
                        exit_price = trade["target_price_numeric"]
                        exit_time = candle_time
                        exit_reason = "Target Hit"
                        break
                else:
                    hit_stop = candle["high"] >= trade["stop_price_numeric"]
                    hit_target = candle["low"] <= trade["target_price_numeric"]
                    if hit_stop and hit_target:
                        exit_price = trade["stop_price_numeric"]
                        exit_time = candle_time
                        exit_reason = "Stop hit first on overlap candle"
                        break
                    if hit_stop:
                        exit_price = trade["stop_price_numeric"]
                        exit_time = candle_time
                        exit_reason = "Stop Hit"
                        break
                    if hit_target:
                        exit_price = trade["target_price_numeric"]
                        exit_time = candle_time
                        exit_reason = "Target Hit"
                        break

            if exit_price is None:
                last_candle = candles[-1]
                exit_price = last_candle["close"]
                exit_time = last_candle["date"].astimezone(APP_TZ).strftime("%H:%M")

            if trade["side"] == "Long":
                pnl_points = exit_price - trade["entry_price_numeric"]
                outcome = "Win" if pnl_points > 0 else "Loss" if pnl_points < 0 else "Flat"
                side_badge = "badge-up"
            else:
                pnl_points = trade["entry_price_numeric"] - exit_price
                outcome = "Win" if pnl_points > 0 else "Loss" if pnl_points < 0 else "Flat"
                side_badge = "badge-down"

            trade_rows.append(
                {
                    "symbol": symbol,
                    "trade_date": day_cursor.isoformat(),
                    "side": trade["side"],
                    "side_badge": side_badge,
                    "entry_time": trade["entry_time"],
                    "entry_price": format_price(trade["entry_price_numeric"]),
                    "entry_price_numeric": round(trade["entry_price_numeric"], 2),
                    "stop_price": format_price(trade["stop_price_numeric"]),
                    "stop_price_numeric": round(trade["stop_price_numeric"], 2),
                    "target_price": format_price(trade["target_price_numeric"]),
                    "target_price_numeric": round(trade["target_price_numeric"], 2),
                    "exit_time": exit_time,
                    "exit_price": format_price(exit_price),
                    "exit_price_numeric": round(exit_price, 2),
                    "outcome": outcome,
                    "outcome_badge": get_trade_outcome_badge(pnl_points),
                    "pnl_points": f"{pnl_points:+.2f}",
                    "pnl_points_numeric": round(pnl_points, 2),
                    "pnl_badge": get_trade_outcome_badge(pnl_points),
                    "range_size": format_price(range_size),
                    "range_size_numeric": round(range_size, 2),
                    "exit_reason": exit_reason,
                }
            )

        day_cursor += datetime.timedelta(days=1)

    trade_rows.sort(key=lambda row: (row["trade_date"], row["symbol"], row["entry_time"]))
    return trade_rows, missing


app = Flask(__name__)


@app.route("/")
def home():
    return redirect("/equity-ohlc")


@app.route("/login")
def login():
    login_kite = build_kite_client(with_access_token=False)
    return redirect(login_kite.login_url())


@app.route("/callback")
def callback():
    global CURRENT_ACCESS_TOKEN

    request_token = request.args.get("request_token")
    if not request_token:
        return {"error": "request_token is missing"}, 400

    creds = get_active_kite_credentials()
    callback_kite = build_kite_client(with_access_token=False)
    data = callback_kite.generate_session(request_token, api_secret=creds["api_secret"])
    access_token = data["access_token"]
    CURRENT_ACCESS_TOKEN = access_token

    env_path = Path(ENV_PATH)
    if not env_path.exists():
        return {"error": f".env file not found at {env_path}"}, 500

    with open(env_path, "r", encoding="utf-8") as file:
        lines = file.readlines()

    with open(env_path, "w", encoding="utf-8") as file:
        for line in lines:
            if line.startswith("KITE_ACCESS_TOKEN"):
                file.write(f"KITE_ACCESS_TOKEN={access_token}\n")
            else:
                file.write(line)

    get_nse_instrument_map.cache_clear()
    return "<h2>Login Successful</h2><p>Token auto updated.</p>"


@app.route("/ltp")
def ltp():
    if not is_market_open():
        return {"status": "Market Closed"}

    client = build_kite_client(with_access_token=True)
    data = client.ltp("NSE:INFY")

    return {"status": "Market Open", "data": data}


@app.route("/equity-ohlc")
def equity_ohlc():
    raw_symbols = request.args.get("symbols", ",".join(DEFAULT_SYMBOLS))
    raw_date = request.args.get("date", get_today_ist().isoformat())
    raw_start = request.args.get("start", DEFAULT_START)
    raw_end = request.args.get("end", DEFAULT_END)

    error = None
    results = []

    try:
        symbols = parse_symbol_list(raw_symbols)
        selected_date = parse_date(raw_date)
        start_time = parse_time(raw_start, DEFAULT_START)
        end_time = parse_time(raw_end, DEFAULT_END)

        if not symbols:
            raise ValueError("Please provide at least one NSE symbol.")
        creds = get_active_kite_credentials()
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("Kite API key or access token is missing in .env.")
        if end_time <= start_time:
            raise ValueError("End time must be after start time.")

        results, missing = get_equity_ohlc(symbols, selected_date, start_time, end_time)
        if missing:
            missing_text = ", ".join(missing)
            error = f"Could not find NSE equity symbols: {missing_text}"
    except Exception as exc:
        symbols = parse_symbol_list(raw_symbols) or DEFAULT_SYMBOLS
        selected_date = raw_date
        start_time = raw_start
        end_time = raw_end
        error = str(exc)

    return render_template_string(
        PAGE_TEMPLATE,
        results=results,
        error=error,
        symbols=symbols,
        request_symbols=raw_symbols,
        selected_date=selected_date if isinstance(selected_date, str) else selected_date.isoformat(),
        today_date=get_today_ist().isoformat(),
        yesterday_date=get_yesterday_ist().isoformat(),
        start_time=start_time if isinstance(start_time, str) else start_time.strftime("%H:%M"),
        end_time=end_time if isinstance(end_time, str) else end_time.strftime("%H:%M"),
    )


@app.route("/equity-scanner")
def equity_scanner():
    raw_symbols = request.args.get("symbols", ",".join(SCANNER_DEFAULT_SYMBOLS))
    raw_date = request.args.get("date", get_today_ist().isoformat())
    raw_start = request.args.get("start", DEFAULT_START)
    raw_end = request.args.get("end", DEFAULT_END)

    error = None
    scanner_rows = []

    try:
        symbols = parse_symbol_list(raw_symbols)
        selected_date = parse_date(raw_date)
        start_time = parse_time(raw_start, DEFAULT_START)
        end_time = parse_time(raw_end, DEFAULT_END)

        if not symbols:
            raise ValueError("Please provide at least one NSE symbol.")
        creds = get_active_kite_credentials()
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("Kite API key or access token is missing in .env.")
        if end_time <= start_time:
            raise ValueError("End time must be after start time.")

        scanner_rows, missing = get_intraday_scanner_rows(symbols, selected_date, start_time, end_time)
        if missing:
            missing_text = ", ".join(missing)
            error = f"Could not find NSE equity symbols: {missing_text}"
    except Exception as exc:
        symbols = parse_symbol_list(raw_symbols) or SCANNER_DEFAULT_SYMBOLS
        selected_date = raw_date
        start_time = raw_start
        end_time = raw_end
        error = str(exc)

    return render_template_string(
        SCANNER_TEMPLATE,
        scanner_rows=scanner_rows,
        error=error,
        symbols=symbols,
        request_symbols=raw_symbols,
        selected_date=selected_date if isinstance(selected_date, str) else selected_date.isoformat(),
        today_date=get_today_ist().isoformat(),
        yesterday_date=get_yesterday_ist().isoformat(),
        start_time=start_time if isinstance(start_time, str) else start_time.strftime("%H:%M"),
        end_time=end_time if isinstance(end_time, str) else end_time.strftime("%H:%M"),
    )


@app.route("/equity-watchlists")
def equity_watchlists():
    active_watchlist = request.args.get("watchlist", "my_intraday")
    raw_symbols = request.args.get("symbols", "")
    raw_date = request.args.get("date", get_today_ist().isoformat())
    raw_start = request.args.get("start", DEFAULT_START)
    raw_end = request.args.get("end", DEFAULT_END)
    refresh_seconds = parse_refresh_seconds(request.args.get("refresh", "30"))

    error = None
    scanner_rows = []

    try:
        symbols = get_symbols_for_watchlist(active_watchlist, raw_symbols)
        selected_date = parse_date(raw_date)
        start_time = parse_time(raw_start, DEFAULT_START)
        end_time = parse_time(raw_end, DEFAULT_END)

        if not symbols:
            raise ValueError("Please provide at least one NSE symbol.")
        creds = get_active_kite_credentials()
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("Kite API key or access token is missing in .env.")
        if end_time <= start_time:
            raise ValueError("End time must be after start time.")

        scanner_rows, missing = get_intraday_scanner_rows(symbols, selected_date, start_time, end_time)
        if missing:
            missing_text = ", ".join(missing)
            error = f"Could not find NSE equity symbols: {missing_text}"
    except Exception as exc:
        symbols = get_symbols_for_watchlist(active_watchlist, raw_symbols) or SCANNER_DEFAULT_SYMBOLS
        selected_date = raw_date
        start_time = raw_start
        end_time = raw_end
        error = str(exc)

    active_watchlist_label = active_watchlist.replace("_", " ").title()
    refresh_label = "Off" if refresh_seconds == 0 else f"{refresh_seconds}s"

    return render_template_string(
        WATCHLIST_TEMPLATE,
        scanner_rows=scanner_rows,
        summary=build_watchlist_summary(scanner_rows),
        error=error,
        symbols=symbols,
        request_symbols=",".join(symbols) if not raw_symbols else raw_symbols,
        selected_date=selected_date if isinstance(selected_date, str) else selected_date.isoformat(),
        today_date=get_today_ist().isoformat(),
        yesterday_date=get_yesterday_ist().isoformat(),
        start_time=start_time if isinstance(start_time, str) else start_time.strftime("%H:%M"),
        end_time=end_time if isinstance(end_time, str) else end_time.strftime("%H:%M"),
        watchlists=get_watchlist_options(),
        active_watchlist=active_watchlist,
        active_watchlist_label=active_watchlist_label,
        refresh_options=get_refresh_options(),
        refresh_seconds=refresh_seconds,
        refresh_label=refresh_label,
    )


@app.route("/scripts-watchlists", methods=["GET", "POST"])
def equity_watchlist_desk():
    state = load_manual_watchlists_state()
    refresh_seconds = parse_refresh_seconds(request.values.get("refresh", "60"))
    active_watchlist_key = request.values.get("watchlist", "watchlist_1")
    selected_symbol = request.values.get("selected") or request.values.get("selected_symbol") or ""
    error = None
    success_message = None

    active_watchlist = get_manual_watchlist(state, active_watchlist_key)
    active_watchlist_key = active_watchlist["key"]

    if request.method == "POST":
        action = request.form.get("action", "")
        symbol = request.form.get("symbol", "").strip()
        add_symbol_value = request.form.get("add_symbol", "").strip()
        target_watchlist = get_manual_watchlist(state, request.form.get("watchlist", active_watchlist_key))
        active_watchlist = target_watchlist
        active_watchlist_key = active_watchlist["key"]

        if action == "rename_watchlist":
            new_name = str(request.form.get("watchlist_name", "")).strip()
            if not new_name:
                error = "Watchlist name cannot be empty."
            else:
                active_watchlist["name"] = new_name[:24]
                state = save_manual_watchlists_state(state)
                success_message = f"Watchlist renamed to {active_watchlist['name']}."
        elif action == "add_stock":
            resolved_symbols = parse_symbol_list(add_symbol_value)
            if not resolved_symbols:
                error = "Could not resolve that stock. Try a valid symbol or company name."
            elif len(active_watchlist.get("stocks") or []) >= MANUAL_WATCHLIST_STOCK_LIMIT:
                error = f"{active_watchlist['name']} already has the maximum of {MANUAL_WATCHLIST_STOCK_LIMIT} stocks."
            else:
                resolved_symbol = resolved_symbols[0]
                if get_manual_watchlist_stock_entry(active_watchlist, resolved_symbol):
                    error = f"{resolved_symbol} is already in {active_watchlist['name']}."
                else:
                    active_watchlist.setdefault("stocks", []).append(
                        {"symbol": resolved_symbol, "note_text": "", "alert_rule": "none"}
                    )
                    state = save_manual_watchlists_state(state)
                    selected_symbol = resolved_symbol
                    success_message = f"{resolved_symbol} added to {active_watchlist['name']}."
        elif action in {"move_up", "move_down", "remove_stock"}:
            stocks = active_watchlist.get("stocks") or []
            index = next((idx for idx, stock in enumerate(stocks) if stock.get("symbol") == symbol), -1)
            if index == -1:
                error = "That stock is no longer in this watchlist."
            elif action == "move_up":
                if index > 0:
                    stocks[index - 1], stocks[index] = stocks[index], stocks[index - 1]
                    state = save_manual_watchlists_state(state)
                    success_message = f"{symbol} moved up."
                selected_symbol = symbol
            elif action == "move_down":
                if index < len(stocks) - 1:
                    stocks[index + 1], stocks[index] = stocks[index], stocks[index + 1]
                    state = save_manual_watchlists_state(state)
                    success_message = f"{symbol} moved down."
                selected_symbol = symbol
            else:
                del stocks[index]
                state = save_manual_watchlists_state(state)
                selected_symbol = stocks[min(index, len(stocks) - 1)]["symbol"] if stocks else ""
                success_message = f"{symbol} removed from {active_watchlist['name']}."
        elif action == "save_meta":
            stock_entry = get_manual_watchlist_stock_entry(active_watchlist, symbol)
            if not stock_entry:
                error = "That stock is no longer available for note updates."
            else:
                stock_entry["note_text"] = str(request.form.get("note_text", "")).strip()[:400]
                stock_entry["alert_rule"] = str(request.form.get("alert_rule", "none")).strip() or "none"
                state = save_manual_watchlists_state(state)
                selected_symbol = symbol
                success_message = f"Saved note and alert rule for {symbol}."

        active_watchlist = get_manual_watchlist(state, active_watchlist_key)

    rows = []
    missing = []
    try:
        rows, missing = get_manual_watchlist_rows(active_watchlist, get_today_ist())
        if missing and not error:
            error = f"Could not fetch live data for: {', '.join(missing)}"
    except Exception as exc:
        error = str(exc)

    if not selected_symbol and rows:
        selected_symbol = rows[0]["symbol"]

    row_map = {row["symbol"]: row for row in rows}
    selected_row = row_map.get(selected_symbol) if selected_symbol else None
    stock_entry = get_manual_watchlist_stock_entry(active_watchlist, selected_symbol) if selected_symbol else None
    if selected_row and stock_entry:
        selected_row["note_text"] = stock_entry.get("note_text", "")
        selected_row["alert_rule"] = stock_entry.get("alert_rule", "none")
        selected_row["alert_label"] = get_manual_watchlist_alert_label(selected_row["alert_rule"])
        selected_row["alert_badge"] = get_manual_watchlist_alert_badge(selected_row["alert_rule"])

    for row in rows:
        stored = get_manual_watchlist_stock_entry(active_watchlist, row["symbol"])
        if stored:
            row["note_text"] = stored.get("note_text", "")
            row["note_preview"] = (row["note_text"][:70] + ("..." if len(row["note_text"]) > 70 else "")) if row["note_text"] else "-"
            row["alert_rule"] = stored.get("alert_rule", "none")
            row["alert_label"] = get_manual_watchlist_alert_label(row["alert_rule"])
            row["alert_badge"] = get_manual_watchlist_alert_badge(row["alert_rule"])

    watchlist_options = get_manual_watchlist_options(state)
    active_watchlist_payload = {
        "key": active_watchlist["key"],
        "name": active_watchlist["name"],
        "stock_count": len(active_watchlist.get("stocks") or []),
    }
    stock_search_options = sorted(
        (
            {"symbol": row["symbol"], "label": f"{row['symbol']} - {row['security']}"}
            for row in load_symbol_master().get("by_symbol", {}).values()
        ),
        key=lambda item: item["symbol"],
    )

    return render_template_string(
        MANUAL_WATCHLIST_TEMPLATE,
        watchlists=watchlist_options,
        active_watchlist=active_watchlist_payload,
        rows=rows,
        selected_row=selected_row,
        selected_symbol=selected_symbol,
        refresh_options=get_refresh_options(),
        refresh_seconds=refresh_seconds,
        refresh_label="Off" if refresh_seconds == 0 else f"{refresh_seconds}s",
        error=error,
        success_message=success_message,
        stock_search_options=stock_search_options,
        summary=build_manual_watchlist_summary(rows),
        alert_options=get_manual_watchlist_alert_options(),
        watchlist_limit=MANUAL_WATCHLIST_LIMIT,
        stock_limit=MANUAL_WATCHLIST_STOCK_LIMIT,
        today_date=get_today_ist().isoformat(),
    )


@app.route("/equity-watchlist-desk", methods=["GET"])
def equity_watchlist_desk_legacy():
    return redirect(f"/scripts-watchlists?{request.query_string.decode()}" if request.query_string else "/scripts-watchlists")


@app.route("/market-watch")
def market_watch():
    refresh_seconds = parse_refresh_seconds(request.args.get("refresh", "30"))
    active_watchlist_key = request.args.get("watchlist", "watchlist_1")
    selected_symbol = request.args.get("selected", "")
    context = get_market_watch_context(active_watchlist_key, selected_symbol, refresh_seconds)
    partials = render_market_watch_partials(context)
    return render_template_string(
        MARKET_WATCH_TEMPLATE,
        **context,
        **partials,
    )


@app.route("/market-watch/partial")
def market_watch_partial():
    refresh_seconds = parse_refresh_seconds(request.args.get("refresh", "30"))
    active_watchlist_key = request.args.get("watchlist", "watchlist_1")
    selected_symbol = request.args.get("selected", "")
    context = get_market_watch_context(active_watchlist_key, selected_symbol, refresh_seconds)
    partials = render_market_watch_partials(context)
    return jsonify(partials)


@app.route("/equity-movers")
def equity_movers():
    active_watchlist = request.args.get("watchlist", "my_intraday")
    raw_symbols = request.args.get("symbols", "")
    raw_date = request.args.get("date", get_today_ist().isoformat())
    refresh_seconds = parse_refresh_seconds(request.args.get("refresh", "30"))

    error = None
    mover_rows = []

    try:
        symbols = get_symbols_for_watchlist(active_watchlist, raw_symbols)
        selected_date = parse_date(raw_date)

        if not symbols:
            raise ValueError("Please provide at least one NSE symbol.")
        creds = get_active_kite_credentials()
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("Kite API key or access token is missing in .env.")

        mover_rows, missing = get_mover_rows(symbols)
        if missing:
            missing_text = ", ".join(missing)
            error = f"Could not fetch quote data for: {missing_text}"
    except Exception as exc:
        symbols = get_symbols_for_watchlist(active_watchlist, raw_symbols) or SCANNER_DEFAULT_SYMBOLS
        selected_date = raw_date
        error = str(exc)

    active_watchlist_label = active_watchlist.replace("_", " ").title()
    refresh_label = "Off" if refresh_seconds == 0 else f"{refresh_seconds}s"

    return render_template_string(
        MOVERS_TEMPLATE,
        mover_rows=mover_rows,
        summary=build_movers_summary(mover_rows),
        error=error,
        symbols=symbols,
        request_symbols=",".join(symbols) if not raw_symbols else raw_symbols,
        selected_date=selected_date if isinstance(selected_date, str) else selected_date.isoformat(),
        today_date=get_today_ist().isoformat(),
        yesterday_date=get_yesterday_ist().isoformat(),
        watchlists=get_watchlist_options(),
        active_watchlist=active_watchlist,
        active_watchlist_label=active_watchlist_label,
        refresh_options=get_refresh_options(),
        refresh_seconds=refresh_seconds,
        refresh_label=refresh_label,
    )


@app.route("/equity-confirmation")
def equity_confirmation():
    active_watchlist = request.args.get("watchlist", "my_intraday")
    raw_symbols = request.args.get("symbols", "")
    raw_date = request.args.get("date", get_today_ist().isoformat())
    raw_start = request.args.get("start", DEFAULT_START)
    raw_end = request.args.get("end", DEFAULT_END)
    refresh_seconds = parse_refresh_seconds(request.args.get("refresh", "30"))

    error = None
    confirmation_rows = []

    try:
        symbols = get_symbols_for_watchlist(active_watchlist, raw_symbols)
        selected_date = parse_date(raw_date)
        start_time = parse_time(raw_start, DEFAULT_START)
        end_time = parse_time(raw_end, DEFAULT_END)

        if not symbols:
            raise ValueError("Please provide at least one NSE symbol.")
        creds = get_active_kite_credentials()
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("Kite API key or access token is missing in .env.")
        if end_time <= start_time:
            raise ValueError("End time must be after start time.")

        confirmation_rows, missing = get_confirmation_rows(symbols, selected_date, start_time, end_time)
        if missing:
            missing_text = ", ".join(missing)
            error = f"Could not find NSE equity symbols: {missing_text}"
    except Exception as exc:
        symbols = get_symbols_for_watchlist(active_watchlist, raw_symbols) or SCANNER_DEFAULT_SYMBOLS
        selected_date = raw_date
        start_time = raw_start
        end_time = raw_end
        error = str(exc)

    active_watchlist_label = active_watchlist.replace("_", " ").title()
    refresh_label = "Off" if refresh_seconds == 0 else f"{refresh_seconds}s"

    return render_template_string(
        CONFIRMATION_TEMPLATE,
        confirmation_rows=confirmation_rows,
        summary=build_confirmation_summary(confirmation_rows),
        error=error,
        symbols=symbols,
        request_symbols=",".join(symbols) if not raw_symbols else raw_symbols,
        selected_date=selected_date if isinstance(selected_date, str) else selected_date.isoformat(),
        today_date=get_today_ist().isoformat(),
        yesterday_date=get_yesterday_ist().isoformat(),
        start_time=start_time if isinstance(start_time, str) else start_time.strftime("%H:%M"),
        end_time=end_time if isinstance(end_time, str) else end_time.strftime("%H:%M"),
        watchlists=get_watchlist_options(),
        active_watchlist=active_watchlist,
        active_watchlist_label=active_watchlist_label,
        refresh_options=get_refresh_options(),
        refresh_seconds=refresh_seconds,
        refresh_label=refresh_label,
    )


@app.route("/equity-sector-strength")
def equity_sector_strength():
    raw_date = request.args.get("date", get_today_ist().isoformat())
    raw_start = request.args.get("start", DEFAULT_START)
    raw_end = request.args.get("end", DEFAULT_END)
    selected_sector = request.args.get("sector", "psu_banks")
    refresh_seconds = parse_refresh_seconds(request.args.get("refresh", "30"))

    error = None
    sector_rows = []
    selected_sector_rows = []
    selected_sector_label = selected_sector.replace("_", " ").title()

    try:
        selected_date = parse_date(raw_date)
        start_time = parse_time(raw_start, DEFAULT_START)
        end_time = parse_time(raw_end, DEFAULT_END)

        creds = get_active_kite_credentials()
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("Kite API key or access token is missing in .env.")
        if end_time <= start_time:
            raise ValueError("End time must be after start time.")

        sector_rows, sector_detail_map, sector_missing = get_sector_strength_rows(selected_date, start_time, end_time)

        if selected_sector not in sector_detail_map and sector_rows:
            selected_sector = sector_rows[0]["sector_key"]

        selected_sector_rows = sector_detail_map.get(selected_sector, [])
        selected_sector_label = selected_sector.replace("_", " ").title()

        if selected_sector in sector_missing and sector_missing[selected_sector]:
            missing_text = ", ".join(sector_missing[selected_sector])
            error = f"Missing or unavailable symbols in {selected_sector_label}: {missing_text}"
    except Exception as exc:
        selected_date = raw_date
        start_time = raw_start
        end_time = raw_end
        error = str(exc)

    refresh_label = "Off" if refresh_seconds == 0 else f"{refresh_seconds}s"

    return render_template_string(
        SECTOR_TEMPLATE,
        sector_rows=sector_rows,
        selected_sector_rows=selected_sector_rows,
        error=error,
        selected_date=selected_date if isinstance(selected_date, str) else selected_date.isoformat(),
        today_date=get_today_ist().isoformat(),
        yesterday_date=get_yesterday_ist().isoformat(),
        start_time=start_time if isinstance(start_time, str) else start_time.strftime("%H:%M"),
        end_time=end_time if isinstance(end_time, str) else end_time.strftime("%H:%M"),
        sector_options=get_sector_options(),
        selected_sector=selected_sector,
        selected_sector_label=selected_sector_label,
        refresh_options=get_refresh_options(),
        refresh_seconds=refresh_seconds,
        refresh_label=refresh_label,
    )


@app.route("/equity-sector-heatmap")
def equity_sector_heatmap():
    raw_date = request.args.get("date", get_today_ist().isoformat())
    raw_start = request.args.get("start", DEFAULT_START)
    raw_end = request.args.get("end", DEFAULT_END)
    selected_sector = request.args.get("sector", "financials")
    selected_sub_sector = request.args.get("subsector", "")
    refresh_seconds = parse_refresh_seconds(request.args.get("refresh", "30"))

    error = None
    sector_rows = []
    sub_sector_rows = []
    selected_sub_sector_rows = []
    selected_sector_label = SECTOR_HEATMAP_GROUPS.get(selected_sector, {}).get("label", selected_sector.replace("_", " ").title())
    selected_sub_sector_label = selected_sub_sector.replace("_", " ").title()
    selected_sub_sector_row = summarize_rotation_bucket("", "Selected Sub-Sector", [])
    summary = build_sector_heatmap_summary([], [])

    try:
        selected_date = parse_date(raw_date)
        start_time = parse_time(raw_start, DEFAULT_START)
        end_time = parse_time(raw_end, DEFAULT_END)

        creds = get_active_kite_credentials()
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("Kite API key or access token is missing in .env.")
        if end_time <= start_time:
            raise ValueError("End time must be after start time.")

        sector_rows, sub_sector_rows_map, sub_sector_detail_map, sector_missing = get_sector_heatmap_data(
            selected_date,
            start_time,
            end_time,
        )

        if selected_sector not in sub_sector_rows_map and sector_rows:
            selected_sector = sector_rows[0]["sector_key"]

        selected_sector_label = SECTOR_HEATMAP_GROUPS.get(selected_sector, {}).get("label", selected_sector.replace("_", " ").title())
        sub_sector_rows = sub_sector_rows_map.get(selected_sector, [])
        if not selected_sub_sector and sub_sector_rows:
            selected_sub_sector = sub_sector_rows[0]["sector_key"]
        elif selected_sub_sector not in {row["sector_key"] for row in sub_sector_rows} and sub_sector_rows:
            selected_sub_sector = sub_sector_rows[0]["sector_key"]

        selected_sub_sector_label = selected_sub_sector.replace("_", " ").title()
        selected_sub_sector_rows = sub_sector_detail_map.get(selected_sub_sector, [])
        selected_sub_sector_row = next(
            (row for row in sub_sector_rows if row["sector_key"] == selected_sub_sector),
            summarize_rotation_bucket(selected_sub_sector, selected_sub_sector_label, []),
        )
        summary = build_sector_heatmap_summary(sector_rows, sub_sector_rows)

        if selected_sector in sector_missing and sector_missing[selected_sector]:
            missing_text = ", ".join(sector_missing[selected_sector])
            error = f"Missing or unavailable symbols in {selected_sector_label}: {missing_text}"
    except Exception as exc:
        selected_date = raw_date
        start_time = raw_start
        end_time = raw_end
        error = str(exc)

    refresh_label = "Off" if refresh_seconds == 0 else f"{refresh_seconds}s"

    return render_template_string(
        SECTOR_HEATMAP_TEMPLATE,
        sector_rows=sector_rows,
        sub_sector_rows=sub_sector_rows,
        selected_sub_sector_rows=selected_sub_sector_rows,
        selected_sub_sector_row=selected_sub_sector_row,
        summary=summary,
        error=error,
        selected_date=selected_date if isinstance(selected_date, str) else selected_date.isoformat(),
        today_date=get_today_ist().isoformat(),
        yesterday_date=get_yesterday_ist().isoformat(),
        start_time=start_time if isinstance(start_time, str) else start_time.strftime("%H:%M"),
        end_time=end_time if isinstance(end_time, str) else end_time.strftime("%H:%M"),
        sector_options=get_heatmap_sector_options(),
        sub_sector_options=get_heatmap_sub_sector_options(selected_sector),
        selected_sector=selected_sector,
        selected_sector_label=selected_sector_label,
        selected_sub_sector=selected_sub_sector,
        selected_sub_sector_label=selected_sub_sector_label,
        refresh_options=get_refresh_options(),
        refresh_seconds=refresh_seconds,
        refresh_label=refresh_label,
    )


@app.route("/equity-rotation-home")
def equity_rotation_home():
    active_watchlist = request.args.get("watchlist", "my_intraday")
    raw_symbols = request.args.get("symbols", "")
    raw_date = request.args.get("date", get_today_ist().isoformat())
    raw_start = request.args.get("start", DEFAULT_START)
    raw_end = request.args.get("end", DEFAULT_END)
    refresh_seconds = parse_refresh_seconds(request.args.get("refresh", "30"))

    error = None
    symbols = get_symbols_for_watchlist(active_watchlist, raw_symbols)
    sector_rows = []
    heatmap_sector_rows = []
    confirmation_rows = []
    level_rows = []
    heatmap_summary = build_sector_heatmap_summary([], [])
    home_summary = build_rotation_home_summary([], heatmap_summary, [], [])
    top_longs = []
    top_shorts = []
    near_pdh_rows = []
    near_pdl_rows = []

    try:
        selected_date = parse_date(raw_date)
        start_time = parse_time(raw_start, DEFAULT_START)
        end_time = parse_time(raw_end, DEFAULT_END)

        if not symbols:
            raise ValueError("Please provide at least one NSE symbol.")
        creds = get_active_kite_credentials()
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("Kite API key or access token is missing in .env.")
        if end_time <= start_time:
            raise ValueError("End time must be after start time.")

        heatmap_sector_rows, _, _, _ = get_sector_heatmap_data(selected_date, start_time, end_time)
        sector_rows = heatmap_sector_rows
        heatmap_summary = build_sector_heatmap_summary(heatmap_sector_rows, [])
        confirmation_rows, confirmation_missing = get_confirmation_rows(
            symbols,
            selected_date,
            start_time,
            end_time,
            include_ai=False,
        )
        level_rows, level_missing = get_previous_day_level_rows(symbols, selected_date)

        top_longs = [row for row in confirmation_rows if row["confirmation_status"] == "Confirmed Long"][:4]
        top_shorts = [row for row in confirmation_rows if row["confirmation_status"] == "Confirmed Short"][:4]

        pdh_candidates = [row for row in level_rows if row["status_label"] != "Above PDH"]
        pdl_candidates = [row for row in level_rows if row["status_label"] != "Below PDL"]
        near_pdh_rows = sorted(pdh_candidates, key=lambda row: abs(row["distance_pdh_numeric"]))[:4]
        near_pdl_rows = sorted(pdl_candidates, key=lambda row: abs(row["distance_pdl_numeric"]))[:4]

        home_summary = build_rotation_home_summary(sector_rows, heatmap_summary, confirmation_rows, level_rows)

        missing_values = sorted(set(confirmation_missing + level_missing))
        if missing_values:
            error = f"Some symbols had partial data: {', '.join(missing_values)}"
    except Exception as exc:
        selected_date = raw_date
        start_time = raw_start
        end_time = raw_end
        error = str(exc)

    active_watchlist_label = active_watchlist.replace("_", " ").title()
    refresh_label = "Off" if refresh_seconds == 0 else f"{refresh_seconds}s"

    return render_template_string(
        ROTATION_HOME_TEMPLATE,
        error=error,
        symbols=symbols,
        request_symbols=",".join(symbols) if not raw_symbols else raw_symbols,
        selected_date=selected_date if isinstance(selected_date, str) else selected_date.isoformat(),
        today_date=get_today_ist().isoformat(),
        yesterday_date=get_yesterday_ist().isoformat(),
        start_time=start_time if isinstance(start_time, str) else start_time.strftime("%H:%M"),
        end_time=end_time if isinstance(end_time, str) else end_time.strftime("%H:%M"),
        watchlists=get_watchlist_options(),
        active_watchlist=active_watchlist,
        active_watchlist_label=active_watchlist_label,
        refresh_options=get_refresh_options(),
        refresh_seconds=refresh_seconds,
        refresh_label=refresh_label,
        sector_rows=sector_rows,
        heatmap_sector_rows=heatmap_sector_rows,
        heatmap_summary=heatmap_summary,
        home_summary=home_summary,
        top_longs=top_longs,
        top_shorts=top_shorts,
        near_pdh_rows=near_pdh_rows,
        near_pdl_rows=near_pdl_rows,
    )


@app.route("/equity-market-breadth")
def equity_market_breadth():
    active_watchlist = request.args.get("watchlist", "my_intraday")
    raw_symbols = request.args.get("symbols", "")
    raw_date = request.args.get("date", get_today_ist().isoformat())
    raw_start = request.args.get("start", DEFAULT_START)
    raw_end = request.args.get("end", DEFAULT_END)
    refresh_seconds = parse_refresh_seconds(request.args.get("refresh", "30"))

    error = None
    symbols = get_symbols_for_watchlist(active_watchlist, raw_symbols)
    scanner_rows = []
    mover_rows = []
    level_rows = []
    sector_rows = []
    breadth_rows = []
    summary = build_market_breadth_summary([], [], [], [])

    try:
        selected_date = parse_date(raw_date)
        start_time = parse_time(raw_start, DEFAULT_START)
        end_time = parse_time(raw_end, DEFAULT_END)

        if not symbols:
            raise ValueError("Please provide at least one NSE symbol.")
        creds = get_active_kite_credentials()
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("Kite API key or access token is missing in .env.")
        if end_time <= start_time:
            raise ValueError("End time must be after start time.")

        scanner_rows, scanner_missing = get_intraday_scanner_rows(
            symbols,
            selected_date,
            start_time,
            end_time,
            include_ai=False,
        )
        mover_rows, mover_missing = get_mover_rows(symbols)
        level_rows, level_missing = get_previous_day_level_rows(symbols, selected_date)
        sector_rows, _, _, _ = get_sector_heatmap_data(selected_date, start_time, end_time)

        mover_map = {row["symbol"]: row for row in mover_rows}
        level_map = {row["symbol"]: row for row in level_rows}
        breadth_rows = []
        for scanner_row in scanner_rows:
            mover_row = mover_map.get(scanner_row["symbol"])
            level_row = level_map.get(scanner_row["symbol"])
            if not mover_row or not level_row:
                continue

            breadth_row = dict(scanner_row)
            breadth_row.update(
                {
                    "day_change_pct": mover_row["day_change_pct"],
                    "day_change_badge": mover_row["day_change_badge"],
                    "gap_pct": mover_row["gap_pct"],
                    "gap_badge": mover_row["gap_badge"],
                    "status_label": level_row["status_label"],
                    "status_badge": level_row["status_badge"],
                    "distance_pdh": level_row["distance_pdh"],
                    "distance_pdh_badge": level_row["distance_pdh_badge"],
                    "distance_pdl": level_row["distance_pdl"],
                    "distance_pdl_badge": level_row["distance_pdl_badge"],
                }
            )
            breadth_rows.append(breadth_row)

        summary = build_market_breadth_summary(scanner_rows, mover_rows, level_rows, sector_rows)

        missing_values = sorted(set(scanner_missing + mover_missing + level_missing))
        if missing_values:
            error = f"Some symbols had partial data: {', '.join(missing_values)}"
    except Exception as exc:
        selected_date = raw_date
        start_time = raw_start
        end_time = raw_end
        error = str(exc)

    active_watchlist_label = active_watchlist.replace("_", " ").title()
    refresh_label = "Off" if refresh_seconds == 0 else f"{refresh_seconds}s"

    return render_template_string(
        MARKET_BREADTH_TEMPLATE,
        error=error,
        symbols=symbols,
        request_symbols=",".join(symbols) if not raw_symbols else raw_symbols,
        selected_date=selected_date if isinstance(selected_date, str) else selected_date.isoformat(),
        today_date=get_today_ist().isoformat(),
        yesterday_date=get_yesterday_ist().isoformat(),
        start_time=start_time if isinstance(start_time, str) else start_time.strftime("%H:%M"),
        end_time=end_time if isinstance(end_time, str) else end_time.strftime("%H:%M"),
        watchlists=get_watchlist_options(),
        active_watchlist=active_watchlist,
        active_watchlist_label=active_watchlist_label,
        refresh_options=get_refresh_options(),
        refresh_seconds=refresh_seconds,
        refresh_label=refresh_label,
        sector_rows=sector_rows,
        breadth_rows=breadth_rows,
        summary=summary,
    )


@app.route("/equity-backtest")
def equity_backtest():
    active_watchlist = request.args.get("watchlist", "my_intraday")
    raw_symbols = request.args.get("symbols", "")
    raw_from_date = request.args.get("from_date", (get_today_ist() - datetime.timedelta(days=14)).isoformat())
    raw_to_date = request.args.get("to_date", get_today_ist().isoformat())
    raw_start = request.args.get("start", DEFAULT_START)
    raw_end = request.args.get("end", DEFAULT_END)
    direction = request.args.get("direction", "both")
    stop_multiple = parse_positive_float(request.args.get("stop_multiple", "1.0"), 1.0)
    target_multiple = parse_positive_float(request.args.get("target_multiple", "1.5"), 1.5)

    error = None
    symbols = get_symbols_for_watchlist(active_watchlist, raw_symbols)
    trade_rows = []
    summary = build_backtest_summary([])

    try:
        from_date = parse_date(raw_from_date)
        to_date = parse_date(raw_to_date)
        start_time = parse_time(raw_start, DEFAULT_START)
        end_time = parse_time(raw_end, DEFAULT_END)

        if not symbols:
            raise ValueError("Please provide at least one NSE symbol.")
        creds = get_active_kite_credentials()
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("Kite API key or access token is missing in .env.")
        if to_date < from_date:
            raise ValueError("To date must be on or after from date.")
        if end_time <= start_time:
            raise ValueError("ORB end time must be after ORB start time.")
        if direction not in {"both", "long", "short"}:
            raise ValueError("Direction must be one of: both, long, short.")

        trade_rows, missing = get_orb_backtest_rows(
            symbols,
            from_date,
            to_date,
            start_time,
            end_time,
            direction,
            stop_multiple,
            target_multiple,
        )
        summary = build_backtest_summary(trade_rows)

        if missing:
            error = f"Some symbols were unavailable on NSE: {', '.join(sorted(set(missing)))}"
    except Exception as exc:
        from_date = raw_from_date
        to_date = raw_to_date
        start_time = raw_start
        end_time = raw_end
        error = str(exc)

    active_watchlist_label = active_watchlist.replace("_", " ").title()
    direction_label = next((item["label"] for item in get_backtest_direction_options() if item["value"] == direction), direction.title())

    return render_template_string(
        BACKTEST_TEMPLATE,
        error=error,
        trade_rows=trade_rows,
        summary=summary,
        watchlists=get_watchlist_options(),
        active_watchlist=active_watchlist,
        active_watchlist_label=active_watchlist_label,
        request_symbols=",".join(symbols) if not raw_symbols else raw_symbols,
        from_date=from_date if isinstance(from_date, str) else from_date.isoformat(),
        to_date=to_date if isinstance(to_date, str) else to_date.isoformat(),
        start_time=start_time if isinstance(start_time, str) else start_time.strftime("%H:%M"),
        end_time=end_time if isinstance(end_time, str) else end_time.strftime("%H:%M"),
        direction=direction,
        direction_label=direction_label,
        direction_options=get_backtest_direction_options(),
        stop_multiple=f"{stop_multiple:.2f}",
        target_multiple=f"{target_multiple:.2f}",
        presets=build_backtest_presets(
            active_watchlist,
            (",".join(symbols) if not raw_symbols else raw_symbols),
            start_time if isinstance(start_time, str) else start_time.strftime("%H:%M"),
            end_time if isinstance(end_time, str) else end_time.strftime("%H:%M"),
            direction,
            f"{stop_multiple:.2f}",
            f"{target_multiple:.2f}",
        ),
    )


ARBITRAGE_LIVE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraderHub Arbitrage Live</title>
  <style>
    :root {
      --bg: #f3ecdf;
      --panel: #fffdf8;
      --ink: #182027;
      --muted: #5d6872;
      --line: #d9d0bd;
      --accent: #1f6f5f;
      --accent-strong: #174c41;
      --up: #116149;
      --up-soft: #d7efe7;
      --down: #8a2e2e;
      --down-soft: #f7dddd;
      --neutral: #7a5a18;
      --neutral-soft: #f5ebcc;
      --info: #1f3f73;
      --info-soft: #dde8f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(31,111,95,0.12), transparent 25%),
        linear-gradient(180deg, #fbf7ef 0%, #ece3d6 100%);
    }
    .page { max-width: 1240px; margin: 0 auto; padding: 22px 14px 56px; }
    .hero, .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: 0 18px 44px rgba(24,32,39,0.08);
    }
    .hero {
      overflow: hidden;
      background:
        radial-gradient(circle at top right, rgba(255,255,255,0.12), transparent 24%),
        linear-gradient(135deg, rgba(20,44,62,0.98), rgba(31,111,95,0.92));
      color: #f8f5ef;
      padding: 24px;
    }
    .hero-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(280px, 0.9fr);
      gap: 18px;
      align-items: stretch;
    }
    h1 { margin: 0; font-size: 40px; line-height: 1; }
    h2 { margin: 0 0 12px; font-size: 24px; }
    .sub {
      margin: 12px 0 0;
      font-size: 16px;
      line-height: 1.55;
      color: rgba(248,245,239,0.88);
      max-width: 880px;
    }
    .meta, .hero-links, .button-row, .queue-steps {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }
    .meta { margin-top: 14px; }
    .hero-links { margin-top: 16px; }
    .pill, .queue-step {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.16);
      font-size: 14px;
    }
    .hero-links a, .secondary-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 12px 16px;
      border-radius: 14px;
      border: 1px solid var(--line);
      text-decoration: none;
      background: #fff;
      color: var(--ink);
      font-weight: 700;
      cursor: pointer;
    }
    .hero-stage {
      position: relative;
      overflow: hidden;
      border-radius: 22px;
      border: 1px solid rgba(255,255,255,0.18);
      background:
        radial-gradient(circle at top right, rgba(255,255,255,0.18), transparent 32%),
        linear-gradient(180deg, rgba(10,21,33,0.58), rgba(10,21,33,0.12));
      min-height: 250px;
      padding: 18px;
    }
    .hero-stage::after {
      content: "";
      position: absolute;
      left: 18px;
      right: 18px;
      bottom: 18px;
      height: 62px;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(232,214,174,0.18), rgba(232,214,174,0.3));
      border: 1px solid rgba(255,255,255,0.08);
    }
    .stage-label {
      position: relative;
      z-index: 2;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.12);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .desk-crew {
      position: relative;
      z-index: 2;
      display: flex;
      justify-content: center;
      align-items: flex-end;
      gap: 14px;
      margin-top: 14px;
      min-height: 170px;
    }
    .crew-card { width: 31%; min-width: 84px; text-align: center; color: #f8f5ef; }
    .avatar { position: relative; width: 88px; height: 112px; margin: 0 auto 10px; }
    .avatar-head {
      position: absolute; left: 50%; top: 0; width: 56px; height: 56px; transform: translateX(-50%);
      border-radius: 50%; background: #f2d0b4; border: 2px solid rgba(24,32,39,0.18);
      box-shadow: inset 0 -6px 0 rgba(0,0,0,0.05);
    }
    .avatar-head::before, .avatar-head::after {
      content: ""; position: absolute; top: 22px; width: 7px; height: 7px; border-radius: 50%; background: #182027;
    }
    .avatar-head::before { left: 15px; }
    .avatar-head::after { right: 15px; }
    .avatar-face {
      position: absolute; left: 50%; top: 29px; width: 20px; height: 10px; transform: translateX(-50%);
      border-bottom: 2px solid #182027; border-radius: 0 0 16px 16px;
    }
    .avatar-body {
      position: absolute; left: 50%; top: 46px; width: 64px; height: 62px; transform: translateX(-50%);
      border-radius: 18px 18px 14px 14px; border: 2px solid rgba(255,255,255,0.24);
    }
    .avatar-screen {
      position: absolute; left: 50%; bottom: -2px; width: 80px; height: 26px; transform: translateX(-50%);
      border-radius: 10px; border: 1px solid rgba(255,255,255,0.2); background: rgba(11,23,35,0.68);
      box-shadow: 0 8px 16px rgba(7,13,20,0.2); overflow: hidden;
    }
    .avatar-screen::before {
      content: ""; position: absolute; inset: 4px 6px; border-radius: 6px;
      background: linear-gradient(90deg, rgba(17,97,73,0.75), rgba(255,255,255,0.12), rgba(138,46,46,0.75));
    }
    .crew-card.bull .avatar-body { background: linear-gradient(180deg, rgba(17,97,73,0.44), rgba(17,97,73,0.18)); }
    .crew-card.bear .avatar-body { background: linear-gradient(180deg, rgba(138,46,46,0.4), rgba(138,46,46,0.14)); }
    .crew-card.scout .avatar-body { background: linear-gradient(180deg, rgba(31,63,115,0.42), rgba(31,63,115,0.14)); }
    .crew-name { font-size: 14px; font-weight: 700; letter-spacing: 0.03em; }
    .crew-role { margin-top: 4px; font-size: 12px; color: rgba(248,245,239,0.78); line-height: 1.35; }
    .card { margin-top: 18px; padding: 20px; }
    .grid-3, .grid-2, .summary-grid, .ready-grid, .trade-grid, .metrics-grid {
      display: grid;
      gap: 14px;
    }
    .grid-3, .summary-grid { grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); }
    .grid-2, .ready-grid, .trade-grid { grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
    .metrics-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .field label {
      display: block;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 6px;
      font-weight: 700;
    }
    input, select {
      width: 100%;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }
    .primary-btn {
      width: 100%;
      border: 0;
      border-radius: 14px;
      padding: 13px 16px;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      background: var(--accent);
      color: #fff;
    }
    .secondary-btn {
      background: #faf7f1;
      width: 100%;
      border-radius: 14px;
      font: inherit;
    }
    .summary-box, .sheet-box, .metric-box, .trade-card, .ready-card {
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.82);
      border-radius: 18px;
    }
    .summary-box, .metric-box { padding: 14px; }
    .summary-label, .metric-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 6px;
      font-weight: 700;
    }
    .summary-value, .metric-value { font-size: 24px; font-weight: 700; }
    .summary-note { color: var(--muted); font-size: 13px; line-height: 1.45; margin-top: 6px; }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }
    .badge-up { background: var(--up-soft); color: var(--up); }
    .badge-down { background: var(--down-soft); color: var(--down); }
    .badge-neutral { background: var(--neutral-soft); color: var(--neutral); }
    .badge-info { background: var(--info-soft); color: var(--info); }
    .error {
      margin-top: 14px;
      border-radius: 16px;
      padding: 14px 16px;
      background: #f7e3d9;
      color: #8a3b12;
      border: 1px solid rgba(138,59,18,0.18);
    }
    .sheet-box { padding: 16px; }
    .sheet-title {
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 10px;
      font-weight: 700;
    }
    .pair-sheet {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
    }
    .pair-leg {
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #faf7f1;
    }
    .pair-leg.buy { border-left: 4px solid var(--up); }
    .pair-leg.sell { border-left: 4px solid var(--down); }
    .leg-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      margin-bottom: 10px;
    }
    .leg-title { font-size: 18px; font-weight: 700; }
    .leg-sub { color: var(--muted); font-size: 13px; }
    .ready-card, .trade-card { padding: 16px; }
    .ready-head, .trade-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 12px;
    }
    .symbol { font-size: 26px; font-weight: 700; }
    .route { color: var(--muted); font-size: 14px; margin-top: 4px; line-height: 1.4; }
    .desk-note {
      margin-top: 10px;
      color: var(--muted);
      line-height: 1.5;
      font-size: 14px;
    }
    .action-bar {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-top: 14px;
    }
    .notice-shell {
      display: grid;
      grid-template-columns: 86px 1fr;
      gap: 16px;
      align-items: center;
      padding: 18px;
      border-radius: 20px;
      border: 1px dashed var(--line);
      background: linear-gradient(180deg, rgba(255,255,255,0.85), rgba(247,243,234,0.9));
    }
    .notice-figure {
      position: relative;
      width: 78px;
      height: 96px;
      margin: 0 auto;
    }
    .notice-figure .avatar-head { width: 48px; height: 48px; border-width: 1px; }
    .notice-figure .avatar-head::before, .notice-figure .avatar-head::after { top: 18px; width: 6px; height: 6px; }
    .notice-figure .avatar-body { width: 56px; height: 48px; top: 38px; border-width: 1px; background: linear-gradient(180deg, rgba(31,63,115,0.42), rgba(31,63,115,0.14)); }
    .notice-figure .avatar-screen { width: 72px; height: 20px; }
    .notice-title { font-size: 18px; font-weight: 700; margin-bottom: 6px; }
    .notice-copy { color: var(--muted); line-height: 1.55; font-size: 14px; }
    .state-banner {
      margin-top: 14px;
      padding: 14px 16px;
      border-radius: 18px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.18);
      line-height: 1.5;
    }
    .tiny { font-size: 12px; color: var(--muted); }
    .full-width { grid-column: 1 / -1; }
    @media (max-width: 860px) {
      .hero-grid { grid-template-columns: 1fr; }
      h1 { font-size: 32px; }
      .page { padding: 18px 12px 40px; }
      .hero, .card { border-radius: 18px; }
      .hero-stage { min-height: 220px; }
      .crew-card { width: 32%; }
      .avatar { width: 76px; height: 100px; }
      .avatar-head { width: 48px; height: 48px; }
      .avatar-body { width: 56px; height: 54px; }
      .avatar-screen { width: 72px; }
      .notice-shell { grid-template-columns: 1fr; text-align: left; }
    }
    @media (max-width: 560px) {
      .action-bar, .metrics-grid { grid-template-columns: 1fr; }
      .hero-links a, .secondary-btn, .primary-btn { width: 100%; }
      .button-row, .hero-links, .queue-steps { flex-direction: column; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="hero-grid">
        <div>
          <h1>Arbitrage Live</h1>
          <p class="sub">
            A real-money arbitrage assistant for your own Zerodha account. The scanner keeps the same approved formula, then hands both legs
            to Zerodha’s official basket confirmation screen so you can review and place the paired trade manually without unattended execution.
          </p>
          <div class="meta">
            <div class="pill">Capital: {{ capital_display }}</div>
            <div class="pill">Max Trades: {{ live_rules.max_trades_per_day }}</div>
            <div class="pill">Min Spread: {{ min_spread_display }}</div>
            <div class="pill">Net Positive Only: {{ net_positive_label }}</div>
            <div class="pill">Auto Refresh: {{ refresh_label }}</div>
          </div>
          <div class="state-banner" id="live-state-banner">
            <span class="badge {{ market_state.badge_class }}">{{ market_state.label }}</span>
            <div style="margin-top: 10px;">{{ market_state.detail }}</div>
            <div style="margin-top: 8px;"><strong>{{ live_pause_title }}:</strong> {{ live_pause_reason or "Broker feed is stable and the live queue is active." }}</div>
            <div class="tiny" id="live-updated-at" style="margin-top: 8px;">Last updated: {{ market_state.detail.split(' as of ')[-1].rstrip('.') if ' as of ' in market_state.detail else 'just now' }}</div>
          </div>
          <div class="hero-links">
            <a href="/equity-arbitrage">Scanner Page</a>
            <a href="/equity-arbitrage-virtual">Virtual Desk</a>
          </div>
        </div>
        <div class="hero-stage">
          <div class="stage-label">Live Trading Crew</div>
          <div class="desk-crew">
            <div class="crew-card bull">
              <div class="avatar"><div class="avatar-head"></div><div class="avatar-face"></div><div class="avatar-body"></div><div class="avatar-screen"></div></div>
              <div class="crew-name">Pair Captain</div>
              <div class="crew-role">Keeps both arbitrage legs together as one action.</div>
            </div>
            <div class="crew-card scout">
              <div class="avatar"><div class="avatar-head"></div><div class="avatar-face"></div><div class="avatar-body"></div><div class="avatar-screen"></div></div>
              <div class="crew-name">Depth Scout</div>
              <div class="crew-role">Only promotes setups that survive depth, time, and net filters.</div>
            </div>
            <div class="crew-card bear">
              <div class="avatar"><div class="avatar-head"></div><div class="avatar-face"></div><div class="avatar-body"></div><div class="avatar-screen"></div></div>
              <div class="crew-name">Risk Officer</div>
              <div class="crew-role">Stops the queue after the trade cap or unstable broker data.</div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Live Controls</h2>
      <form method="get" class="grid-3">
        <div class="field">
          <label for="capital">Fund Size (INR)</label>
          <input id="capital" name="capital" value="{{ capital_display }}" placeholder="20000">
        </div>
        <div class="field">
          <label for="max_trades">Max Trades Today</label>
          <input id="max_trades" name="max_trades" value="{{ max_trades_display }}" placeholder="10">
        </div>
        <div class="field">
          <label for="min_spread">Min Spread / Share</label>
          <input id="min_spread" name="min_spread" value="{{ min_spread_display }}" placeholder="0.20">
        </div>
        <div class="field">
          <label for="refresh">Auto Refresh</label>
          <select id="refresh" name="refresh">
            {% for option in refresh_options %}
            <option value="{{ option.value }}" {{ 'selected' if option.value == refresh_seconds else '' }}>{{ option.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="field">
          <label for="net_positive_only">Net Positive Only</label>
          <select id="net_positive_only" name="net_positive_only">
            <option value="1" {{ 'selected' if net_positive_only else '' }}>Yes</option>
            <option value="0" {{ 'selected' if not net_positive_only else '' }}>No</option>
          </select>
        </div>
        <div class="field" style="align-self: end;">
          <button class="primary-btn" type="submit">Refresh Live Queue</button>
        </div>
      </form>
      <div id="live-error-box">
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
      </div>
    </section>

    <section class="card">
      <h2>Desk Summary</h2>
      <div class="summary-grid" id="live-summary-grid">
        <div class="summary-box"><div class="summary-label">Opportunities</div><div class="summary-value">{{ summary.opportunity_count }}</div><div class="summary-note">Tradable spreads after filters.</div></div>
        <div class="summary-box"><div class="summary-label">Best Net</div><div class="summary-value">{{ summary.best_net_profit }}</div><div class="summary-note">Strongest live opportunity right now.</div></div>
        <div class="summary-box"><div class="summary-label">Ready Queue</div><div class="summary-value">{{ ready_setup_count }}/{{ live_rules.max_ready_setups }}</div><div class="summary-note">Top setups ready for a paired execution handoff.</div></div>
        <div class="summary-box"><div class="summary-label">Launched Today</div><div class="summary-value">{{ live_trade_book.launched_count }}/{{ live_rules.max_trades_per_day }}</div><div class="summary-note">Logged live pairs from this page today.</div></div>
        <div class="summary-box"><div class="summary-label">Remaining Slots</div><div class="summary-value">{{ live_trade_book.remaining_trades }}</div><div class="summary-note">Live queue stops once this reaches zero.</div></div>
        <div class="summary-box"><div class="summary-label">Estimated Net Book</div><div class="summary-value">{{ live_trade_book.total_live_net }}</div><div class="summary-note">Running estimated net across launched pairs.</div></div>
        <div class="summary-box"><div class="summary-label">Rejected For EQ / Identity</div><div class="summary-value">{{ scan_meta.rejected_not_common_eq }}</div><div class="summary-note">Filtered out before scan because they were not validated as matching NSE+BSE EQ cash shares.</div></div>
        <div class="summary-box"><div class="summary-label">Stale Quotes</div><div class="summary-value">{{ scan_meta.rejected_stale_quotes }}</div><div class="summary-note">Skipped because quote timestamps were too old for a live pair.</div></div>
        <div class="summary-box"><div class="summary-label">Missing Depth</div><div class="summary-value">{{ scan_meta.rejected_missing_depth }}</div><div class="summary-note">Skipped because one or both exchanges lacked usable top depth.</div></div>
      </div>
    </section>

    <section class="card">
      <h2>Best Opportunity Spotlight</h2>
      <div id="live-spotlight-section">
      {% if spotlight %}
      <div class="ready-card">
        <div class="ready-head">
          <div>
            <div class="symbol">{{ spotlight.symbol }}</div>
            <div class="route">{{ spotlight.route }} at {{ spotlight.timestamp }}</div>
          </div>
          <span class="badge {{ spotlight.badge_class }}">{{ spotlight.net_profit }}</span>
        </div>
        <div class="metrics-grid">
          <div class="metric-box"><div class="metric-label">Gross Spread</div><div class="metric-value">{{ spotlight.gross_spread }}</div></div>
          <div class="metric-box"><div class="metric-label">Tradable Qty</div><div class="metric-value">{{ spotlight.quantity }}</div></div>
          <div class="metric-box"><div class="metric-label">Liquidity</div><div class="metric-value" style="font-size:18px;">{{ spotlight.liquidity_warning }}</div></div>
          <div class="metric-box"><div class="metric-label">Desk Note</div><div class="metric-value" style="font-size:18px;">{{ spotlight.note }}</div></div>
        </div>
      </div>
      {% else %}
      <div class="notice-shell">
        <div class="notice-figure">
          <div class="avatar-head"></div><div class="avatar-face"></div><div class="avatar-body"></div><div class="avatar-screen"></div>
        </div>
        <div>
          <div class="notice-title">No Lead Pair Yet</div>
          <div class="notice-copy">The live desk is scanning, but nothing is strong enough yet to become the main execution candidate. That usually means the spread is thin, the net edge is too small, or the depth is fading too quickly.</div>
        </div>
      </div>
      {% endif %}
      </div>
    </section>

    <section class="card">
      <h2>Ready Live Pairs</h2>
      <div class="queue-steps" style="margin-bottom: 14px;">
        <div class="queue-step">Step 1: Let the queue validate spread, depth, and persistence.</div>
        <div class="queue-step">Step 2: Open the official Zerodha basket in a separate tab.</div>
        <div class="queue-step">Step 3: Review both legs together and confirm manually.</div>
      </div>
      <div id="live-ready-section">
      {% if ready_setups %}
      <div class="ready-grid">
        {% for setup in ready_setups %}
        <div class="ready-card">
          <div class="ready-head">
            <div>
              <div class="symbol">{{ setup.symbol }}</div>
              <div class="route">{{ setup.route }} | seen for {{ setup.persisted_seconds }}s</div>
            </div>
            <span class="badge {{ setup.ready_badge }}">{{ setup.rank_label }}</span>
          </div>
          <div class="metrics-grid">
            <div class="metric-box"><div class="metric-label">Net Profit</div><div class="metric-value">{{ setup.net_profit }}</div></div>
            <div class="metric-box"><div class="metric-label">Gross Spread</div><div class="metric-value">{{ setup.gross_spread }}</div></div>
            <div class="metric-box"><div class="metric-label">Quantity</div><div class="metric-value">{{ setup.quantity }}</div></div>
            <div class="metric-box"><div class="metric-label">Charges</div><div class="metric-value">{{ setup.total_charges }}</div></div>
          </div>
          <div class="sheet-box" style="margin-top: 12px;">
            <div class="sheet-title">Paired Execution Sheet</div>
            <div class="pair-sheet">
              <div class="pair-leg buy">
                <div class="leg-head">
                  <div>
                    <div class="leg-title">Buy Leg</div>
                    <div class="leg-sub">{{ setup.buy_exchange }} | {{ product_label }} | {{ order_type_label }}</div>
                  </div>
                  <span class="badge badge-up">{{ setup.buy_exchange }}</span>
                </div>
                <div class="metrics-grid">
                  <div class="metric-box"><div class="metric-label">Symbol</div><div class="metric-value" style="font-size:18px;">{{ setup.symbol }}</div></div>
                  <div class="metric-box"><div class="metric-label">Limit Price</div><div class="metric-value">{{ setup.buy_price }}</div></div>
                  <div class="metric-box"><div class="metric-label">Quantity</div><div class="metric-value">{{ setup.quantity }}</div></div>
                  <div class="metric-box"><div class="metric-label">Timestamp</div><div class="metric-value" style="font-size:18px;">{{ setup.timestamp }}</div></div>
                </div>
              </div>
              <div class="pair-leg sell">
                <div class="leg-head">
                  <div>
                    <div class="leg-title">Sell Leg</div>
                    <div class="leg-sub">{{ setup.sell_exchange }} | {{ product_label }} | {{ order_type_label }}</div>
                  </div>
                  <span class="badge badge-down">{{ setup.sell_exchange }}</span>
                </div>
                <div class="metrics-grid">
                  <div class="metric-box"><div class="metric-label">Symbol</div><div class="metric-value" style="font-size:18px;">{{ setup.symbol }}</div></div>
                  <div class="metric-box"><div class="metric-label">Limit Price</div><div class="metric-value">{{ setup.sell_price }}</div></div>
                  <div class="metric-box"><div class="metric-label">Quantity</div><div class="metric-value">{{ setup.quantity }}</div></div>
                  <div class="metric-box"><div class="metric-label">Liquidity</div><div class="metric-value" style="font-size:18px;">{{ setup.liquidity_warning }}</div></div>
                </div>
              </div>
            </div>
          </div>
          <div class="desk-note">
            This is one arbitrage action with two exchange legs. The button below opens Zerodha’s official basket review in a new tab so you can confirm both legs together.
          </div>
          <form id="{{ setup.form_id }}" method="post" action="https://kite.zerodha.com/connect/basket" target="_blank">
            <input type="hidden" name="api_key" value="{{ kite_api_key }}">
            <input type="hidden" name="data" value='{{ setup.basket_payload|e }}'>
          </form>
          <div class="action-bar">
            <button class="primary-btn" type="button" onclick="executePair('{{ setup.setup_key }}', '{{ setup.form_id }}')">Execute Arbitrage Pair</button>
            <button class="secondary-btn" type="button" onclick="snoozePair('{{ setup.setup_key }}')">Snooze {{ live_rules.cooldown_seconds }}s</button>
          </div>
        </div>
        {% endfor %}
      </div>
      {% else %}
      <div class="notice-shell">
        <div class="notice-figure">
          <div class="avatar-head"></div><div class="avatar-face"></div><div class="avatar-body"></div><div class="avatar-screen"></div>
        </div>
        <div>
          <div class="notice-title">No Pair Is Fully Ready Yet</div>
          <div class="notice-copy">The engine is still waiting for the live queue to satisfy spread, minimum depth, persistence, and net-profit checks together. Once a pair clears the rules, it will show up here as a one-tap paired execution card.</div>
        </div>
      </div>
      {% endif %}
      </div>
    </section>

    <section class="card">
      <h2>Launched Trade Book</h2>
      <div id="live-tradebook-section">
      {% if live_trade_book.open_trades or live_trade_book.closed_trades %}
      <div class="trade-grid">
        {% for trade in live_trade_book.open_trades %}
        <div class="trade-card">
          <div class="trade-head">
            <div>
              <div class="symbol">{{ trade.symbol }}</div>
              <div class="route">{{ trade.route }} | launched at {{ trade.launched_at }}</div>
            </div>
            <span class="badge {{ trade.status_badge }}">{{ trade.status }}</span>
          </div>
          <div class="metrics-grid">
            <div class="metric-box"><div class="metric-label">Buy</div><div class="metric-value" style="font-size:18px;">{{ trade.buy_exchange }} {{ trade.buy_price }}</div></div>
            <div class="metric-box"><div class="metric-label">Sell</div><div class="metric-value" style="font-size:18px;">{{ trade.sell_exchange }} {{ trade.sell_price }}</div></div>
            <div class="metric-box"><div class="metric-label">Quantity</div><div class="metric-value">{{ trade.quantity }}</div></div>
            <div class="metric-box"><div class="metric-label">Net</div><div class="metric-value">{{ trade.net_profit }}</div></div>
          </div>
          <div class="action-bar">
            <button class="secondary-btn" type="button" onclick="closeTrade('{{ trade.trade_id }}')">Mark Closed</button>
            <div class="tiny" style="display:flex;align-items:center;justify-content:center;padding:12px;">{{ trade.trade_id }}</div>
          </div>
        </div>
        {% endfor %}
        {% for trade in live_trade_book.closed_trades %}
        <div class="trade-card">
          <div class="trade-head">
            <div>
              <div class="symbol">{{ trade.symbol }}</div>
              <div class="route">{{ trade.route }} | {{ trade.launched_at }} {% if trade.closed_at %}to {{ trade.closed_at }}{% endif %}</div>
            </div>
            <span class="badge {{ trade.status_badge }}">{{ trade.status }}</span>
          </div>
          <div class="metrics-grid">
            <div class="metric-box"><div class="metric-label">Buy</div><div class="metric-value" style="font-size:18px;">{{ trade.buy_exchange }} {{ trade.buy_price }}</div></div>
            <div class="metric-box"><div class="metric-label">Sell</div><div class="metric-value" style="font-size:18px;">{{ trade.sell_exchange }} {{ trade.sell_price }}</div></div>
            <div class="metric-box"><div class="metric-label">Quantity</div><div class="metric-value">{{ trade.quantity }}</div></div>
            <div class="metric-box"><div class="metric-label">Net</div><div class="metric-value">{{ trade.net_profit }}</div></div>
          </div>
        </div>
        {% endfor %}
      </div>
      {% else %}
      <div class="notice-shell">
        <div class="notice-figure">
          <div class="avatar-head"></div><div class="avatar-face"></div><div class="avatar-body"></div><div class="avatar-screen"></div>
        </div>
        <div>
          <div class="notice-title">No Live Trades Logged Yet</div>
          <div class="notice-copy">Once you launch a paired execution from this page, it will appear here so you can keep track of today’s live arbitrage flow without losing the scanner context.</div>
        </div>
      </div>
      {% endif %}
      </div>
    </section>
  </div>
  <script>
    async function postLiveAction(action, payload) {
      const body = new URLSearchParams();
      body.set("action", action);
      body.set("max_trades", "{{ live_rules.max_trades_per_day }}");
      Object.entries(payload || {}).forEach(([key, value]) => body.set(key, value));
      const response = await fetch("/equity-arbitrage-live/action", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
        body: body.toString()
      });
      return response.json();
    }

    async function executePair(setupKey, formId) {
      try {
        const result = await postLiveAction("launch_live", { setup_key: setupKey });
        if (!result.ok) {
          alert(result.message || "This live pair could not be launched.");
          return;
        }
        document.getElementById(formId).submit();
        setTimeout(() => window.location.reload(), 1200);
      } catch (error) {
        alert("The live desk could not reach the local action endpoint.");
      }
    }

    async function snoozePair(setupKey) {
      try {
        const result = await postLiveAction("dismiss_live", { setup_key: setupKey });
        if (result.message) {
          alert(result.message);
        }
        window.location.reload();
      } catch (error) {
        alert("The setup could not be snoozed right now.");
      }
    }

    async function closeTrade(tradeId) {
      try {
        const result = await postLiveAction("close_live", { trade_id: tradeId });
        if (result.message) {
          alert(result.message);
        }
        window.location.reload();
      } catch (error) {
        alert("The trade could not be marked closed right now.");
      }
    }

    async function refreshLiveSections() {
      const params = new URLSearchParams({
        capital: "{{ capital_display }}",
        max_trades: "{{ max_trades_display }}",
        min_spread: "{{ min_spread_display }}",
        net_positive_only: "{{ 1 if net_positive_only else 0 }}",
        refresh: "{{ refresh_seconds }}"
      });
      const response = await fetch("/equity-arbitrage-live/partial?" + params.toString(), {
        headers: { "X-Requested-With": "XMLHttpRequest" }
      });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      const stateNode = document.getElementById("live-state-banner");
      if (stateNode && payload.state_banner_html !== undefined) stateNode.outerHTML = payload.state_banner_html;
      const errorNode = document.getElementById("live-error-box");
      if (errorNode && payload.error_html !== undefined) errorNode.innerHTML = payload.error_html;
      const summaryNode = document.getElementById("live-summary-grid");
      if (summaryNode && payload.summary_html !== undefined) summaryNode.outerHTML = payload.summary_html;
      const spotlightNode = document.getElementById("live-spotlight-section");
      if (spotlightNode && payload.spotlight_html !== undefined) spotlightNode.outerHTML = payload.spotlight_html;
      const readyNode = document.getElementById("live-ready-section");
      if (readyNode && payload.ready_html !== undefined) readyNode.outerHTML = payload.ready_html;
      const tradeNode = document.getElementById("live-tradebook-section");
      if (tradeNode && payload.tradebook_html !== undefined) tradeNode.outerHTML = payload.tradebook_html;
    }

    {% if refresh_seconds > 0 %}
    window.setInterval(() => {
      refreshLiveSections();
    }, {{ refresh_seconds * 1000 }});
    {% endif %}
  </script>
</body>
</html>
"""


def build_arbitrage_page_context(request_data, request_method):
    refresh_seconds = parse_refresh_seconds(request_data.get("refresh", "30"))
    capital_amount = parse_positive_float(request_data.get("capital", f"{ARBITRAGE_RULES['capital_amount']:.0f}"), ARBITRAGE_RULES["capital_amount"])
    min_spread = parse_positive_float(request_data.get("min_spread", f"{ARBITRAGE_RULES['min_spread']:.2f}"), ARBITRAGE_RULES["min_spread"])
    net_positive_only = request_data.get("net_positive_only", "1") != "0"
    reference_date = get_today_ist()
    now_dt = datetime.datetime.now(APP_TZ)

    error = None
    symbols = get_common_equity_symbols()
    arbitrage_rows = []
    summary = build_arbitrage_summary([])
    scan_meta = build_arbitrage_rejection_summary({})
    post_analysis_groups = build_arbitrage_post_analysis(reference_date)
    recurring_archive = build_arbitrage_recurring_summary(post_analysis_groups)
    spotlight = None
    market_state = get_market_state()
    ready_setups = []
    virtual_pause_reason = ""
    virtual_state_payload = load_arbitrage_virtual_state()
    virtual_state_payload, _, day_state = ensure_virtual_day_state(virtual_state_payload, reference_date)
    virtual_trade_book = build_virtual_trade_book(day_state)
    action_message = None

    try:
        if not symbols:
            raise ValueError("No common NSE/BSE EQ cash shares were available in the stock master.")
        creds = get_active_kite_credentials()
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("Kite API key or access token is missing in .env.")

        arbitrage_rows, missing, raw_scan_meta = get_cash_arbitrage_rows(
            symbols,
            capital_amount,
            min_spread,
            net_positive_only,
        )
        scan_meta = build_arbitrage_rejection_summary(raw_scan_meta)
        summary = build_arbitrage_summary(arbitrage_rows)
        update_arbitrage_history(arbitrage_rows, reference_date)
        post_analysis_groups = build_arbitrage_post_analysis(reference_date)
        recurring_archive = build_arbitrage_recurring_summary(post_analysis_groups)
        spotlight = build_best_arbitrage_spotlight(arbitrage_rows)
        broker_stable, broker_reason = evaluate_arbitrage_broker_health(error, len(missing), len(symbols), now_dt)
        day_state["paused"] = not broker_stable
        day_state["pause_reason"] = broker_reason
        ready_setups = update_arbitrage_virtual_candidates(day_state, arbitrage_rows, now_dt, broker_stable)

        if request_method == "POST":
            action = request_data.get("action", "")
            if action == "prepare_virtual":
                action_message = create_virtual_trade(day_state, request_data.get("setup_key", ""), now_dt)
            elif action == "dismiss_setup":
                action_message = dismiss_virtual_setup(day_state, request_data.get("setup_key", ""), now_dt)
            elif action == "archive_virtual":
                action_message = archive_virtual_trade(day_state, request_data.get("trade_id", ""), now_dt)

            ready_setups = update_arbitrage_virtual_candidates(day_state, arbitrage_rows, now_dt, broker_stable)
            virtual_trade_book = build_virtual_trade_book(day_state)
            save_arbitrage_virtual_state(virtual_state_payload)
        else:
            virtual_trade_book = build_virtual_trade_book(day_state)
            save_arbitrage_virtual_state(virtual_state_payload)
        if virtual_trade_book["prepared_count"] >= ARBITRAGE_RULES["max_trades_per_day"]:
            day_state["paused"] = True
            day_state["pause_reason"] = "New prep setups are paused because the 10-trade daily limit has been reached."
            virtual_pause_reason = day_state["pause_reason"]
            save_arbitrage_virtual_state(virtual_state_payload)
        else:
            virtual_pause_reason = day_state.get("pause_reason", "")

        if missing:
            error = (
                f"{len(missing)} shares were skipped because they did not have usable two-exchange depth quotes at scan time."
            )
    except Exception as exc:
        error = str(exc)
        day_state["paused"] = True
        day_state["pause_reason"] = "Virtual prep paused because the latest broker scan failed."
        virtual_pause_reason = day_state["pause_reason"]
        virtual_trade_book = build_virtual_trade_book(day_state)
        save_arbitrage_virtual_state(virtual_state_payload)

    refresh_label = "Off" if refresh_seconds == 0 else f"{refresh_seconds}s"
    net_positive_label = "Yes" if net_positive_only else "No"
    if action_message:
        error = action_message if error is None else f"{action_message} {error}"

    virtual_pause_title = "Paused" if virtual_pause_reason else "Active"
    return dict(
        error=error,
        arbitrage_rows=arbitrage_rows,
        summary=summary,
        common_symbol_count=len(symbols),
        capital_display=f"{capital_amount:.0f}",
        min_spread_display=f"{min_spread:.2f}",
        refresh_options=get_refresh_options_with_fast(),
        refresh_seconds=refresh_seconds,
        refresh_label=refresh_label,
        net_positive_only=net_positive_only,
        net_positive_label=net_positive_label,
        scan_mode_label="Full Common EQ Universe",
        scan_meta=scan_meta,
        archive_days=ARBITRAGE_HISTORY_RETENTION_DAYS,
        post_analysis_groups=post_analysis_groups,
        recurring_archive=recurring_archive,
        spotlight=spotlight,
        market_state=market_state,
        rules=ARBITRAGE_RULES,
        ready_setups=ready_setups,
        ready_setup_count=len(ready_setups),
        virtual_trade_book=virtual_trade_book,
        virtual_pause_reason=virtual_pause_reason,
        virtual_pause_title=virtual_pause_title,
    )


def build_arbitrage_live_context(request_data):
    refresh_seconds = parse_refresh_seconds(request_data.get("refresh", "30"))
    capital_amount = parse_positive_float(request_data.get("capital", f"{ARBITRAGE_RULES['capital_amount']:.0f}"), ARBITRAGE_RULES["capital_amount"])
    min_spread = parse_positive_float(request_data.get("min_spread", f"{ARBITRAGE_RULES['min_spread']:.2f}"), ARBITRAGE_RULES["min_spread"])
    max_trades = parse_positive_int(request_data.get("max_trades", ARBITRAGE_RULES["max_trades_per_day"]), ARBITRAGE_RULES["max_trades_per_day"])
    net_positive_only = request_data.get("net_positive_only", "1") != "0"
    reference_date = get_today_ist()
    now_dt = datetime.datetime.now(APP_TZ)
    live_rules = build_arbitrage_runtime_rules(max_trades)

    error = None
    symbols = get_common_equity_symbols()
    arbitrage_rows = []
    summary = build_arbitrage_summary([])
    scan_meta = build_arbitrage_rejection_summary({})
    spotlight = None
    market_state = get_market_state()
    ready_setups = []
    live_pause_reason = ""
    live_state_payload = load_arbitrage_live_state()
    live_state_payload, _, day_state = ensure_live_day_state(live_state_payload, reference_date)
    live_trade_book = build_live_trade_book(day_state, live_rules)

    creds = get_active_kite_credentials()
    kite_api_key = creds["api_key"]

    try:
        if not symbols:
            raise ValueError("No common NSE/BSE EQ cash shares were available in the stock master.")
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("Kite API key or access token is missing in .env.")

        arbitrage_rows, missing, raw_scan_meta = get_cash_arbitrage_rows(
            symbols,
            capital_amount,
            min_spread,
            net_positive_only,
        )
        scan_meta = build_arbitrage_rejection_summary(raw_scan_meta)
        summary = build_arbitrage_summary(arbitrage_rows)
        spotlight = build_best_arbitrage_spotlight(arbitrage_rows)
        broker_stable, broker_reason = evaluate_arbitrage_broker_health(error, len(missing), len(symbols), now_dt)
        day_state["paused"] = not broker_stable
        day_state["pause_reason"] = broker_reason
        ready_setups = update_arbitrage_live_candidates(day_state, arbitrage_rows, now_dt, broker_stable, live_rules)
        live_trade_book = build_live_trade_book(day_state, live_rules)
        save_arbitrage_live_state(live_state_payload)

        if live_trade_book["launched_count"] >= live_rules["max_trades_per_day"]:
            day_state["paused"] = True
            day_state["pause_reason"] = f"New live pairs are paused because the {live_rules['max_trades_per_day']}-trade daily limit has been reached."
            live_pause_reason = day_state["pause_reason"]
            save_arbitrage_live_state(live_state_payload)
        else:
            live_pause_reason = day_state.get("pause_reason", "")

        if missing:
            error = f"{len(missing)} shares were skipped because they did not have usable two-exchange depth quotes at scan time."
    except Exception as exc:
        error = str(exc)
        day_state["paused"] = True
        day_state["pause_reason"] = "Live execution is paused because the latest broker scan failed."
        live_pause_reason = day_state["pause_reason"]
        live_trade_book = build_live_trade_book(day_state, live_rules)
        save_arbitrage_live_state(live_state_payload)

    refresh_label = "Off" if refresh_seconds == 0 else f"{refresh_seconds}s"
    net_positive_label = "Yes" if net_positive_only else "No"
    ready_setups = prepare_live_ready_setups(ready_setups, product="CNC", order_type="LIMIT")
    live_pause_title = "Paused" if live_pause_reason else "Active"
    return dict(
        error=error,
        arbitrage_rows=arbitrage_rows,
        summary=summary,
        common_symbol_count=len(symbols),
        capital_display=f"{capital_amount:.0f}",
        min_spread_display=f"{min_spread:.2f}",
        max_trades_display=str(max_trades),
        refresh_options=get_refresh_options_with_fast(),
        refresh_seconds=refresh_seconds,
        refresh_label=refresh_label,
        net_positive_only=net_positive_only,
        net_positive_label=net_positive_label,
        scan_meta=scan_meta,
        spotlight=spotlight,
        market_state=market_state,
        live_rules=live_rules,
        ready_setups=ready_setups,
        ready_setup_count=len(ready_setups),
        live_trade_book=live_trade_book,
        live_pause_reason=live_pause_reason,
        live_pause_title=live_pause_title,
        kite_api_key=kite_api_key,
        order_type_label="LIMIT",
        product_label="CNC",
    )


def render_arbitrage_live_partials(context):
    state_banner_html = render_template_string(
        """
        <div class="state-banner" id="live-state-banner">
          <span class="badge {{ market_state.badge_class }}">{{ market_state.label }}</span>
          <div style="margin-top: 10px;">{{ market_state.detail }}</div>
          <div style="margin-top: 8px;"><strong>{{ live_pause_title }}:</strong> {{ live_pause_reason or "Broker feed is stable and the live queue is active." }}</div>
          <div class="tiny" id="live-updated-at" style="margin-top: 8px;">Last updated: {{ market_state.detail.split(' as of ')[-1].rstrip('.') if ' as of ' in market_state.detail else 'just now' }}</div>
        </div>
        """,
        **context,
    )
    error_html = ""
    if context.get("error"):
        error_html = render_template_string("""<div class="error">{{ error }}</div>""", **context)
    summary_html = render_template_string(
        """
        <div class="summary-grid" id="live-summary-grid">
          <div class="summary-box"><div class="summary-label">Opportunities</div><div class="summary-value">{{ summary.opportunity_count }}</div><div class="summary-note">Tradable spreads after filters.</div></div>
          <div class="summary-box"><div class="summary-label">Best Net</div><div class="summary-value">{{ summary.best_net_profit }}</div><div class="summary-note">Strongest live opportunity right now.</div></div>
          <div class="summary-box"><div class="summary-label">Ready Queue</div><div class="summary-value">{{ ready_setup_count }}/{{ live_rules.max_ready_setups }}</div><div class="summary-note">Top setups ready for a paired execution handoff.</div></div>
          <div class="summary-box"><div class="summary-label">Launched Today</div><div class="summary-value">{{ live_trade_book.launched_count }}/{{ live_rules.max_trades_per_day }}</div><div class="summary-note">Logged live pairs from this page today.</div></div>
          <div class="summary-box"><div class="summary-label">Remaining Slots</div><div class="summary-value">{{ live_trade_book.remaining_trades }}</div><div class="summary-note">Live queue stops once this reaches zero.</div></div>
          <div class="summary-box"><div class="summary-label">Estimated Net Book</div><div class="summary-value">{{ live_trade_book.total_live_net }}</div><div class="summary-note">Running estimated net across launched pairs.</div></div>
          <div class="summary-box"><div class="summary-label">Rejected For EQ / Identity</div><div class="summary-value">{{ scan_meta.rejected_not_common_eq }}</div><div class="summary-note">Filtered out before scan because they were not validated as matching NSE+BSE EQ cash shares.</div></div>
          <div class="summary-box"><div class="summary-label">Stale Quotes</div><div class="summary-value">{{ scan_meta.rejected_stale_quotes }}</div><div class="summary-note">Skipped because quote timestamps were too old for a live pair.</div></div>
          <div class="summary-box"><div class="summary-label">Missing Depth</div><div class="summary-value">{{ scan_meta.rejected_missing_depth }}</div><div class="summary-note">Skipped because one or both exchanges lacked usable top depth.</div></div>
        </div>
        """,
        **context,
    )
    spotlight_html = render_template_string(
        """
        <div id="live-spotlight-section">
        {% if spotlight %}
          <div class="ready-card">
            <div class="ready-head">
              <div>
                <div class="symbol">{{ spotlight.symbol }}</div>
                <div class="route">{{ spotlight.route }} at {{ spotlight.timestamp }}</div>
              </div>
              <span class="badge {{ spotlight.badge_class }}">{{ spotlight.net_profit }}</span>
            </div>
            <div class="metrics-grid">
              <div class="metric-box"><div class="metric-label">Gross Spread</div><div class="metric-value">{{ spotlight.gross_spread }}</div></div>
              <div class="metric-box"><div class="metric-label">Tradable Qty</div><div class="metric-value">{{ spotlight.quantity }}</div></div>
              <div class="metric-box"><div class="metric-label">Liquidity</div><div class="metric-value" style="font-size:18px;">{{ spotlight.liquidity_warning }}</div></div>
              <div class="metric-box"><div class="metric-label">Desk Note</div><div class="metric-value" style="font-size:18px;">{{ spotlight.note }}</div></div>
            </div>
          </div>
        {% else %}
          <div class="notice-shell">
            <div class="notice-figure">
              <div class="avatar-head"></div><div class="avatar-face"></div><div class="avatar-body"></div><div class="avatar-screen"></div>
            </div>
            <div>
              <div class="notice-title">No Lead Pair Yet</div>
              <div class="notice-copy">The live desk is scanning, but nothing is strong enough yet to become the main execution candidate. That usually means the spread is thin, the net edge is too small, or the depth is fading too quickly.</div>
            </div>
          </div>
        {% endif %}
        </div>
        """,
        **context,
    )
    ready_html = render_template_string(
        """
        <div id="live-ready-section">
        {% if ready_setups %}
          <div class="ready-grid">
          {% for setup in ready_setups %}
            <div class="ready-card">
              <div class="ready-head">
                <div>
                  <div class="symbol">{{ setup.symbol }}</div>
                  <div class="route">{{ setup.route }} | seen for {{ setup.persisted_seconds }}s</div>
                </div>
                <span class="badge {{ setup.ready_badge }}">{{ setup.rank_label }}</span>
              </div>
              <div class="metrics-grid">
                <div class="metric-box"><div class="metric-label">Net Profit</div><div class="metric-value">{{ setup.net_profit }}</div></div>
                <div class="metric-box"><div class="metric-label">Gross Spread</div><div class="metric-value">{{ setup.gross_spread }}</div></div>
                <div class="metric-box"><div class="metric-label">Quantity</div><div class="metric-value">{{ setup.quantity }}</div></div>
                <div class="metric-box"><div class="metric-label">Charges</div><div class="metric-value">{{ setup.total_charges }}</div></div>
              </div>
              <div class="sheet-box" style="margin-top: 12px;">
                <div class="sheet-title">Paired Execution Sheet</div>
                <div class="pair-sheet">
                  <div class="pair-leg buy">
                    <div class="leg-head">
                      <div><div class="leg-title">Buy Leg</div><div class="leg-sub">{{ setup.buy_exchange }} | {{ product_label }} | {{ order_type_label }}</div></div>
                      <span class="badge badge-up">{{ setup.buy_exchange }}</span>
                    </div>
                    <div class="metrics-grid">
                      <div class="metric-box"><div class="metric-label">Symbol</div><div class="metric-value" style="font-size:18px;">{{ setup.symbol }}</div></div>
                      <div class="metric-box"><div class="metric-label">Limit Price</div><div class="metric-value">{{ setup.buy_price }}</div></div>
                      <div class="metric-box"><div class="metric-label">Quantity</div><div class="metric-value">{{ setup.quantity }}</div></div>
                      <div class="metric-box"><div class="metric-label">Timestamp</div><div class="metric-value" style="font-size:18px;">{{ setup.timestamp }}</div></div>
                    </div>
                  </div>
                  <div class="pair-leg sell">
                    <div class="leg-head">
                      <div><div class="leg-title">Sell Leg</div><div class="leg-sub">{{ setup.sell_exchange }} | {{ product_label }} | {{ order_type_label }}</div></div>
                      <span class="badge badge-down">{{ setup.sell_exchange }}</span>
                    </div>
                    <div class="metrics-grid">
                      <div class="metric-box"><div class="metric-label">Symbol</div><div class="metric-value" style="font-size:18px;">{{ setup.symbol }}</div></div>
                      <div class="metric-box"><div class="metric-label">Limit Price</div><div class="metric-value">{{ setup.sell_price }}</div></div>
                      <div class="metric-box"><div class="metric-label">Quantity</div><div class="metric-value">{{ setup.quantity }}</div></div>
                      <div class="metric-box"><div class="metric-label">Liquidity</div><div class="metric-value" style="font-size:18px;">{{ setup.liquidity_warning }}</div></div>
                    </div>
                  </div>
                </div>
              </div>
              <div class="desk-note">This is one arbitrage action with two exchange legs. The button below opens Zerodha’s official basket review in a new tab so you can confirm both legs together.</div>
              <form id="{{ setup.form_id }}" method="post" action="https://kite.zerodha.com/connect/basket" target="_blank">
                <input type="hidden" name="api_key" value="{{ kite_api_key }}">
                <input type="hidden" name="data" value='{{ setup.basket_payload|e }}'>
              </form>
              <div class="action-bar">
                <button class="primary-btn" type="button" onclick="executePair('{{ setup.setup_key }}', '{{ setup.form_id }}')">Execute Arbitrage Pair</button>
                <button class="secondary-btn" type="button" onclick="snoozePair('{{ setup.setup_key }}')">Snooze {{ live_rules.cooldown_seconds }}s</button>
              </div>
            </div>
          {% endfor %}
          </div>
        {% else %}
          <div class="notice-shell">
            <div class="notice-figure">
              <div class="avatar-head"></div><div class="avatar-face"></div><div class="avatar-body"></div><div class="avatar-screen"></div>
            </div>
            <div>
              <div class="notice-title">No Pair Is Fully Ready Yet</div>
              <div class="notice-copy">The engine is still waiting for the live queue to satisfy spread, minimum depth, persistence, and net-profit checks together. Once a pair clears the rules, it will show up here as a one-tap paired execution card.</div>
            </div>
          </div>
        {% endif %}
        </div>
        """,
        **context,
    )
    tradebook_html = render_template_string(
        """
        <div id="live-tradebook-section">
        {% if live_trade_book.open_trades or live_trade_book.closed_trades %}
          <div class="trade-grid">
          {% for trade in live_trade_book.open_trades %}
            <div class="trade-card">
              <div class="trade-head">
                <div>
                  <div class="symbol">{{ trade.symbol }}</div>
                  <div class="route">{{ trade.route }} | launched at {{ trade.launched_at }}</div>
                </div>
                <span class="badge {{ trade.status_badge }}">{{ trade.status }}</span>
              </div>
              <div class="metrics-grid">
                <div class="metric-box"><div class="metric-label">Buy</div><div class="metric-value" style="font-size:18px;">{{ trade.buy_exchange }} {{ trade.buy_price }}</div></div>
                <div class="metric-box"><div class="metric-label">Sell</div><div class="metric-value" style="font-size:18px;">{{ trade.sell_exchange }} {{ trade.sell_price }}</div></div>
                <div class="metric-box"><div class="metric-label">Quantity</div><div class="metric-value">{{ trade.quantity }}</div></div>
                <div class="metric-box"><div class="metric-label">Net</div><div class="metric-value">{{ trade.net_profit }}</div></div>
              </div>
              <div class="action-bar">
                <button class="secondary-btn" type="button" onclick="closeTrade('{{ trade.trade_id }}')">Mark Closed</button>
                <div class="tiny" style="display:flex;align-items:center;justify-content:center;padding:12px;">{{ trade.trade_id }}</div>
              </div>
            </div>
          {% endfor %}
          {% for trade in live_trade_book.closed_trades %}
            <div class="trade-card">
              <div class="trade-head">
                <div>
                  <div class="symbol">{{ trade.symbol }}</div>
                  <div class="route">{{ trade.route }} | {{ trade.launched_at }} {% if trade.closed_at %}to {{ trade.closed_at }}{% endif %}</div>
                </div>
                <span class="badge {{ trade.status_badge }}">{{ trade.status }}</span>
              </div>
              <div class="metrics-grid">
                <div class="metric-box"><div class="metric-label">Buy</div><div class="metric-value" style="font-size:18px;">{{ trade.buy_exchange }} {{ trade.buy_price }}</div></div>
                <div class="metric-box"><div class="metric-label">Sell</div><div class="metric-value" style="font-size:18px;">{{ trade.sell_exchange }} {{ trade.sell_price }}</div></div>
                <div class="metric-box"><div class="metric-label">Quantity</div><div class="metric-value">{{ trade.quantity }}</div></div>
                <div class="metric-box"><div class="metric-label">Net</div><div class="metric-value">{{ trade.net_profit }}</div></div>
              </div>
            </div>
          {% endfor %}
          </div>
        {% else %}
          <div class="notice-shell">
            <div class="notice-figure">
              <div class="avatar-head"></div><div class="avatar-face"></div><div class="avatar-body"></div><div class="avatar-screen"></div>
            </div>
            <div>
              <div class="notice-title">No Live Trades Logged Yet</div>
              <div class="notice-copy">Once you launch a paired execution from this page, it will appear here so you can keep track of today’s live arbitrage flow without losing the scanner context.</div>
            </div>
          </div>
        {% endif %}
        </div>
        """,
        **context,
    )
    return {
        "state_banner_html": state_banner_html,
        "error_html": error_html,
        "summary_html": summary_html,
        "spotlight_html": spotlight_html,
        "ready_html": ready_html,
        "tradebook_html": tradebook_html,
    }


@app.route("/equity-arbitrage", methods=["GET", "POST"])
def equity_arbitrage():
    request_data = request.form if request.method == "POST" else request.args
    context = build_arbitrage_page_context(request_data, request.method)
    return render_template_string(
        ARBITRAGE_TEMPLATE,
        **context,
    )


@app.route("/equity-arbitrage-virtual", methods=["GET", "POST"])
def equity_arbitrage_virtual():
    request_data = request.form if request.method == "POST" else request.args
    context = build_arbitrage_page_context(request_data, request.method)
    return render_template_string(
        ARBITRAGE_VIRTUAL_TEMPLATE,
        **context,
    )


@app.route("/equity-arbitrage-live")
def equity_arbitrage_live():
    context = build_arbitrage_live_context(request.args)
    return render_template_string(
        ARBITRAGE_LIVE_TEMPLATE,
        **context,
    )


@app.route("/equity-arbitrage-live/partial")
def equity_arbitrage_live_partial():
    context = build_arbitrage_live_context(request.args)
    return jsonify(render_arbitrage_live_partials(context))


@app.route("/equity-arbitrage-live/action", methods=["POST"])
def equity_arbitrage_live_action():
    reference_date = get_today_ist()
    now_dt = datetime.datetime.now(APP_TZ)
    action = request.form.get("action", "")
    max_trades = parse_positive_int(request.form.get("max_trades", ARBITRAGE_RULES["max_trades_per_day"]), ARBITRAGE_RULES["max_trades_per_day"])
    live_rules = build_arbitrage_runtime_rules(max_trades)
    live_state_payload = load_arbitrage_live_state()
    live_state_payload, _, day_state = ensure_live_day_state(live_state_payload, reference_date)

    if action == "launch_live":
        broker_stable, broker_reason = evaluate_arbitrage_broker_health(None, 0, 0, now_dt)
        if not broker_stable:
            day_state["paused"] = True
            day_state["pause_reason"] = broker_reason
            save_arbitrage_live_state(live_state_payload)
            return jsonify({"ok": False, "message": broker_reason})
        success, message = create_live_trade(day_state, request.form.get("setup_key", ""), now_dt, live_rules)
    elif action == "dismiss_live":
        success, message = dismiss_live_setup(day_state, request.form.get("setup_key", ""), now_dt, live_rules)
    elif action == "close_live":
        success, message = close_live_trade(day_state, request.form.get("trade_id", ""), now_dt)
    else:
        success, message = False, "Unknown live action."

    if int(day_state.get("launched_count", 0)) >= live_rules["max_trades_per_day"]:
        day_state["paused"] = True
        day_state["pause_reason"] = f"New live pairs are paused because the {live_rules['max_trades_per_day']}-trade daily limit has been reached."

    save_arbitrage_live_state(live_state_payload)
    live_trade_book = build_live_trade_book(day_state, live_rules)
    return jsonify(
        {
            "ok": success,
            "message": message,
            "launched_count": live_trade_book["launched_count"],
            "remaining_trades": live_trade_book["remaining_trades"],
            "paused": bool(day_state.get("paused")),
            "pause_reason": day_state.get("pause_reason", ""),
        }
    )


@app.route("/equity-arbitrage-export.csv")
def equity_arbitrage_export():
    reference_date = get_today_ist()
    post_analysis_groups = build_arbitrage_post_analysis(reference_date)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "date",
            "symbol",
            "route",
            "best_gross_spread",
            "best_net_profit",
            "first_seen",
            "last_seen",
            "detection_count",
            "liquidity_warning",
            "story_note",
        ]
    )

    for group in post_analysis_groups:
        for story in group["stories"]:
            writer.writerow(
                [
                    group["day_label"],
                    story["symbol"],
                    story["route"],
                    story["max_gross_spread"],
                    story["max_net_profit"],
                    story["first_seen"],
                    story["last_seen"],
                    story["detection_count"],
                    story["liquidity_warning"],
                    story["story_note"],
                ]
            )

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=equity-arbitrage-post-analysis.csv"},
    )


@app.route("/equity-trade-plan")
def equity_trade_plan():
    active_watchlist = request.args.get("watchlist", "my_intraday")
    raw_symbols = request.args.get("symbols", "")
    raw_date = request.args.get("date", get_today_ist().isoformat())
    raw_start = request.args.get("start", DEFAULT_START)
    raw_end = request.args.get("end", DEFAULT_END)
    risk_multiple = parse_positive_float(request.args.get("risk_multiple", "1.0"), 1.0)
    target_one_multiple = parse_positive_float(request.args.get("target_one_multiple", "1.0"), 1.0)
    target_two_multiple = parse_positive_float(request.args.get("target_two_multiple", "2.0"), 2.0)

    error = None
    symbols = get_symbols_for_watchlist(active_watchlist, raw_symbols)
    trade_plan_rows = []
    summary = build_trade_plan_summary([])

    try:
        selected_date = parse_date(raw_date)
        start_time = parse_time(raw_start, DEFAULT_START)
        end_time = parse_time(raw_end, DEFAULT_END)

        if not symbols:
            raise ValueError("Please provide at least one NSE symbol.")
        creds = get_active_kite_credentials()
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("Kite API key or access token is missing in .env.")
        if end_time <= start_time:
            raise ValueError("ORB end time must be after ORB start time.")
        if target_two_multiple < target_one_multiple:
            raise ValueError("Target 2 should be greater than or equal to Target 1.")

        trade_plan_rows, missing = get_trade_plan_rows(
            symbols,
            selected_date,
            start_time,
            end_time,
            risk_multiple,
            target_one_multiple,
            target_two_multiple,
        )
        summary = build_trade_plan_summary(trade_plan_rows)

        if missing:
            error = f"Some symbols had partial data: {', '.join(missing)}"
    except Exception as exc:
        selected_date = raw_date
        start_time = raw_start
        end_time = raw_end
        error = str(exc)

    active_watchlist_label = active_watchlist.replace("_", " ").title()

    return render_template_string(
        TRADE_PLAN_TEMPLATE,
        error=error,
        trade_plan_rows=trade_plan_rows,
        summary=summary,
        watchlists=get_watchlist_options(),
        active_watchlist=active_watchlist,
        active_watchlist_label=active_watchlist_label,
        request_symbols=",".join(symbols) if not raw_symbols else raw_symbols,
        selected_date=selected_date if isinstance(selected_date, str) else selected_date.isoformat(),
        today_date=get_today_ist().isoformat(),
        yesterday_date=get_yesterday_ist().isoformat(),
        start_time=start_time if isinstance(start_time, str) else start_time.strftime("%H:%M"),
        end_time=end_time if isinstance(end_time, str) else end_time.strftime("%H:%M"),
        risk_multiple=f"{risk_multiple:.2f}",
        target_one_multiple=f"{target_one_multiple:.2f}",
        target_two_multiple=f"{target_two_multiple:.2f}",
    )


@app.route("/equity-previous-levels")
def equity_previous_levels():
    universe_mode = request.args.get("universe_mode", "nifty50")
    signal_view = request.args.get("signal_view", "actionable")
    raw_date = request.args.get("date", get_today_ist().isoformat())
    refresh_seconds = parse_refresh_seconds(request.args.get("refresh", "30"))

    error = None
    level_rows = []

    try:
        symbols = get_auto_previous_levels_universe(universe_mode)
        selected_date = parse_date(raw_date)

        if not symbols:
            raise ValueError("No eligible symbols were available for the selected universe.")
        creds = get_active_kite_credentials()
        if not creds["api_key"] or not creds["access_token"]:
            raise ValueError("Kite API key or access token is missing in .env.")

        all_level_rows, missing = get_previous_day_level_rows(symbols, selected_date)
        level_rows = filter_previous_level_rows(all_level_rows, signal_view)
        if missing:
            error = f"{len(missing)} symbols were skipped because previous-day levels could not be loaded for them."
    except Exception as exc:
        symbols = get_auto_previous_levels_universe(universe_mode)
        selected_date = raw_date
        error = str(exc)

    universe_labels = {option["key"]: option["label"] for option in get_previous_levels_universe_mode_options()}
    signal_labels = {option["key"]: option["label"] for option in get_previous_levels_signal_view_options()}
    refresh_label = "Off" if refresh_seconds == 0 else f"{refresh_seconds}s"

    return render_template_string(
        PD_LEVELS_TEMPLATE,
        level_rows=level_rows,
        summary=build_previous_levels_summary(level_rows),
        error=error,
        symbols=symbols,
        selected_date=selected_date if isinstance(selected_date, str) else selected_date.isoformat(),
        today_date=get_today_ist().isoformat(),
        yesterday_date=get_yesterday_ist().isoformat(),
        universe_mode=universe_mode,
        universe_label=universe_labels.get(universe_mode, "Nifty 50"),
        universe_mode_options=get_previous_levels_universe_mode_options(),
        signal_view=signal_view,
        signal_view_label=signal_labels.get(signal_view, "Breakouts + Breakdowns"),
        signal_view_options=get_previous_levels_signal_view_options(),
        refresh_options=get_refresh_options(),
        refresh_seconds=refresh_seconds,
        refresh_label=refresh_label,
    )


STOCK_HUB_SAMPLE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ seo_title }}</title>
  <meta name="description" content="{{ seo_description }}">
  <link rel="canonical" href="{{ canonical_url }}">
  <meta property="og:title" content="{{ seo_title }}">
  <meta property="og:description" content="{{ seo_description }}">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{{ canonical_url }}">
  <meta name="twitter:card" content="summary_large_image">
  <script type="application/ld+json">
  {{ schema_json|safe }}
  </script>
  <style>
    :root {
      --bg: #f4f6f8;
      --paper: #ffffff;
      --panel: #f8fafc;
      --panel-strong: #ffffff;
      --line: #d9e1e8;
      --ink: #1f2b38;
      --muted: #637182;
      --accent: #176f62;
      --accent-strong: #0e554b;
      --up-soft: #daf0e4;
      --up: #116d47;
      --down-soft: #f9dcdc;
      --down: #99353a;
      --warn-soft: #f6ebc5;
      --warn: #9a6c00;
      --info-soft: #dbe8fb;
      --info: #245fa7;
      --shadow: 0 18px 40px rgba(34, 38, 43, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(23,111,98,0.05), transparent 30%),
        radial-gradient(circle at bottom left, rgba(120,132,145,0.08), transparent 28%),
        var(--bg);
    }
    a { color: inherit; }
    .page {
      max-width: 1380px;
      margin: 0 auto;
      padding: 18px 14px 36px;
    }
    .microbar {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 14px;
    }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(280px, 0.65fr);
      gap: 16px;
      align-items: stretch;
    }
    .hero-main, .hero-side, .section, .ad-slot, .peer-table-wrap, .chart-shell, .insight-grid > div {
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 22px;
      box-shadow: var(--shadow);
    }
    .hero-main {
      padding: 20px 22px 18px;
      background: linear-gradient(145deg, #173549, #176f62 70%);
      color: #fff;
      overflow: hidden;
      position: relative;
    }
    .hero-main::after {
      content: "";
      position: absolute;
      right: -40px;
      bottom: -36px;
      width: 210px;
      height: 210px;
      border-radius: 50%;
      background: rgba(255,255,255,0.08);
    }
    .hero-kicker {
      font-size: 12px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      opacity: 0.86;
      margin-bottom: 10px;
    }
    .hero-head {
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: start;
      position: relative;
      z-index: 1;
    }
    h1 {
      margin: 0;
      font-size: 44px;
      line-height: 0.95;
    }
    .hero-sub {
      margin-top: 10px;
      font-size: 18px;
      color: rgba(255,255,255,0.84);
    }
    .hero-price {
      text-align: right;
      min-width: 210px;
    }
    .hero-ltp {
      font-size: 52px;
      font-weight: 700;
      line-height: 0.92;
      font-variant-numeric: tabular-nums;
    }
    .hero-change {
      margin-top: 10px;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.13);
      font-size: 18px;
      font-weight: 700;
    }
    .hero-tags {
      position: relative;
      z-index: 1;
      margin-top: 18px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .tag {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 7px 11px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.03em;
      white-space: nowrap;
    }
    .tag-up { background: var(--up-soft); color: var(--up); }
    .tag-down { background: var(--down-soft); color: var(--down); }
    .tag-warn { background: var(--warn-soft); color: var(--warn); }
    .tag-info { background: var(--info-soft); color: var(--info); }
    .hero-grid {
      position: relative;
      z-index: 1;
      margin-top: 18px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .hero-box {
      padding: 12px 12px 13px;
      border-radius: 16px;
      background: rgba(255,255,255,0.10);
      border: 1px solid rgba(255,255,255,0.12);
    }
    .hero-label {
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: rgba(255,255,255,0.74);
      margin-bottom: 4px;
    }
    .hero-value {
      font-size: 22px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }
    .hero-side {
      padding: 18px;
      display: grid;
      gap: 12px;
      align-content: start;
      background: linear-gradient(180deg, #ffffff, #f6f8fb);
    }
    .ad-slot {
      border-style: dashed;
      box-shadow: none;
      background: repeating-linear-gradient(
        -45deg,
        rgba(23,111,98,0.03),
        rgba(23,111,98,0.03) 10px,
        rgba(160,172,186,0.06) 10px,
        rgba(160,172,186,0.06) 20px
      ), var(--panel);
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      color: var(--muted);
      font-size: 14px;
      font-weight: 700;
      min-height: 86px;
      padding: 14px;
    }
    .ad-slot.tall { min-height: 220px; }
    .side-card {
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px 15px;
    }
    .side-title {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 8px;
      font-weight: 700;
    }
    .side-text {
      font-family: Arial, Helvetica, sans-serif;
      font-size: 14px;
      color: #324252;
      line-height: 1.55;
    }
    .section-nav {
      margin-top: 16px;
      display: flex;
      gap: 10px;
      overflow-x: auto;
      padding-bottom: 4px;
      scrollbar-width: thin;
    }
    .nav-chip {
      text-decoration: none;
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 10px 14px;
      white-space: nowrap;
      font-size: 13px;
      font-weight: 700;
      color: var(--accent-strong);
    }
    .layout {
      margin-top: 16px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(240px, 300px);
      gap: 16px;
      align-items: start;
    }
    .main-stack {
      display: grid;
      gap: 16px;
    }
    .section {
      padding: 18px 18px 16px;
    }
    .section h2 {
      margin: 0 0 6px;
      font-size: 28px;
    }
    .section-note {
      font-family: Arial, Helvetica, sans-serif;
      color: var(--muted);
      font-size: 14px;
      margin-bottom: 14px;
      line-height: 1.55;
    }
    .overview-grid, .insight-grid, .tech-grid, .financial-grid {
      display: grid;
      gap: 12px;
    }
    .overview-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .insight-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .tech-grid { grid-template-columns: 1.2fr 0.8fr; }
    .financial-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .metric-card, .insight-grid > div, .financial-row {
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--panel-strong);
      padding: 13px 14px;
    }
    .metric-label, .mini-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      font-weight: 700;
      margin-bottom: 6px;
    }
    .metric-value {
      font-size: 24px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }
    .metric-sub {
      margin-top: 6px;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--muted);
      font-size: 13px;
    }
    .chart-shell {
      background: linear-gradient(180deg, #102434, #14354a);
      color: #fff;
      padding: 14px;
      overflow: hidden;
    }
    .chart-head {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      margin-bottom: 10px;
    }
    .chart-title {
      font-size: 18px;
      font-weight: 700;
    }
    .chart-box {
      height: 280px;
      border-radius: 16px;
      position: relative;
      overflow: hidden;
      background:
        linear-gradient(to right, rgba(255,255,255,0.07) 1px, transparent 1px) 0 0 / 12.5% 100%,
        linear-gradient(to bottom, rgba(255,255,255,0.07) 1px, transparent 1px) 0 0 / 100% 20%,
        linear-gradient(180deg, rgba(18,58,82,0.95), rgba(7,19,28,0.95));
    }
    .chart-svg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
    }
    .chart-key {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 10px;
      font-family: Arial, Helvetica, sans-serif;
      font-size: 12px;
      color: rgba(255,255,255,0.82);
    }
    .key-dot {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 999px;
      margin-right: 6px;
    }
    .stats-stack {
      display: grid;
      gap: 10px;
    }
    .list-table, .peer-table {
      width: 100%;
      border-collapse: collapse;
      font-family: Arial, Helvetica, sans-serif;
      font-size: 14px;
    }
    .list-table th, .peer-table th {
      text-align: left;
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      border-bottom: 1px solid var(--line);
      padding: 9px 8px;
      white-space: nowrap;
    }
    .list-table td, .peer-table td {
      padding: 11px 8px;
      border-bottom: 1px solid rgba(215,203,180,0.72);
      font-variant-numeric: tabular-nums;
    }
    .list-table tr:last-child td, .peer-table tr:last-child td { border-bottom: none; }
    .peer-table-wrap { padding: 10px 12px 6px; overflow-x: auto; }
    .section-aside {
      display: grid;
      gap: 16px;
      position: sticky;
      top: 12px;
    }
    .quick-box {
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 16px;
      box-shadow: var(--shadow);
    }
    .quick-box h3 {
      margin: 0 0 10px;
      font-size: 22px;
    }
    .quick-list {
      display: grid;
      gap: 10px;
    }
    .quick-row {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      font-family: Arial, Helvetica, sans-serif;
      font-size: 14px;
      padding-bottom: 8px;
      border-bottom: 1px solid rgba(215,203,180,0.7);
    }
    .quick-row:last-child { border-bottom: none; padding-bottom: 0; }
    .muted {
      color: var(--muted);
      font-family: Arial, Helvetica, sans-serif;
    }
    .story-card {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      background: var(--panel-strong);
    }
    .story-card + .story-card { margin-top: 10px; }
    .story-title {
      font-family: Arial, Helvetica, sans-serif;
      font-size: 15px;
      font-weight: 700;
      margin-bottom: 4px;
    }
    .story-meta {
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 7px;
      font-family: Arial, Helvetica, sans-serif;
    }
    .story-copy {
      font-family: Arial, Helvetica, sans-serif;
      font-size: 14px;
      color: #334253;
      line-height: 1.55;
    }
    .footer-note {
      margin-top: 18px;
      padding: 14px 16px;
      border: 1px dashed var(--line);
      border-radius: 16px;
      background: rgba(255,255,255,0.92);
      color: var(--muted);
      font-size: 13px;
      line-height: 1.65;
      font-family: Arial, Helvetica, sans-serif;
    }
    @media (max-width: 1160px) {
      .hero, .layout, .tech-grid { grid-template-columns: 1fr; }
      .section-aside { position: static; }
    }
    @media (max-width: 880px) {
      .hero-head { flex-direction: column; }
      .hero-price { text-align: left; min-width: 0; }
      .hero-grid, .overview-grid, .financial-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .insight-grid { grid-template-columns: 1fr; }
      h1 { font-size: 36px; }
      .hero-ltp { font-size: 42px; }
    }
    @media (max-width: 620px) {
      .page { padding: 12px 10px 28px; }
      .hero-main, .hero-side, .section, .quick-box { border-radius: 18px; }
      .hero-grid, .overview-grid, .financial-grid { grid-template-columns: 1fr; }
      .section-nav { gap: 8px; }
      .nav-chip { padding: 9px 12px; }
      h1 { font-size: 30px; }
      .hero-ltp { font-size: 36px; }
      .chart-box { height: 230px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <div class="microbar">
      <div>Stocks &rsaquo; Telecom &rsaquo; {{ stock.symbol }} Research Page Sample</div>
      <div>SEO sample | No ads live yet | Last reviewed {{ today_date }}</div>
    </div>

    <div class="hero">
      <div class="hero-main">
        <div class="hero-kicker">TraderHub Stock Intelligence</div>
        <div class="hero-head">
          <div>
            <h1>{{ stock.symbol }}</h1>
            <div class="hero-sub">{{ stock.company_name }}</div>
            <div class="hero-sub">{{ stock.exchange }} | {{ stock.series }} Series | {{ stock.sector }} | {{ stock.industry }}</div>
          </div>
          <div class="hero-price">
            <div class="hero-ltp">{{ stock.ltp }}</div>
            <div class="hero-change">{{ stock.change_rupees }} | {{ stock.change_pct }}</div>
          </div>
        </div>
        <div class="hero-tags">
          {% for badge in hero_badges %}
          <span class="tag {{ badge.kind }}">{{ badge.label }}</span>
          {% endfor %}
        </div>
        <div class="hero-grid">
          <div class="hero-box"><div class="hero-label">Market Cap</div><div class="hero-value">{{ stock.market_cap }}</div></div>
          <div class="hero-box"><div class="hero-label">52W Range</div><div class="hero-value">{{ stock.range_52w }}</div></div>
          <div class="hero-box"><div class="hero-label">VWAP</div><div class="hero-value">{{ stock.vwap }}</div></div>
          <div class="hero-box"><div class="hero-label">Previous Close</div><div class="hero-value">{{ stock.prev_close }}</div></div>
        </div>
      </div>

      <div class="hero-side">
        <div class="ad-slot">Top Banner Sponsor Slot<br>Space for Ads</div>
        <div class="side-card">
          <div class="side-title">Page Purpose</div>
          <div class="side-text">This phase-1 sample is designed as a clean stock intelligence page: overview first, then technical, financials, peers, holdings, deals, and news. Layout is ad-ready without feeling ad-heavy on day one.</div>
        </div>
        <div class="side-card">
          <div class="side-title">SEO Notes</div>
          <div class="side-text">Single clear H1, stock-specific title, stock-specific description, canonical URL, schema JSON-LD, strong section headings, and readable structured content for future search visibility.</div>
        </div>
      </div>
    </div>

    <div class="section-nav">
      <a class="nav-chip" href="#overview">Overview</a>
      <a class="nav-chip" href="#technical">Technical</a>
      <a class="nav-chip" href="#financials">Financials</a>
      <a class="nav-chip" href="#peers">Peers</a>
      <a class="nav-chip" href="#ownership">Ownership & Deals</a>
      <a class="nav-chip" href="#news">News & Events</a>
    </div>

    <div class="layout">
      <div class="main-stack">
        <section class="section" id="overview">
          <h2>Overview</h2>
          <div class="section-note">A fast, uncluttered summary of the stock, its live position, and why it matters today. This section should become the default entry point for users who search for a specific company page.</div>
          <div class="overview-grid">
            {% for metric in overview_metrics %}
            <div class="metric-card">
              <div class="metric-label">{{ metric.label }}</div>
              <div class="metric-value">{{ metric.value }}</div>
              <div class="metric-sub">{{ metric.subtext }}</div>
            </div>
            {% endfor %}
          </div>
          <div class="footer-note">
            {{ stock.company_name }} is shown here as a sample profile. In the real version, this overview will be populated dynamically from live market data, reference data, and company master data.
          </div>
        </section>

        <section class="section" id="technical">
          <h2>Technical Snapshot</h2>
          <div class="section-note">Use this section to combine your current TraderHub strength: price context, levels, studies, and live chart-driven decision support. The chart is a sample visual placeholder in phase 1.</div>
          <div class="tech-grid">
            <div class="chart-shell">
              <div class="chart-head">
                <div class="chart-title">{{ stock.symbol }} Technical Chart Sample</div>
                <span class="tag tag-info">1D | Candles | VWAP + RSI later</span>
              </div>
              <div class="chart-box">
                <svg class="chart-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                  <polyline fill="none" stroke="#f8b84b" stroke-width="1.3" points="0,72 7,68 14,70 21,61 28,56 35,58 42,53 49,46 56,48 63,41 70,36 77,39 84,28 91,32 100,22"></polyline>
                  <polyline fill="none" stroke="#7ad7a7" stroke-width="1.1" points="0,78 7,73 14,72 21,65 28,62 35,61 42,59 49,54 56,51 63,49 70,45 77,43 84,39 91,37 100,34"></polyline>
                  <line x1="0" y1="40" x2="100" y2="40" stroke="#eb6b6b" stroke-width="0.7" stroke-dasharray="3 3"></line>
                  <line x1="0" y1="58" x2="100" y2="58" stroke="#5db0ff" stroke-width="0.7" stroke-dasharray="3 3"></line>
                  <line x1="0" y1="66" x2="100" y2="66" stroke="#9df1d4" stroke-width="0.7" stroke-dasharray="3 3"></line>
                </svg>
              </div>
              <div class="chart-key">
                <span><span class="key-dot" style="background:#f8b84b;"></span>Price path</span>
                <span><span class="key-dot" style="background:#7ad7a7;"></span>VWAP guide</span>
                <span><span class="key-dot" style="background:#eb6b6b;"></span>PDH</span>
                <span><span class="key-dot" style="background:#5db0ff;"></span>Prev close</span>
                <span><span class="key-dot" style="background:#9df1d4;"></span>Support band</span>
              </div>
            </div>

            <div class="stats-stack">
              {% for item in technical_metrics %}
              <div class="metric-card">
                <div class="metric-label">{{ item.label }}</div>
                <div class="metric-value">{{ item.value }}</div>
                <div class="metric-sub">{{ item.subtext }}</div>
              </div>
              {% endfor %}
            </div>
          </div>
        </section>

        <section class="section">
          <h2>Technical Studies</h2>
          <div class="section-note">This is where phase-1 can already look rich without overbuilding: short summaries, indicator values, moving-average view, and support/resistance levels.</div>
          <div class="insight-grid">
            {% for card in study_cards %}
            <div>
              <div class="mini-label">{{ card.label }}</div>
              <div class="metric-value" style="font-size:22px;">{{ card.value }}</div>
              <div class="metric-sub">{{ card.copy }}</div>
            </div>
            {% endfor %}
          </div>
          <div class="ad-slot" style="margin-top:14px;">Inline Sponsor Slot<br>Space for Ads</div>
        </section>

        <section class="section" id="financials">
          <h2>Financial Snapshot</h2>
          <div class="section-note">For phase 1, this should be summary-first rather than every line item. Users want quick quality clues first, then deeper balance-sheet and P&amp;L detail later.</div>
          <div class="financial-grid">
            {% for row in financial_metrics %}
            <div class="financial-row">
              <div class="metric-label">{{ row.label }}</div>
              <div class="metric-value" style="font-size:23px;">{{ row.value }}</div>
              <div class="metric-sub">{{ row.subtext }}</div>
            </div>
            {% endfor %}
          </div>
        </section>

        <section class="section" id="peers">
          <h2>Peer Group Comparison</h2>
          <div class="section-note">This comparison section is one of the biggest practical wins. It helps users understand whether the stock is expensive, stronger, or weaker than close competitors without leaving the page.</div>
          <div class="peer-table-wrap">
            <table class="peer-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Market Cap</th>
                  <th>P/E</th>
                  <th>ROE</th>
                  <th>Debt/Equity</th>
                  <th>1Y Return</th>
                </tr>
              </thead>
              <tbody>
                {% for peer in peers %}
                <tr>
                  <td>{{ peer.company }}</td>
                  <td>{{ peer.market_cap }}</td>
                  <td>{{ peer.pe }}</td>
                  <td>{{ peer.roe }}</td>
                  <td>{{ peer.de_ratio }}</td>
                  <td>{{ peer.return_1y }}</td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
        </section>

        <section class="section" id="ownership">
          <h2>Holdings, FII/DII, Deals</h2>
          <div class="section-note">This section combines ownership quality and market activity. It is inspired by India-focused stock pages, but presented in a cleaner layout.</div>
          <table class="list-table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Value</th>
                <th>Latest Signal</th>
              </tr>
            </thead>
            <tbody>
              {% for item in holdings_deals %}
              <tr>
                <td>{{ item.label }}</td>
                <td>{{ item.value }}</td>
                <td>{{ item.note }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </section>

        <section class="section" id="news">
          <h2>News & Events</h2>
          <div class="section-note">This is where earnings, management commentary, block deals, and major business updates should live. For the sample, it shows the intended card structure.</div>
          {% for story in news_items %}
          <div class="story-card">
            <div class="story-title">{{ story.title }}</div>
            <div class="story-meta">{{ story.meta }}</div>
            <div class="story-copy">{{ story.copy }}</div>
          </div>
          {% endfor %}
        </section>
      </div>

      <aside class="section-aside">
        <div class="quick-box">
          <h3>Quick Stats</h3>
          <div class="quick-list">
            {% for item in quick_stats %}
            <div class="quick-row">
              <span class="muted">{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
            {% endfor %}
          </div>
        </div>
        <div class="ad-slot tall">Right Rail Sponsor Slot<br>Space for Ads</div>
        <div class="quick-box">
          <h3>Why This Page Works</h3>
          <div class="side-text">
            It blends the breadth expected from Indian stock portals with the cleaner section hierarchy used by research-first platforms. The idea is to make one company page feel useful for both traders and investors.
          </div>
        </div>
      </aside>
    </div>
  </div>
</body>
</html>
"""


def get_stock_hub_sample_context():
    stock = {
        "symbol": "BHARTIARTL",
        "company_name": "Bharti Airtel Limited",
        "exchange": "NSE",
        "series": "EQ",
        "sector": "Telecom",
        "industry": "Telecommunications Service",
        "ltp": "1,768.40",
        "change_rupees": "+18.15",
        "change_pct": "+1.04%",
        "market_cap": "₹10.6 L Cr",
        "range_52w": "₹1,066 - ₹1,912",
        "vwap": "1,754.80",
        "prev_close": "1,750.25",
    }
    seo_title = "Bharti Airtel Share Price, Technicals, Financials, Peers & Deals | TraderHub Sample"
    seo_description = (
        "Explore a sample TraderHub stock intelligence page for Bharti Airtel with live-price style summary, "
        "technical snapshot, financial metrics, peer comparison, holdings, deals, and ad-ready SEO-friendly layout."
    )
    schema_json = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": seo_title,
            "description": seo_description,
            "url": "https://bot.traderhub.in/stock-hub-sample",
            "about": {
                "@type": "Corporation",
                "name": stock["company_name"],
                "tickerSymbol": stock["symbol"],
            },
        },
        indent=2,
    )
    return {
        "seo_title": seo_title,
        "seo_description": seo_description,
        "canonical_url": "https://bot.traderhub.in/stock-hub-sample",
        "schema_json": schema_json,
        "today_date": get_today_ist().isoformat(),
        "stock": stock,
        "hero_badges": [
            {"label": "Above VWAP", "kind": "tag-up"},
            {"label": "Near 52W High", "kind": "tag-warn"},
            {"label": "Telecom Leader", "kind": "tag-info"},
            {"label": "Strong Delivery Trend", "kind": "tag-up"},
        ],
        "overview_metrics": [
            {"label": "Open", "value": "1,742.00", "subtext": "Gap-up opening above previous close"},
            {"label": "Day Range", "value": "1,738 - 1,772", "subtext": "Holding near upper range"},
            {"label": "Volume", "value": "71.3 L", "subtext": "Above recent session average"},
            {"label": "Previous Day High / Low", "value": "1,756 / 1,718", "subtext": "Trading above prior breakout line"},
            {"label": "52W High / Low", "value": "1,912 / 1,066", "subtext": "Still within long-term leadership zone"},
            {"label": "Avg Volume", "value": "54.8 L", "subtext": "Useful for volume-spike interpretation"},
            {"label": "Business Summary", "value": "Pan-India telecom major", "subtext": "Wireless, broadband, enterprise, digital"},
            {"label": "Event Calendar", "value": "Results in 12 days", "subtext": "Earnings and telecom tariff watch"},
        ],
        "technical_metrics": [
            {"label": "Daily RSI", "value": "63.4", "subtext": "Positive momentum without extreme overbought pressure"},
            {"label": "MA View", "value": "Bullish", "subtext": "Price above 20DMA, 50DMA and 200DMA"},
            {"label": "Pivot Bias", "value": "R1 in focus", "subtext": "Bullish if support band holds intraday"},
            {"label": "Support / Resistance", "value": "1,742 / 1,781", "subtext": "Key short-term decision zone"},
        ],
        "study_cards": [
            {"label": "RSI (14)", "value": "63.4", "copy": "Momentum is constructive. Not overheated yet, but strong enough to support trend continuation."},
            {"label": "MACD", "value": "Bullish Crossover", "copy": "The structure suggests improving medium-term momentum and stronger follow-through probability."},
            {"label": "20 / 50 / 200 DMA", "value": "Above all 3", "copy": "This is the cleanest quick trend filter for investors and swing traders."},
            {"label": "Intraday Structure", "value": "Above VWAP", "copy": "This aligns well with your current TraderHub intraday logic and trade-plan workflow."},
            {"label": "PDH / PDL Context", "value": "PDH reclaimed", "copy": "A useful signal for continuation-style setups and market-watch routing."},
            {"label": "Technical Summary", "value": "Constructive", "copy": "The phase-1 page should compress many indicators into one practical sentence, not force users to decode everything manually."},
        ],
        "financial_metrics": [
            {"label": "Sales Growth", "value": "+10.8%", "subtext": "Recent annual revenue expansion remains healthy"},
            {"label": "Profit Growth", "value": "+14.2%", "subtext": "Margin discipline supporting earnings"},
            {"label": "ROE", "value": "17.6%", "subtext": "Comfortable profitability profile"},
            {"label": "ROCE", "value": "15.9%", "subtext": "Useful for capital efficiency comparison"},
            {"label": "Debt / Equity", "value": "1.62", "subtext": "Important to compare with telecom peer set"},
            {"label": "Book Value", "value": "₹233.40", "subtext": "Balance sheet anchor"},
            {"label": "EPS (TTM)", "value": "₹31.90", "subtext": "Core profitability metric"},
            {"label": "Operating Margin", "value": "24.7%", "subtext": "Operational quality snapshot"},
        ],
        "peers": [
            {"company": "Bharti Airtel", "market_cap": "₹10.6 L Cr", "pe": "55.4", "roe": "17.6%", "de_ratio": "1.62", "return_1y": "+41.8%"},
            {"company": "Reliance Jio proxy", "market_cap": "N/A", "pe": "N/A", "roe": "N/A", "de_ratio": "N/A", "return_1y": "N/A"},
            {"company": "Vodafone Idea", "market_cap": "₹89.7 K Cr", "pe": "Loss", "roe": "Negative", "de_ratio": "High", "return_1y": "-22.4%"},
            {"company": "Tata Communications", "market_cap": "₹52.1 K Cr", "pe": "41.8", "roe": "18.1%", "de_ratio": "0.19", "return_1y": "+12.5%"},
        ],
        "holdings_deals": [
            {"label": "Promoter Holding", "value": "53.1%", "note": "Stable promoter control profile"},
            {"label": "FII Holding", "value": "21.8%", "note": "Useful when foreign ownership trends are available"},
            {"label": "DII Holding", "value": "16.4%", "note": "Institutional domestic support remains relevant"},
            {"label": "Block / Bulk Deal Watch", "value": "No major fresh alert in sample", "note": "This zone should surface the newest notable deal first"},
            {"label": "Pledge", "value": "Nil / low sample", "note": "Important risk flag when real data is connected"},
        ],
        "news_items": [
            {
                "title": "Tariff and subscriber commentary remain central to sentiment",
                "meta": "Sample event note | Telecom theme | Research-style summary",
                "copy": "The real page should convert scattered headlines into a compact event summary. Traders care about immediate reaction; investors care about earnings impact and capital allocation."
            },
            {
                "title": "Institutional flows and large deals deserve visible placement",
                "meta": "Sample market-activity note | FII/DII | Deal flow",
                "copy": "If block deals or institutional holding changes are available, they should be shown near the ownership section rather than buried under unrelated content."
            },
            {
                "title": "Peer context can be a decisive user-retention feature",
                "meta": "Sample product note | Peer comparison | Stickiness",
                "copy": "One reason users stay on a stock page is that they can compare quality, valuation, and trend with the nearest alternatives without leaving the page."
            },
        ],
        "quick_stats": [
            {"label": "Exchange / Series", "value": "NSE / EQ"},
            {"label": "Sector", "value": "Telecom"},
            {"label": "Industry", "value": "Telecom Services"},
            {"label": "VWAP Position", "value": "Above VWAP"},
            {"label": "52W Context", "value": "Near upper zone"},
            {"label": "Phase-1 Ad Mode", "value": "Placeholders only"},
        ],
    }


@app.route("/stock-hub-sample")
def stock_hub_sample():
    return render_template_string(STOCK_HUB_SAMPLE_TEMPLATE, **get_stock_hub_sample_context())


@app.route("/api/equity-ohlc")
def equity_ohlc_api():
    raw_symbols = request.args.get("symbols", ",".join(DEFAULT_SYMBOLS))
    raw_date = request.args.get("date", get_today_ist().isoformat())
    raw_start = request.args.get("start", DEFAULT_START)
    raw_end = request.args.get("end", DEFAULT_END)

    symbols = parse_symbol_list(raw_symbols)
    selected_date = parse_date(raw_date)
    start_time = parse_time(raw_start, DEFAULT_START)
    end_time = parse_time(raw_end, DEFAULT_END)

    if not symbols:
        return jsonify({"error": "Please provide at least one NSE symbol."}), 400
    creds = get_active_kite_credentials()
    if not creds["api_key"] or not creds["access_token"]:
        return jsonify({"error": "Kite API key or access token is missing in .env."}), 500
    if end_time <= start_time:
        return jsonify({"error": "End time must be after start time."}), 400

    results, missing = get_equity_ohlc(symbols, selected_date, start_time, end_time)

    return jsonify(
        {
            "date": selected_date.isoformat(),
            "start": start_time.strftime("%H:%M"),
            "end": end_time.strftime("%H:%M"),
            "symbols": symbols,
            "missing_symbols": missing,
            "results": results,
        }
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=True)
