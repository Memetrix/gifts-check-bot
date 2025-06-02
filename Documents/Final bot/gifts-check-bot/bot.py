import os
import asyncio
import traceback
from datetime import datetime, timedelta, timezone
from telebot import TeleBot, types
from telethon import TelegramClient
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest
from db import is_approved, save_approved, get_approved_user

# Конфигурация
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")
chat_id = int(os.getenv("CHAT_ID"))
session_file = "cleaner-service/sessions/userbot_session"
channel_id = int(os.getenv("CHANNEL_ID", 2608127062))  # @narrator по умолчанию

bot = TeleBot(bot_token)
bot.skip_pending = True

# Получение knockdown-подарков
def check_knockdowns(user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> (int, str):
    async def run():
        async with TelegramClient(session_file, api_id, api_hash) as client:
            try:
                await client.get_dialogs()

                # 1. Попытка по user_id
                try:
                    entity = await client.get_input_entity(user_id)
                    print(f"✅ Найден по user_id: {user_id}")
                except Exception as e_id:
                    print(f"⚠️ Не найден по user_id: {e_id}")

                    # 2. Попытка по username
                    if username:
                        try:
                            entity = await client.get_input_entity(f"@{username}")
                            print(f"✅ Найден по username: @{username}")
                        except Exception as e_username:
                            print(f"⚠️ Не найден по username: {e_username}")
                            entity = None
                    else:
                        entity = None

                    # 3. Попытка по имени и фамилии через участников канала
                    if not entity and (first_name or last_name):
                        print(f"🔍 Ищу по имени: {first_name} {last_name} в канале...")
                        try:
                            async for user in client.iter_participants(channel_id, search=first_name or ""):
                                if user.first_name == first_name and user.last_name == last_name:
                                    entity = InputUser(user.id, user.access_hash)
                                    print(f"✅ Найден по имени: {first_name} {last_name}")
                                    break
                        except Exception as e_name:
                            print(f"⚠️ Ошибка при поиске по имени: {e_name}")

                if not entity:
                    print(f"❌ Не удалось получить entity: {user_id}")
                    return -1, None

                # Сбор подарков
                count = 0
                offset = ""
                while True:
                    result = await client(GetUserStarGiftsRequest(user_id=entity, offset=offset, limit=100))
                    for g in result.gifts:
                        data = g.to_dict()
                        gift = data.get("gift")
                        if gift:
                            for attr in gift.get("attributes", []):
                                if "name" in attr and attr["name"].lower() == "knockdown":
                                    count += 1
                                    break
                    if not result.next_offset:
                        break
                    offset = result.next_offset

                return count, getattr(entity, "username", None)
            except Exception as e:
                print(f"❌ Ошибка в check_knockdowns: {e}")
                return -1, None
    return asyncio.run(run())

# /start
@bot.message_handler(commands=["start"])
def start_message(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔍 Проверить подарки", callback_data="check_gifts"))
    bot.send_message(message.chat.id,
        "Привет! Я проверяю, есть ли у тебя минимум 6 knockdown‑подарков 🎁\n"
        "Нажми кнопку ниже, чтобы пройти проверку.",
        reply_markup=markup)

# Проверка
@bot.callback_query_handler(func=lambda call: call.data == "check_gifts")
def handle_check(call):
    user_id = call.from_user.id
    username = call.from_user.username
    first_name = call.from_user.first_name
    last_name = call.from_user.last_name
    now = datetime.now(timezone.utc)

    user = get_approved_user(user_id)

    if user:
        invite_link = user[2]
        created_at = user[3]
        count, _ = check_knockdowns(user_id, username, first_name, last_name)

        if count < 6:
            bot.send_message(call.message.chat.id,
                "❌ Ранее ты проходил проверку, но сейчас у тебя меньше 6 knockdown-подарков.\n"
                "Пожалуйста, пополни коллекцию и попробуй снова.")
            return

        if invite_link and created_at and (now - created_at) < timedelta(minutes=15):
            bot.send_message(call.message.chat.id,
                f"🔁 Ты недавно прошёл проверку.\nВот твоя персональная ссылка:\n{invite_link}")
            return

        try:
            invite = bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
            bot.send_message(call.message.chat.id,
                f"🔁 Ты снова прошёл проверку! Вот новая ссылка:\n{invite.invite_link}")
            save_approved(user_id, username, count, invite.invite_link)
            return
        except Exception as e:
            bot.send_message(call.message.chat.id, f"⚠️ Не удалось создать ссылку: {e}")
            return

    # Первый раз
    try:
        count, _ = check_knockdowns(user_id, username, first_name, last_name)
        if count >= 6:
            invite = bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
            bot.send_message(call.message.chat.id,
                f"✅ У тебя {count} knockdown-подарков. Доступ разрешён!\n"
                f"Вот твоя персональная ссылка:\n{invite.invite_link}")
            save_approved(user_id, username, count, invite.invite_link)
        else:
            bot.send_message(call.message.chat.id,
                f"❌ У тебя только {count} knockdown-подарков.\n"
                "Пожалуйста, купи недостающие на @mrkt.")
    except Exception as e:
        bot.send_message(call.message.chat.id, "⚠️ Внутренняя ошибка. Попробуй позже.")
        traceback.print_exc()

print("🤖 Бот запущен и готов к работе")
bot.infinity_polling(timeout=10, long_polling_timeout=5)
