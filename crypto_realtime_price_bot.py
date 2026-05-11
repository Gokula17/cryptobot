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

SOL_WALLET = "3KfYUxGhqNWQYWuP1eQF8ipnGxayqTeuhz3SJ8gw2oYi"
MONTHLY_PRICE_SOL = 0.10

FREE_USERS = [8294085828]

# =====================================================
# FLASK (RENDER KEEP ALIVE)
# =====================================================

web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "Bot is running"

def run_web():
    web_app.run(host="0.0.0.0", port=10000)

threading.Thread(target=run_web).start()

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

    expiry = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
    return expiry > datetime.now()

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

PREMIUM CRYPTO BOT

COMMANDS:
/premium → Buy Premium
/verify → Verify Payment
/myplan → Check Plan
/myid → Get ID
/all → All USDT Coins

SEND SYMBOLS:
BTCUSDT
ETHUSDT
SOLUSDT
""")

# =====================================================
# MY ID
# =====================================================

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"YOUR ID: {update.effective_user.id}")

# =====================================================
# PREMIUM INFO
# =====================================================

async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"""
PRICE: {MONTHLY_PRICE_SOL} SOL

SEND TO:
{SOL_WALLET}

AFTER PAYMENT:
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
        await update.message.reply_text("ALREADY USED TRANSACTION")
        return

    try:
        url = f"https://public-api.solscan.io/transaction/{tx_hash}"
        r = requests.get(url, timeout=20)

        if r.status_code != 200:
            await update.message.reply_text("TRANSACTION NOT FOUND")
            return

        data = r.json()

        if "blockTime" not in data:
            await update.message.reply_text("INVALID TRANSACTION")
            return

        found = False
        paid = 0

        if "solTransfers" in data:
            for t in data["solTransfers"]:
                try:
                    if t.get("destination") == SOL_WALLET:
                        lamports = t.get("lamport", 0)
                        amount = lamports / 1e9

                        if amount >= MONTHLY_PRICE_SOL:
                            found = True
                            paid = amount
                            break
                except:
                    pass

        if not found:
            await update.message.reply_text("INSUFFICIENT PAYMENT")
            return

        cursor.execute("INSERT INTO used_transactions VALUES (?)", (tx_hash,))
        conn.commit()

        expiry = add_premium(user_id)

        await update.message.reply_text(f"""
PAYMENT VERIFIED

AMOUNT: {paid} SOL
PREMIUM ACTIVE UNTIL:
{expiry}
""")

    except Exception as e:
        await update.message.reply_text(f"ERROR: {e}")

# =====================================================
# MY PLAN
# =====================================================

async def myplan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in FREE_USERS:
        await update.message.reply_text("FREE PREMIUM ACTIVE")
        return

    cursor.execute("SELECT expiry_date FROM premium_users WHERE user_id=?", (user_id,))
    result = cursor.fetchone()

    if not result:
        await update.message.reply_text("NO ACTIVE PLAN")
        return

    await update.message.reply_text(f"EXPIRES: {result[0]}")

# =====================================================
# PRICE CHECK (SAFE)
# =====================================================

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_premium(user_id):
        await update.message.reply_text("PREMIUM REQUIRED")
        return

    symbol = update.message.text.upper().strip()

    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        r = requests.get(url, timeout=10)
        data = r.json()

        if "price" in data:
            await update.message.reply_text(f"{symbol}: {data['price']} USDT")
        else:
            await update.message.reply_text("INVALID SYMBOL")

    except Exception as e:
        await update.message.reply_text(f"ERROR: {e}")

# =====================================================
# ALL COINS (FIXED KEYERROR SAFE)
# =====================================================

async def all_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_premium(user_id):
        await update.message.reply_text("PREMIUM REQUIRED")
        return

    try:
        url = "https://api.binance.com/api/v3/exchangeInfo"
        r = requests.get(url, timeout=20)

        data = r.json()

        if "symbols" not in data:
            await update.message.reply_text(
                f"API ERROR: {data.get('msg', 'Unknown error')}"
            )
            return

        coins = [
            s["symbol"] for s in data["symbols"]
            if s["symbol"].endswith("USDT")
        ]

        coins.sort()

        chunk_size = 50
        for i in range(0, len(coins), chunk_size):
            await update.message.reply_text("\n".join(coins[i:i+chunk_size]))

    except Exception as e:
        await update.message.reply_text(f"ERROR: {e}")

# =====================================================
# MAIN (FIXED SYNTAX ERROR)
# =====================================================

def main():
    if not BOT_TOKEN:
        print("BOT_TOKEN not set in environment")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("premium", premium))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CommandHandler("myplan", myplan))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("all", all_coins))

    # ONLY valid USDT symbols
    app.add_handler(
        MessageHandler(
            filters.Regex("^[A-Z]{2,20}USDT$"),
            price
        )
    )

    print("BOT RUNNING...")
    app.run_polling()

# =====================================================
# RUN
# =====================================================

if __name__ == "__main__":
    main()
