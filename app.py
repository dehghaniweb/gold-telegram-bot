import os
from flask import Flask
import pandas as pd
import requests
import yfinance as yf

app = Flask(__name__)

# اطلاعات ربات تلگرام خود را اینجا وارد کنید
TELEGRAM_BOT_TOKEN = "8728273739:AAFXg6QY4r33cF0tM1KSWswMQ3Ge32UuOJQ"
TELEGRAM_CHAT_ID = "167186163"


def send_telegram_message(message):
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
  try:
    requests.post(url, json=payload)
  except Exception as e:
    print(f"Error sending telegram: {e}")


@app.route("/")
def run_strategy():
  try:
    # دریافت دیتای طلای جهانی با نماد اسپات XAUUSD=X در بازه 5 دقیقه‌ای
    df = yf.download(
        tickers="XAUUSD=X", period="5d", interval="5m", progress=False
    )

    if df.empty:
      return "No data received", 500

    # اصلاح فرمت ستون‌ها در صورت چندبعدی بودن
    if isinstance(df.columns, pd.MultiIndex):
      df.columns = df.columns.droplevel(1)

    df = df.dropna()

    # محاسبه سقف و کف روزانه برای شبیه‌سازی منطق استراتژی شما
    df["Date"] = df.index.date
    daily_stats = df.groupby("Date").agg({"High": "max", "Low": "min"}).shift(1)
    df = df.join(daily_stats, on="Date", rsuffix="_daily")

    # بررسی آخرین کندل بسته‌شده
    last_candle = df.iloc[-2]
    close_p = float(last_candle["Close"])
    y_high = float(last_candle["High_daily"])
    y_low = float(last_candle["Low_daily"])

    # بررسی شرط‌های شکست سقف یا کف دیروز
    if not pd.isna(y_high) and float(last_candle["High"]) >= y_high:
      send_telegram_message(
          f"🚨 **سیگنال طلا (XAUUSD)**\n🔹 برخورد/شکست سقف دیروز\nقیمت فعلی: `{close_p}`"
      )
      return "Buy Alert Sent", 200

    elif not pd.isna(y_low) and float(last_candle["Low"]) <= y_low:
      send_telegram_message(
          f"🚨 **سیگنال طلا (XAUUSD)**\n🔸 برخورد/شکست کف دیروز\nقیمت فعلی: `{close_p}`"
      )
      return "Sell Alert Sent", 200

    return "Checked - No Signal", 200

  except Exception as e:
    return f"Error: {str(e)}", 500


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
