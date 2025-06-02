import os
import asyncio
import psycopg2
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest

# Конфигурация
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
session_file = "sessions/userbot_session"
admin_user_id = int(os.getenv("ADMIN_USER_ID"))
slava_user_id = 1911659577
chat_id = int(os.getenv("CHAT_ID"))

# Исключения — админы и системные аккаунты
EXCLUDED_ADMINS = {
    "gifts_check_bot", "knockdownclub", "tap_monster", "knockdown_club",
    8123231575, 934264793, 5855748096, 7071295533, 7870945546
}

# Подсчёт knockdown-подарков
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

        report = ["📋 Отчёт по knockdown-подаркам:\n"]
        results = []
        total = 0

        async for user in client.iter_participants(chat_id):
            total += 1
            user_id = user.id
            username = user.username.lower() if user.username else None
            label = f"@{user.username}" if user.username else str(user_id)

            if user_id in EXCLUDED_ADMINS or (username and username in EXCLUDED_ADMINS):
                continue

            if not user.access_hash:
                results.append((label, -1, "нет access_hash"))
                continue

            count, error = await get_knockdown_count_safe(client, user_id, user.access_hash)
            if error:
                results.append((label, -1, f"ошибка — {error}"))
            else:
                results.append((label, count, None))

        # Сортировка от большего к меньшему
        results.sort(key=lambda x: x[1], reverse=True)

        for label, count, error in results:
            if error:
                report.append(f"⚠️ {label}: {error}")
            elif count < 6:
                report.append(f"❗️ {label}: {count} knockdown")
            else:
                report.append(f"🎁 {label}: {count} knockdown")

        report.append(f"\n👥 Users in group — {total}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = f"log_cleaner_{timestamp}.txt"

        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report))

        for uid in [admin_user_id, slava_user_id]:
            await client.send_file(uid, log_path, caption="📄 Отчёт по knockdown")

if __name__ == "__main__":
    asyncio.run(main())
