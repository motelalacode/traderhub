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
from app.symbol_resolver import load_symbol_master, resolve_symbol_list

APP_TZ = ZoneInfo("Asia/Kolkata")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ARBITRAGE_HISTORY_PATH = DATA_DIR / "arbitrage_history.json"
ARBITRAGE_VIRTUAL_STATE_PATH = DATA_DIR / "arbitrage_virtual_state.json"
ARBITRAGE_HISTORY_RETENTION_DAYS = 3
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
    master = load_symbol_master()
    nse_map = get_nse_instrument_map()
    bse_map = get_bse_instrument_map()
    common_symbols = []

    for symbol, row in master["by_symbol"].items():
        if row.get("series") != "EQ":
            continue
        if symbol not in nse_map or symbol not in bse_map:
            continue

        nse_series = str(nse_map[symbol].get("tradingsymbol") or "").upper()
        bse_series = str(bse_map[symbol].get("tradingsymbol") or "").upper()
        if nse_series and bse_series:
            common_symbols.append(symbol)

    return sorted(common_symbols)


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

    for symbol in eligible_symbols:
        nse_quote = quote_data.get(f"NSE:{symbol}")
        bse_quote = quote_data.get(f"BSE:{symbol}")
        if not nse_quote or not bse_quote:
            missing.append(symbol)
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
            continue

        capital_qty = math.floor(capital_amount / buy_price) if buy_price > 0 else 0
        tradable_qty = max(0, min(capital_qty, buy_qty_depth, sell_qty_depth))
        if tradable_qty <= 0:
            continue

        gross_profit_numeric = gross_spread_numeric * tradable_qty
        charges = estimate_cash_arbitrage_charges(buy_price * tradable_qty, sell_price * tradable_qty)
        net_profit_numeric = gross_profit_numeric - charges["total_charges"]
        if net_positive_only and net_profit_numeric <= 0:
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

    arbitrage_rows.sort(key=lambda row: row["net_profit_numeric"], reverse=True)
    skipped = [symbol for symbol in symbols if symbol not in common_symbols]
    missing.extend(skipped)
    return arbitrage_rows, sorted(set(missing))


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

        arbitrage_rows, missing = get_cash_arbitrage_rows(
            symbols,
            capital_amount,
            min_spread,
            net_positive_only,
        )
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
