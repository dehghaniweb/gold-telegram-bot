import json
import os
from flask import Flask
import pandas as pd
import requests

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

STATUS_FILE = "/tmp/last_signal_status.json"


def save_status(data):
  try:
    with open(STATUS_FILE, "w") as f:
      json.dump(data, f)
  except Exception as e:
    print(f"Error saving status: {e}")


def load_status():
  if os.path.exists(STATUS_FILE):
    try:
      with open(STATUS_FILE, "r") as f:
        return json.load(f)
    except:
      pass
  return {
      "signal": "هنوز سیگنالی ثبت نشده است",
      "price": 0,
      "time": "-",
      "ratio": 0,
  }


def send_telegram_message(message):
  if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    return False
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
  try:
    res = requests.post(url, json=payload, timeout=10)
    return res.status_code == 200
  except Exception as e:
    print(f"Error sending telegram: {e}")
    return False


@app.route("/")
def run_strategy():
  try:
    url = "https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD=X?interval=5m&range=2d"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=10)
    data = response.json()

    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]

    df = pd.DataFrame({
        "timestamp": pd.to_datetime(timestamps, unit="s"),
        "open": quote["open"],
        "high": quote["high"],
        "low": quote["low"],
        "close": quote["close"],
    }).dropna()

    if df.empty:
      return "No data received", 500

    curr_candle = df.iloc[-2]
    prev_candle = df.iloc[-3]

    candle_time = str(curr_candle["timestamp"])
    c_close = round(float(curr_candle["close"]), 2)
    c_open = round(float(curr_candle["open"]), 2)
    c_high = round(float(curr_candle["high"]), 2)
    c_low = round(float(curr_candle["low"]), 2)

    p_high = round(float(prev_candle["high"]), 2)
    p_low = round(float(prev_candle["low"]), 2)

    body_size = abs(c_close - c_open)
    candle_range = c_high - c_low if (c_high - c_low) > 0 else 0.001
    body_ratio = body_size / candle_range

    green_circle = (c_close > c_open) and (body_ratio >= 0.50)
    red_circle = (c_close < c_open) and (body_ratio >= 0.50)
    star_buy = (c_close > c_open) and (c_close > p_high) and (c_low <= p_low)
    star_sell = (c_close < c_open) and (c_close < p_low) and (c_high >= p_high)

    current_status = load_status()
    last_time = current_status.get("time", "")

    signal_name = "Checked - No New Signal"

    if candle_time != last_time:
      if star_buy:
        signal_name = "⭐ ستاره خرید طلا"
        send_telegram_message(
            f"⭐ **ستاره خرید طلا (XAUUSD)**\nقیمت اسپات: `{c_close}`\nزمان:"
            f" `{candle_time}`"
        )
      elif star_sell:
        signal_name = "⭐ ستاره فروش طلا"
        send_telegram_message(
            f"⭐ **ستاره فروش طلا (XAUUSD)**\nقیمت اسپات: `{c_close}`\nزمان:"
            f" `{candle_time}`"
        )
      elif green_circle:
        signal_name = "🟢 دایره سبز طلا"
        send_telegram_message(
            f"🟢 **دایره سبز طلا (XAUUSD)**\nقیمت اسپات: `{c_close}`\nزمان:"
            f" `{candle_time}`"
        )
      elif red_circle:
        signal_name = "🔴 دایره قرمز طلا"
        send_telegram_message(
            f"🔴 **دایره قرمز طلا (XAUUSD)**\nقیمت اسپات: `{c_close}`\nزمان:"
            f" `{candle_time}`"
        )

      if signal_name != "Checked - No New Signal":
        save_status({
            "signal": signal_name,
            "price": c_close,
            "time": candle_time,
            "ratio": round(body_ratio, 2),
        })

    return (
        f"Bot is Live & Active! Last Action: {signal_name} | Price: {c_close}",
        200,
    )

  except Exception as e:
    return f"Error: {str(e)}", 500


# صفحه اختصاصی برای دیدن آخرین وضعیت ربات با یک کلیک
@app.route("/status")
def status_page():
  st = load_status()
  return (
      f"<h2>📊 آخرین وضعیت ربات طلا (XAUUSD)</h2>"
      f"<p><b>آخرین سیگنال:</b> {st['signal']}</p>"
      f"<p><b>قیمت ثبت شده:</b> {st['price']}</p>"
      f"<p><b>زمان کندل:</b> {st['time']}</p>"
      f"<hr><p>سیستم کاملاً فعال و متصل به رندر است. ✅</p>"
  )


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
