import os
import requests
import sqlite3
import threading
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
# SESSION (IMPORTANT FOR RENDER)
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
    tx_hash TEXT PRIMARY KEY
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
# ADD PREMIUM
# =====================================================

def add_premium(user_id: int):
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

    await update.message.reply_text(
        f"""WELCOME {user.first_name}

📊 CRYPTO BOT (RENDER SAFE)

COMMANDS:
/premium
/verify TX_HASH
/myplan
/myid

Send:
BTCUSDT
ETHUSDT
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
# VERIFY PAYMENT
# =====================================================

async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text("Usage: /verify TX_HASH")
        return

    tx_hash = context.args[0]

    cursor.execute("SELECT tx_hash FROM used_transactions WHERE tx_hash=?", (tx_hash,))
    if cursor.fetchone():
        await update.message.reply_text("❌ Already used TX")
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
        amount_paid = 0

        for t in transfers:
            if t.get("destination") == SOL_WALLET:
                amount_paid = float(t.get("lamport", 0)) / 1e9
                if amount_paid >= MONTHLY_PRICE_SOL:
                    valid = True
                    break

        if not valid:
            await update.message.reply_text("❌ Payment insufficient")
            return

        cursor.execute("INSERT INTO used_transactions VALUES (?)", (tx_hash,))
        conn.commit()

        expiry = add_premium(user_id)

        await update.message.reply_text(
            f"""✅ VERIFIED
AMOUNT: {amount_paid} SOL
EXPIRES: {expiry}"""
        )

    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

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
# PRICE (RENDER SAFE HYBRID)
# =====================================================

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_premium(user_id):
        await update.message.reply_text("❌ Premium required")
        return

    try:
        symbol = update.message.text.upper().strip()

        # 1️⃣ TRY BINANCE MIRROR
        url = f"https://data-api.binance.vision/api/v3/ticker/price?symbol={symbol}"
        r = session.get(url, timeout=8)

        if r.status_code == 200:
            data = r.json()
            price = data.get("price")
            if price:
                await update.message.reply_text(f"{symbol}: ${price}")
                return

        # 2️⃣ FALLBACK COINGECKO
        coin = symbol.replace("USDT", "").lower()

        cg = session.get(
            f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd",
            timeout=10
        )

        cg_data = cg.json()

        price = cg_data.get(coin, {}).get("usd")

        if not price:
            await update.message.reply_text("❌ Price not found")
            return

        await update.message.reply_text(f"{symbol}: ${price} (fallback)")

    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

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

    # price handler
    app.add_handler(MessageHandler(filters.Regex("^[A-Z0-9]{2,15}$"), price))

    print("BOT RUNNING (RENDER SAFE)")
    app.run_polling()

# =====================================================
# RUN
# =====================================================

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    main()
