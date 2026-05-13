import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, redirect, render_template_string, request
from kiteconnect import KiteConnect

from app.config import ENV_PATH, KITE_API_KEY, KITE_API_SECRET, get_runtime_config

APP_TZ = ZoneInfo("Asia/Kolkata")
DEFAULT_SYMBOLS = ["IOC", "PNB"]
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


def is_market_open():
    now = datetime.datetime.now(APP_TZ).time()
    start = datetime.time(9, 0)
    end = datetime.time(15, 30)
    return start <= now <= end


def get_today_ist():
    return datetime.datetime.now(APP_TZ).date()


def get_yesterday_ist():
    return get_today_ist() - datetime.timedelta(days=1)


def parse_symbol_list(raw_symbols):
    values = [item.strip().upper() for item in raw_symbols.split(",")]
    return [item for item in values if item]


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


@app.route("/debug-kite")
def debug_kite():
    creds = get_active_kite_credentials()

    if not creds["api_key"]:
        return jsonify({"ok": False, "error": "KITE_API_KEY is missing in .env"}), 500
    if not creds["api_secret"]:
        return jsonify({"ok": False, "error": "KITE_API_SECRET is missing in .env"}), 500
    if not creds["access_token"]:
        return jsonify({"ok": False, "error": "KITE_ACCESS_TOKEN is missing in .env"}), 500

    try:
        debug_client = build_kite_client(with_access_token=True)
        profile = debug_client.profile()
        margins = debug_client.margins()

        return jsonify(
            {
                "ok": True,
                "message": "Zerodha credentials are valid.",
                "token_source": "memory" if CURRENT_ACCESS_TOKEN else "env",
                "profile": {
                    "user_id": profile.get("user_id"),
                    "user_name": profile.get("user_name"),
                    "email": profile.get("email"),
                    "broker": profile.get("broker"),
                },
                "margin_segments": list(margins.keys()) if isinstance(margins, dict) else [],
            }
        )
    except Exception as exc:
        return jsonify(
            {
                "ok": False,
                "error": str(exc),
                "token_source": "memory" if CURRENT_ACCESS_TOKEN else "env",
                "api_key_suffix": creds["api_key"][-4:] if creds["api_key"] else None,
                "access_token_suffix": creds["access_token"][-6:] if creds["access_token"] else None,
                "hint": "Login again from /login and confirm .env received a fresh KITE_ACCESS_TOKEN.",
            }
        ), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=True)
