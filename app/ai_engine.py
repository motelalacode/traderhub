# app/ai_engine.py
from app.config import GEMINI_KEY, OPENAI_KEY

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None


client = OpenAI(api_key=OPENAI_KEY) if OpenAI and OPENAI_KEY else None

if genai and GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)


def get_ai_insight(u, c, corr):
    prompt = (
        f"USDINR: {u}% | CRUDE: {c}% | Corr: {corr}\n"
        "Give 1-line professional trading insight."
    )

    if client:
        try:
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
            )
            return res.choices[0].message.content
        except Exception:
            pass

    if genai and GEMINI_KEY:
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            return model.generate_content(prompt).text
        except Exception:
            pass

    direction = "same direction" if (u >= 0 and c >= 0) or (u < 0 and c < 0) else "opposite direction"
    return (
        f"USDINR and crude moved in {direction}; "
        f"correlation snapshot is {corr:.2f} with changes {u:.2f}% and {c:.2f}%."
    )


def get_trade_setup_insight(symbol, orb_status, breakout_gap, vwap_status, volume_status):
    prompt = (
        f"Symbol: {symbol}\n"
        f"ORB status: {orb_status}\n"
        f"Breakout gap: {breakout_gap:.2f}\n"
        f"VWAP status: {vwap_status}\n"
        f"Volume status: {volume_status}\n"
        "Give one short intraday trading suggestion in plain English."
    )

    if client:
        try:
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
            )
            return res.choices[0].message.content
        except Exception:
            pass

    if genai and GEMINI_KEY:
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            return model.generate_content(prompt).text
        except Exception:
            pass

    if orb_status == "Above OR High" and vwap_status == "Above VWAP":
        return f"{symbol} is showing bullish intraday strength; watch for continuation while it stays above VWAP."
    if orb_status == "Below OR Low" and vwap_status == "Below VWAP":
        return f"{symbol} is showing bearish intraday weakness; watch for further downside while it stays below VWAP."
    return f"{symbol} is mixed intraday; wait for cleaner confirmation from price and volume before acting."
