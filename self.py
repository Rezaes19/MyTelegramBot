from telethon.sync import TelegramClient, events

api_id = 34996139
api_hash = "a1f3db16cae2919cfb05e61d1e968b8d"
bot_token = "8763155587:AAFyqwUzGx8VuQlfFWhknqfzmjyxM7zinyg"

bot = TelegramClient('bot', api_id, api_hash).start(bot_token=bot_token)

@bot.on(events.NewMessage(pattern='ping'))
async def ping(event):
    await event.reply('pong')

print("ربات روشنه!")
bot.run_until_disconnected()
