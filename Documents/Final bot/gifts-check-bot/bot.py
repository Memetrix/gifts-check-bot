import telebot
import asyncio
import os

from telethon.sync import TelegramClient
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest

# Загружаем переменные окружения
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")

# Инициализация Telebot и Telethon
bot = telebot.TeleBot(bot_token)
userbot = TelegramClient("userbot_session", api_id, api_hash)
userbot.start()

# Команда /start
@bot.message_handler(commands=["start"])
def start_message(message):
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🔍 Проверить подарки", callback_data="check_gifts"))
    bot.send_message(message.chat.id, "Привет! Нажми кнопку ниже, чтобы проверить свои подарки 🎁", reply_markup=markup)

# Обработка кнопки
@bot.callback_query_handler(func=lambda call: call.data == "check_gifts")
def handle_check(call):
    telegram_id = call.from_user.id

    try:
        async def check():
            user = await userbot.get_input_entity(telegram_id)
            result = await userbot(GetUserStarGiftsRequest(user_id=user, offset="", limit=100))

            knockdown_count = 0
            for g in result.gifts:
                data = g.to_dict()
                gift = data.get("gift")
                if not gift or "attributes" not in gift:
                    continue
                for attr in gift["attributes"]:
                    if "name" in attr and attr["name"].lower() == "knockdown":
                        knockdown_count += 1
                        break

            if knockdown_count >= 6:
                return f"✅ У тебя {knockdown_count} knockdown-подарков. Доступ разрешён!"
            else:
                return f"❌ У тебя только {knockdown_count} knockdown-подарков. Нужно минимум 6.\nПопробуй докупить на @mrkt"

        result_text = asyncio.run(check())
        bot.send_message(call.message.chat.id, result_text)

    except Exception as e:
        bot.send_message(call.message.chat.id, "⚠️ Ошибка при проверке подарков.")
        print("❌ Ошибка:", e)

print("🤖 Бот запущен и ожидает...")
bot.infinity_polling()