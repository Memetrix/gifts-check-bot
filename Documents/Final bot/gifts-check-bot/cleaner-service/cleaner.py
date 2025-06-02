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

EXCLUDED_ADMINS = {
    "gifts_check_bot", "knockdownclub", "tap_monster", "knockdown_club",
    8123231575, 934264793, 5855748096, 7071295533, 7870945546
}

# Подсчёт knockdown
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

        users = []
        total = 0

        async for user in client.iter_participants(chat_id):
            total += 1
            user_id = user.id
            username = user.username.lower() if user.username else None

            if user_id in EXCLUDED_ADMINS or (username and username in EXCLUDED_ADMINS):
                continue

            # Формирование метки
            if user.username:
                label = f"@{user.username}"
                display = f"<code>{user.username}</code>"
            else:
                name = f"{user.first_name or ''} {user.last_name or ''}".strip()
                label = f"{name} ({user.id})"
                display = f"<code>{name}</code>"

            if not user.access_hash:
                users.append(("⚠️", display, "нет access_hash"))
                continue

            count, error = await get_knockdown_count_safe(client, user_id, user.access_hash)
            if error:
                users.append(("⚠️", display, f"ошибка — {error}"))
            elif count < 6:
                users.append(("❗️", display, f"{count} knockdown"))
            else:
                users.append(("🎁", display, f"{count} knockdown"))

        # Сортировка
        users.sort(key=lambda x: int(x[2].split()[0]) if "knockdown" in x[2] else -1, reverse=True)

        html = [
            "<b>📋 Отчёт по knockdown‑подаркам</b>",
            f"<i>👥 Users in group — {total}</i>",
            "",
        ]
        for icon, label, detail in users:
            html.append(f"{icon} {label}: {detail}")

        html_content = "\n".join(html)

        for uid in [admin_user_id, slava_user_id]:
            await client.send_message(uid, html_content, parse_mode="html")

if __name__ == "__main__":
    asyncio.run(main())
