import os
import requests
import sqlite3
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")

FREE_USERS = {8294085828}

# ================= DB =================

conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS premium (
    user_id INTEGER PRIMARY KEY,
    expiry TEXT
)
""")

conn.commit()

# ================= PREMIUM CHECK =================

def is_premium(user_id):
    if user_id in FREE_USERS:
        return True

    cursor.execute("SELECT expiry FROM premium WHERE user_id=?", (user_id,))
    row = cursor.fetchone()

    if not row:
        return False

    try:
        return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S") > datetime.now()
    except:
        return False

# ================= ADD PREMIUM =================

def add_premium(user_id):
    expiry = datetime.now() + timedelta(days=30)

    cursor.execute("""
        INSERT OR REPLACE INTO premium (user_id, expiry)
        VALUES (?, ?)
    """, (user_id, expiry.strftime("%Y-%m-%d %H:%M:%S")))

    conn.commit()
    return expiry

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""
🚀 CRYPTO BOT

Commands:
/premium
/myplan
/all

👉 Send:
BTCUSDT
ETHUSDT
""")

# ================= PREMIUM =================

async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""
💎 PREMIUM PLAN

30 DAYS ACCESS
PRICE: 0.10 SOL
SEND TO WALLET AND VERIFY
""")

# ================= MY PLAN =================

async def myplan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in FREE_USERS:
        await update.message.reply_text("🟢 FREE USER")
        return

    cursor.execute("SELECT expiry FROM premium WHERE user_id=?", (user_id,))
    row = cursor.fetchone()

    if not row:
        await update.message.reply_text("❌ NO PLAN")
        return

    await update.message.reply_text(f"📅 EXPIRES: {row[0]}")

# ================= PRICE =================

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_premium(user_id):
        await update.message.reply_text("❌ PREMIUM REQUIRED")
        return

    symbol = update.message.text.upper().strip()

    try:
        r = requests.get(
            f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
            timeout=10
        )

        data = r.json()
        price = data.get("price")

        if not price:
            await update.message.reply_text("❌ INVALID SYMBOL")
            return

        await update.message.reply_text(f"📊 {symbol} = {price} USDT")

    except:
        await update.message.reply_text("❌ BINANCE ERROR")

# ================= CACHE FOR /ALL =================

CACHE = {
    "data": None,
    "time": None
}

# ================= /ALL FIXED =================

async def all_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_premium(user_id):
        await update.message.reply_text("❌ PREMIUM REQUIRED")
        return

    try:
        now = datetime.now()

        # cache 10 min
        if CACHE["data"] and CACHE["time"] and (now - CACHE["time"]).seconds < 600:
            symbols = CACHE["data"]
        else:
            r = requests.get("https://api.binance.com/api/v3/exchangeInfo", timeout=20)
            data = r.json()

            symbols = [
                s["symbol"]
                for s in data.get("symbols", [])
                if s.get("symbol", "").endswith("USDT")
                and s.get("status") == "TRADING"
            ]

            CACHE["data"] = symbols
            CACHE["time"] = now

        await update.message.reply_text(f"📊 TOTAL USDT PAIRS: {len(symbols)}")

        # safe send
        for i in range(0, len(symbols), 40):
            await update.message.reply_text("\n".join(symbols[i:i+40]))

    except Exception as e:
        await update.message.reply_text(f"ERROR: {str(e)}")

# ================= HANDLER =================

def main():
    if not BOT_TOKEN:
        print("BOT TOKEN MISSING")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("premium", premium))
    app.add_handler(CommandHandler("myplan", myplan))
    app.add_handler(CommandHandler("all", all_coins))

    # IMPORTANT: symbol handler last
    app.add_handler(MessageHandler(filters.Regex("^[A-Z0-9]{6,15}$"), price))

    print("BOT RUNNING...")
    app.run_polling()

# ================= RUN =================

if __name__ == "__main__":
    main()
