import os
import asyncio
import traceback
import telebot
from telethon import TelegramClient
from telethon.tl.types import InputUser
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
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

# Поиск через имя в канале @narrator
async def get_entity_by_name(client, user_id, first_name):
    try:
        participants = await client(GetParticipantsRequest(
            channel='@narrator',
            filter=ChannelParticipantsSearch(first_name),
            offset=0,
            limit=100,
            hash=0
        ))
        for user in participants.users:
            if user.id == user_id:
                print(f"🔍 Найден по имени {first_name}: {user.id}")
                return InputUser(user.id, user.access_hash)
    except Exception as e:
        print(f"⚠️ Ошибка при поиске по имени: {e}")
    return None

# Проверка knockdown-подарков
def check_knockdowns(user_id: int, username: str = None, first_name: str = None) -> (int, str):
    async def run():
        async with TelegramClient(session_file, api_id, api_hash) as client:
            try:
                await client.get_dialogs()
                entity = await client.get_input_entity(user_id)
                print(f"✅ entity найден по ID: {entity}")
            except Exception as e1:
                print(f"⚠️ get_input_entity(user_id) не сработал: {e1}")
                entity = None

                if username:
                    try:
                        entity = await client.get_input_entity(f"@{username}")
                        print(f"✅ fallback через username сработал: {entity}")
                    except Exception as e2:
                        print(f"❌ fallback по username тоже не сработал: {e2}")

                if not entity and first_name:
                    entity = await get_entity_by_name(client, user_id, first_name)
                    if entity:
                        print("✅ Найден через имя, используем как InputUser")

                if not entity:
                    return -1, username

            if not isinstance(entity, InputUser):
                try:
                    entity = InputUser(entity.user_id, entity.access_hash)
                except Exception as conv_err:
                    print(f"❌ Не удалось сконвертировать в InputUser: {conv_err}")
                    return -1, username

            count = 0
            offset = ""
            try:
                while True:
                    result = await client(GetUserStarGiftsRequest(user_id=entity, offset=offset, limit=100))
                    if not result.gifts:
                        break
                    for g in result.gifts:
                        data = g.to_dict()
                        gift_data = data.get("gift")
                        if not gift_data:
                            continue
                        for attr in gift_data.get("attributes", []):
                            if attr.get("name", "").lower() == "knockdown":
                                count += 1
                                break
                    offset = result.next_offset or ""
                    if not offset:
                        break
            except Exception as e:
                print(f"⚠️ Ошибка при получении подарков: {e}")
                return -1, username

            return count, username

    return asyncio.run(run())

# /start
@bot.message_handler(commands=["start"])
def start_message(message):
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("
