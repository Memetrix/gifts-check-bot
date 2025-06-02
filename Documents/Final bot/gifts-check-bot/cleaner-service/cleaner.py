import os
import asyncio
import psycopg2
from telethon import TelegramClient
from telethon.tl.types import InputUser
from telethon.errors import UserAdminInvalidError
from get_user_star_gifts_request import GetUserStarGiftsRequest
from telebot import TeleBot

# Конфигурация
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")
chat_id = int(os.getenv("CHAT_ID"))
session_file = "cleaner-service/sessions/userbot_session"

bot = TeleBot(bot_token)
admin_copy_id = 1911659577  # @slavasemenchuk

# Получение knockdown-подарков
async def get_knockdown_count(client, entity):
    count = 0
    offset = ""
    try:
        while True:
            result = await client(GetUserStarGiftsRequest(user_id=entity, offset=offset, limit=100))
            for g in result.gifts:
                gift = g.to_dict().get("gift")
                if not gift:
                    continue
                for attr in gift.get("attributes", []):
                    if "name" in attr and attr["name"].lower() == "knockdown":
                        count += 1
                        break
            if not result.next_offset:
                break
            offset = result.next_offset
    except Exception as e:
        return -1, str(e)
    return count, None

# Проверка пользователей
async def run_cleaner():
    async with TelegramClient(session_file, api_id, api_hash) as client:
        group = await client.get_entity(chat_id)
        participants = client.iter_participants(group)
        admins = [a async for a in client.iter_participants(group, filter=1)]  # admin filter = 1

        admin_ids = set(a.id for a in admins)
        messages = []

        async for user in participants:
            if user.bot or user.deleted or user.id in admin_ids:
                continue
            try:
                entity = InputUser(user.id, user.access_hash)
                count, error = await get_knockdown_count(client, entity)
                if count == 0:
                    username = f"@{user.username}" if user.username else f"{user.first_name} {user.last_name or ''}".strip()
                    messages.append(f"🚫 {username} ({user.id}) — 0 knockdown")
            except Exception as e:
                messages.append(f"⚠️ {user.id}: ошибка — {e}")

        if messages:
            full_report = "📋 Отчёт: пользователи с 0 knockdown\n\n" + "\n".join(messages)
            bot.send_message(chat_id, full_report)
            bot.send_message(admin_copy_id, full_report)

if __name__ == "__main__":
    asyncio.run(run_cleaner())
