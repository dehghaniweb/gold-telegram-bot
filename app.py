import json
import os

import pandas as pd
import requests
from flask import Flask, request

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

STATUS_FILE = "/tmp/last_signal_status.json"

# ---------------- تنظیمات منطبق با اندیکاتور TradingView ----------------
# شروع روز معاملاتی (در TradingView برای XAUUSD معمولا ساعت 17:00 نیویورک)
DAY_TZ = os.environ.get("DAY_TZ", "America/New_York")
DAY_ROLLOVER_HOUR = int(os.environ.get("DAY_ROLLOVER_HOUR", "17"))

ACTIVE_ZONE_DIST = 30.0  # همان 30 دلار در activeZone
BODY_MIN = 0.30  # strongBody
WICK_MIN = 0.10  # validLowerWick / validUpperWick
MAX_SIGNAL_AGE_MIN = 15  # فقط سیگنال‌های تازه ارسال می‌شوند
DISPLAY_TF = "5min"  # نمایش روی 5 دقیقه (هر 5 دقیقه حداکثر یک قرمز و یک سبز)

KEYBOARD = {
    "inline_keyboard": [[{
        "text": "🔄 آخرین وضعیت بازار و قیمت اسپات",
        "callback_data": "check_status",
    }]]
}


# ---------------- ذخیره وضعیت ----------------
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
        st = json.load(f)
        st.setdefault("sent", [])
        return st
    except Exception:
      pass
  return {
      "signal": "هنوز سیگنالی ثبت نشده است",
      "price": 0,
      "time": "-",
      "sent": [],
  }


# ---------------- قیمت اسپات ----------------
def get_live_spot_price():
  try:
    res = requests.get("https://api.gold-api.com/price/XAU", timeout=5)
    data = res.json()
    if "price" in data:
      return round(float(data["price"]), 2)
  except Exception:
    pass

  try:
    res = requests.get("https://data-asg.goldprice.org/dbjson/usd", timeout=5)
    price = res.json()["items"][0]["xauPrice"]
    if price:
      return round(float(price), 2)
  except Exception:
    pass

  return load_status().get("price", 0)


# ---------------- دریافت کندل‌های 1 دقیقه ----------------
# اولویت با نماد اسپات (XAUUSD=X)؛ اگر نبود فیوچرز (GC=F) با تطبیق اختلاف
SYMBOLS = [("XAUUSD=X", False), ("GC=F", True)]


def _fetch_symbol(symbol):
  url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
         "?interval=1m&range=5d")
  headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
  data = requests.get(url, headers=headers, timeout=10).json()
  result = data["chart"]["result"][0]
  quote = result["indicators"]["quote"][0]
  df = pd.DataFrame({
      "timestamp": pd.to_datetime(result["timestamp"], unit="s", utc=True),
      "open": quote["open"],
      "high": quote["high"],
      "low": quote["low"],
      "close": quote["close"],
  }).dropna()
  return df[(df["high"] > 0) & (df["low"] > 0)]


def fetch_candles_1m():
  for symbol, needs_offset in SYMBOLS:
    try:
      df = _fetch_symbol(symbol)
      if len(df) < 500:  # داده کافی نیست (حداقل 2-3 روز لازم است)
        continue
      for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
      if needs_offset:
        live_spot = get_live_spot_price()
        if live_spot and live_spot > 0:
          diff = live_spot - float(df["close"].iloc[-1])
          for col in ("open", "high", "low", "close"):
            df[col] = df[col] + diff
      # آخرین کندل هنوز بسته نشده (barstate.isconfirmed)
      df = df.iloc[:-1].reset_index(drop=True)
      df["local"] = df["timestamp"].dt.tz_convert(DAY_TZ)
      df.attrs["source"] = symbol
      return df
    except Exception:
      continue
  return pd.DataFrame()


