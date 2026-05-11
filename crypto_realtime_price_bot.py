import telebot
import requests

TOKEN = "8435427608:AAFPstc0KQfDWg-MK2DBXb6g_rVVNKwueN4"
bot = telebot.TeleBot(TOKEN)

# Start command
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(
        message,
        "Send coin symbol like BTC or ETH"
    )

# Price checker
@bot.message_handler(func=lambda message: True)
def get_price(message):

    try:

        text = message.text.upper()

        coins = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana"
        }

        if text not in coins:
            bot.reply_to(message, "Coin not supported")
            return

        coin_id = coins[text]

        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"

        response = requests.get(url)

        data = response.json()

        price = data[coin_id]["usd"]

        bot.reply_to(
            message,
            f"{text} Price: ${price}"
        )

    except Exception as e:
        print(e)
        bot.reply_to(message, "Error getting price")

print("Bot Started...")

bot.infinity_polling()
