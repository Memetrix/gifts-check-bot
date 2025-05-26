import os
import asyncio
import traceback
import telebot
from telethon import TelegramClient
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest
from db import is_approved, save_approved

# Конфигурация
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")
chat_id = int(os.getenv("CHAT_ID", "-1002655130461"))
session_file = "userbot_session"

bot = telebot.TeleBot(bot_token)
bot.skip_pending = True

# /start
@bot.message_handler(commands=["start"])
def start_message(message):
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🔍 Проверить подарки", callback_data="check_gifts"))
    bot.send_message(message.chat.id,
        "Привет! Я проверяю, есть ли у тебя минимум 6 knockdown‑подарков 🎁\n"
        "Нажми кнопку ниже, чтобы пройти проверку.",
        reply_markup=markup)

# Проверка knockdown-подарков
def check_knockdowns(user_id: int) -> (int, str):
    async def run():
        async with TelegramClient(session_file, api_id, api_hash) as client:
            try:
                await client.get_dialogs()
                entity = await client.get_input_entity(user_id)
                if not isinstance(entity, InputUser):
                    entity = InputUser(entity.user_id, entity.access_hash)

                result = await client(GetUserStarGiftsRequest(user_id=entity, offset="", limit=100))
                count = 0
                for g in result.gifts:
                    data = g.to_dict()
                    gift_data = data.get("gift")
                    if not gift_data or "title" not in gift_data or "slug" not in gift_data:
                        continue
                    for attr in gift_data.get("attributes", []):
                        if "name" in attr and attr["name"].lower() == "knockdown":
                            count += 1
                            break

                return count, getattr(entity, "username", None)
            except Exception as e:
                print(f"❌ Ошибка при проверке: {e}")
                return -1, None

    return asyncio.run(run())

# Кнопка
@bot.callback_query_handler(func=lambda call: call.data == "check_gifts")
def handle_check(call):
    user_id = call.from_user.id

    if is_approved(user_id):
        bot.send_message(call.message.chat.id,
            "✅ Ты уже прошёл проверку.\nЕсли у тебя есть доступ, не нужно генерировать ссылку повторно.")
        return

    try:
        count, username = check_knockdowns(user_id)

        if count == -1:
            bot.send_message(call.message.chat.id,
                "❗️Telegram не разрешает мне проверить твой профиль.\n"
                "Убедись, что ты подписан на @narrator или напиши боту в личку.")
            return

        if count >= 6:
            invite = bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
            bot.send_message(call.message.chat.id,
                f"✅ У тебя {count} knockdown-подарков. Доступ разрешён!\n"
                f"Вот твоя персональная ссылка:\n{invite.invite_link}")
            save_approved(user_id, username, count)
        else:
            bot.send_message(call.message.chat.id,
                f"❌ У тебя только {count} knockdown-подарков.\n"
                "Попробуй докупить недостающие на @mrkt.")
    except Exception:
        bot.send_message(call.message.chat.id, "⚠️ Внутренняя ошибка. Попробуй позже.")
        traceback.print_exc()

# 📊 /sumgifts — общее количество knockdown у участников
@bot.message_handler(commands=["sumgifts"])
def handle_sumgifts(message):
    user_id = message.from_user.id
    chat_id_tg = message.chat.id

    bot.send_message(chat_id_tg, "🔄 Считаю общее количество knockdown-подарков у участников...")

    async def run():
        total = 0
        async with TelegramClient(session_file, api_id, api_hash) as client:
            group = await client.get_entity(chat_id)
            async for user in client.iter_participants(group):
                try:
                    entity = InputUser(user.id, user.access_hash)
                    result = await client(GetUserStarGiftsRequest(user_id=entity, offset="", limit=100))
                    for g in result.gifts:
                        data = g.to_dict()
                        for attr in data["gift"].get("attributes", []):
                            if "name" in attr and attr["name"].lower() == "knockdown":
                                total += 1
                                break
                except:
                    continue

        bot.send_message(chat_id_tg, f"🎁 Общее количество knockdown-подарков: {total}")

    asyncio.run(run())

print("🤖 Бот запущен и готов считать подарки")
bot.infinity_polling(timeout=10, long_polling_timeout=5)