# ---------------- موتور 1 دقیقه‌ای (ترجمه calc1m پاین) ----------------
def compute_signals(df):
  """
  خروجی: لیست رویدادها با type در {red, green, star_high, star_low}
  """
  df = df.copy()
  df["day"] = (df["local"] - pd.Timedelta(hours=DAY_ROLLOVER_HOUR)).dt.date
  stats = df.groupby("day").agg(h=("high", "max"), l=("low", "min"))
  days = list(stats.index)
  # روز اول داده ناقص است؛ high/low دیروز فقط از روز سوم به بعد معتبر است
  prev_of = {days[i]: days[i - 1] for i in range(2, len(days))}

  events = []

  cur_day = None
  high_touched = low_touched = False
  last_blue_low = last_yellow_high = None
  last_blue_bar = last_yellow_bar = None
  high_broken = low_broken = False
  last_circle = 0
  last_shown_red_high = last_shown_green_low = None
  prev_h = prev_l = None

  for i, row in enumerate(df.itertuples()):
    o, h, l, c = row.open, row.high, row.low, row.close

    # ---- روز جدید ----
    if row.day != cur_day:
      cur_day = row.day
      high_touched = low_touched = False
      last_blue_low = last_yellow_high = None
      last_blue_bar = last_yellow_bar = None
      high_broken = low_broken = False
      last_circle = 0
      last_shown_red_high = last_shown_green_low = None

    pday = prev_of.get(row.day)
    yh = float(stats.loc[pday, "h"]) if pday is not None else None
    yl = float(stats.loc[pday, "l"]) if pday is not None else None

    # ---- اولین لمس (ستاره) ----
    if yh is not None and not high_touched and h >= yh:
      high_touched = True
      events.append({"type": "star_high", "time": row.timestamp, "price": yh})
    if yl is not None and not low_touched and l <= yl:
      low_touched = True
      events.append({"type": "star_low", "time": row.timestamp, "price": yl})

    # ---- نفوذ به high/low دیروز + ناحیه فعال ----
    if yh is not None and h >= yh:
      high_broken = True
    if yl is not None and l <= yl:
      low_broken = True

    high_zone = high_broken and yh is not None and h >= yh - ACTIVE_ZONE_DIST
    low_zone = low_broken and yl is not None and l <= yl + ACTIVE_ZONE_DIST
    active = high_zone or low_zone

    # ---- کیفیت کندل ----
    rng = h - l
    body = abs(c - o)
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    strong_body = rng > 0 and body / rng >= BODY_MIN
    valid_lower = rng > 0 and lower_wick / rng >= WICK_MIN
    valid_upper = rng > 0 and upper_wick / rng >= WICK_MIN
    have_prev = prev_h is not None

    # ---- آبی / زرد ----
    blue = (active and rng > 0 and have_prev and c > o and l < prev_l
            and h > prev_h and strong_body and valid_lower)
    yellow = (active and rng > 0 and have_prev and c < o and h > prev_h
              and l < prev_l and strong_body and valid_upper)

    if blue:
      last_blue_low = l
      last_blue_bar = i
    if yellow:
      last_yellow_high = h
      last_yellow_bar = i

    # ---- قرمز / سبز ----
    red_big = (active and last_blue_low is not None
               and last_yellow_bar is not None and last_blue_bar is not None
               and last_yellow_bar > last_blue_bar and i > last_yellow_bar
               and l <= last_blue_low)
    green_big = (active and last_yellow_high is not None
                 and last_blue_bar is not None and last_yellow_bar is not None
                 and last_blue_bar > last_yellow_bar and i > last_blue_bar
                 and h >= last_yellow_high)

    red_new = red_big and (last_circle != 1 or last_shown_red_high is None
                           or h > last_shown_red_high)
    green_new = green_big and (last_circle != -1
                               or last_shown_green_low is None
                               or l < last_shown_green_low)

    if red_new:
      last_circle = 1
      last_shown_red_high = h
      last_shown_green_low = None
      events.append({"type": "red", "time": row.timestamp, "price": h})
    if green_new:
      last_circle = -1
      last_shown_green_low = l
      last_shown_red_high = None
      events.append({"type": "green", "time": row.timestamp, "price": l})

    prev_h, prev_l = h, l

  return events


def build_alerts(events):
  """مثل نمایش 5 دقیقه‌ای: در هر کندل 5 دقیقه از هر نوع آخرین رویداد"""
  buckets = {}
  for ev in events:
    b = ev["time"].floor(DISPLAY_TF)
    buckets[(ev["type"], b)] = ev
  alerts = []
  for (typ, b), ev in buckets.items():
    alerts.append({**ev, "bucket": b, "key": f"{typ}@{b.isoformat()}"})
  alerts.sort(key=lambda a: a["time"])
  return alerts


LABELS = {
    "red": "🔴 دایره قرمز اسپات طلا",
    "green": "🟢 دایره سبز اسپات طلا",
    "star_high": "⭐ لمس high دیروز (ستاره بالا)",
    "star_low": "⭐ لمس low دیروز (ستاره پایین)",
}


def fmt_time(ts):
  return ts.tz_convert("Asia/Tehran").strftime("%Y-%m-%d %H:%M")


def when_text(ts):
  """«امروز ساعت 14:05» / «دیروز ساعت 23:10» / تاریخ کامل (به وقت تهران)"""
  t = ts.tz_convert("Asia/Tehran")
  now = pd.Timestamp.now(tz="Asia/Tehran")
  delta = (now.normalize() - t.normalize()).days
  hm = t.strftime("%H:%M")
  if delta == 0:
    return f"امروز ساعت {hm}"
  if delta == 1:
    return f"دیروز ساعت {hm}"
  return f"{t.strftime('%Y-%m-%d')} ساعت {hm}"


