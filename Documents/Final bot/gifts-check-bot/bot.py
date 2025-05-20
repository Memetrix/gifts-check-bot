import os
import telebot
import asyncio
import traceback
from telethon import TelegramClient
from telethon.tl.types import InputUserSelf
from get_user_star_gifts_request import GetUserStarGiftsRequest

# 📦 Переменные среды
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")

bot = telebot.TeleBot(bot_token)
bot.skip_pending = True

# 📥 Функция проверки по username
def check_knockdowns(username: str) -> str:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run():
        async with TelegramClient("userbot_session", api_id, api_hash) as client:
            if username:
                entity = await client.get_input_entity(username)
            else:
                entity = InputUserSelf()

            result = await client(GetUserStarGiftsRequest(user_id=entity, offset="", limit=100))

            knockdown_count = 0
            for g in result.gifts:
                data = g.to_dict()
                gift_data = data.get("gift")
                if not gift_data or "title" not in gift_data or "slug" not in gift_data:
                    continue
                for attr in gift_data.get("attributes", []):
                    if "name" in attr and attr["name"].lower() == "knockdown":
                        knockdown_count += 1
                        break

            if knockdown_count >= 6:
                return f"✅ У пользователя {username} {knockdown_count} knockdown-подарков. Доступ разрешён!"
            else:
                return f"❌ У пользователя {username} только {knockdown_count} knockdown-подарков. Нужно минимум 6."

    return loop.run_until_complete(run())

# 📥 Обработка текстовых сообщений
@bot.message_handler(func=lambda message: True)
def handle_username(message):
    username = message.text.strip()
    if not username.startswith("@"):
        bot.send_message(message.chat.id, "❗️Пожалуйста, отправь username в формате @username")
        return

    try:
        response = check_knockdowns(username)
        bot.send_message(message.chat.id, response)
    except Exception:
        bot.send_message(message.chat.id, "⚠️ Ошибка при проверке подарков.")
        traceback.print_exc()

print("🤖 MVP бот запущен. Ждёт сообщения...")
bot.infinity_polling()
