import os
from flask import Flask
import pandas as pd
import requests

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ذخیره زمان آخرین سیگنال جهت جلوگیری از ارسال پیام تکراری
last_signal_time = None


def send_telegram_message(message):
  if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    return
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
  try:
    requests.post(url, json=payload, timeout=10)
  except Exception as e:
    print(f"Error sending telegram: {e}")


@app.route("/")
def run_strategy():
  global last_signal_time

  try:
    # دریافت دیتای اسپات طلا (XAUUSD)
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

    # کندل‌های اخیر جهت بررسی الگوهای ستاره و دایره
    curr_candle = df.iloc[-2]  # آخرین کندل کامل بسته‌شده
    prev_candle = df.iloc[-3]  # کندل ماقبل آخر

    candle_time = str(curr_candle["timestamp"])

    c_close = round(float(curr_candle["close"]), 2)
    c_open = round(float(curr_candle["open"]), 2)
    c_high = round(float(curr_candle["high"]), 2)
    c_low = round(float(curr_candle["low"]), 2)

    p_close = round(float(prev_candle["close"]), 2)
    p_open = round(float(prev_candle["open"]), 2)
    p_high = round(float(prev_candle["high"]), 2)
    p_low = round(float(prev_candle["low"]), 2)

    # محاسبه پارامترهای کندل
    body_size = abs(c_close - c_open)
    candle_range = c_high - c_low if (c_high - c_low) > 0 else 0.001

    # 1. منطق ستاره خرید (⭐ Buy Star) - برگشت قوی صعودی بعد از کف
    star_buy = (c_close > c_open) and (c_close > p_high) and (c_low <= p_low)

    # 2. منطق ستاره فروش (⭐ Sell Star) - برگشت قوی نزولی بعد از سقف
    star_sell = (c_close < c_open) and (c_close < p_low) and (c_high >= p_high)

    # 3. منطق دایره سبز (🟢 Green Circle)
    green_circle = (c_close > c_open) and (body_size / candle_range >= 0.60)

    # 4. منطق دایره قرمز (🔴 Red Circle)
    red_circle = (c_close < c_open) and (body_size / candle_range >= 0.60)

    # بررسی ثبت سیگنال جدید
    if candle_time != last_signal_time:

      if star_buy:
        last_signal_time = candle_time
        send_telegram_message(
            f"⭐ **سیگنال ستاره خرید طلا (XAUUSD)**\n"
            f"قیمت اسپات: `{c_close}`\n"
            f"زمان کندل: `{candle_time}`"
        )
        return "Buy Star Alert Sent", 200

      elif star_sell:
        last_signal_time = candle_time
        send_telegram_message(
            f"⭐ **سیگنال ستاره فروش طلا (XAUUSD)**\n"
            f"قیمت اسپات: `{c_close}`\n"
            f"زمان کندل: `{candle_time}`"
        )
        return "Sell Star Alert Sent", 200

      elif green_circle:
        last_signal_time = candle_time
        send_telegram_message(
            f"🟢 **دایره سبز (خرید طلا - XAUUSD)**\n"
            f"قیمت اسپات: `{c_close}`"
        )
        return "Green Circle Sent", 200

      elif red_circle:
        last_signal_time = candle_time
        send_telegram_message(
            f"🔴 **دایره قرمز (فروش طلا - XAUUSD)**\n"
            f"قیمت اسپات: `{c_close}`"
        )
        return "Red Circle Sent", 200

    return "Checked - No New Signal", 200

  except Exception as e:
    return f"Error: {str(e)}", 500


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