def verification_report():
  """آخرین ستاره / سبز / قرمز با زمان تهران (برای صحت‌سنجی با چارت)"""
  df = fetch_candles_1m()
  if df.empty or len(df) < 10:
    return "⚠️ داده‌ی کندل در دسترس نیست."
  events = compute_signals(df)

  def last(types):
    evs = [e for e in events if e["type"] in types]
    return evs[-1] if evs else None

  def line(title, ev):
    if not ev:
      return f"{title}: در ۵ روز اخیر ثبت نشده"
    return f"{title}: {when_text(ev['time'])} (قیمت `{round(ev['price'], 2)}`)"

  return "\n".join([
      "🔎 **صحت‌سنجی (وقت تهران)**",
      line("⭐ آخرین ستاره", last(("star_high", "star_low"))),
      line("🟢 آخرین سبز", last(("green",))),
      line("🔴 آخرین قرمز", last(("red",))),
      f"📡 منبع داده: `{df.attrs.get('source', '?')}`",
  ])


# ---------------- مسیر اصلی (پینگ دوره‌ای) ----------------
@app.route("/")
def run_strategy():
  try:
    df = fetch_candles_1m()
    if df.empty or len(df) < 10:
      return "Data temporarily empty", 200

    events = compute_signals(df)
    alerts = build_alerts(events)

    cutoff = df["timestamp"].iloc[-1] - pd.Timedelta(minutes=MAX_SIGNAL_AGE_MIN)
    st = load_status()
    sent = set(st.get("sent", []))
    new_sent = False

    for a in alerts:
      if a["time"] < cutoff or a["key"] in sent:
        continue
      price = round(a["price"], 2)
      name = LABELS[a["type"]]
      send_telegram_message(
          f"{name} (XAUUSD)\nقیمت: `{price}`\nزمان (تهران): `{fmt_time(a['time'])}`",
          reply_markup=KEYBOARD,
      )
      sent.add(a["key"])
      new_sent = True
      st["signal"] = name
      st["price"] = price
      st["time"] = fmt_time(a["time"])

    if new_sent:
      st["sent"] = sorted(sent)[-200:]
      save_status(st)

    return f"Bot Active! Price: {get_live_spot_price()}", 200
  except Exception as e:
    return f"Handled Exception: {str(e)}", 200


def send_telegram_message(message, reply_markup=None, chat_id=None):
  chat_id = chat_id or TELEGRAM_CHAT_ID
  if not TELEGRAM_BOT_TOKEN or not chat_id:
    return False
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
  if reply_markup:
    payload["reply_markup"] = reply_markup
  try:
    return requests.post(url, json=payload, timeout=10).json()
  except Exception:
    return False


def status_text(title):
  st = load_status()
  live_p = get_live_spot_price()
  return (
      f"{title}\n\n"
      f"💵 قیمت لحظه‌ای اسپات: `{live_p}`\n"
      f"🎯 آخرین سیگنال: `{st['signal']}`\n"
      f"💰 قیمت زمان سیگنال: `{st['price']}`\n"
      f"⏱ زمان کندل: `{st['time']}`\n\n"
      f"{verification_report()}"
  )


@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
  update = request.get_json()
  if not update:
    return "ok", 200

  if "message" in update and "text" in update["message"]:
    chat_id = update["message"]["chat"]["id"]
    send_telegram_message(
        status_text("🤖 **ربات پایش اسپات طلا (XAUUSD)**"),
        reply_markup=KEYBOARD,
        chat_id=chat_id,
    )
  elif "callback_query" in update:
    cq = update["callback_query"]
    try:
      requests.post(
          f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
          json={"callback_query_id": cq["id"]},
          timeout=5,
      )
    except Exception:
      pass
    chat_id = cq.get("message", {}).get("chat", {}).get("id")
    send_telegram_message(
        status_text("📊 **گزارش وضعیت لحظه‌ای اسپات طلا (XAUUSD)**"),
        reply_markup=KEYBOARD,
        chat_id=chat_id,
    )
  return "ok", 200


@app.route("/status")
def status_page():
  st = load_status()
  live_p = get_live_spot_price()
  return (
      f"<h2>📊 آخرین وضعیت ربات اسپات طلا (XAUUSD)</h2>"
      f"<p><b>قیمت لحظه‌ای اسپات:</b> {live_p}</p>"
      f"<p><b>آخرین سیگنال:</b> {st['signal']}</p>"
      f"<pre style='white-space:pre-wrap'>{verification_report().replace('`', '').replace('**', '')}</pre>"
  )


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
