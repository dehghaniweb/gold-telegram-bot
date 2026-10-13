import json
import os
from flask import Flask, request
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
  except Exception:
    pass


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


def fetch_spot_data(interval="5m", range_val="3d"):
  """دریافت کندل‌های اسپات طلا (XAUUSD=X) مستقیماً از یاهو با هدرهای مرورگر"""
  url = f"https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD=X?interval={interval}&range={range_val}"
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/122.0.0.0 Safari/537.36"
      ),
      "Accept": "application/json",
      "Referer": "https://finance.yahoo.com",
  }
  try:
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
    return df
  except Exception:
    return pd.DataFrame()


def get_live_spot_price():
  """دریافت قیمت لحظه‌ای اسپات طلا"""
  df = fetch_spot_data(interval="1m", range_val="1d")
  if not df.empty:
    return round(float(df["close"].iloc[-1]), 2)
  st = load_status()
  return st.get("price", 0)


# بررسی خودکار بازار روی اسپات طلا (XAUUSD)
@app.route("/")
def run_strategy():
  try:
    df = fetch_spot_data(interval="5m", range_val="3d")

    if df.empty:
      return "Data temporarily empty", 200

    if len(df) < 3:
      return "Not enough candles", 200

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
    keyboard = {
        "inline_keyboard": [[{
            "text": "🔄 آخرین وضعیت بازار و قیمت اسپات",
            "callback_data": "check_status",
        }]]
    }

    if candle_time != str(last_time):
      if star_buy:
        signal_name = "⭐ ستاره خرید اسپات طلا"
        send_telegram_message(
            f"⭐ **ستاره خرید اسپات طلا (XAUUSD)**\nقیمت:"
            f" `{c_close}`\nزمان: `{candle_time}`",
            reply_markup=keyboard,
        )
      elif star_sell:
        signal_name = "⭐ ستاره فروش اسپات طلا"
        send_telegram_message(
            f"⭐ **ستاره فروش اسپات طلا (XAUUSD)**\nقیمت:"
            f" `{c_close}`\nزمان: `{candle_time}`",
            reply_markup=keyboard,
        )
      elif green_circle:
        signal_name = "🟢 دایره سبز اسپات طلا"
        send_telegram_message(
            f"🟢 **دایره سبز اسپات طلا (XAUUSD)**\nقیمت:"
            f" `{c_close}`\nزمان: `{candle_time}`",
            reply_markup=keyboard,
        )
      elif red_circle:
        signal_name = "🔴 دایره قرمز اسپات طلا"
        send_telegram_message(
            f"🔴 **دایره قرمز اسپات طلا (XAUUSD)**\nقیمت:"
            f" `{c_close}`\nزمان: `{candle_time}`",
            reply_markup=keyboard,
        )

      if signal_name != "Checked - No New Signal":
        save_status({
            "signal": signal_name,
            "price": c_close,
            "time": str(candle_time),
            "ratio": round(body_ratio, 2),
        })

    return f"Bot Active (Spot XAUUSD)! Last Signal: {signal_name} | Price: {c_close}", 200

  except Exception as e:
    return f"Handled Exception: {str(e)}", 200


def send_telegram_message(message, reply_markup=None):
  if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    return False
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {
      "chat_id": TELEGRAM_CHAT_ID,
      "text": message,
      "parse_mode": "Markdown",
  }
  if reply_markup:
    payload["reply_markup"] = reply_markup
  try:
    res = requests.post(url, json=payload, timeout=10)
    return res.json()
  except Exception:
    return False


# دریافت پیام‌ها و کلیک‌ها از تلگرام (Webhook)
@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
  update = request.get_json()
  if not update:
    return "ok", 200

  keyboard = {
      "inline_keyboard": [[{
          "text": "🔄 آخرین وضعیت بازار و قیمت اسپات",
          "callback_data": "check_status",
      }]]
  }

  if "message" in update and "text" in update["message"]:
    chat_id = update["message"]["chat"]["id"]
    st = load_status()
    live_p = get_live_spot_price()
    msg = (
        f"🤖 **ربات پایش اسپات طلا (XAUUSD)**\n\n"
        f"💵 قیمت لحظه‌ای اسپات: `{live_p}`\n"
        f"🎯 آخرین سیگنال: `{st['signal']}`\n"
        f"💰 قیمت زمان سیگنال: `{st['price']}`\n"
        f"⏱ زمان کندل: `{st['time']}`"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "Markdown",
            "reply_markup": keyboard,
        },
    )

  elif "callback_query" in update:
    st = load_status()
    live_p = get_live_spot_price()

    msg = (
        f"📊 **گزارش وضعیت لحظه‌ای اسپات طلا (XAUUSD)**\n\n"
        f"💵 قیمت لحظه‌ای اسپات: `{live_p}`\n"
        f"🎯 آخرین سیگنال: `{st['signal']}`\n"
        f"💰 قیمت زمان سیگنال: `{st['price']}`\n"
        f"⏱ زمان کندل: `{st['time']}`"
    )
    send_telegram_message(msg, reply_markup=keyboard)

  return "ok", 200


@app.route("/status")
def status_page():
  st = load_status()
  live_p = get_live_spot_price()
  return (
      f"<h2>📊 آخرین وضعیت ربات اسپات طلا (XAUUSD)</h2>"
      f"<p><b>قیمت لحظه‌ای اسپات:</b> {live_p}</p>"
      f"<p><b>آخرین سیگنال:</b> {st['signal']}</p>"
  )


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
