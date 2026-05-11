import os
import requests
import sqlite3
from datetime import datetime, timedelta
from flask import Flask
import threading

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# =====================================================
# CONFIG
# =====================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

SOL_WALLET = "3KfYUxGhqNWQYWuP1QeF8ipnGxayqTeuhz3SJ8gw2oYi"
MONTHLY_PRICE_SOL = 0.10

FREE_USERS = [8294085828]

# =====================================================
# FLASK KEEP ALIVE
# =====================================================

app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "BOT RUNNING"

def run_web():
    app_web.run(host="0.0.0.0", port=10000, debug=False, use_reloader=False)

# =====================================================
# DATABASE
# =====================================================

conn = sqlite3.connect("premium_users.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS premium_users (
    user_id INTEGER PRIMARY KEY,
    expiry_date TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS used_transactions (
    tx_hash TEXT PRIMARY KEY
)
""")

conn.commit()

# =====================================================
# PREMIUM CHECK
# =====================================================

def is_premium(user_id):
    if user_id in FREE_USERS:
        return True

    cursor.execute("SELECT expiry_date FROM premium_users WHERE user_id=?", (user_id,))
    result = cursor.fetchone()

    if not result:
        return False

    try:
        expiry = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
        return expiry > datetime.now()
    except:
        return False

# =====================================================
# ADD PREMIUM
# =====================================================

def add_premium(user_id):
    expiry = datetime.now() + timedelta(days=30)

    cursor.execute("""
        INSERT OR REPLACE INTO premium_users (user_id, expiry_date)
        VALUES (?, ?)
    """, (user_id, expiry.strftime("%Y-%m-%d %H:%M:%S")))

    conn.commit()
    return expiry

# =====================================================
# START
# =====================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    await update.message.reply_text(f"""
WELCOME {user.first_name}

CRYPTO BOT

COMMANDS:
/premium
/verify TX
/myplan
/myid
/all

SEND:
BTCUSDT
ETHUSDT
""")

# =====================================================
# MY ID
# =====================================================

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"ID: {update.effective_user.id}")

# =====================================================
# PREMIUM INFO
# =====================================================

async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"""
PRICE: {MONTHLY_PRICE_SOL} SOL

SEND TO:
{SOL_WALLET}

VERIFY:
/verify TX_HASH
""")

# =====================================================
# VERIFY PAYMENT
# =====================================================

async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if len(context.args) == 0:
        await update.message.reply_text("USAGE: /verify TX_HASH")
        return

    tx_hash = context.args[0]

    cursor.execute("SELECT tx_hash FROM used_transactions WHERE tx_hash=?", (tx_hash,))
    if cursor.fetchone():
        await update.message.reply_text("ALREADY USED")
        return

    try:
        url = f"https://public-api.solscan.io/transaction/{tx_hash}"
        r = requests.get(url, timeout=20)

        if r.status_code != 200:
            await update.message.reply_text("TX NOT FOUND")
            return

        data = r.json()

        if not isinstance(data, dict):
            await update.message.reply_text("INVALID TX")
            return

        found = False
        paid = 0

        transfers = data.get("solTransfers") or data.get("tokenTransfers") or []

        for t in transfers:
            if t.get("destination") == SOL_WALLET:
                amount = float(t.get("lamport", 0)) / 1e9
                if amount >= MONTHLY_PRICE_SOL:
                    found = True
                    paid = amount
                    break

        if not found:
            await update.message.reply_text("INSUFFICIENT PAYMENT")
            return

        cursor.execute("INSERT INTO used_transactions VALUES (?)", (tx_hash,))
        conn.commit()

        expiry = add_premium(user_id)

        await update.message.reply_text(f"""
PAYMENT VERIFIED
AMOUNT: {paid} SOL
EXPIRES: {expiry}
""")

    except Exception as e:
        await update.message.reply_text(f"ERROR: {str(e)}")

# =====================================================
# MY PLAN
# =====================================================

async def myplan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in FREE_USERS:
        await update.message.reply_text("FREE PLAN ACTIVE")
        return

    cursor.execute("SELECT expiry_date FROM premium_users WHERE user_id=?", (user_id,))
    result = cursor.fetchone()

    if not result:
        await update.message.reply_text("NO PLAN")
        return

    await update.message.reply_text(f"EXPIRES: {result[0]}")

# =====================================================
# PRICE CHECK
# =====================================================

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_premium(user_id):
        await update.message.reply_text("PREMIUM REQUIRED")
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
            await update.message.reply_text("INVALID SYMBOL")
            return

        await update.message.reply_text(f"{symbol}: {price} USDT")

    except:
        await update.message.reply_text("API ERROR")

# =====================================================
# ALL COINS
# =====================================================

async def all_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_premium(user_id):
        await update.message.reply_text("PREMIUM REQUIRED")
        return

    try:
        r = requests.get("https://api.binance.com/api/v3/exchangeInfo", timeout=20)
        data = r.json()

        symbols = data.get("symbols", [])

        coins = [
            s["symbol"] for s in symbols
            if s.get("symbol", "").endswith("USDT")
        ]

        await update.message.reply_text("\n".join(coins[:100]))

    except Exception as e:
        await update.message.reply_text(f"ERROR: {str(e)}")

# =====================================================
# MAIN
# =====================================================

def main():
    if not BOT_TOKEN:
        print("BOT_TOKEN missing")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("premium", premium))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CommandHandler("myplan", myplan))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("all", all_coins))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, price))

    print("BOT RUNNING...")
    app.run_polling()

# =====================================================
# RUN
# =====================================================

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    main()
