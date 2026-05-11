import telebot
import requests

TOKEN = "8435427608:AAFPstc0KQfDWg-MK2DBXb6g_rVVNKwueN4"

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(
        message,
        "Send coin symbol like BTC or ETH"
    )

@bot.message_handler(func=lambda m: True)
def price(message):

    coin = message.text.lower()

    coins = {
        "btc": "bitcoin",
        "eth": "ethereum",
        "sol": "solana"
    }

    if coin not in coins:
        bot.reply_to(message, "Coin not supported")
        return

    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coins[coin]}&vs_currencies=usd"

    data = requests.get(url).json()

    price = data[coins[coin]]["usd"]

    bot.reply_to(message, f"{coin.upper()} Price: ${price}")

bot.infinity_polling()