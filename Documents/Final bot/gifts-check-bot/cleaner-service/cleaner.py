import os
import asyncio
import psycopg2
from telethon import TelegramClient
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest
from datetime import datetime

# Конфигурация
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
session_file = "sessions/userbot_session"
admin_user_id = int(os.getenv("ADMIN_USER_ID"))
chat_id = int(os.getenv("CHAT_ID"))

# Подсчёт подарков
async def get_knockdown_count_safe(client, user_id, access_hash):
    count = 0
    offset = ""
    try:
        entity = InputUser(user_id, access_hash)
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

        report_lines = ["📋 Отчёт по knockdown-подаркам:\n"]
        total_users = 0

        # Только текущие участники группы
        async for user in client.iter_participants(chat_id):
            total_users += 1
            user_id = user.id
            username = f"@{user.username}" if user.username else str(user_id)

            if not user.access_hash:
                report_lines.append(f"⚠️ {username}: нет access_hash — пропущен")
                continue

            count, error = await get_knockdown_count_safe(client, user_id, user.access_hash)
            if error:
                report_lines.append(f"⚠️ {username}: ошибка — {error}")
            else:
                report_lines.append(f"🎁 {username}: {count} knockdown")

        report_lines.append(f"\n👥 Users in group — {total_users}")

        # Сохраняем в .txt
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = f"log_cleaner_{timestamp}.txt"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))

        # Отправляем файл тебе
        await client.send_file(admin_user_id, log_path, caption="📄 Отчёт по knockdown")

if __name__ == "__main__":
    asyncio.run(main())
