import os
import asyncio
import psycopg2
from telethon import TelegramClient
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest
from telebot import TeleBot

# Конфигурация
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
session_file = "userbot_session"
chat_id = int(os.getenv("CHAT_ID"))
bot_token = os.getenv("BOT_TOKEN")
bot = TeleBot(bot_token)

# Получение knockdown-подарков
async def get_knockdown_count_safe(client, entity):
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
                if not gift_data or "title" not in gift_data or "slug" not in gift_data:
                    continue
                for attr in gift_data.get("attributes", []):
                    if "name" in attr and attr["name"].lower() == "knockdown":
                        count += 1
                        break
            offset = result.next_offset or ""
            if not offset:
                break
    except Exception as e:
        return -1, str(e)
    return count, None

# Основная функция
async def main():
    async with TelegramClient(session_file, api_id, api_hash) as client:
        conn = psycopg2.connect(
            host=os.getenv("PGHOST"),
            dbname=os.getenv("PGDATABASE"),
            user=os.getenv("PGUSER"),
            password=os.getenv("PGPASSWORD"),
            port=os.getenv("PGPORT")
        )
        cur = conn.cursor()
        cur.execute("SELECT user_id, username FROM approved_users")
        users = cur.fetchall()

        report_lines = ["📋 Проверка knockdown-подарков:\n"]
        for user_id, username in users:
            name = f"@{username}" if username else str(user_id)
            try:
                entity = InputUser(user_id, 0)  # access_hash не нужен для кастомных методов
                count, error = await get_knockdown_count_safe(client, entity)
                if error:
                    report_lines.append(f"⚠️ {name}: ошибка — {error}")
                else:
                    report_lines.append(f"🎁 {name}: {count} knockdown")
            except Exception as e:
                report_lines.append(f"❌ {name}: не удалось проверить — {e}")

        # Отправляем отчет по частям
        chunk = ""
        for line in report_lines:
            if len(chunk + "\n" + line) > 4000:
                bot.send_message(chat_id, chunk)
                chunk = ""
            chunk += line + "\n"

        if chunk:
            bot.send_message(chat_id, chunk)

if __name__ == "__main__":
    asyncio.run(main())
