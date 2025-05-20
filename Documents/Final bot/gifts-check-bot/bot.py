import os
import telebot
import threading
import asyncio
from telethon import TelegramClient
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest

# Получаем переменные окружения
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")

bot = telebot.TeleBot(bot_token)

# Функция получения knockdown-подарков
def get_knockdown_count(user_id: int) -> int:
    # Создаём event loop вручную
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def inner():
        async with TelegramClient("userbot_session", api_id, api_hash) as client:
            entity = await client.get_input_entity(user_id)
            result = await client(GetUserStarGiftsRequest(user_id=entity, offset="", limit=100))

            count = 0
            for g in result.gifts:
                data = g.to_dict()
                gift = data.get("gift")
                if not gift or "attributes" not in gift:
                    continue
                for attr in gift["attributes"]:
                    if "name" in attr and attr["name"].lower() == "knockdown":
                        count += 1
                        break
            return count

    return loop.run_until_complete(inner())

# Обработка /start
@bot.message_handler(commands=["start"])
def start_message(message):
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🔍 Проверить подарки", callback_data="check_gifts"))
    bot.send_message(message.chat.id, "Привет! Нажми кнопку ниже, чтобы проверить свои подарки 🎁", reply_markup=markup)

# Обработка кнопки
@bot.callback_query_handler(func=lambda call: call.data == "check_gifts")
def handle_check(call):
    def run_check():
        user_id = call.from_user.id
        try:
            count = get_knockdown_count(user_id)
            if count >= 6:
                msg = f"✅ У тебя {count} knockdown-подарков. Доступ разрешён!"
            else:
                msg = f"❌ У тебя только {count} knockdown-подарков. Нужно минимум 6.\nПопробуй докупить на @mrkt"
            bot.send_message(call.message.chat.id, msg)
        except Exception as e:
            bot.send_message(call.message.chat.id, "⚠️ Ошибка при проверке подарков.")
            print("❌ Ошибка:", e)

    threading.Thread(target=run_check).start()

print("🤖 Бот запущен и ожидает...")
bot.infinity_polling()
