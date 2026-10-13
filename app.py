import os
from flask import Flask
import pandas as pd
import requests

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# حافظه موقت برای ذخیره وضعیت آخرین سیگنال تا پیام تکراری ارسال نشود
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
    # دریافت دیتای دقیق و اسپات طلا (XAUUSD) هم‌قیمت با تریدینگ‌ویو
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

    # بررسی کندل قبلی بسته‌شده (برای اطمینان از تثبیت دایره/سیگنال)
    last_candle = df.iloc[-2]
    candle_time = str(last_candle["timestamp"])
    close_p = round(float(last_candle["close"]), 2)
    open_p = round(float(last_candle["open"]), 2)
    high_p = round(float(last_candle["high"]), 2)
    low_p = round(float(last_candle["low"]), 2)

    # -------------------------------------------------------------
    # منطق دایره‌های استراتژی 27 در 5 دقیقه
    # -------------------------------------------------------------
    body_size = abs(close_p - open_p)
    candle_range = high_p - low_p

    # تشخیص دایره سبز (سیگنال خرید با کیفیّت کندل و چرخش)
    green_circle = (close_p > open_p) and (
        body_size >= candle_range * 0.55
    )  # کندل قدرتمند صعودی

    # تشخیص دایره قرمز (سیگنال فروش با کیفیّت کندل و چرخش)
    red_circle = (close_p < open_p) and (
        body_size >= candle_range * 0.55
    )  # کندل قدرتمند نزولی

    # ارسال پیام تنها در صورت شکل‌گیری دایره جدید (جلوگیری از پیام‌های تکراری ۵ دقیقه‌ای)
    if candle_time != last_signal_time:

      if green_circle:
        last_signal_time = candle_time
        send_telegram_message(
            f"🟢 **دایره سبز (سیگنال خرید طلا - XAUUSD)**\n"
            f"قیمت دقیق اسپات: `{close_p}`\n"
            f"تایم‌فریم: 5 دقیقه"
        )
        return f"Green Circle Alert Sent for {close_p}", 200

      elif red_circle:
        last_signal_time = candle_time
        send_telegram_message(
            f"🔴 **دایره قرمز (سیگنال فروش طلا - XAUUSD)**\n"
            f"قیمت دقیق اسپات: `{close_p}`\n"
            f"تایم‌فریم: 5 دقیقه"
        )
        return f"Red Circle Alert Sent for {close_p}", 200

    return "Checked - No New Circle Signal", 200

  except Exception as e:
    return f"Error: {str(e)}", 500


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
