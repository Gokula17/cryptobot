import os
import requests
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from flask import Flask

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =====================================================
# CONFIG
# =====================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

SOL_WALLET = "3KfYUxGhqNWQYWuP1QeF8ipnGxayqTeuhz3SJ8gw2oYi"
MONTHLY_PRICE_SOL = 0.10

FREE_USERS = {8294085828}

# =====================================================
# SESSION
# =====================================================

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
})

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
    tx_hash TEXT PRIMARY KEY,
    user_id INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS verify_attempts (
    user_id INTEGER PRIMARY KEY,
    last_try INTEGER
)
""")

conn.commit()

# =====================================================
# PREMIUM CHECK
# =====================================================

def is_premium(user_id: int):
    if user_id in FREE_USERS:
        return True

    cursor.execute("SELECT expiry_date FROM premium_users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()

    if not row:
        return False

    try:
        return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S") > datetime.now()
    except:
        return False

# =====================================================
# ADD / EXTEND PREMIUM
# =====================================================

def add_premium(user_id: int):
    cursor.execute("SELECT expiry_date FROM premium_users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()

    now = datetime.now()

    if row:
        try:
            current = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            expiry = current + timedelta(days=30) if current > now else now + timedelta(days=30)
        except:
            expiry = now + timedelta(days=30)
    else:
        expiry = now + timedelta(days=30)

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

    await update.message.reply_text(
        f"""WELCOME {user.first_name}

📊 CRYPTO BOT

COMMANDS:
/premium
/verify TX_HASH
/myplan
/myid
/all
/majorcoins

Send:
BTC / BTCUSDT / btc
ETH / ETHUSDT
"""
    )

# =====================================================
# MY ID
# =====================================================

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your ID: {update.effective_user.id}")

# =====================================================
# PREMIUM INFO
# =====================================================

async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"""💎 PREMIUM PLAN

PRICE: {MONTHLY_PRICE_SOL} SOL

SEND TO:
{SOL_WALLET}

VERIFY:
/verify TX_HASH
"""
    )

# =====================================================
# MY PLAN
# =====================================================

async def myplan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in FREE_USERS:
        await update.message.reply_text("🟢 FREE PLAN ACTIVE")
        return

    cursor.execute("SELECT expiry_date FROM premium_users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()

    if not row:
        await update.message.reply_text("❌ No active plan")
        return

    await update.message.reply_text(f"📅 Expires: {row[0]}")

# =====================================================
# VERIFY (SECURED)
# =====================================================

async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text("Usage: /verify TX_HASH")
        return

    tx_hash = context.args[0]

    # anti spam cooldown
    cursor.execute("SELECT last_try FROM verify_attempts WHERE user_id=?", (user_id,))
    row = cursor.fetchone()

    now = int(time.time())

    if row and now - row[0] < 10:
        await update.message.reply_text("⏳ Wait 10 seconds before retrying")
        return

    cursor.execute("""
        INSERT OR REPLACE INTO verify_attempts (user_id, last_try)
        VALUES (?, ?)
    """, (user_id, now))
    conn.commit()

    # check TX reuse
    cursor.execute("SELECT tx_hash FROM used_transactions WHERE tx_hash=?", (tx_hash,))
    if cursor.fetchone():
        await update.message.reply_text("❌ TX already used")
        return

    try:
        url = f"https://public-api.solscan.io/transaction/{tx_hash}"
        r = session.get(url, timeout=15)

        if r.status_code != 200:
            await update.message.reply_text("❌ TX not found")
            return

        data = r.json()
        transfers = data.get("solTransfers", [])

        valid = False
        amount = 0

        for t in transfers:
            if t.get("destination") == SOL_WALLET:
                amount = float(t.get("lamport", 0)) / 1e9
                if amount >= MONTHLY_PRICE_SOL:
                    valid = True
                    break

        if not valid:
            await update.message.reply_text("❌ Payment invalid or insufficient")
            return

        # bind TX to user (security)
        cursor.execute(
            "INSERT INTO used_transactions (tx_hash, user_id) VALUES (?, ?)",
            (tx_hash, user_id)
        )
        conn.commit()

        expiry = add_premium(user_id)

        await update.message.reply_text(
            f"""✅ VERIFIED

AMOUNT: {amount} SOL
EXPIRES: {expiry}
"""
        )

    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

# =====================================================
# PRICE (SMART INPUT)
# =====================================================

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_premium(user_id):
        await update.message.reply_text("❌ Premium required")
        return

    try:
        symbol = update.message.text.upper().replace("/", "").strip()

        if not symbol.endswith("USDT"):
            symbol += "USDT"

        url = f"https://data-api.binance.vision/api/v3/ticker/price?symbol={symbol}"
        r = session.get(url, timeout=8)

        if r.status_code == 200:
            price = r.json().get("price")
            if price:
                await update.message.reply_text(f"{symbol}: ${price}")
                return

        await update.message.reply_text("❌ Invalid symbol")

    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

# =====================================================
# ALL PAIRS
# =====================================================

async def all_pairs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_premium(update.effective_user.id):
        await update.message.reply_text("❌ Premium required")
        return

    r = session.get("https://data-api.binance.vision/api/v3/ticker/price")
    data = r.json()

    pairs = [x["symbol"] for x in data if x["symbol"].endswith("USDT")]

    msg = ""
    parts = []

    for s in pairs:
        if len(msg) > 3500:
            parts.append(msg)
            msg = ""
        msg += s + "\n"

    parts.append(msg)

    for p in parts[:5]:
        await update.message.reply_text(p)

# =====================================================
# MAJOR COINS
# =====================================================

async def majorcoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_premium(update.effective_user.id):
        await update.message.reply_text("❌ Premium required")
        return

    r = session.get("https://data-api.binance.vision/api/v3/ticker/price")
    data = {i["symbol"]: i["price"] for i in r.json()}

    coins = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
             "ADAUSDT","DOGEUSDT","TRXUSDT","AVAXUSDT","LINKUSDT"]

    msg = "🔥 MAJOR COINS\n\n"

    for c in coins:
        if c in data:
            msg += f"{c}: ${data[c]}\n"

    await update.message.reply_text(msg)

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
    app.add_handler(CommandHandler("all", all_pairs))
    app.add_handler(CommandHandler("majorcoins", majorcoins))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, price))

    print("BOT RUNNING")
    app.run_polling()

# =====================================================
# RUN
# =====================================================

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    main()
