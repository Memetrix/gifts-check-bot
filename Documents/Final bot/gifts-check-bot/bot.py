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
session_file = "cleaner-service/sessions/userbot_session"

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
    username = call.from_user.username

    # Если пользователь уже был одобрен ранее
    if is_approved(user_id):
        count, _ = check_knockdowns(user_id)
        if count < 6:
            bot.send_message(call.message.chat.id,
                "❌ Ты был верифицирован ранее, но сейчас у тебя меньше 6 knockdown-подарков.\n"
                "Пожалуйста, купи недостающие подарки на @mrkt.")
            return
        else:
            try:
                invite = bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
                bot.send_message(call.message.chat.id,
                    f"🔁 У тебя снова есть 6+ knockdown-подарков.\n"
                    f"Вот новая персональная ссылка:\n{invite.invite_link}")
                return
            except Exception as e:
                bot.send_message(call.message.chat.id, f"⚠️ Не удалось создать ссылку: {e}")
                return

    # Если пользователь не в базе — первая проверка
    try:
        count, _ = check_knockdowns(user_id)
        if count >= 6:
            invite = bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
            bot.send_message(call.message.chat.id,
                f"✅ У тебя {count} knockdown-подарков. Доступ разрешён!\n"
                f"Вот твоя персональная ссылка:\n{invite.invite_link}")
            save_approved(user_id, username, count)
        else:
            bot.send_message(call.message.chat.id,
                f"❌ У тебя только {count} knockdown-подарков.\n"
                "Пожалуйста, купи недостающие подарки на @mrkt.")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"⚠️ Ошибка при проверке: {e}")
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
