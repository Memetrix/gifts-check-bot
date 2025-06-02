import os
import asyncio
import psycopg2
from telethon import TelegramClient
from get_user_star_gifts_request import GetUserStarGiftsRequest
from telebot import TeleBot

# Конфигурация
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
session_file = "sessions/userbot_session"
admin_user_id = int(os.getenv("ADMIN_USER_ID"))  # 👈 Добавь переменную в Railway
bot_token = os.getenv("BOT_TOKEN")
bot = TeleBot(bot_token)

# Получение knockdown-подарков
async def get_knockdown_count_safe(client, user_id):
    count = 0
    offset = ""
    try:
        entity = await client.get_input_entity(user_id)
        while True:
            result = await client(GetUserStarGiftsRequest(user_id=entity, offset=offset, limit=100))
            if not result.gifts:
                break
            for g in result.gifts:
                gift_data = g.to_dict().get("gift")
                if not gift_data:
                    continue
                for attr in gift_data.get("attributes", []):
                    if "name" in attr and attr["name"].lower() == "knockdown":
                        count += 1
                        break
            offset = result.next_offset or ""
            if not offset:
                break
        return count, None
    except Exception as e:
        return -1, str(e)

# Основной запуск
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

        report_lines = ["📋 Knockdown Gifts Report:\n"]
        for user_id, username in users:
            name = f"@{username}" if username else str(user_id)
            count, error = await get_knockdown_count_safe(client, user_id)
            if error:
                report_lines.append(f"⚠️ {name}: ошибка — {error}")
            else:
                report_lines.append(f"🎁 {name}: {count} knockdown")

        full_report = "\n".join(report_lines)
        if len(full_report) > 4096:
            for i in range(0, len(full_report), 4000):
                bot.send_message(admin_user_id, full_report[i:i+4000])
        else:
            bot.send_message(admin_user_id, full_report)

if __name__ == "__main__":
    asyncio.run(main())
