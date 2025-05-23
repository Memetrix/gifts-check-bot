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

# Проверка knockdown-подарков по user_id (с fallback на username)
def check_knockdowns(user_id: int, username: str = None) -> (int, str):
    async def run():
        async with TelegramClient(session_file, api_id, api_hash) as client:
            try:
                await client.get_dialogs()
                entity = await client.get_input_entity(user_id)
                print(f"✅ get_input_entity(user_id) сработал: {entity}")
            except Exception as e:
                print(f"⚠️ get_input_entity(user_id) не сработал: {e}")
                if username:
                    try:
                        entity = await client.get_input_entity(f"@{username}")
                        print(f"✅ fallback через @username сработал: {entity}")
                    except Exception as e2:
                        print(f"❌ fallback по username тоже не сработал: {e2}")
                        return -1, None
                else:
                    print("❌ username отсутствует, fallback невозможен")
                    return -1, None

            if not isinstance(entity, InputUser):
                try:
                    entity = InputUser(entity.user_id, entity.access_hash)
                except Exception as conv_err:
                    print(f"❌ Не удалось сконвертировать в InputUser: {conv_err}")
                    return -1, None

            try:
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

                print(f"🎁 У пользователя найдено knockdown: {count}")
                return count, getattr(entity, "username", None)
            except Exception as e:
                print("❌ Ошибка при получении подарков:", e)
                return -1, None

    return asyncio.run(run())

# /start
@bot.message_handler(commands=["start"])
def start_message(message):
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🔍 Проверить подарки", callback_data="check_self"))
    bot.send_message(message.chat.id,
        "Привет! Я проверяю, есть ли у тебя минимум 6 knockdown‑подарков 🎁\n"
        "Нажми кнопку ниже, чтобы пройти проверку.",
        reply_markup=markup)

# Кнопка
@bot.callback_query_handler(func=lambda call: call.data == "check_self")
def handle_check(call):
    user_id = call.from_user.id
    username = call.from_user.username or None

    if is_approved(user_id):
        bot.send_message(call.message.chat.id,
            "✅ Ты уже прошёл проверку.\nЕсли у тебя есть доступ, не нужно генерировать ссылку повторно.")
        return

    try:
        count, resolved_username = check_knockdowns(user_id, username)

        if count == -1:
            bot.send_message(call.message.chat.id,
                "❗️Telegram пока не разрешает мне проверить твой профиль.\n\n"
                "Пожалуйста, укажи username в профиле или напиши мне личное сообщение.")
            return

        if count >= 6:
            invite = bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
            bot.send_message(call.message.chat.id,
                f"✅ У тебя {count} knockdown-подарков. Доступ разрешён!\n"
                f"Вот твоя персональная ссылка для входа в группу:\n{invite.invite_link}")
            save_approved(user_id, resolved_username or username, count)
        else:
            bot.send_message(call.message.chat.id,
                f"❌ У тебя только {count} knockdown-подарков.\n"
                "Попробуй докупить недостающие на @mrkt.")
    except Exception:
        bot.send_message(call.message.chat.id, "⚠️ Внутренняя ошибка. Попробуй позже.")
        traceback.print_exc()

print("🤖 Бот запущен и ожидает...")
bot.infinity_polling(timeout=10, long_polling_timeout=5)
