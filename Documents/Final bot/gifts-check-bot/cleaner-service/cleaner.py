import os
import asyncio
from datetime import datetime
from telebot import TeleBot
from telethon import TelegramClient
from telethon.tl.types import InputUser
from telethon.tl.functions.messages import GetDialogsRequest
from get_user_star_gifts_request import GetUserStarGiftsRequest

# Создание нужной папки под сессию
os.makedirs("cleaner-service/sessions", exist_ok=True)

# Конфиг из переменных окружения
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")
chat_id = int(os.getenv("CHAT_ID"))
admin_id = 1911659577
session_file = "cleaner-service/sessions/userbot_session"

bot = TeleBot(bot_token)

# Получение knockdown-подарков
async def get_knockdown_count(client, entity):
    count = 0
    offset = ""
    try:
        while True:
            result = await client(GetUserStarGiftsRequest(user_id=entity, offset=offset, limit=100))
            if not result.gifts:
                break
            for g in result.gifts:
                gift = g.to_dict().get("gift")
                if not gift:
                    continue
                for attr in gift.get("attributes", []):
                    if "name" in attr and attr["name"].lower() == "knockdown":
                        count += 1
                        break
            offset = result.next_offset or ""
            if not offset:
                break
    except Exception as e:
        return -1, f"ошибка — {e}"
    return count, None

# Основная логика
async def run_cleaner():
    report_lines = []
    try:
        async with TelegramClient(session_file, api_id, api_hash) as client:
            group = await client.get_entity(chat_id)
            participants = []
            async for user in client.iter_participants(group):
                participants.append(user)

            admins = await client.get_participants(group, filter=ChannelParticipantsAdmins())

            admin_ids = {admin.id for admin in admins}

            for user in participants:
                if user.id in admin_ids:
                    continue

                try:
                    entity = InputUser(user.id, user.access_hash)
                    count, error = await get_knockdown_count(client, entity)

                    username = f"@{user.username}" if user.username else f"{user.first_name or ''} {user.last_name or ''}".strip()
                    identifier = f"{username or user.id}"

                    if count == 0:
                        report_lines.append(f"🚫 {identifier} ({user.id}) — 0 knockdown")
                    elif error:
                        report_lines.append(f"⚠️ {identifier} ({user.id}): {error}")

                except Exception as e:
                    username = f"@{user.username}" if user.username else f"{user.first_name or ''} {user.last_name or ''}".strip()
                    report_lines.append(f"⚠️ {username or user.id} ({user.id}): ошибка — {e}")
                    continue

        if report_lines:
            text = "📋 Проверка knockdown-подарков:\n\n" + "\n".join(report_lines)
            bot.send_message(chat_id, text)
            if admin_id != chat_id:
                bot.send_message(admin_id, text)

    except Exception as e:
        error_text = f"❌ Ошибка при запуске cleaner: {e}"
        bot.send_message(admin_id, error_text)

# Запуск
if __name__ == "__main__":
    asyncio.run(run_cleaner())
