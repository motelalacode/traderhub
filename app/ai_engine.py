# app/ai_engine.py
import openai
import google.generativeai as genai
from config import OPENAI_KEY, GEMINI_KEY

openai.api_key = OPENAI_KEY
genai.configure(api_key=GEMINI_KEY)

def get_ai_insight(u, c, corr):
    prompt = f"""
    USDINR: {u}% | CRUDE: {c}% | Corr: {corr}
    Give 1-line professional trading insight.
    """

    try:
        res = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        return res['choices'][0]['message']['content']

    except:
        model = genai.GenerativeModel("gemini-pro")
        return model.generate_content(prompt).text