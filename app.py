import os
from flask import Flask
import pandas as pd
import requests
import yfinance as yf

app = Flask(__name__)

# خواندن اطلاعات امنیتی از متغیرهای محیطی سرور (بدون لو رفتن در گیت‌هاب)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def send_telegram_message(message):
  if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print("Telegram credentials missing!")
    return
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
  try:
    requests.post(url, json=payload)
  except Exception as e:
    print(f"Error sending telegram: {e}")


@app.route("/")
def run_strategy():
  try:
    df = yf.download(
        tickers="XAUUSD=X", period="5d", interval="5m", progress=False
    )

    if df.empty:
      return "No data received", 500

    if isinstance(df.columns, pd.MultiIndex):
      df.columns = df.columns.droplevel(1)

    df = df.dropna()

    df["Date"] = df.index.date
    daily_stats = df.groupby("Date").agg({"High": "max", "Low": "min"}).shift(1)
    df = df.join(daily_stats, on="Date", rsuffix="_daily")

    last_candle = df.iloc[-2]
    close_p = float(last_candle["Close"])
    y_high = float(last_candle["High_daily"])
    y_low = float(last_candle["Low_daily"])

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
