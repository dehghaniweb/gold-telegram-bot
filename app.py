import json
import os
from flask import Flask, request
import pandas as pd
import requests
import yfinance as yf

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


# بررسی خودکار بازار (توسط cron-job صدا زده می‌شود)
@app.route("/")
def run_strategy():
  try:
    ticker = yf.Ticker("GC=F")
    df = ticker.history(period="3d", interval="5m", progress=False)

    if df.empty:
      return "Data temporarily empty", 200

    if isinstance(df.columns, pd.MultiIndex):
      df.columns = df.columns.droplevel(1)

    df = df.dropna()
    if len(df) < 3:
      return "Not enough candles", 200

    curr_candle = df.iloc[-2]
    prev_candle = df.iloc[-3]

    candle_time = str(curr_candle.name)
    c_close = round(float(curr_candle["Close"]), 2)
    c_open = round(float(curr_candle["Open"]), 2)
    c_high = round(float(curr_candle["High"]), 2)
    c_low = round(float(curr_candle["Low"]), 2)

    p_high = round(float(prev_candle["High"]), 2)
    p_low = round(float(prev_candle["Low"]), 2)

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
            "text": "🔄 آخرین وضعیت بازار و قیمت",
            "callback_data": "check_status",
        }]]
    }

    if candle_time != str(last_time):
      if star_buy:
        signal_name = "⭐ ستاره خرید طلا"
        send_telegram_message(
            f"⭐ **ستاره خرید طلا (GC=F)**\nقیمت: `{c_close}`\nزمان:"
            f" `{candle_time}`",
            reply_markup=keyboard,
        )
      elif star_sell:
        signal_name = "⭐ ستاره فروش طلا"
        send_telegram_message(
            f"⭐ **ستاره فروش طلا (GC=F)**\nقیمت: `{c_close}`\nزمان:"
            f" `{candle_time}`",
            reply_markup=keyboard,
        )
      elif green_circle:
        signal_name = "🟢 دایره سبز طلا"
        send_telegram_message(
            f"🟢 **دایره سبز طلا (GC=F)**\nقیمت: `{c_close}`\nزمان:"
            f" `{candle_time}`",
            reply_markup=keyboard,
        )
      elif red_circle:
        signal_name = "🔴 دایره قرمز طلا"
        send_telegram_message(
            f"🔴 **دایره قرمز طلا (GC=F)**\nقیمت: `{c_close}`\nزمان:"
            f" `{candle_time}`",
            reply_markup=keyboard,
        )

      if signal_name != "Checked - No New Signal":
        save_status({
            "signal": signal_name,
            "price": c_close,
            "time": str(candle_time),
            "ratio": round(body_ratio, 2),
        })

    return f"Bot Active! Last Signal: {signal_name} | Price: {c_close}", 200

  except Exception as e:
    return f"Handled Exception: {str(e)}", 200


# دریافت پیام‌ها و کلیک‌ها از تلگرام (Webhook)
@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
  update = request.get_json()
  if not update:
    return "ok", 200

  keyboard = {
      "inline_keyboard": [[{
          "text": "🔄 آخرین وضعیت بازار و قیمت",
          "callback_data": "check_status",
      }]]
  }

  # اگر کاربر هر متنی به ربات فرستاد
  if "message" in update and "text" in update["message"]:
    chat_id = update["message"]["chat"]["id"]
    st = load_status()
    msg = (
        f"🤖 **ربات پایش طلا فعال است**\n\n"
        f"🎯 آخرین سیگنال: `{st['signal']}`\n"
        f"💰 قیمت ثبت شده: `{st['price']}`\n"
        f"⏱ زمان کندل: `{st['time']}`\n\n"
        f"برای دریافت آخرین وضعیت، روی دکمه زیر کلیک کنید:"
    )
    # ارسال پیام همراه با دکمه شیشه‌ای
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

  # اگر کاربر روی دکمه شیشه‌ای کلیک کرد
  elif "callback_query" in update:
    callback = update["callback_query"]
    st = load_status()
    try:
      ticker = yf.Ticker("GC=F")
      current_price = round(
          float(ticker.history(period="1d", interval="1m")["Close"].iloc[-1]),
          2,
      )
    except:
      current_price = st["price"]

    msg = (
        f"📊 **گزارش وضعیت لحظه‌ای طلا (GC=F)**\n\n"
        f"💵 قیمت لحظه‌ای: `{current_price}`\n"
        f"🎯 آخرین سیگنال: `{st['signal']}`\n"
        f"💰 قیمت زمان سیگنال: `{st['price']}`\n"
        f"⏱ زمان کندل: `{st['time']}`"
    )
    send_telegram_message(msg, reply_markup=keyboard)

  return "ok", 200


# صفحه وضعیت پشتیبان
@app.route("/status")
def status_page():
  st = load_status()
  return (
      f"<h2>📊 آخرین وضعیت ربات طلا</h2>"
      f"<p><b>آخرین سیگنال:</b> {st['signal']}</p>"
      f"<p><b>قیمت ثبت شده:</b> {st['price']}</p>"
  )


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
